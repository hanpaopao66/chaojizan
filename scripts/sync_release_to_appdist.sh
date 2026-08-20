#!/bin/bash
# 把某个 GitHub Release 的 APK 原样同步到部署机 appdist，并更新 versions.json。
#
# 用法: scripts/sync_release_to_appdist.sh v0.12.1-b2052 "更新说明一句话"
#
# ## 为什么要有这个脚本
#
# #274 把发版的信任根从开发机换成了公开 CI：APK 由 release.yml 在公开 runner
# 上从 tag 构建，SHA-256 写进 Release 附件，Release 正文里写着
# 「官网下载页与应用内更新走 appdist 通道，由运维把**本页同一批产物**同步过去
#   —— 两边哈希应当一致，不一致请立刻开 issue」。
#
# 但当时只做到「CI 出包发 Release」，没人把那一批产物送到 appdist ——
# 而 release_apks.sh **永远本地重打**。用它去同步的话，appdist 上是开发机
# 编出来的另一份包，哈希和 Release 页对不上，等于自己打脸自己写的那句话。
#
# 所以这个脚本只做搬运，不碰编译器：
#   下载 Release 附件 → 用附件里的 SHA256SUMS.txt 核一遍 → scp 到 appdist
#   → 落地再核一遍 → 写 versions.json。
#
# ## 前提
#
#   - release.yml 已经跑完并发布了该 tag 的 Release（gh release view 能看到）；
#   - 本机在部署机同一网段（LAN-only，见 deploy/.env.deploy）。
set -eo pipefail
cd "$(dirname "$0")/.."

TAG=${1:?用法: sync_release_to_appdist.sh <tag，如 v0.12.1-b2052> <更新说明>}
NOTES=${2:?缺更新说明（会写进 versions.json，旧版 App 的更新弹窗里显示）}

[ -f deploy/.env.deploy ] && . deploy/.env.deploy
API=${PUBLIC_BASE:?缺 PUBLIC_BASE：写在 deploy/.env.deploy（不入库）}
DEPLOY=${DEPLOY:?缺 DEPLOY=user@host：写在 deploy/.env.deploy（不入库）}
REPO=$(git remote get-url origin | sed -E 's#.*[:/]([^/]+/[^/]+)(\.git)?$#\1#')

# tag 形如 v0.12.1-b2052 —— 版本号和 build 号都从它解析，
# 不另外传参：两处各写一遍迟早会写岔，而写岔的后果是
# versions.json 说 build 2052、APK 里其实是 2051，已装用户永远收不到更新
VERSION="${TAG#v}"; VERSION="${VERSION%-b*}"
BUILD="${TAG##*-b}"
echo "$BUILD" | grep -qE '^[0-9]+$' || { echo "✗ tag 里解析不出 build 号：$TAG"; exit 1; }
echo "== 同步 $TAG（版本 $VERSION，build $BUILD）=="

# 先探部署机通不通。LAN-only，换个网段就发不了，
# 别烧满 SSH 超时再死在 scp 中途（deploy_server.sh 同款预检）
HOST=${DEPLOY#*@}
if ! nc -z -G 5 "$HOST" 22 2>/dev/null; then
  echo "✗ 连不上部署机 $HOST:22。"
  echo "  发版是 LAN-only —— 接回部署机所在网段或连上 VPN 再来。"
  echo "  线上不受影响，还是原来那版。"
  exit 1
fi

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

echo "== 下载 Release 附件 =="
gh release download "$TAG" -R "$REPO" -D "$WORK" \
  -p 'chaojizan-*-arm64.apk' -p 'SHA256SUMS.txt'

echo "== 核对 CI 写下的 SHA-256（下载途中坏了在这里拦）=="
( cd "$WORK" && shasum -a 256 -c SHA256SUMS.txt ) || {
  echo "✗ 附件哈希和 SHA256SUMS.txt 对不上，中止"; exit 1; }

for app in user merchant rider; do
  [ -f "$WORK/chaojizan-${app}-arm64.apk" ] || {
    echo "✗ Release 里没有 chaojizan-${app}-arm64.apk"; exit 1; }
done

# versionCode 必须和 tag 里的 build 平码。CI 已经验过一道，
# 这里再验一道是因为**搬运的是文件不是信任**：万一 tag 和附件对不上
# （手工传过附件、Release 被编辑过），错的包一旦进了 appdist，
# 已装用户就再也收不到更新提示了
if command -v aapt2 >/dev/null 2>&1 || [ -n "${ANDROID_HOME:-}" ]; then
  AAPT=$(command -v aapt2 || ls "$ANDROID_HOME"/build-tools/*/aapt2 2>/dev/null | tail -1)
  if [ -n "$AAPT" ]; then
    for app in user merchant rider; do
      CODE=$("$AAPT" dump badging "$WORK/chaojizan-${app}-arm64.apk" \
             | head -1 | sed -n "s/.*versionCode='\([0-9]*\)'.*/\1/p")
      [ "$CODE" = "$BUILD" ] || {
        echo "✗ ${app} 包里 versionCode=$CODE，而 tag 说 build=$BUILD"; exit 1; }
    done
    echo "  versionCode 平码 ✓"
  fi
else
  echo "  (本机没有 aapt2，跳过 versionCode 复核 —— CI 那道闸已经验过)"
fi

echo "== 上传到部署机 appdist =="
ssh "$DEPLOY" 'mkdir -p ~/super-z/appdist'
for app in user merchant rider; do
  scp -q "$WORK/chaojizan-${app}-arm64.apk" \
      "$DEPLOY:~/super-z/appdist/chaojizan-${app}-arm64.apk"
  echo "  chaojizan-${app}-arm64.apk ✓"
done

echo "== 复核落地哈希（传输途中出错在这里拦）=="
declare -A SHA
for app in user merchant rider; do
  LOCAL=$(shasum -a 256 "$WORK/chaojizan-${app}-arm64.apk" | awk '{print $1}')
  REMOTE=$(ssh "$DEPLOY" "shasum -a 256 ~/super-z/appdist/chaojizan-${app}-arm64.apk | awk '{print \$1}'")
  [ "$REMOTE" = "$LOCAL" ] || { echo "✗ ${app} 上传后哈希不符，中止"; exit 1; }
  SHA[$app]=$LOCAL
done
echo "  三端哈希一致 ✓（且与 Release 页同值）"

echo "== 更新 versions.json =="
ssh "$DEPLOY" "python3 - << 'PYEOF'
import json, os
shas = {'user': '${SHA[user]}', 'merchant': '${SHA[merchant]}',
        'rider': '${SHA[rider]}'}
data = {}
for app in ['user', 'merchant', 'rider']:
    data[app] = {
        'version': '$VERSION',
        'build': $BUILD,
        'url': '$API/appdist/chaojizan-' + app + '-arm64.apk',
        'notes': '''$NOTES''',
        'force': False,
        # 应用内安装前用它校验；缺这个字段客户端会退回浏览器下载（#123）
        'sha256': shas[app],
    }
open(os.path.expanduser('~/super-z/appdist/versions.json'), 'w').write(
    json.dumps(data, ensure_ascii=False, indent=2))
print('versions.json -> v$VERSION build $BUILD')
PYEOF"

echo "== 验证 =="
curl -s -m 10 --noproxy '*' "$API/app/latest?app=user" | head -c 240; echo
echo
echo "同步完成 ✓ 旧版用户打开 App 即会收到更新提示"
echo "  appdist 上的包 = Release $TAG 的同一批产物，两边 SHA-256 一致。"
