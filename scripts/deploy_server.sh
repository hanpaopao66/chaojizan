#!/bin/bash
# 服务端发版:rsync 代码到部署机 → 容器重建 → 迁移自动执行 → 健康验证
#
# 注意顺序:发 APK 前先跑本脚本!新版 App 依赖新接口(如 /stats/overview、
# /orders/{no}/refunds),服务端不更新用户会见到 404。
#
# 用法:scripts/deploy_server.sh          (需在部署机所在局域网)
set -e
cd "$(dirname "$0")/.."

# 部署机地址不入库:deploy/.env.deploy(gitignore)写 DEPLOY=user@host,或环境变量传入
[ -f deploy/.env.deploy ] && . deploy/.env.deploy
DEPLOY=${DEPLOY:?缺部署机地址:在 deploy/.env.deploy 写 DEPLOY=user@host(不入库)}
PUBLIC_BASE=${PUBLIC_BASE:?缺对外域名:在 deploy/.env.deploy 写 PUBLIC_BASE=https://域名(不入库)}
# 注意:不能写 DEST=~/super-z,本机 shell 会把 ~ 展开成本机家目录
DEST='~/super-z'

echo "== 记录版本号(透明中心/页脚展示,证明线上跑的就是仓里的代码) =="
{ git describe --tags --always 2>/dev/null || echo unknown; \
  date -u +%FT%TZ; } > server/app_version.txt

echo "== 同步代码(排除依赖与产物) =="
# 前三个 exclude 保护部署机上仅存的运行数据(本地仓库没有这些目录,
# 不加会被 --delete 清掉:.env.prod=生产密钥 / appdist=线上 APK / letsencrypt=证书)
rsync -az --delete \
  --exclude 'deploy/.env.prod' --exclude 'appdist' --exclude 'deploy/letsencrypt' \
  --exclude 'deploy/certs' --exclude 'deploy/tunnel' \
  --exclude 'deploy/wxpay-certs' --exclude 'server/certs' \
  --exclude 'deploy/certbot-www' --exclude 'deploy/renew.log' \
  --exclude 'deploy/nginx/conf.d/legacy*' --exclude 'deploy/.domains.local' \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude 'node_modules' --exclude 'build' --exclude '.dart_tool' \
  --exclude 'server/.env' --exclude 'server/uploads' --exclude 'server/appdist' \
  --exclude 'marketing' --exclude '.claude' \
  ./ "$DEPLOY:$DEST/"

echo "== 重建容器(alembic 迁移在启动时自动执行) =="
ssh "$DEPLOY" "cd $DEST/deploy && \
  docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build"

# nginx **必须最后重启一次**。
#
# nginx 在启动时把 upstream 的容器名解析成 IP 就**缓存住不再解析**,
# 而 compose 重建时 api 容器会换 IP。表现是:部署当下健康检查是绿的
# (那一刻 IP 还没变),十几分钟后全站 502,错误日志里是
# 「connect() failed (113: Host is unreachable) ... upstream: 172.24.0.7」——
# 那个 IP 是上一代 api 容器的。
#
# 2026-08-01 的 v0.8.0 发版就是这么挂的:APK 都发出去了、健康检查也过了,
# 十分钟后官网和接口全 502,静态文件也一起挂(它们同在一个 server 块)。
echo "== 重启 nginx(让它重新解析 api 的新 IP) =="
ssh "$DEPLOY" "cd $DEST/deploy && \
  docker compose -f docker-compose.prod.yml --env-file .env.prod restart nginx"
sleep 3

echo "== 健康验证 =="
sleep 8
for i in $(seq 1 15); do
  curl -sf -m 10 --noproxy '*' $PUBLIC_BASE/health && break
  sleep 4
done
echo
# 静态文件单独验一次:appdist 是旧版 App 检查更新的入口,
# 它挂了等于所有用户都收不到更新 —— 而它和接口同在一个 server 块,
# nginx upstream 一坏是一起坏的
VJSON=$(curl -s -o /dev/null -w '%{http_code}' -m 10 --noproxy '*' \
  "$PUBLIC_BASE/appdist/versions.json")
[ "$VJSON" = "200" ] || { echo "✗ appdist/versions.json 返回 $VJSON,更新入口是坏的"; exit 1; }
echo "  appdist/versions.json 200 ✓"
curl -s -m 10 --noproxy '*' "$PUBLIC_BASE/stats/overview" | head -c 120
echo
echo "服务端发版完成 ✓ (确认上面 stats 有数据后再发 APK)"
