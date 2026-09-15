#!/bin/bash
# 预发环境部署(docs/STAGING.md):预发机是局域网里的一台 Mac mini,对外 https://staging.chaojizan.cc:8443。
#
#   bash scripts/deploy_staging.sh init [--reset-gate]   第一次:在预发机上生成密钥、门禁、占位证书、frpc 配置
#   bash scripts/deploy_staging.sh [提交]                部署某个提交(缺省 HEAD):
#        同步代码 → 生成 nginx 配置 → 编网页版 → 取证书 → 建镜像 → 迁移彩排 → 起服务 → 验证
#   选项:--skip-web 网页版没改就不重编(省几分钟);--no-rehearsal 跳过迁移彩排
#
# 读 deploy/.env.deploy(不入库):
#   STAGING=user@预发机地址                         预发机(局域网)
#   STAGING_BASE=https://staging.chaojizan.cc:8443   对外地址:网页版编进去的接口地址、api 的 PUBLIC_BASE_URL
#   DEPLOY / PUBLIC_BASE                             生产部署机:签预发证书、现导一份生产库做彩排
#                                                    (走 deploy_target 那一套,在外面自动走私密通道)
#
# 两条不变量:
#  - **只部署提交过的代码**,和生产一样从干净检出同步。预发要验的是「将要上线的那一份」;
#    工作区里没提交的改动、仓库目录里的设计稿压缩包,都不该出现在预发上;
#  - **生产数据不进预发的库**。预发是开发配置(验证码直接回显、谁都能登录任何账号),
#    迁移彩排用一次性容器(deploy/rehearse-migrations.sh),跑完连同导出文件一起删。
set -eo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
[ -f deploy/.env.deploy ] && . deploy/.env.deploy
STAGING=${STAGING:?缺预发机地址:在 deploy/.env.deploy 写 STAGING=user@host(不入库)}
STAGING_BASE=${STAGING_BASE:?缺预发对外地址:在 deploy/.env.deploy 写 STAGING_BASE=https://staging.chaojizan.cc:8443}
STAGING_HOST=$(echo "$STAGING_BASE" | sed -E 's#^https://([^:/]+).*#\1#')
DEST='~/super-z-staging'     # 别写成不加引号的 ~:会在本机展开成本机家目录

st() { ssh -n -o BatchMode=yes "$STAGING" "export PATH=/opt/homebrew/bin:\$PATH; $1"; }
# 往预发机写文件(stdin 流进去):证书、生产 frpc 的服务端信息、彩排用的导出 —— 都不落开发机
st_write() { ssh -o BatchMode=yes "$STAGING" "umask 077; mkdir -p \"\$(dirname $1)\" && cat > $1"; }

MODE=deploy; REF=HEAD; SKIP_WEB=0; REHEARSE=1; RESET_GATE=""
for a in "$@"; do
  case "$a" in
    init) MODE=init ;;
    --reset-gate) RESET_GATE=--reset-gate ;;
    --skip-web) SKIP_WEB=1 ;;
    --no-rehearsal) REHEARSE=0 ;;
    -*) echo "不认识的选项 $a"; exit 2 ;;
    *) REF=$a ;;
  esac
done

# rsync 排除:生产那份(deploy_server.sh)+ 预发机本地生成、部署时不能被 --delete 冲掉的
EXCLUDES=(--exclude 'deploy/.env.prod' --exclude 'deploy/.env.staging' --exclude 'deploy/.env.deploy'
  --exclude 'appdist' --exclude 'deploy/letsencrypt' --exclude '/webapp' --exclude '/backups'
  --exclude 'deploy/healthcheck.log' --exclude 'deploy/certs' --exclude 'deploy/tunnel'
  --exclude 'deploy/wxpay-certs' --exclude 'server/certs' --exclude 'deploy/certbot-www'
  --exclude 'deploy/renew.log' --exclude 'deploy/nginx/conf.d/legacy*' --exclude 'deploy/.domains.local'
  --exclude 'deploy/staging-gate' --exclude 'deploy/nginx/staging.generated' --exclude 'deploy/.rehearsal'
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' --exclude 'node_modules' --exclude 'build'
  --exclude '.dart_tool' --exclude 'server/.env' --exclude 'server/uploads' --exclude 'server/private_uploads'
  --exclude 'server/appdist' --exclude 'marketing' --exclude '.claude')

echo "== 预发机 $STAGING =="
st 'docker info --format "   docker {{.ServerVersion}} / {{.NCPU}} 核 / {{.MemTotal}} 字节内存"' \
  || { echo "✗ 预发机上的 docker 不通(colima 没起?在预发机上 brew services list 看一下)"; exit 1; }

# 生产部署机:签证书、导生产库都要。deploy_target 会改 DEPLOY(走通道时变成 user@127.0.0.1)
prod_ssh() { ssh $SSH_OPTS -o BatchMode=yes "$DEPLOY" "$@"; }
PROD_READY=0
prod_connect() {
  [ "$PROD_READY" = 1 ] && return 0
  DEPLOY=${DEPLOY:?缺生产部署机地址 DEPLOY(deploy/.env.deploy)}
  . scripts/deploy_target.sh
  deploy_target || return 1
  echo "   生产部署机:$DEPLOY_VIA"
  PROD_READY=1
}

# ---------------------------------------------------------------------------
# 检出:和生产一样从干净的工作树同步(见文件头)
WT=$(mktemp -d "${TMPDIR:-/tmp}/superz-staging.XXXXXX")
cleanup() { git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"; }
trap cleanup EXIT
git worktree add --detach "$WT" "$REF" >/dev/null 2>&1 || { echo "✗ 检出 $REF 失败"; exit 1; }
VERSION=$(git -C "$WT" describe --tags --always)
echo "== 部署 $VERSION($(git -C "$WT" log -1 --format='%h %<(40,trunc)%s' | sed 's/ *$//'))=="
[ -z "$(git status --porcelain --untracked-files=no)" ] || \
  echo "   注意:工作区有没提交的改动,不会带上预发(只部署提交过的代码)"
{ echo "$VERSION"; date -u +%FT%TZ; } > "$WT/server/app_version.txt"

echo "== 同步代码 =="
rsync -az --delete "${EXCLUDES[@]}" "$WT/" "$STAGING:$DEST/"

if [ "$MODE" = init ]; then
  echo "== 初始化预发机 =="
  prod_connect || { echo "✗ 连不上生产部署机:frpc 要用它的服务端地址和 token"; exit 1; }
  # 只取 frpc 的公共段(第一个 [[ 表头之前)里的服务端地址、端口、认证、传输设置,不取生产那几条转发 ——
  # 转发里也有 transport.* 字段,整文件 grep 会把它们捎成顶层配置。token 从生产直接流到预发机,不落开发机
  prod_ssh "sed -n '/^\\[\\[/q;p' ~/super-z/deploy/tunnel/frpc.toml | grep -E '^[[:space:]]*(serverAddr|serverPort|auth\\.|transport\\.)'" \
    | st_write "$DEST/deploy/tunnel/frps-common.toml"
  st "bash $DEST/deploy/staging-init.sh '$STAGING_BASE' $RESET_GATE"
  echo "✓ 初始化完成。接着跑一次 bash scripts/deploy_staging.sh 部署"
  exit 0
fi
st "test -f $DEST/deploy/.env.staging && test -f $DEST/deploy/tunnel/frpc.staging.toml" \
  || { echo "✗ 预发机还没初始化:先跑 bash scripts/deploy_staging.sh init"; exit 1; }

echo "== nginx 配置(照抄生产 location + 预发证书和门禁)=="
python3 "$WT/scripts/gen_staging_nginx.py" "$WT/deploy/nginx/conf.d/superz.conf" "$WT/.staging-nginx" >/dev/null
# macOS 自带的是 openrsync,不认 --chmod:先在本地把权限摆好(nginx 的 worker 按请求读这些文件),再 -a 原样带过去
chmod -R u=rwX,go=rX "$WT/.staging-nginx"
rsync -a --delete "$WT/.staging-nginx/" "$STAGING:$DEST/deploy/nginx/staging.generated/"

if [ "$SKIP_WEB" = 0 ]; then
  echo "== 网页版(和发版同样的参数,只有接口地址换成预发)=="
  # 不能用 GitHub Release 里的那份:接口地址是编译时写死的,那份会去调生产
  (cd "$WT/apps/user_app" && flutter build web --release --base-href /web/ --no-web-resources-cdn \
      --web-define=SZ_FONT_FALLBACK_BASE=fontfallback/ \
      --dart-define=SUPERZ_CHANNEL=self "--dart-define=SUPERZ_API=$STAGING_BASE" \
      > "$WT/.web-build.log" 2>&1) || { tail -30 "$WT/.web-build.log"; echo "✗ 网页版没编过"; exit 1; }
  python3 "$WT/scripts/pack_user_web.py" "$WT/apps/user_app/build/web" "$WT/.staging-web.tar.gz" \
    --font-cache "$HOME/.cache/superz-web-fonts" | tail -1
  mkdir -p "$WT/.staging-web" && tar -xzf "$WT/.staging-web.tar.gz" -C "$WT/.staging-web"
  # compose 把 deploy/ 旁边的 ../webapp 挂给 nginx(/web/ → /srv/webapp/current/)
  chmod -R u=rwX,go=rX "$WT/.staging-web"
  rsync -a --delete "$WT/.staging-web/" "$STAGING:$DEST/webapp/current/"
else
  echo "== 网页版:跳过(--skip-web)=="
fi

echo "== 预发证书 =="
if [ "$(dig +short "$STAGING_HOST" A | tail -1)" = "" ]; then
  echo "   $STAGING_HOST 还没有 DNS 记录,先用自签名占位(见 docs/STAGING.md「上线前你要做的」)"
elif prod_connect; then
  # 脚本用这次检出里的那份、从 stdin 喂过去:生产部署机上的代码是上一次生产部署的,可能还没有这个脚本;
  # 也不往生产目录里单独放文件(那里只该有 deploy_server.sh 同步过去的东西)
  if CERT_OUT=$(prod_ssh "bash -s -- $STAGING_HOST ~/super-z/deploy" < "$WT/deploy/staging-cert.sh" 2>&1); then
    echo "$CERT_OUT" | tail -1 | sed 's/^/   /'
    prod_ssh "cat ~/super-z/deploy/certs/staging/fullchain.pem" | st_write "$DEST/deploy/certs/staging/fullchain.pem"
    prod_ssh "cat ~/super-z/deploy/certs/staging/privkey.pem" | st_write "$DEST/deploy/certs/staging/privkey.pem"
    st "chmod 644 $DEST/deploy/certs/staging/fullchain.pem"
  else
    echo "$CERT_OUT" | tail -8 | sed 's/^/   /'
    echo "   ✗ 签证书没成功,先用预发机上现有的那张"
  fi
fi

echo "== 基础镜像 =="
# 预发机的网络拉 Docker Hub 时断时续(国内镜像源也会中途 EOF),MinIO 更是 Hub 上已经没有了。
# 所以缺的镜像由开发机拉 arm64 版、docker save 过去 —— 走局域网,一两分钟的事。
# 清单 = compose 里写了 image 的服务(不含本栈自己构建的 superz-staging-*)+ server/Dockerfile 的基础镜像
MISSING=$(st "cd $DEST && { bash deploy/staging-compose.sh config --images; grep -E '^FROM ' server/Dockerfile | awk '{print \$2}'; } \
  | grep -v '^superz-staging-' | sort -u | while read -r i; do docker image inspect \"\$i\" >/dev/null 2>&1 || echo \"\$i\"; done")
if [ -n "$MISSING" ]; then
  docker info >/dev/null 2>&1 || { echo "✗ 预发机缺镜像,要从开发机灌,但开发机的 docker 没开"; exit 1; }
  for i in $MISSING; do
    docker pull -q --platform linux/arm64 "$i" >/dev/null
    docker save "$i" | gzip -1 | ssh -o BatchMode=yes "$STAGING" 'export PATH=/opt/homebrew/bin:$PATH; gunzip | docker load -q'
  done
else
  echo "   都在"
fi

echo "== 构建镜像 =="
st "bash $DEST/deploy/staging-compose.sh build -q"

if [ "$REHEARSE" = 1 ]; then
  echo "== 迁移彩排(生产库现导一份 → 一次性容器 → 用这次的代码迁移 → 销毁)=="
  if prod_connect; then
    # 现导,不用 03:30 那份备份:要验的是「现在」的生产数据。导出直接流到预发机,不落开发机
    prod_ssh "docker exec deploy-db-1 pg_dump -U superz -Fc superz" | st_write "$DEST/deploy/.rehearsal/prod.dump"
    st "bash $DEST/deploy/rehearse-migrations.sh $DEST/deploy/.rehearsal/prod.dump"
  else
    echo "✗ 连不上生产部署机,彩排做不了。确认迁移不需要彩排的话加 --no-rehearsal 再跑"
    exit 1
  fi
else
  echo "== 迁移彩排:跳过(--no-rehearsal)=="
fi

echo "== 起服务 =="
st "bash $DEST/deploy/staging-compose.sh up -d --remove-orphans"
# 同生产:nginx 最后重启一次,重新解析 api 的新 IP(见 deploy_server.sh 里 2026-08-01 那次)
st "bash $DEST/deploy/staging-compose.sh restart nginx" >/dev/null

# 空库(第一次部署)灌演示数据。seed 在 minio 配置下会随机生成演示口令并打印一次 —— 写进预发机上的文件,不打到这里
if [ "$(st "bash $DEST/deploy/staging-compose.sh exec -T db psql -U superz -d superz -Atc 'select count(*) from users'" | tr -d '\r')" = "0" ]; then
  echo "== 空库:灌演示数据 =="
  st "cd $DEST/deploy && bash staging-compose.sh exec -T api python -m scripts.seed > staging-gate/seed.log 2>&1 \
      && bash staging-compose.sh exec -T api python -m scripts.demo_seed >> staging-gate/seed.log 2>&1 \
      && chmod 600 staging-gate/seed.log"
  echo "   演示账号 13800000000(管理员)/ …01 顾客 / …02 商家 / …03 骑手;验证码登录时直接显示"
fi

echo "== 验证 =="
sleep 5
# 在预发机本机过门禁验(cookie 值只在预发机上,不经过这里)
HEALTH=""
for _ in $(seq 1 20); do
  HEALTH=$(st "cd $DEST/deploy && T=\$(sed -E 's/^\"([0-9a-f]+)\".*/\\1/' staging-gate/token.map) && \
    curl -sk -m 5 -H \"Cookie: sz_staging_gate=\$T\" https://127.0.0.1:8443/health" 2>/dev/null || true)
  echo "$HEALTH" | grep -q '"status":"ok"' && break
  sleep 3
done
echo "   $HEALTH"
echo "$HEALTH" | grep -q "\"version\":\"$VERSION\"" || { echo "✗ 预发上跑的不是 $VERSION"; exit 1; }
GATE=$(st "curl -sk -m 5 -o /dev/null -w '%{http_code} %{redirect_url}' https://127.0.0.1:8443/")
echo "   不带通行 cookie:$GATE(应当 302 到 /__gate)"
case "$GATE" in 302*) ;; *) echo "✗ 门禁没生效"; exit 1 ;; esac
st "docker logs --tail 20 superz-staging-frpc-1 2>&1" | grep -E "start proxy success|error|login" | tail -2 | sed 's/^/   frpc: /'
EXT=$(curl -s -m 10 --noproxy '*' -o /dev/null -w '%{http_code}' "$STAGING_BASE/" || true)
if [ "$EXT" = "302" ]; then
  echo "   外网 $STAGING_BASE/ → 302 ✓"
else
  echo "   外网 $STAGING_BASE/ 还打不开($EXT):DNS 记录和云服务器安全组见 docs/STAGING.md「上线前你要做的」"
fi
echo "预发部署完成 ✓ $VERSION"
