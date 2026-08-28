#!/usr/bin/env bash
# 宽屏布局的两条底线,写错都**不报错** —— 功能全对、测试全绿,只是桌面上难用。
#
#   1. 弹层走 szShowSheet,不直接 showModalBottomSheet
#      底部弹层是给拇指设计的。钉在 1440 桌面屏底会变成横贯屏底的一条长条,
#      内容挤在左边一小块,而视线在屏幕中央。
#
#   2. 弹窗走 SzDialog,不直接 AlertDialog
#      Material 的默认内边距是给桌面留的,手机上空白比正文还多。
#
#   3. 带 appBar 的页面走 SzPageScaffold,不直接 Scaffold
#      push 出来的子页不在 SzNavScaffold 里。裸 Scaffold 在 1440 上整页铺满:
#      返回箭头钉在屏幕最左上角,提交按钮横跨 1440 —— 一个按钮一米宽。
#      这一条是**验收时才发现的**:改完外壳看着都对,点进子页才露馅。
#
# 见 packages/shared/lib/src/responsive.dart。
#
# ⚠️ 三条规则都**先剥掉注释再判定**。原来按原始文本搜,于是在代码里写一句
# 「这里走 szShowSheet 而不是 showModalBottomSheet,因为宽屏上……」也会被判违规,
# 逼着人把最自然的那半句解释删掉 —— 守卫把说明理由这件事罚掉了。
# 剥的只是注释:真调用后面跟着注释照样抓。
set -eo pipefail
cd "$(dirname "$0")/.."

fail=0

# 从 `路径:行号:内容` 的匹配里,丢掉那些「只出现在注释里」的。
# `https://` 这类 URL 里的 // 不当注释(前面紧挨着冒号)。
drop_comment_only() {
  python3 -c '
import sys

pat = sys.argv[1]
for raw in sys.stdin:
    line = raw.rstrip("\n")
    parts = line.split(":", 2)          # 路径和行号原样留着,只对内容剥
    body = parts[2] if len(parts) == 3 else line
    i = 0
    while True:
        i = body.find("//", i)
        if i < 0:
            break
        if i > 0 and body[i - 1] == ":":    # https:// / ws:// 不是注释
            i += 2
            continue
        body = body[:i]
        break
    if pat in body:
        print(line)
' "$1"
}

# ⚠️ 只放行 SzDialog 内部那一处,**不是整个文件**。
# 原来这里排除的是整个 sz_widgets.dart,于是同一个文件里另一处裸的
# AlertDialog(「要放弃已填的内容吗」)一直没被抓到 —— 组件库自己
# 没守自己的规矩,而守卫正好在那儿睁一只眼。
dialogs=$(grep -rn --include="*.dart" "AlertDialog(" apps packages \
  | grep -v "packages/shared/lib/src/sz_widgets.dart:.*=> AlertDialog(" \
  | grep -v "packages/shared/test/dialog_density_test.dart" \
  | grep -v "packages/shared/test/dialog_layout_test.dart" \
  | drop_comment_only "AlertDialog(" || true)
if [ -n "$dialogs" ]; then
  echo "✗ 直接用了 AlertDialog,改成 SzDialog:"
  echo "$dialogs" | sed 's/^/    /'
  echo "  参数同名(title/content/actions),直接换名字就行。"
  echo "  Material 的默认内边距是给桌面留的:标题上 24、标题到正文 20、"
  echo "  正文到按钮 24 —— 手机上一个两行字的弹窗,空白比正文还多。"
  fail=1
fi

sheets=$(grep -rn --include="*.dart" "showModalBottomSheet" apps packages \
  | grep -v "packages/shared/lib/src/responsive.dart" \
  | drop_comment_only "showModalBottomSheet" || true)
if [ -n "$sheets" ]; then
  echo "✗ 直接调了 showModalBottomSheet,改成 szShowSheet:"
  echo "$sheets" | sed 's/^/    /'
  echo "  builder 照原样写 —— SafeArea、拖拽条、键盘避让的差异 helper 自己吸收。"
  fail=1
fi

# 带 appBar 的裸 Scaffold。用 python 做括号配对,避免把
# "Scaffold( 后面很多行才出现 appBar" 漏掉或误报。
bare=$(python3 - <<'PY'
import pathlib, re, sys


def blank_comments(s):
    """把注释换成**等长空格** —— 长度不变,行号和下面的括号配对都不受影响。

    `//` 行注释(`///` 文档注释同理)和 `/* */` 块注释都算;
    `https://` 这类 URL 里的 // 不算(前面紧挨着冒号)。
    """
    out, i, n = list(s), 0, len(s)
    while i < n:
        if s[i] == "/" and i + 1 < n and s[i + 1] == "/":
            if i > 0 and s[i - 1] == ":":
                i += 2
                continue
            while i < n and s[i] != "\n":
                out[i] = " "
                i += 1
        elif s[i] == "/" and i + 1 < n and s[i + 1] == "*":
            end = s.find("*/", i + 2)
            end = n if end < 0 else end + 2
            while i < end:
                if out[i] != "\n":
                    out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def args_of(s, open_idx):
    depth, i, out = 0, open_idx, []
    while i < len(s):
        c = s[i]
        if c in "([{":
            depth += 1
            if depth == 1:
                i += 1; continue
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return "".join(out)
        elif depth == 1:
            out.append(c)
        i += 1
    return "".join(out)

hits = []
for root in ("apps", "packages/shared/lib"):
    for p in pathlib.Path(root).rglob("*.dart"):
        if p.name == "responsive.dart":
            continue
        s = blank_comments(p.read_text())
        for m in re.finditer(r"(?<![A-Za-z0-9_])Scaffold\(", s):
            if re.search(r"\bappBar\s*:", args_of(s, m.end() - 1)):
                hits.append(f"{p}:{s[:m.start()].count(chr(10)) + 1}")
print("\n".join(hits))
PY
)
if [ -n "$bare" ]; then
  echo "✗ 这些带 appBar 的页面还是裸 Scaffold,改成 SzPageScaffold:"
  echo "$bare" | sed 's/^/    /'
  echo "  参数同名,直接换名字就行。放地图/图表/表格的传 contentMaxWidth: kWideMaxWidth。"
  fail=1
fi

[ $fail -eq 0 ] && echo "✓ 弹层和子页都走了自适应外壳"
exit $fail
