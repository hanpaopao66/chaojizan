#!/bin/bash
# 一键发版:三端打包 → 传部署机 appdist → 更新 versions.json
# 旧版 App 打开即弹「发现新版本」,点击更新浏览器下载,覆盖安装(同签名+build 递增)。
#
# 用法:TIANDITU_KEY=xxx scripts/release_apks.sh 0.3.0 3 "更新说明一句话"
#      (TIANDITU_KEY 可省;省略时配送地图为示意模式,见 docs/AMAP_SETUP.md)
#   $1 版本名(versionName)  $2 build 号(必须递增!)  $3 更新说明
set -e
cd "$(dirname "$0")/.."

VERSION=${1:?用法: release_apks.sh <版本名> <build号> <更新说明>}
BUILD=${2:?缺 build 号}
NOTES=${3:?缺更新说明}
[ -f deploy/.env.deploy ] && . deploy/.env.deploy
API=${PUBLIC_BASE:?缺对外域名:在 deploy/.env.deploy 写 PUBLIC_BASE=https://域名(不入库)}
DEPLOY=${DEPLOY:?缺部署机地址:在 deploy/.env.deploy 写 DEPLOY=user@host(不入库)}

for app in user merchant rider; do
  echo "== 打包 ${app}_app v$VERSION+$BUILD =="
  # obfuscate+split-debug-info:Dart 代码混淆并剥离符号(瘦 ~2MB/端);
  # 崩溃堆栈用 build/symbols/<app>-<version> 里的符号表还原(flutter symbolize)。
  # 注意:用 --target-platform 出单 arm64 包,不用 --split-per-abi ——
  # split 会给 versionCode 加 ABI 偏移(arm64 = 2000+build),而应用内更新
  # 检查拿 versionCode 和 versions.json 的 build 平码比较,偏移会让
  # 已装用户永远收不到更新提示(历史版本 2003/2004 都是平码)
  (cd apps/${app}_app && flutter build apk --release \
      --target-platform android-arm64 \
      --build-name="$VERSION" --build-number="$BUILD" \
      --obfuscate --split-debug-info=build/symbols/$VERSION+$BUILD \
      --dart-define=SUPERZ_API=$API \
      --dart-define=SUPERZ_ICP=陕ICP备2025064101号-5 \
      --dart-define=TIANDITU_KEY=${TIANDITU_KEY:-} | grep -E "apk|Built")
done

echo "== 校验 versionCode 平码(防更新检查失灵) =="
AAPT=$(ls "$HOME"/Library/Android/sdk/build-tools/*/aapt2 2>/dev/null | tail -1)
if [ -n "$AAPT" ]; then
  for app in user merchant rider; do
    CODE=$("$AAPT" dump badging apps/${app}_app/build/app/outputs/flutter-apk/app-release.apk | head -1 | sed -n 's/.*versionCode=.\([0-9]*\).*/\1/p')
    [ "$CODE" = "$BUILD" ] || { echo "✗ ${app} versionCode=$CODE ≠ build=$BUILD,中止"; exit 1; }
  done
  echo "  三端 versionCode == $BUILD ✓"
fi

echo "== 计算 SHA-256(应用内安装要用它校验,不校验等于给中间人开口子) =="
# 不用关联数组:macOS 自带的是 bash 3.2,declare -A 直接报错
apk_path() { echo "apps/${1}_app/build/app/outputs/flutter-apk/app-release.apk"; }
SHA_user=$(shasum -a 256 "$(apk_path user)" | awk '{print $1}')
SHA_merchant=$(shasum -a 256 "$(apk_path merchant)" | awk '{print $1}')
SHA_rider=$(shasum -a 256 "$(apk_path rider)" | awk '{print $1}')
for app in user merchant rider; do
  eval "echo \"  ${app}: \$SHA_${app}\""
done

echo "== 上传 APK 到部署机 =="
ssh $DEPLOY 'mkdir -p ~/super-z/appdist'
for app in user merchant rider; do
  scp -q apps/${app}_app/build/app/outputs/flutter-apk/app-release.apk \
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
        'force': False,
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
