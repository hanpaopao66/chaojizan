#!/usr/bin/env bash
# 硬编码字号的**棘轮**:只许降不许涨。
#
# ## 为什么是棘轮而不是清零
#
# 三端有 737 处硬编码 fontSize、34 种不同的值。一次改完不现实,
# 而且纯搬运没有用户可见的收益 —— 真正的毛病是长辈版 1.4× 下画不画出界,
# 那个由 packages/shared/test/large_text_overflow_test.dart 盯着。
#
# 这个脚本只干一件事:**别再涨**。新写的代码用 brand.dart 里的
# kFontMicro/kFontNote/kFontBody/kFontBodyLg/kFontTitle,
# 想加第 35 种字号就得先说服这个脚本。
#
# 基数降下来之后要**手动改小 BASELINE** —— 不自动写回,
# 否则一次性删掉一堆代码会把基数悄悄拉低,下次谁加回来都发现不了。
set -euo pipefail
cd "$(dirname "$0")/.."

# 当前基数。降下来了就手动改小这个数(并在提交信息里说一声)。
# 737 → 724:三端「我的/店铺」页换用 SzEntryTile 之后,
# 那些手写的 fontSize 11/11.5/14.5 跟着少了 13 处(#294)。
# 724 → 720:首页商家卡重排,四行 meta 收进一个 dim() helper,
# 原来每处各写一遍 fontSize 11.5 的地方少了 4 处。
# 720 → 719:抢单卡删掉重复的「跑程」行,连带少一处。
BASELINE=719

count=$(grep -rhoE 'fontSize: *[0-9.]+' \
  packages/shared/lib apps/user_app/lib apps/merchant_app/lib apps/rider_app/lib \
  --include='*.dart' | wc -l | tr -d ' ')

kinds=$(grep -rhoE 'fontSize: *[0-9.]+' \
  packages/shared/lib apps/user_app/lib apps/merchant_app/lib apps/rider_app/lib \
  --include='*.dart' | grep -oE '[0-9.]+$' | sort -u | wc -l | tr -d ' ')

echo "  硬编码 fontSize:$count 处(基数 $BASELINE),共 $kinds 种取值"

if [ "$count" -gt "$BASELINE" ]; then
  echo
  echo "✗ 比基数多了 $((count - BASELINE)) 处。"
  echo "  新代码请用 brand.dart 里的字号档位:"
  echo "    kFontMicro 11 / kFontNote 12 / kFontBody 13 / kFontBodyLg 14 / kFontTitle 16"
  echo "  确实需要一个档位外的字号(比如承诺条那种记忆点大字),"
  echo "  就在这里把 BASELINE 加上去,并在提交信息里写清是哪一处、为什么。"
  exit 1
fi

if [ "$count" -lt "$BASELINE" ]; then
  echo "  ✓ 比基数少了 $((BASELINE - count)) 处 —— 记得把脚本里的 BASELINE 改成 $count"
fi
echo "✓ 字号没有继续发散"
