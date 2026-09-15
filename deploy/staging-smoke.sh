#!/usr/bin/env bash
# 预发冒烟(docs/STAGING.md):在**预发机本机**过门禁,把几条主干走一遍。由 scripts/deploy_staging.sh 在部署最后调。
#
#   bash ~/super-z-staging/deploy/staging-smoke.sh [对外地址]
#
# 走的是本机 127.0.0.1:8443,但带上对外域名(curl --resolve):nginx 和 api 看到的 Host 和外网进来时一模一样。
# 门禁 cookie 从 staging-gate/token.map 现读,只在这台机器上用,不打印。
set -euo pipefail
cd "$(dirname "$0")"
BASE=${1:-$(grep -E '^PUBLIC_BASE_URL=' .env.staging | cut -d= -f2-)}
HOST=$(echo "$BASE" | sed -E 's#^https://([^:/]+).*#\1#')
PORT=$(echo "$BASE" | sed -nE 's#^https://[^:/]+:([0-9]+).*#\1#p'); PORT=${PORT:-443}
TOKEN=$(sed -E 's/^"([0-9a-f]+)".*/\1/' staging-gate/token.map)
# 自签名占位证书时 -k;正式证书换上以后同样能过
C=(curl -sk -m 15 --resolve "$HOST:$PORT:127.0.0.1" -H "Cookie: sz_staging_gate=$TOKEN")
URL="https://$HOST:$PORT"
# 本机转发的是 127.0.0.1:8443 → 虚拟机里 nginx 的 443;对外端口不是 8443 时按 8443 连
[ "$PORT" = 8443 ] || { C=(curl -sk -m 15 --connect-to "$HOST:$PORT:127.0.0.1:8443" -H "Cookie: sz_staging_gate=$TOKEN"); }

fail=0
ok() { echo "   ✓ $1"; }
bad() { echo "   ✗ $1"; fail=1; }
code() { "${C[@]}" -o /dev/null -w '%{http_code}' "$@"; }

[ "$(code "$URL/web/")" = 200 ] && ok "网页版 /web/" || bad "网页版 /web/ 打不开"
[ "$(code "$URL/web/main.dart.js")" = 200 ] && ok "网页版脚本" || bad "网页版 main.dart.js 打不开"
# 网页版编进去的接口地址必须是预发自己(编成生产的话,在预发上点的都落到生产上)
if "${C[@]}" "$URL/web/main.dart.js" | grep -qF "$BASE"; then
  ok "网页版接口地址是预发($BASE)"
else
  bad "网页版里没有预发接口地址 $BASE:可能编成了生产的"
fi
for p in /admin/ /merchant /dev; do
  s=$("${C[@]}" -o /dev/null -w '%{http_code}' -H 'Sec-Fetch-Dest: document' -H 'Accept: text/html' "$URL$p")
  case "$s" in 200|301|302) ok "后台 $p ($s)" ;; *) bad "后台 $p 返回 $s" ;; esac
done
FEAT=$("${C[@]}" "$URL/config" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("features"))' 2>/dev/null || true)
[ -n "$FEAT" ] && ok "配置下发 features=$FEAT" || bad "/config 取不到"

# 开发配置:验证码随响应回显 → 用演示顾客登录 → 看得到演示店
DEV=$("${C[@]}" -H 'Content-Type: application/json' -d '{"phone":"13800000001"}' "$URL/auth/sms-code" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("dev_code",""))' 2>/dev/null || true)
if [ -n "$DEV" ]; then
  ok "验证码直接回显(开发配置)"
  TK=$("${C[@]}" -H 'Content-Type: application/json' \
    -d "{\"phone\":\"13800000001\",\"code\":\"$DEV\",\"role\":\"customer\"}" "$URL/auth/sms-login" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' 2>/dev/null || true)
  if [ -n "$TK" ]; then
    ok "演示顾客 13800000001 登录"
    N=$("${C[@]}" -H "Authorization: Bearer $TK" "$URL/merchants" \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d if isinstance(d, list) else d.get("items", [])))' 2>/dev/null || echo 0)
    [ "${N:-0}" -gt 0 ] && ok "首页店铺 $N 家(带着门禁 cookie 和 Bearer 两样一起过)" || bad "首页一家店都没有"
  else
    bad "验证码登录失败"
  fi
else
  bad "验证码没有回显:.env.staging 的 APP_ENV 不是 dev?"
fi
exit $fail
