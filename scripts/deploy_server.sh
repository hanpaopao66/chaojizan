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
  --exclude 'deploy/certbot-www' --exclude 'deploy/renew.log' \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude 'node_modules' --exclude 'build' --exclude '.dart_tool' \
  --exclude 'server/.env' --exclude 'server/uploads' --exclude 'server/appdist' \
  --exclude 'marketing' --exclude '.claude' \
  ./ "$DEPLOY:$DEST/"

echo "== 重建容器(alembic 迁移在启动时自动执行) =="
ssh "$DEPLOY" "cd $DEST/deploy && \
  docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build"

echo "== 健康验证 =="
sleep 8
for i in $(seq 1 15); do
  curl -sf -m 10 --noproxy '*' https://aikas.com.cn/health && break
  sleep 4
done
echo
curl -s -m 10 --noproxy '*' "https://aikas.com.cn/stats/overview" | head -c 120
echo
echo "服务端发版完成 ✓ (确认上面 stats 有数据后再发 APK)"
