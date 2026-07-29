#!/usr/bin/env bash
# 走查截图:release 构建 gallery → 静态服务 → 无头 Chrome 出浅色/深色两张 PNG。
#
#   packages/shared/example/tool/shot.sh <输出名> [宽] [高]
#   例:packages/shared/example/tool/shot.sh design_tokens 560 2300
#      → marketing/design/screens/design_tokens_light.png
#        marketing/design/screens/design_tokens_dark.png
#
# 用 release 不用 `flutter run`:debug 的 web 产物是 DDC 分片,
# main.dart.js 只是几 KB 的引导器,没法判断"编完了没",拍出来是白页。
# 第八辑每条任务的验收都要交这两张图(见 docs/DEV-PROMPTS-8.md)。
set -euo pipefail

NAME="${1:?用法: tool/shot.sh <输出名> [宽] [高]}"
W="${2:-560}"
H="${3:-2300}"
PORT="${PORT:-5599}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

cd "$(dirname "$0")/.."
ROOT="$(cd ../../.. && pwd)"
OUT="$ROOT/marketing/design/screens"
mkdir -p "$OUT"

echo "== 构建 gallery(release web)=="
flutter build web --release --no-web-resources-cdn > /tmp/superz_gallery_build.log 2>&1 \
  || { tail -30 /tmp/superz_gallery_build.log; exit 1; }

echo "== 静态服务 :$PORT =="
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory build/web \
  > /tmp/superz_gallery_serve.log 2>&1 &
SERVE_PID=$!
trap 'kill $SERVE_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -sf -m 2 -o /dev/null "http://127.0.0.1:$PORT/" && break
  sleep 1
done

for mode in light dark; do
  q=""
  [ "$mode" = dark ] && q="?dark=1"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --virtual-time-budget=12000 --window-size="$W,$H" \
    --screenshot="$OUT/${NAME}_${mode}.png" \
    "http://127.0.0.1:$PORT/index.html$q" > /dev/null 2>&1
  bytes=$(stat -f%z "$OUT/${NAME}_${mode}.png")
  # 全白页压出来只有几 KB,基本等于没拍到——直接判失败,别让空图混进验收
  [ "$bytes" -gt 20000 ] || { echo "截图疑似空白($bytes 字节): ${NAME}_${mode}"; exit 1; }
  echo "已出图 ${NAME}_${mode}.png($bytes 字节)"
done
