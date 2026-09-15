#!/usr/bin/env bash
# 预发域名的证书(docs/STAGING.md)。在**生产部署机**上跑,不是预发机。
#
# 为什么在这里签:frp 是 TCP 直通,云服务器的 80 端口整个转给生产 nginx,而生产 nginx 80 端口的
# `server_name _` 会答任何域名的 HTTP-01 挑战(和 mp-cert.sh 同一个办法)。预发机只有一个非标准端口
# 对外,Let's Encrypt 不会去那里验证。
#
# 签好的两个文件由 scripts/deploy_staging.sh 取走、直接流到预发机(不落开发机)。续期也跟着预发部署走:
# certonly --keep-until-expiring 离到期还有 30 天以上时什么都不做,所以每次部署预发都跑一遍也不费事。
#
#   bash ~/super-z/deploy/staging-cert.sh staging.chaojizan.cc
#   bash -s -- staging.chaojizan.cc ~/super-z/deploy < staging-cert.sh    # deploy_staging.sh 这么调(见那边的注释)
set -euo pipefail
HOST=${1:?用法: staging-cert.sh <预发域名> [部署机的 deploy 目录]}
# 从 stdin 跑时 $0 是 bash,dirname 取不到脚本位置 —— 那时由第二个参数给出目录
cd "${2:-$(dirname "$0")}"
[ -f docker-compose.prod.yml ] || { echo "✗ $(pwd) 不是部署机的 deploy 目录"; exit 2; }
# 只认 chaojizan.cc 下的子域名:这个脚本拿的是生产的 certbot 账号和挑战目录,别被用去签不相干的域名
case "$HOST" in
  *[!a-z0-9.-]*|.*|*..*) echo "✗ 不像域名: $HOST"; exit 2 ;;
  *.chaojizan.cc) ;;
  *) echo "✗ 只签 chaojizan.cc 下的子域名: $HOST"; exit 2 ;;
esac

mkdir -p letsencrypt certbot-www
docker run --rm -v "$PWD/letsencrypt:/etc/letsencrypt" -v "$PWD/certbot-www:/var/www/certbot" \
  certbot/certbot certonly -n --webroot -w /var/www/certbot --cert-name "$HOST" --keep-until-expiring \
  --register-unsafely-without-email --agree-tos -d "$HOST"
# letsencrypt/ 由 certbot 容器以 root 写入,宿主用户读不了 —— 同 mp-cert.sh 借容器拷(-L 解引用 live/ 下的符号链接),
# 拷完把属主交还给登录用户,deploy_staging.sh 才能用 ssh 读走
docker run --rm -v "$PWD/letsencrypt:/le:ro" -v "$PWD/certs:/certs" alpine sh -c "
  mkdir -p /certs/staging &&
  cp -L /le/live/$HOST/fullchain.pem /le/live/$HOST/privkey.pem /certs/staging/ &&
  chmod 644 /certs/staging/fullchain.pem && chmod 600 /certs/staging/privkey.pem &&
  chown -R $(id -u):$(id -g) /certs/staging"
echo "✓ 预发证书在 certs/staging/,到期 $(openssl x509 -enddate -noout -in certs/staging/fullchain.pem | cut -d= -f2)"
