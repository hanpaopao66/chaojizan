#!/bin/bash
# 打用户端的应用商店包(单门店版),并核对最终 APK 的权限清单。
#
# 用法:scripts/build_store_user.sh <版本名> <build号>
#      例:scripts/build_store_user.sh 0.25.0 2068
#   TENCENT_MAP_KEY=xxx 可选(同 release_apks.sh)
#
# 单门店版是什么、为什么是编译期:packages/shared/lib/src/edition.dart。
# 和 release_apks.sh 的区别:那个脚本发官网直链包、顺带出三端商店包;这个只出用户端商店包,
# 不碰部署机、不改 versions.json,打完留在 build/store-apks/ 等人工提交。
#
# 打完会核对三件事,任何一件不对就中止(核的是**最终 APK**,不是源码里的清单 ——
# 插件经清单合并夹带的权限只在最终 APK 里看得到):
#   1. 没有应用内安装权限 REQUEST_INSTALL_PACKAGES(商店禁止绕过审核自更新);
#   2. 没有相机、麦克风、蓝牙权限(单门店版用不到,隐私政策附录也写了不申请);
#   3. 没有认领 chaojizan.cc/m/ 的小程序直达链接。
set -e
cd "$(dirname "$0")/.."

VERSION=${1:?用法: build_store_user.sh <版本名> <build号>}
BUILD=${2:?缺 build 号}
[ -f deploy/.env.deploy ] && . deploy/.env.deploy
API=${PUBLIC_BASE:-https://chaojizan.cc}
OUT_DIR=build/store-apks
OUT="$OUT_DIR/chaojizan-user-single-store-v$VERSION+$BUILD-arm64.apk"
mkdir -p "$OUT_DIR"

echo "== 打包用户端单门店版 v$VERSION+$BUILD(应用商店包,API=$API) =="
(cd apps/user_app && flutter build apk --release \
    --target-platform android-arm64 \
    --build-name="$VERSION" --build-number="$BUILD" \
    --obfuscate --split-debug-info=build/symbols/store-single-$VERSION+$BUILD \
    -PSUPERZ_CHANNEL=store -PSUPERZ_EDITION=single \
    --dart-define=SUPERZ_CHANNEL=store \
    --dart-define=SUPERZ_EDITION=single \
    --dart-define=SUPERZ_API=$API \
    --dart-define=SUPERZ_ICP=陕ICP备2025064101号-5 \
    --dart-define=TENCENT_MAP_KEY=${TENCENT_MAP_KEY:-} | grep -E "apk|Built")
cp apps/user_app/build/app/outputs/flutter-apk/app-release.apk "$OUT"

scripts/check_store_apk.sh "$OUT" "$BUILD"
echo "商店包:$OUT"
