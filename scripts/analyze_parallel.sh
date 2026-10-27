#!/bin/bash
# make analyze 里的重活,并行跑:四个 Dart 包的 analyze + 单测、扫转义美元符、三个网页项目的 tsc、
# 小程序 SDK 和官方小程序的测试、文档检查。检查项和原来串行时一项不少(CI「三端静态检查」也是这些)。
#
# 原来是一项接一项串着跑,整轮两分多钟,大半时间是在等前一个包跑完。
#
# ## 两条规矩(都是踩出来的)
#
# 1. **先统一 pub get,之后一律 --no-pub。**
#    `flutter test` 不带 --no-pub 会顺手 pub get、改写自己包的解析;而包解析一过期,analyze 会喷出几千条
#    「package:flutter/material.dart 不存在」—— 全是假的。串行的时候这件事靠「每个包先 pub get 再 analyze」
#    兜住;并行时别的包正跑着 analyze,解析在它脚下一变就是这几千条噪音。所以 pub get 单独一轮跑完,
#    后面的 analyze、test 都不许再动解析。
# 2. **同一个包的 analyze、单测、单门店版单测串在一个任务里。** 两次 flutter test 同时往同一个包的
#    build 目录写会打架;不同的包之间互不相干,可以并行。
#    试过把 analyze 和单测拆成两个任务同时跑(analyze 只读,不打架):10 核的机器上 15 个任务抢 CPU,
#    反而从 71s 慢到 77s —— 并行的粒度到「一个包一个任务」为止。
#
# ## 为什么单测也在这儿
#
# CI 的「三端静态检查」里有独立的一步 `dart 单测`,而本地 make analyze 原来只跑 analyze —— 于是「本地全绿」
# 和「CI 通过」之间一直差着几百条测试。实际撞过一次:改了商家端订单卡的「⋯」菜单,analyze 干净、
# 全套 e2e 干净、推上去被 CI 里的 order_tab_test 顶回来。analyze 只看类型,测试才看行为。
#
# 每个任务的输出各写一份日志,全部跑完按固定顺序报:成功的一行,失败的整份日志打出来。
# 有一个失败退出码就是 1 —— 不在第一个失败处停,一次看全。
set -u
cd "$(dirname "$0")/.."

OUT=$(mktemp -d "${TMPDIR:-/tmp}/sz-analyze.XXXXXX")
trap 'rm -rf "$OUT"' EXIT
DART_PKGS="packages/shared apps/user_app apps/merchant_app apps/rider_app"
T0=$SECONDS

echo "== flutter pub get(四个包一起)=="
PIDS=""
for d in $DART_PKGS; do
  (cd "$d" && flutter pub get) > "$OUT/pub-$(echo "$d" | tr / _).log" 2>&1 &
  PIDS="$PIDS $!"
done
FAIL=0
for p in $PIDS; do wait "$p" || FAIL=1; done
if [ "$FAIL" -ne 0 ]; then
  cat "$OUT"/pub-*.log
  echo "✗ flutter pub get 失败"
  exit 1
fi
echo "  ✓ ($((SECONDS - T0))s)"

# 一个 Dart 包:analyze → 单测 →(用户端)单门店版单测
dart_pkg() {
  cd "$1" || return 1
  echo "-- flutter analyze"
  flutter analyze --no-pub || return 1
  # 没有 test 目录的包跳过,不当失败
  if [ -n "$(find test -name '*_test.dart' 2>/dev/null)" ]; then
    echo "-- flutter test"
    flutter test --no-pub || return 1
  fi
  # 用户端单门店版(应用商店包,packages/shared/lib/src/edition.dart)靠编译期常量收起入口,
  # 它的测试要带着那个常量跑;上面那一轮不带参数的 flutter test 里这组是跳过的
  if [ "$1" = apps/user_app ]; then
    echo "-- 单门店版单测"
    flutter test --no-pub --dart-define=SUPERZ_EDITION=single test/single_store_test.dart || return 1
  fi
}

# 扫 Dart 字符串里的转义美元符:'\$id' 在 Dart 里是字面量 $id 不是插值,请求会带着字面的 $orderNo 发出去。
# analyze 不报(语法合法)、e2e 也照不到(测的是服务端),只能靠扫。
# 模式必须是「字面反斜杠 + 字面美元」= BRE 的 \\\$。原来 Makefile 里写错过一次(BRE 里末尾的 $ 是行尾锚点),
# 只找得到"行尾的反斜杠",一直返回绿灯 —— 守卫写错比没有守卫更糟。挪到这里之后造过反例验证它会红
dollar_scan() {
  if grep -rn '\\\$' --include='*.dart' packages/ apps/; then
    echo "✗ 上面这些 '\\\$x' 是字面量,不是插值"
    return 1
  fi
  echo "没有转义美元符"
}

NAMES=""
# $1 = 任务名(只用字母数字下划线),其余 = 要跑的命令
job() {
  local name=$1
  shift
  NAMES="$NAMES $name"
  ( s=$SECONDS; "$@"; rc=$?; echo "$((SECONDS - s))" > "$OUT/$name.dur"; exit $rc ) \
      > "$OUT/$name.log" 2>&1 &
  eval "PID_$name=$!"
}

# 最慢的(用户端)先发
job dart_user dart_pkg apps/user_app
job dart_merchant dart_pkg apps/merchant_app
job dart_rider dart_pkg apps/rider_app
job dart_shared dart_pkg packages/shared
job dollar dollar_scan
job merchant_web sh -c 'cd merchant-web && npx tsc --noEmit'
job admin_web sh -c 'cd admin-web && npx tsc --noEmit'
job developer_web sh -c 'cd developer-web && npx tsc --noEmit'
# 小程序:SDK(假宿主)、官方小程序的纯函数、文档参考页与 SDK 导出一致(DEV-PROMPTS-39 #338)
job miniapp_sdk sh -c 'cd packages/miniapp-sdk && npm test'
job miniapps sh -c 'cd miniapps && npx tsc -p . && node scripts/test.mjs && node scripts/check_miniapp_meta.mjs'
job sdk_docs node scripts/check_sdk_docs.mjs

label() {
  case $1 in
    dart_shared) echo "packages/shared analyze + 单测" ;;
    dart_user) echo "apps/user_app analyze + 单测 + 单门店版单测" ;;
    dart_merchant) echo "apps/merchant_app analyze + 单测" ;;
    dart_rider) echo "apps/rider_app analyze + 单测" ;;
    dollar) echo "Dart 字符串里没有转义美元符" ;;
    merchant_web) echo "merchant-web tsc" ;;
    admin_web) echo "admin-web tsc" ;;
    developer_web) echo "developer-web tsc" ;;
    miniapp_sdk) echo "miniapp-sdk 测试" ;;
    miniapps) echo "官方小程序 tsc + 测试 + 标准化检查" ;;
    sdk_docs) echo "小程序文档与 SDK 导出一致" ;;
    *) echo "$1" ;;
  esac
}

echo "== 并行跑 $(echo $NAMES | wc -w | tr -d ' ') 项检查 =="
FAIL=0
for name in $NAMES; do
  eval "pid=\$PID_$name"
  if wait "$pid"; then
    echo "  ✓ $(label "$name")($(cat "$OUT/$name.dur")s)"
  else
    FAIL=1
    echo "  ✗ $(label "$name") —— 日志:"
    sed 's/^/      /' "$OUT/$name.log"
  fi
done
echo "== 共 $((SECONDS - T0))s =="
exit $FAIL
