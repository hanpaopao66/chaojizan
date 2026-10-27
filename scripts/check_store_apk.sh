#!/bin/bash
# 核对用户端单门店版商店包的最终 APK(build_store_user.sh、release_apks.sh 都调它)。
#
# 用法:scripts/check_store_apk.sh <apk> [期望的 versionCode]
#
# 核的是最终 APK 而不是源码清单:插件(flutter_webrtc、record、mobile_scanner)经清单合并夹带的权限
# 只在最终 APK 里看得到。说明见 packages/shared/lib/src/edition.dart 与
# apps/user_app/android/app/src/single/AndroidManifest.xml。
set -e
APK=${1:?用法: check_store_apk.sh <apk> [versionCode]}
WANT_CODE=${2:-}
AAPT=$(ls "$HOME"/Library/Android/sdk/build-tools/*/aapt2 2>/dev/null | tail -1)
[ -n "$AAPT" ] || { echo "✗ 找不到 aapt2,没法核对权限 —— 提交商店前不能跳过这一步"; exit 1; }

if [ -n "$WANT_CODE" ]; then
  CODE=$("$AAPT" dump badging "$APK" | head -1 | sed -n 's/.*versionCode=.\([0-9]*\).*/\1/p')
  [ "$CODE" = "$WANT_CODE" ] || { echo "✗ versionCode=$CODE ≠ $WANT_CODE"; exit 1; }
  echo "  versionCode == $WANT_CODE ✓"
fi

PERMS=$("$AAPT" dump permissions "$APK")
BAD=""
for p in REQUEST_INSTALL_PACKAGES CAMERA RECORD_AUDIO MODIFY_AUDIO_SETTINGS \
         BLUETOOTH BLUETOOTH_ADMIN BLUETOOTH_CONNECT BLUETOOTH_SCAN \
         READ_CONTACTS READ_PHONE_STATE ACCESS_BACKGROUND_LOCATION \
         READ_EXTERNAL_STORAGE WRITE_EXTERNAL_STORAGE QUERY_ALL_PACKAGES; do
  echo "$PERMS" | grep -q "name='android.permission.$p'" && BAD="$BAD $p"
done
[ -z "$BAD" ] || { echo "✗ 单门店版不该有的权限:$BAD"; echo "$PERMS"; exit 1; }
echo "  没有应用内安装、相机、麦克风、蓝牙、通讯录、后台定位权限 ✓"

if "$AAPT" dump xmltree --file AndroidManifest.xml "$APK" | grep -q '"/m/"'; then
  echo "✗ 还认领着 chaojizan.cc/m/ 的小程序直达链接"; exit 1
fi
echo "  不认领小程序直达链接 ✓"

# 系统分享接收(收到后弹聊天会话选择):单门店版没有聊天,不该出现在系统分享面板里
if "$AAPT" dump xmltree --file AndroidManifest.xml "$APK" | grep -q 'android.intent.action.SEND'; then
  echo "✗ 还声明着接收系统分享(ACTION_SEND)"; exit 1
fi
echo "  不接收系统分享 ✓"

# 签名:必须是正式证书。没有 android/key.properties 的机器会悄悄回落 debug 签名(build.gradle.kts),
# 那个包装得上、跑得起来,提交商店却和 App 备案登记的证书指纹对不上(docs/STORE-REVIEW.md 第一节)
WANT_SHA256=e61ec79bae6b28fca8563bfd93bdea832b46e7214fa7412bf6c0dd581cd63249
APKSIGNER=$(ls "$HOME"/Library/Android/sdk/build-tools/*/apksigner 2>/dev/null | tail -1)
JBR="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
[ -z "${JAVA_HOME:-}" ] && [ -d "$JBR" ] && export JAVA_HOME="$JBR" PATH="$JBR/bin:$PATH"
[ -n "$APKSIGNER" ] || { echo "✗ 找不到 apksigner,没法核对签名"; exit 1; }
GOT_SHA256=$("$APKSIGNER" verify --print-certs "$APK" 2>&1 \
    | sed -n 's/.*certificate SHA-256 digest: *\([0-9a-f]*\).*/\1/p' | head -1)
[ -n "$GOT_SHA256" ] || { echo "✗ 读不出签名证书(apksigner 要 Java:设 JAVA_HOME)"; exit 1; }
[ "$GOT_SHA256" = "$WANT_SHA256" ] || {
  echo "✗ 签名证书不是正式证书(SHA-256 $GOT_SHA256)—— 这台机器多半没有 apps/user_app/android/key.properties"
  exit 1; }
echo "  正式签名(和 App 备案登记的证书指纹一致)✓"

echo "  最终权限清单:"
echo "$PERMS" | sed -n "s/.*name='android.permission.\([A-Z_]*\)'.*/    \1/p"
