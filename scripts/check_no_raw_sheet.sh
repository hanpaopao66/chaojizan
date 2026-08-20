#!/usr/bin/env bash
# 弹层必须走 szShowSheet,不能直接 showModalBottomSheet。
#
# 为什么要拦:底部弹层是给**拇指**设计的。钉在 1440px 的桌面屏底,
# 它会变成横贯屏底的一条长条 —— 内容挤在左边一小块,而视线在屏幕中央。
# szShowSheet 按可用宽度自动切成居中对话框。
#
# 这条检查是必要的,因为写错**不报错**:功能全对、测试全绿,
# 只是桌面上难用。见 packages/shared/lib/src/responsive.dart。
set -eo pipefail
cd "$(dirname "$0")/.."

hits=$(grep -rn --include="*.dart" "showModalBottomSheet" apps packages \
  | grep -v "packages/shared/lib/src/responsive.dart" || true)

if [ -n "$hits" ]; then
  echo "✗ 这些地方直接调了 showModalBottomSheet,改成 szShowSheet:"
  echo "$hits" | sed 's/^/    /'
  echo
  echo "  szShowSheet 会按屏宽自动选形态:窄屏底部弹层,宽屏居中对话框。"
  echo "  builder 照原样写就行 —— SafeArea、拖拽条、键盘避让的差异 helper 自己吸收。"
  exit 1
fi
echo "✓ 弹层调用点全部走 szShowSheet"
