#!/bin/bash
# 一键发版:三端打包 → 传部署机 appdist → 更新 versions.json
# 旧版 App 打开即弹「发现新版本」,点击更新浏览器下载,覆盖安装(同签名+build 递增)。
#
# 用法:TENCENT_MAP_KEY=xxx scripts/release_apks.sh 0.3.0 3 "更新说明一句话"
#      (可省;省略时配送地图退化为品牌网格示意,方位与距离仍真实)
#      SKIP_STORE=1 只出官网直链包(默认直链包 + 商店包都出,共 6 个)
#   $1 版本名(versionName)  $2 build 号(必须递增!)  $3 更新说明
#
# 版本门禁(两个都是环境变量,默认与从前一致,不传就是老行为):
#   FORCE=1        这一版强制更新(versions.json 的 force=true)
#   MIN_BUILD=<n>  低于这个 build 的客户端视为过旧
#
# 这两个字段以前在脚本里**写死成 False / 根本不存在**,于是
# "强制更新"这个能力名义上有、实际上永远关着,想用还得改脚本再发一次版。
# 例:MIN_BUILD=8 FORCE=1 scripts/release_apks.sh 0.13.0 14 "修了支付回调"
#
# 两种产物不能混(#192):
#   官网直链包 build/release-apks/chaojizan-<端>-arm64.apk
#       —— 带应用内自更新,上传部署机 appdist,versions.json 指向它;
#   商店包     build/store-apks/chaojizan-<端>-store-v<版本>+<build>-arm64.apk
#       —— 清单里摘掉 REQUEST_INSTALL_PACKAGES、App 内更新检查关闭,
#          只留在本地等人工提交各应用商店,**绝不上传 appdist**。
set -e
cd "$(dirname "$0")/.."

VERSION=${1:?用法: release_apks.sh <版本名> <build号> <更新说明>}
BUILD=${2:?缺 build 号}
NOTES=${3:?缺更新说明}
# 门禁参数。默认 false / 0 = 与改造前完全一致的行为
FORCE_JSON=false
[ "${FORCE:-0}" = "1" ] && FORCE_JSON=true
MIN_BUILD=${MIN_BUILD:-0}
# 早点炸:min_build 比本次 build 还大的话,新包自己都过不了门禁,
# 而这个错误要等用户更新完打不开才会被发现
case "$MIN_BUILD" in
  ''|*[!0-9]*) echo "✗ MIN_BUILD 必须是数字,收到:$MIN_BUILD"; exit 1;;
esac
[ "$MIN_BUILD" -le "$BUILD" ] || {
  echo "✗ MIN_BUILD($MIN_BUILD) 大于本次 build($BUILD),这会把新版自己也挡在门外"
  exit 1; }
[ -f deploy/.env.deploy ] && . deploy/.env.deploy
API=${PUBLIC_BASE:?缺对外域名:在 deploy/.env.deploy 写 PUBLIC_BASE=https://域名(不入库)}
DEPLOY=${DEPLOY:?缺部署机地址:在 deploy/.env.deploy 写 DEPLOY=user@host(不入库)}

SELF_DIR=build/release-apks
STORE_DIR=build/store-apks
rm -rf "$SELF_DIR" "$STORE_DIR"
mkdir -p "$SELF_DIR"

# $1 = 端(user/merchant/rider),$2 = 渠道(self/store)
build_apk() {
  local app=$1 channel=$2 GRADLE_ARG=
  # store 渠道要两边一起传:-P 给 Gradle(摘权限),--dart-define 给 Dart
  # (关更新检查,见 shared/update_checker.dart)。少传一边就是个半成品
  [ "$channel" = store ] && GRADLE_ARG=-PSUPERZ_CHANNEL=store
  # obfuscate+split-debug-info:Dart 代码混淆并剥离符号(瘦 ~2MB/端);
  # 崩溃堆栈用 build/symbols/<渠道>-<version> 里的符号表还原(flutter symbolize)。
  # 符号表按渠道分目录:两次构建的混淆映射不一样,共用一个目录会被后一次覆盖,
  # 到时候拿商店包的符号表去还原直链包的堆栈,还原出来的是错的
  # 注意:用 --target-platform 出单 arm64 包,不用 --split-per-abi ——
  # split 会给 versionCode 加 ABI 偏移(arm64 = 2000+build),而应用内更新
  # 检查拿 versionCode 和 versions.json 的 build 平码比较,偏移会让
  # 已装用户永远收不到更新提示(历史版本 2003/2004 都是平码)
  (cd apps/${app}_app && flutter build apk --release \
      --target-platform android-arm64 \
      --build-name="$VERSION" --build-number="$BUILD" \
      --obfuscate --split-debug-info=build/symbols/$channel-$VERSION+$BUILD \
      $GRADLE_ARG \
      --dart-define=SUPERZ_CHANNEL=$channel \
      --dart-define=SUPERZ_API=$API \
      --dart-define=SUPERZ_ICP=陕ICP备2025064101号-5 \
      --dart-define=TENCENT_MAP_KEY=${TENCENT_MAP_KEY:-} | grep -E "apk|Built")
}

# 两个渠道的产物都叫 app-release.apk,后打的会盖掉先打的 —— 打完立刻拷走
for app in user merchant rider; do
  echo "== 打包 ${app}_app v$VERSION+$BUILD(官网直链包) =="
  build_apk $app self
  cp apps/${app}_app/build/app/outputs/flutter-apk/app-release.apk \
      "$SELF_DIR/chaojizan-${app}-arm64.apk"
done

if [ -z "${SKIP_STORE:-}" ]; then
  mkdir -p "$STORE_DIR"
  for app in user merchant rider; do
    echo "== 打包 ${app}_app v$VERSION+$BUILD(应用商店包) =="
    build_apk $app store
    # 商店包是人工提交的,文件名带上版本便于存档;直链包的名字要和线上
    # URL 一字不差(versions.json 里写死),所以那边反而不能带版本号
    cp apps/${app}_app/build/app/outputs/flutter-apk/app-release.apk \
        "$STORE_DIR/chaojizan-${app}-store-v$VERSION+$BUILD-arm64.apk"
  done
fi

AAPT=$(ls "$HOME"/Library/Android/sdk/build-tools/*/aapt2 2>/dev/null | tail -1)

echo "== 校验 versionCode 平码(防更新检查失灵) =="
if [ -n "$AAPT" ]; then
  for app in user merchant rider; do
    CODE=$("$AAPT" dump badging "$SELF_DIR/chaojizan-${app}-arm64.apk" | head -1 | sed -n 's/.*versionCode=.\([0-9]*\).*/\1/p')
    [ "$CODE" = "$BUILD" ] || { echo "✗ ${app} versionCode=$CODE ≠ build=$BUILD,中止"; exit 1; }
  done
  echo "  三端 versionCode == $BUILD ✓"
fi

echo "== 校验渠道权限(#192:商店包不许带安装权限) =="
if [ -n "$AAPT" ]; then
  has_install_perm() {
    "$AAPT" dump permissions "$1" | grep -q "android.permission.REQUEST_INSTALL_PACKAGES"
  }
  for app in user merchant rider; do
    has_install_perm "$SELF_DIR/chaojizan-${app}-arm64.apk" || {
      echo "✗ ${app} 直链包没有 REQUEST_INSTALL_PACKAGES,应用内安装会失败,中止"; exit 1; }
    if [ -z "${SKIP_STORE:-}" ]; then
      ! has_install_perm "$STORE_DIR/chaojizan-${app}-store-v$VERSION+$BUILD-arm64.apk" || {
        echo "✗ ${app} 商店包仍带 REQUEST_INSTALL_PACKAGES —— 上架必被驳回,中止"; exit 1; }
    fi
  done
  echo "  直链包带安装权限、商店包已摘除 ✓"
else
  echo "  ⚠️ 找不到 aapt2,跳过权限核对 —— 提交商店前务必手工确认"
fi

echo "== 计算 SHA-256(应用内安装要用它校验,不校验等于给中间人开口子) =="
# 不用关联数组:macOS 自带的是 bash 3.2,declare -A 直接报错
apk_path() { echo "$SELF_DIR/chaojizan-${1}-arm64.apk"; }
SHA_user=$(shasum -a 256 "$(apk_path user)" | awk '{print $1}')
SHA_merchant=$(shasum -a 256 "$(apk_path merchant)" | awk '{print $1}')
SHA_rider=$(shasum -a 256 "$(apk_path rider)" | awk '{print $1}')
for app in user merchant rider; do
  eval "echo \"  ${app}: \$SHA_${app}\""
done

echo "== 上传 APK 到部署机(只传直链包,商店包留在本地) =="
ssh $DEPLOY 'mkdir -p ~/super-z/appdist'
for app in user merchant rider; do
  scp -q "$(apk_path $app)" \
      $DEPLOY:~/super-z/appdist/chaojizan-${app}-arm64.apk
  echo "  chaojizan-${app}-arm64.apk ✓"
done

echo "== 复核部署机上的文件哈希(传输途中出错就在这里拦下) =="
for app in user merchant rider; do
  REMOTE=$(ssh $DEPLOY "shasum -a 256 ~/super-z/appdist/chaojizan-${app}-arm64.apk | awk '{print \$1}'")
  eval "LOCAL=\$SHA_${app}"
  [ "$REMOTE" = "$LOCAL" ] || { echo "✗ ${app} 上传后哈希不符,中止"; exit 1; }
done
echo "  三端哈希一致 ✓"

# 见证节点绿色版:构建过就顺带上传(scripts/build_witness_dist.sh 生成)
if [ -d build/witness-dist ]; then
  echo "== 上传见证节点绿色版 =="
  ssh $DEPLOY 'mkdir -p ~/super-z/appdist/witness'
  scp -q "build/witness-dist/chaojizan-witness-windows.exe" \
      "build/witness-dist/chaojizan-witness-macos.zip" \
      "build/witness-dist/chaojizan-witness-linux.tar.gz" \
      $DEPLOY:'~/super-z/appdist/witness/'
  echo "  绿色版 ×3 ✓"
fi

echo "== 更新 versions.json =="
ssh $DEPLOY "python3 - << EOF
import json
shas = {'user': '$SHA_user', 'merchant': '$SHA_merchant',
        'rider': '$SHA_rider'}
data = {}
for app in ['user', 'merchant', 'rider']:
    data[app] = {
        'version': '$VERSION',
        'build': $BUILD,
        'url': '$API/appdist/chaojizan-' + app + '-arm64.apk',
        'notes': '''$NOTES''',
        # force:这一版是否强制更新(发版当时的一次性决定)
        'force': $FORCE_JSON,
        # min_build:低于它的客户端视为过旧(**持续有效**的下限,与 force 不同)。
        # 服务端 /app/latest 原样透出,当前只用于观测,不拦截
        'min_build': $MIN_BUILD,
        # 应用内安装前用它校验;缺这个字段客户端会退回浏览器下载(#123)
        'sha256': shas[app],
    }
import os
open(os.path.expanduser('~/super-z/appdist/versions.json'), 'w').write(
    json.dumps(data, ensure_ascii=False, indent=2))
print('versions.json -> v$VERSION build $BUILD')
EOF"

echo "== 验证 =="
curl -s -m 10 --noproxy '*' "$API/app/latest?app=user" | head -c 200; echo
echo "发版完成 🎉 旧版用户打开 App 即会收到更新提示"

if [ -z "${SKIP_STORE:-}" ]; then
  echo
  echo "== 商店包(不含自更新,提交应用商店用;没上传、也不该上传) =="
  ls -1 "$STORE_DIR"
fi
