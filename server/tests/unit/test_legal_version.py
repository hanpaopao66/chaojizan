"""用户协议、隐私政策的版本号各处一致,两份隐私政策、两份用户协议逐条一致;
用户协议的售后那一条按 2026-09-15 的口径(商家有责任全款退,配送费也退)。

版本号决定要不要重新征求同意(packages/shared/lib/src/privacy_gate.dart:本地记的同意版本
和 kLegalVersion 对不上就重新弹)。它在五个地方:App 内的 kLegalVersion、网页版隐私政策的
更新日期和生效日期、网页版用户协议的更新日期、两个鸿蒙端的 LEGAL_VERSION。

撞过的:鸿蒙两端的 LEGAL_VERSION 从 2026-07-28 起就没跟过 —— 隐私政策改了好几版,
鸿蒙用户一次都没被重新征求同意。2026-09-15 统一,这里锁住。

隐私政策、用户协议各有两份(App 内 legal.dart、网页 legal-privacy.html / legal-terms.html),
编号的条目逐条一字不差(Dart 里的 ** 就是网页上的 <strong>,网页上的链接只比文字)。
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DART = (REPO / "packages/shared/lib/src/legal.dart").read_text(encoding="utf-8")
PRIVACY_HTML = (REPO / "server/static/legal-privacy.html").read_text(encoding="utf-8")
TERMS_HTML = (REPO / "server/static/legal-terms.html").read_text(encoding="utf-8")
HARMONY = ("apps/merchant_app_harmony/entry/src/main/ets/pages/Index.ets",
           "apps/user_app_harmony/entry/src/main/ets/pages/Index.ets")


def _version() -> str:
    return re.search(r"const String kLegalVersion = '(\d{4}-\d{2}-\d{2})';", DART).group(1)


def test_版本号五处一致():
    v = _version()
    m = re.search(r"更新日期:(\S+) · 生效日期:(\S+?)<br>", PRIVACY_HTML)
    assert m and m.groups() == (v, v), f"网页版隐私政策的日期 {m and m.groups()} 和 App 内 {v} 对不上"
    t = re.search(r"更新日期:(\S+) · 与 App 内展示文本一致", TERMS_HTML)
    assert t and t.group(1) == v, f"网页版用户协议的日期 {t and t.group(1)} 和 App 内 {v} 对不上"
    for rel in HARMONY:
        src = (REPO / rel).read_text(encoding="utf-8")
        h = re.search(r"const LEGAL_VERSION: string = '([\d-]+)';", src)
        assert h and h.group(1) == v, f"{rel} 的 LEGAL_VERSION {h and h.group(1)} 和 App 内 {v} 对不上"


def test_不早于2026_09_15():
    """2026-09-15 这一版改了隐私政策(申诉、公开账本那两条),版本号只许往后走"""
    assert _version() >= "2026-09-15"


def _numbered_html() -> list[str]:
    out = []
    for line in PRIVACY_HTML.splitlines():
        if not re.match(r"^\s*(<p>)?\d+\. ", line):
            continue
        line = re.sub(r"^\s*<p>", "", line.strip()).removesuffix("<br>").removesuffix("</p>")
        line = line.replace("<strong>", "**").replace("</strong>", "**")
        out.append(re.sub(r"<a [^>]*>(.*?)</a>", r"\1", line))
    return out


def _numbered_dart() -> list[str]:
    body = DART.split("const String kPrivacyText = '''", 1)[1].split("''';", 1)[0]
    return [line for line in body.splitlines() if re.match(r"^\d+\. ", line)]


def test_两份隐私政策逐条一字不差():
    h, d = _numbered_html(), _numbered_dart()
    assert len(h) == len(d) >= 30, (len(h), len(d))
    diff = [(a, b) for a, b in zip(h, d) if a != b]
    assert not diff, "两份隐私政策不一样的条目:\n" + "\n".join(
        f"网页:{a}\nApp :{b}" for a, b in diff)


def _terms_html() -> list[str]:
    """网页版用户协议的编号条目。段内有续行(一条拆成两行写),先拼起来再按 <br> / </p> 分条"""
    body = TERMS_HTML.split("<body>", 1)[1].split("<footer", 1)[0].replace("\n", "")
    for tag in ("<br>", "</p>", "<p>"):
        body = body.replace(tag, "\n")
    body = re.sub(r"<h2>(.*?)</h2>", r"\n\1\n", body)
    body = re.sub(r"<a [^>]*>(.*?)</a>", r"\1", body)
    body = body.replace("<strong>", "**").replace("</strong>", "**")
    return [x.strip() for x in body.splitlines() if re.match(r"^\s*\d+\. ", x)]


def _terms_dart() -> list[str]:
    body = DART.split("const String kTermsText = '''", 1)[1].split("''';", 1)[0]
    return [line for line in body.splitlines() if re.match(r"^\d+\. ", line)]


def test_两份用户协议逐条一字不差():
    """网页版抬头写着「与 App 内展示文本一致」—— 原来第四节第 1 条就不一致(网页多一个括号)"""
    h, d = _terms_html(), _terms_dart()
    assert len(h) == len(d) >= 25, (len(h), len(d))
    diff = [(a, b) for a, b in zip(h, d) if a != b]
    assert not diff, "两份用户协议不一样的条目:\n" + "\n".join(
        f"网页:{a}\nApp :{b}" for a, b in diff)


def test_售后那一条按2026_09_15的口径():
    """商家有责任,顾客拿回全款(配送费和小费也退),钱由商家出;骑手有责任同样全额退;
    平台券抵扣的那部分不退现金;平台判错了,平台自己认(services/merchant_fault、rider_fault、
    routers/appeals)。原来只写「商家同意后全额原路退款」"""
    item = next(x for x in _terms_dart() if x.startswith("4. 送达后"))
    for word in ("商家同意", "商家的责任", "申诉成立", "没出餐或餐品不齐", "食品安全投诉",
                 "全额原路退回", "配送费和小费也退", "由商家承担", "骑手的责任",
                 "平台券抵扣的那部分不退现金", "平台判错了,平台自己认"):
        assert word in item, word
    assert "商家同意后全额原路退款。" not in DART + TERMS_HTML


def test_公开账本那一条照实说是逐笔的():
    """原来写「公示的是资金流向汇总数据」—— 公开账本其实逐笔列每一行,2026-09-15 起还有判责和
    申诉改判的行。订单号只以哈希出现、不含个人身份信息,这两句要在"""
    item = next(x for x in _numbered_dart() if x.startswith("3. 平台账目透明"))
    for word in ("逐笔", "申诉改判", "哈希", "不含你的个人身份信息"):
        assert word in item, word
    assert "汇总数据,不含" not in item
