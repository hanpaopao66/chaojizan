#!/usr/bin/env bash
# 预发机一次性准备(docs/STAGING.md)。在**预发机**上跑,由 scripts/deploy_staging.sh init 调:
#
#   bash ~/super-z-staging/deploy/staging-init.sh https://staging.chaojizan.cc:8443 [--reset-gate]
#
# 密钥、门禁密码、cookie 值都在这台机器上现生成,不经过开发机,也不打印出来。已经有的一律不动
# (重跑安全);--reset-gate 只换门禁密码和 cookie(换完所有人要重新输一次密码)。
#
# 生成的东西都在 rsync 排除清单里(scripts/deploy_staging.sh),部署不会把它们冲掉:
#   .env.staging              api 等容器的运行配置(APP_ENV=dev、各项随机密钥、预发对外地址)
#   staging-gate/             门禁:htpasswd、cookie 值(token.map / set-cookie.conf)、给人看的 access.txt
#   certs/staging/            证书。先放自签名占位让 nginx 起得来,正式的由部署机签(staging-cert.sh)
#   tunnel/frpc.staging.toml  frpc:部署脚本从生产 frpc.toml 流过来的服务端地址和 token + 预发这一条转发
set -euo pipefail
cd "$(dirname "$0")"
BASE=${1:?用法: staging-init.sh <预发对外地址> [--reset-gate]}
RESET_GATE=${2:-}
case "$BASE" in https://*) ;; *) echo "✗ 预发对外地址要是 https:// 开头: $BASE"; exit 2 ;; esac
HOST=$(echo "$BASE" | sed -E 's#^https://([^:/]+).*#\1#')
PORT=$(echo "$BASE" | sed -nE 's#^https://[^:/]+:([0-9]+).*#\1#p')
PORT=${PORT:-443}
umask 077
mkdir -p staging-gate certs/staging tunnel nginx/staging.generated ../webapp/current
# nginx 的 worker(容器里 uid 101)按请求读门禁文件、通过页和网页版,这几级目录要让它进得去;
# tunnel/ 里有 frps 的 token,保持 700
chmod 755 staging-gate certs certs/staging nginx nginx/staging.generated ../webapp ../webapp/current

if [ ! -f .env.staging ]; then
  MINIO_PW=$(openssl rand -hex 24)
  cat > .env.staging <<EOF
# 预发环境运行配置(docs/STAGING.md)。staging-init.sh 生成,只在预发机上,不进仓库。
# APP_ENV=dev:验证码直接回显、模拟支付、视频等开关缺省开 —— 对外靠 nginx 门禁挡人。
APP_ENV=dev
POSTGRES_PASSWORD=$(openssl rand -hex 24)
JWT_SECRET=$(openssl rand -hex 32)
MINIO_ROOT_USER=superz-staging
MINIO_ROOT_PASSWORD=$MINIO_PW
STORAGE_BACKEND=minio
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=superz-staging
MINIO_SECRET_KEY=$MINIO_PW
MINIO_SECURE=false
PUBLIC_BASE_URL=$BASE
MOCK_PAY_ENABLED=true
ADMIN_PASSWORD_LOGIN=true
# 不配短信、推送、地图、微信支付:预发不给真人发短信和推送,不占生产的地图配额,也不碰真钱
EOF
  echo "✓ 生成 .env.staging"
else
  echo "· .env.staging 已有,不动"
fi

if [ ! -f staging-gate/htpasswd ] || [ "$RESET_GATE" = "--reset-gate" ]; then
  # cookie 值用 16 字节(32 位十六进制):nginx map 的键超过哈希桶(默认 64 字节)会起不来,本地实测过
  TOKEN=$(openssl rand -hex 16)
  PW=$(openssl rand -hex 12)
  printf '"%s" 1;\n' "$TOKEN" > staging-gate/token.map
  printf 'add_header Set-Cookie "sz_staging_gate=%s; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax";\n' \
    "$TOKEN" > staging-gate/set-cookie.conf
  # apr1 是 nginx 自己实现的格式,不依赖容器里 libc 的 crypt;密码是 24 位随机十六进制,格式强弱无所谓
  printf 'staging:%s\n' "$(openssl passwd -apr1 "$PW")" > staging-gate/htpasswd
  cat > staging-gate/access.txt <<EOF
超级赞预发环境
地址:$BASE/
第一次打开会要求输入(浏览器弹框):
  用户名 staging
  密码   $PW
通过后这台设备 30 天内不用再输。换密码:bash scripts/deploy_staging.sh init --reset-gate
EOF
  # nginx 容器以 nginx 用户读这几个文件(只读挂载):目录 755、文件 644;access.txt 只给人看,保持 600
  chmod 755 staging-gate
  chmod 644 staging-gate/token.map staging-gate/set-cookie.conf staging-gate/htpasswd
  echo "✓ 门禁已生成(用户名 staging,密码在预发机 $(pwd)/staging-gate/access.txt)"
else
  echo "· 门禁已有,不动(要换:--reset-gate)"
fi

if [ ! -s certs/staging/fullchain.pem ] || [ ! -s certs/staging/privkey.pem ]; then
  # 正式证书还没拷过来时先放一张自签名的:证书文件不存在 nginx 就起不来
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=$HOST" \
    -keyout certs/staging/privkey.pem -out certs/staging/fullchain.pem 2>/dev/null
  # 私钥只有 nginx 主进程(root)在启动时读,600 就够
  chmod 644 certs/staging/fullchain.pem
  chmod 600 certs/staging/privkey.pem
  echo "✓ 放了自签名占位证书(正式证书等 DNS 生效后由部署脚本从部署机取)"
fi

if [ -s tunnel/frps-common.toml ]; then
  {
    echo "# 预发 frpc(docs/STAGING.md)。staging-init.sh 生成,只在预发机上。"
    echo "# 服务端地址和 token 来自生产部署机的 frpc.toml(deploy_staging.sh init 直接流过来,没落开发机)"
    cat tunnel/frps-common.toml
    echo
    echo '[[proxies]]'
    echo 'name = "superz-staging-https"'
    echo 'type = "tcp"'
    echo 'localIP = "127.0.0.1"'
    echo 'localPort = 8443           # 预发 nginx 的 443(docker-compose.staging.yml 发布成 8443)'
    echo "remotePort = $PORT"
  } > tunnel/frpc.staging.toml
  rm -f tunnel/frps-common.toml
  echo "✓ frpc 配置已生成:云服务器 :$PORT → 这台 nginx"
elif [ ! -f tunnel/frpc.staging.toml ]; then
  echo "✗ 没有 frpc 配置,也没收到生产那边的服务端信息 —— 用 scripts/deploy_staging.sh init 跑,别单独跑这个脚本"
  exit 1
fi
