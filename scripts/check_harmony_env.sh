#!/bin/bash
# 鸿蒙开发环境自检:装完 DevEco Studio 之后跑一次,确认能不能开始编 .hap。
#
# 为什么要这个脚本:DevEco 的命令行工具不在 PATH 里,而且 SDK 版本、
# 签名配置这些缺一样就编不出包,报错还不一定说得清缺的是哪一样。
# 与其在 IDE 里点半天,不如一次性把该有的都验一遍。
#
# 用法:bash scripts/check_harmony_env.sh
set -u

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)/apps/user_app_harmony"
DEVECO="/Applications/DevEco-Studio.app"
TOOLS="$DEVECO/Contents/tools"
OK=0
FAIL=0

say_ok()   { echo "  ✓ $1"; OK=$((OK+1)); }
say_fail() { echo "  ✗ $1"; FAIL=$((FAIL+1)); }

echo "== 1. DevEco Studio =="
if [ -d "$DEVECO" ]; then
  VER=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" \
        "$DEVECO/Contents/Info.plist" 2>/dev/null || echo "未知")
  say_ok "已安装($VER)"
else
  say_fail "没找到 $DEVECO —— 去 developer.huawei.com 下 Mac(ARM) 版"
fi

echo "== 2. 命令行工具 =="
# hvigorw 是构建器,ohpm 是包管理器,hdc 是设备调试。
# 它们随 DevEco 一起装,但**默认不在 PATH 里**
for t in hvigorw ohpm hdc node; do
  if command -v "$t" >/dev/null 2>&1; then
    say_ok "$t 在 PATH 里($(command -v "$t"))"
  elif [ -x "$TOOLS/$t/bin/$t" ] || [ -x "$TOOLS/$t" ]; then
    say_ok "$t 随 DevEco 装了,但不在 PATH(见文末提示)"
  else
    say_fail "$t 没找到"
  fi
done

echo "== 3. HarmonyOS SDK =="
# 默认落在 ~/Library/Huawei/Sdk 或 DevEco 的 sdk 目录
SDK_DIRS=("$HOME/Library/Huawei/Sdk" "$HOME/Library/OpenHarmony/Sdk" "$DEVECO/Contents/sdk")
FOUND_SDK=""
for d in "${SDK_DIRS[@]}"; do
  [ -d "$d" ] && FOUND_SDK="$d" && break
done
if [ -n "$FOUND_SDK" ]; then
  say_ok "SDK 目录:$FOUND_SDK"
  # 工程目标是 API 20(HarmonyOS 6),下探兼容到 12
  if ls "$FOUND_SDK" 2>/dev/null | grep -qE "^(20|HarmonyOS-NEXT|hms)" ; then
    say_ok "看起来有 API 20 相关目录"
  else
    echo "    · 已装的:$(ls "$FOUND_SDK" 2>/dev/null | tr '\n' ' ')"
    say_fail "没看到 API 20 —— 在 DevEco 的 SDK Manager 里补装"
  fi
else
  say_fail "没找到 SDK —— 首次启动 DevEco 时跟向导装一次"
fi

echo "== 4. 工程本身 =="
if [ -f "$APP_DIR/build-profile.json5" ] && [ -f "$APP_DIR/entry/src/main/module.json5" ]; then
  say_ok "工程在 $APP_DIR"
else
  say_fail "工程文件不完整"
fi
if [ -d "$APP_DIR/oh_modules" ]; then
  say_ok "依赖已同步(oh_modules 存在)"
else
  echo "    · 还没同步依赖,首次在 DevEco 里打开会自动做"
fi

echo
echo "-- 通过 $OK 项,失败 $FAIL 项 --"
if [ "$FAIL" -gt 0 ]; then
  cat <<'TIP'

把命令行工具加进 PATH(加到 ~/.zshrc,新开终端生效):

  export DEVECO_HOME="/Applications/DevEco-Studio.app/Contents"
  export PATH="$DEVECO_HOME/tools/ohpm/bin:$DEVECO_HOME/tools/hvigor/bin:$DEVECO_HOME/sdk/default/openharmony/toolchains:$PATH"

加完之后 hvigorw / ohpm / hdc 就能直接用,不用开 IDE 也能编包和装机。
TIP
  exit 1
fi

echo "环境齐了。接下来可以在工程目录下直接编包:"
echo "  cd $APP_DIR && hvigorw assembleHap --mode module -p product=default"
exit 0
