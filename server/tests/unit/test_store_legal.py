"""单门店版(应用商店里的用户端,packages/shared/lib/src/edition.dart)的协议和隐私政策。

- 网页版(/legal/store-terms、/legal/store-privacy,商店后台填的链接)和 App 内逐字一致 ——
  网页由 scripts/gen_store_legal.py 生成,这里拦「改了 Dart 忘了重新生成」;
- 正文里不出现单门店版没有的功能。政策写了 App 里没有的功能,和功能多于政策一样,
  都是检测报告里的「收集使用规则与实际不符」;
- 权限附录只有网络、通知、位置、相册 —— 和安卓单门店版清单(src/single/AndroidManifest.xml)摘掉的那几项对得上。
"""
import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DART = (REPO / "packages/shared/lib/src/legal.dart").read_text(encoding="utf-8")


def _gen():
    spec = importlib.util.spec_from_file_location("gen_store_legal", REPO / "scripts/gen_store_legal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_网页版和App内逐字一致():
    gen = _gen()
    for const, path in gen.OUT.items():
        assert path.read_text(encoding="utf-8") == gen.render(gen.dart_text(const)), (
            f"{path.name} 和 legal.dart 的 {const} 对不上,跑 python3 scripts/gen_store_legal.py")


def test_按形态取正文():
    """完整版的三个常量原样留着;对外的 kLegalVersion / kTermsText / kPrivacyText 按 kSingleStore 选"""
    for name, single, full in (("kLegalVersion", "_kLegalVersionSingle", "_kLegalVersionFull"),
                               ("kTermsText", "_kTermsSingle", "_kTermsFull"),
                               ("kPrivacyText", "_kPrivacySingle", "_kPrivacyFull")):
        assert f"const String {name} = kSingleStore ? {single} : {full};" in DART, name
    single = re.search(r"const String _kLegalVersionSingle = '([\d-]+)';", DART).group(1)
    assert single >= "2026-10-27"


def test_不写单门店版没有的功能():
    gen = _gen()
    text = gen.dart_text("_kTermsSingle") + gen.dart_text("_kPrivacySingle")
    for word in ("骑手", "聊天", "视频", "论坛", "音乐", "小程序", "机器人", "信用分", "团购", "住宿",
                 "实名", "透明中心", "公开账本", "扫一扫", "麦克风权限：", "5%"):
        assert word not in text, word
    assert "不为其他商家提供入驻、展示或交易服务" in text


def test_权限附录只有四项():
    body = _gen().dart_text("_kPrivacySingle").split("附录：应用权限申请与使用说明", 1)[1]
    perms = [line[2:].split("：", 1)[0] for line in body.splitlines() if line.startswith("· ")]
    assert perms == ["网络", "通知", "位置", "相册"], perms
    assert "不申请相机、麦克风、通讯录权限" in body


def test_协议页给自动检测抓得到_HEAD和带斜杠都直接200():
    """商店的隐私政策自动检测要求静态页、不再跳转(2026-10 OPPO 打回过):原来 HEAD 回 405 + JSON,
    带斜杠的地址 307 跳转。四个协议页带不带斜杠、GET 和 HEAD 都要直接给 HTML"""
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    paths = [p for name in ("terms", "privacy", "store-terms", "store-privacy")
             for p in (f"/legal/{name}", f"/legal/{name}/")]
    # 商店后台填的短地址(照商店规范示例 https://www.example.com/privacy/ 的样子)
    paths += ["/privacy", "/privacy/", "/terms", "/terms/"]
    for path in paths:
        for method in ("GET", "HEAD"):
            r = c.request(method, path, follow_redirects=False)
            assert r.status_code == 200, (method, path, r.status_code)
            assert r.headers["content-type"].startswith("text/html"), (method, path)
    # 短地址给的是门店点餐版
    assert "门店点餐版" in c.get("/privacy/").text and "门店点餐版" in c.get("/terms/").text


def test_门店点餐版正文用全角标点_网页只用一种字体():
    """商店规范:中文显示、统一一种字体、无乱用符号。中文里夹半角逗号冒号括号算乱用符号;网址不算"""
    import re

    gen = _gen()
    for const in ("_kTermsSingle", "_kPrivacySingle"):
        text = re.sub(r"https?://\S+", "", gen.dart_text(const))
        assert not re.search(r'[,;:()"]', text), (const, re.findall(r'.{6}[,;:()"].{6}', text)[:5])
    page = (REPO / "server/static/legal-store-privacy.html").read_text(encoding="utf-8")
    assert re.findall(r"font-family:([^;]+);", page) == [" sans-serif"]
    assert '<meta charset="utf-8">' in page
