#!/usr/bin/env bash
# 证书自动续期(webroot 模式,零停机)。部署机 crontab(每周一 04:30):
#   30 4 * * 1 ~/super-z/deploy/renew-cert.sh >> ~/super-z/deploy/renew.log 2>&1
#
# 首次签发(一次性,域名解析生效且 80 端口链路通了之后):
#   cd ~/super-z/deploy && mkdir -p letsencrypt certbot-www
#   docker run --rm -v "$PWD/letsencrypt:/etc/letsencrypt" -v "$PWD/certbot-www:/var/www/certbot" \
#     certbot/certbot certonly -n --webroot -w /var/www/certbot -d chaojizan.cc \
#     --register-unsafely-without-email --agree-tos
set -euo pipefail

cd "$(dirname "$0")"
DOMAINS=(chaojizan.cc)
# 附加域名(如历史域名)写在服务器本地 .domains.local(每行一个,不入库)
[ -f .domains.local ] && while read -r d; do DOMAINS+=("$d"); done < .domains.local

echo "[$(date '+%F %T')] 开始检查续期"

# certbot renew:30 天内到期才真续,否则跳过
docker run --rm \
  -v "$PWD/letsencrypt:/etc/letsencrypt" \
  -v "$PWD/certbot-www:/var/www/certbot" \
  certbot/certbot renew --webroot -w /var/www/certbot --quiet

# 同步到 nginx 挂载目录(-L 解引用 live/ 符号链接)并热重载。
# letsencrypt/ 由 certbot 容器以 root 写入,宿主用户读不了——同样借容器拷贝
for d in "${DOMAINS[@]}"; do
  short=${d%%.*}   # 域名首段作证书目录名
  mkdir -p "certs/$short"
  docker run --rm -v "$PWD/letsencrypt:/le:ro" -v "$PWD/certs:/certs" \
    alpine sh -c "[ -d /le/live/$d ] && cp -L /le/live/$d/fullchain.pem /le/live/$d/privkey.pem /certs/$short/" \
    || echo "跳过 $d(还没签发)"
done
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T nginx nginx -s reload

echo "[$(date '+%F %T')] 续期检查完成,证书到期时间:"
for d in "${DOMAINS[@]}"; do
  docker run --rm -v "$PWD/certs:/certs:ro" alpine/openssl \
    x509 -enddate -noout -in "/certs/${d%%.*}/fullchain.pem"
done
