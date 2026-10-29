#!/usr/bin/env python3
"""从 App 内的单门店版协议正文生成网页版(server/static/legal-store-terms.html / legal-store-privacy.html)。

单门店版(packages/shared/lib/src/edition.dart)是应用商店里的用户端,商店后台填的
「用户协议」「隐私政策」链接指向 /legal/store-terms、/legal/store-privacy。
网页和 App 内必须逐字一致,所以网页不手写,从 legal.dart 生成:

    python3 scripts/gen_store_legal.py           # 改了 legal.dart 里单门店版的正文之后跑一次
    python3 scripts/gen_store_legal.py --check   # 只比对,不一致退出码 1(单测 test_store_legal 也会拦)
"""
import html
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DART = REPO / "packages/shared/lib/src/legal.dart"
OUT = {
    "_kTermsSingle": REPO / "server/static/legal-store-terms.html",
    "_kPrivacySingle": REPO / "server/static/legal-store-privacy.html",
}

_URL = re.compile(r"https?://[^\s;,、。)）]+")
_H2 = re.compile(r"^([一二三四五六七八九十]+、|附录[:：])")
_H3 = re.compile(r"^[(（][一二三四五六七八九十]+[)）]")

HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  /* 商店的隐私政策规范要求「统一一种字体」:只写一种,不排一串备选 */
  body {{ font-family: sans-serif;
         max-width: 720px; margin: 0 auto; padding: 24px 20px 48px; line-height: 1.8; color: #222; }}
  h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.05rem; margin-top: 1.6em; }}
  h3 {{ font-size: .98rem; margin-top: 1.2em; }}
  .muted {{ color: #888; font-size: .9rem; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#111; color:#ddd; }} }}
</style>
</head>
<body>
<!-- 由 scripts/gen_store_legal.py 从 packages/shared/lib/src/legal.dart 生成,别手改 -->
"""

FOOT = """
<footer style="margin-top:32px;text-align:center;font-size:13px;opacity:.7">
  陕西爱卡斯科技有限公司 ·
  <a href="mailto:support@chaojizan.cc">support@chaojizan.cc</a> ·
  <a href="tel:15231109698">15231109698</a><br>
  <a href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer">陕ICP备2025064101号-5</a>
</footer>
</body>
</html>
"""


def dart_text(const: str) -> str:
    """取出 legal.dart 里某个 ''' 常量的正文,把 $_kLegalVersionSingle 换成真实日期。"""
    src = DART.read_text(encoding="utf-8")
    version = re.search(r"const String _kLegalVersionSingle = '([\d-]+)';", src).group(1)
    body = src.split(f"const String {const} = '''", 1)[1].split("''';", 1)[0]
    return body.replace("$_kLegalVersionSingle", version).strip("\n")


def _inline(line: str) -> str:
    out, at = [], 0
    for m in _URL.finditer(line):
        out.append(html.escape(line[at:m.start()], quote=False))
        url = m.group(0)
        out.append(f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer">'
                   f"{html.escape(url, quote=False)}</a>")
        at = m.end()
    out.append(html.escape(line[at:], quote=False))
    return "".join(out)


def render(text: str) -> str:
    lines = text.splitlines()
    title = lines[0]
    parts = [HEAD.format(title=html.escape(title)), f"<h1>{html.escape(title)}</h1>\n"]
    para: list[str] = []

    def flush() -> None:
        if para:
            parts.append("<p>" + "<br>\n".join(para) + "</p>\n")
            para.clear()

    for line in lines[1:]:
        if not line.strip():
            flush()
        elif _H2.match(line):
            flush()
            parts.append(f"\n<h2>{_inline(line)}</h2>\n")
        elif _H3.match(line):
            flush()
            parts.append(f"\n<h3>{_inline(line)}</h3>\n")
        else:
            para.append(_inline(line))
    flush()
    parts.append(FOOT)
    return "".join(parts)


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    for const, path in OUT.items():
        want = render(dart_text(const))
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != want:
                stale.append(path)
        else:
            path.write_text(want, encoding="utf-8")
            print(f"✓ {path.relative_to(REPO)}")
    if stale:
        print("✗ 网页版和 App 内不一致,跑 python3 scripts/gen_store_legal.py:")
        for p in stale:
            print(f"  {p.relative_to(REPO)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
