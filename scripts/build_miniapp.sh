#!/usr/bin/env bash
# 构建一个官方小程序并打成可复现的 zip(DEV-PROMPTS-39 #327 #328)。
#
#   bash scripts/build_miniapp.sh notepad     # → miniapps/notepad/dist/notepad.zip
#   bash scripts/build_miniapp.sh 2048        # → miniapps/2048/dist/2048.zip
#   bash scripts/build_miniapp.sh snake       # → miniapps/snake/dist/snake.zip
#   bash scripts/build_miniapp.sh blocks      # → miniapps/blocks/dist/blocks.zip
#   bash scripts/build_miniapp.sh minesweeper # → miniapps/minesweeper/dist/minesweeper.zip
#   bash scripts/build_miniapp.sh gomoku      # → miniapps/gomoku/dist/gomoku.zip
#   bash scripts/build_miniapp.sh critters    # → miniapps/critters/dist/critters.zip(萌兽三路)
#   bash scripts/build_miniapp.sh sandbox     # → miniapps/sandbox/dist/sandbox.zip(方块原野)
#   bash scripts/build_miniapp.sh cards       # → miniapps/cards/dist/cards.zip(星火牌局)
#   bash scripts/build_miniapp.sh tactical    # → miniapps/tactical/dist/tactical.zip(突击时刻)
#   bash scripts/build_miniapp.sh tower       # → miniapps/tower/dist/tower.zip(瓜田防线:塔防)
#
# 打印的 SHA-256 应该和线上详情页公示的一致。上传用 server/scripts/publish_official_miniapp.py。
set -euo pipefail
app="${1:?用法:build_miniapp.sh <notepad|2048|snake|blocks|minesweeper|gomoku|critters|sandbox|cards|tactical|tower>}"
root="$(cd "$(dirname "$0")/.." && pwd)"
dir="$root/miniapps"
[ -d "$dir/$app" ] || { echo "没有 miniapps/$app"; exit 1; }
if [ ! -x "$dir/node_modules/.bin/vite" ]; then
  (cd "$dir" && npm ci --no-audit --no-fund --registry https://registry.npmmirror.com >/dev/null)
fi
# 类型检查是全局的(几个小程序共用 shared 和 SDK),单测只跑**这个**应用的:
# 打包一个应用不该要求别的应用此刻也是绿的 —— 全量单测在 CI / make analyze 里跑。
# (并行开发时全量会把别人还没写完的用例一起带上,红的没意义。)
(cd "$dir" && node_modules/.bin/tsc -p . \
  && node scripts/test.mjs "$app" >/dev/null \
  && node_modules/.bin/vite build --mode "$app" --logLevel warn)
sha="$(python3 "$root/scripts/zip_reproducible.py" "$dir/$app/dist/pkg" "$dir/$app/dist/$app.zip")"
size="$(wc -c < "$dir/$app/dist/$app.zip" | tr -d ' ')"
echo "miniapps/$app/dist/$app.zip  $size 字节  SHA-256 $sha"
