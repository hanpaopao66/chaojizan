#!/usr/bin/env bash
# 小程序托管域名 mp.chaojizan.cc 的证书(docs/MINIAPP-ROLLOUT.md 2.1)。在部署机上跑。
#
# 现在托管的只有官方小程序和少量第三方应用,用 HTTP-01 webroot(和 renew-cert.sh 同一套 certbot 容器、
# 同一个 certbot-www 目录)签一张多域名证书:mp.chaojizan.cc + 每个托管应用的 <appid>.mp.chaojizan.cc。
# 能这么签是因为:泛解析 *.mp 已经指向云服务器,frp 是 TCP 直通,nginx 80 端口的 server_name _
# 会答任何子域名的验证请求(2026-09-15 实测过)。一张证书最多 100 个域名,托管应用多起来之后换 DNS-01
# 泛域名证书 —— 那要一把只有 DNS 权限的阿里云密钥,由人自己配在部署机上。
#
#   bash ~/super-z/deploy/mp-cert.sh                          # 按库里的托管应用签 / 扩;没变化又没到期就什么都不做
#   bash ~/super-z/deploy/mp-cert.sh --placeholder-if-missing # 还没有证书时放一张自签名占位(deploy_server.sh 调)
#
# 新发布了托管应用(scripts/publish_official_miniapp.py 或开发者后台)就再跑一次:新 appid 进证书、nginx 热重载。
# 续期交给 renew-cert.sh(certbot renew 会一起续这张;.domains.local 里有 mp.chaojizan.cc 才会拷进 certs/mp,
# 这个脚本第一次签完会自己加上)。
set -euo pipefail
cd "$(dirname "$0")"
HOST=mp.chaojizan.cc
DIR=certs/mp

if [ "${1:-}" = "--placeholder-if-missing" ]; then
  mkdir -p "$DIR"
  if [ -s "$DIR/fullchain.pem" ] && [ -s "$DIR/privkey.pem" ]; then exit 0; fi
  echo "托管域名还没有证书:先放一张自签名占位,让 nginx 能起来(托管应用在换上正式证书之前打不开)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=$HOST" \
    -keyout "$DIR/privkey.pem" -out "$DIR/fullchain.pem" 2>/dev/null
  chmod 600 "$DIR/privkey.pem"
  exit 0
fi

# 移除(终态)的应用不再要证书;草稿也要 —— 审核预览、体验版走的都是托管域名
mapfile -t APPIDS < <(docker exec deploy-db-1 psql -U superz -d superz -Atc \
  "select appid from mini_apps where hosting = 'hosted' and status <> 'removed' order by appid")
ARGS=(-d "$HOST")
for a in "${APPIDS[@]}"; do [ -n "$a" ] && ARGS+=(-d "$a.$HOST"); done
n=$(( ${#ARGS[@]} / 2 ))
echo "== 托管域名证书覆盖 $n 个域名(mp + $(( n - 1 )) 个托管应用)=="
if [ "$n" -gt 100 ]; then
  echo "✗ 超过 100 个,一张证书放不下:该换 DNS-01 泛域名证书了(docs/MINIAPP-ROLLOUT.md 2.1)"
  exit 1
fi

mkdir -p letsencrypt certbot-www
docker run --rm -v "$PWD/letsencrypt:/etc/letsencrypt" -v "$PWD/certbot-www:/var/www/certbot" \
  certbot/certbot certonly -n --webroot -w /var/www/certbot --cert-name "$HOST" --expand \
  --register-unsafely-without-email --agree-tos "${ARGS[@]}"
# letsencrypt/ 由 certbot 容器以 root 写入,宿主用户读不了 —— 同样借容器拷(-L 解引用 live/ 下的符号链接)
docker run --rm -v "$PWD/letsencrypt:/le:ro" -v "$PWD/certs:/certs" alpine \
  sh -c "mkdir -p /certs/mp && cp -L /le/live/$HOST/fullchain.pem /le/live/$HOST/privkey.pem /certs/mp/"
grep -qx "$HOST" .domains.local 2>/dev/null || echo "$HOST" >> .domains.local
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T nginx nginx -s reload
echo "✓ 托管域名证书已更新,nginx 已热重载"
