"""国内安卓厂商通道(华为 / 小米 / OPPO / vivo,#384 第二步)。

这四家的接口有个共同点:**错了只回一句笼统的话**。签名算错、时间戳单位错、
消息类别标错,回来的都是「鉴权失败」「参数错误」—— 所以能在这里钉死的东西
都钉死:签名怎么算、时间戳是毫秒还是秒、哪家是 MD5 哪家是 SHA256、
载荷长什么样、什么样的回复才算「这个 token 永远没用了」。

真发一条还是要用 `python -m scripts.push_probe`(各家接口会变,这里测不了那个)。

**判 gone 一律从窄**:少下线一台设备只是多发几次无用请求;
下线错一台是用户从此收不到推送,而且他不会来报这个 bug。
"""
import hashlib
import json

import httpx
import pytest

from app.config import settings
from app.services.push_channels import base, hms, oppo, vivo, xiaomi


@pytest.fixture(autouse=True)
def clean():
    base.reset_clients_for_test()
    hms.reset_token_for_test()
    oppo.reset_token_for_test()
    vivo.reset_token_for_test()
    yield
    base.reset_clients_for_test()
    hms.reset_token_for_test()
    oppo.reset_token_for_test()
    vivo.reset_token_for_test()


def fake(name: str, handler):
    base.set_client_for_test(name, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


# ---------------- 配没配 ----------------

def test_没配的时候一律不发也不抛(monkeypatch):
    import asyncio

    for mod in (hms, xiaomi, oppo, vivo):
        assert mod.configured() is False
        r = asyncio.run(mod.send("t", "标题", "正文"))
        assert r.ok is False and r.gone is False
        assert "没配" in r.error


# ---------------- 签名:两家不一样,最容易抄串 ----------------

def test_oppo_是_sha256():
    got = oppo.sign("KEY", "1700000000000", "SECRET")
    assert got == hashlib.sha256(b"KEY1700000000000SECRET").hexdigest()
    assert len(got) == 64


def test_vivo_是_md5_不是_sha256():
    got = vivo.sign("APPID", "KEY", "1700000000000", "SECRET")
    assert got == hashlib.md5(b"APPIDKEY1700000000000SECRET").hexdigest()
    assert len(got) == 32, "vivo 是 MD5(32 位),写成 SHA256 会一直鉴权失败"


def test_两家的签名不会算成一样():
    a = oppo.sign("K", "1", "S")
    b = vivo.sign("K", "K", "1", "S")
    assert a != b


# ---------------- 华为 ----------------

@pytest.fixture
def hms_on(monkeypatch):
    monkeypatch.setattr(settings, "hms_app_id", "1234567", raising=False)
    monkeypatch.setattr(settings, "hms_app_secret", "sec", raising=False)
    monkeypatch.setattr(settings, "hms_package_user", "cc.chaojizan.user", raising=False)


def test_华为载荷_点击打开首页_自定义字段是字符串(hms_on):
    m = hms.message("TOK", "晚风", "李四: 在吗", {"type": "chat", "chat_id": 7})
    assert m["message"]["token"] == ["TOK"]
    n = m["message"]["android"]["notification"]
    assert n["title"] == "晚风" and n["body"] == "李四: 在吗"
    assert n["click_action"]["type"] == 3, "3 = 打开应用首页"
    data = m["message"]["android"]["data"]
    assert isinstance(data, str), "华为要求自定义字段是字符串"
    assert json.loads(data)["chat_id"] == 7


def test_华为_成功码(hms_on):
    import asyncio

    def handler(req):
        if "oauth" in str(req.url):
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600})
        assert req.headers["authorization"] == "Bearer AT"
        return httpx.Response(200, json={"code": "80000000", "msg": "Success"})

    fake("hms", handler)
    r = asyncio.run(hms.send("TOK", "a", "b"))
    assert r.ok is True


def test_华为_只有点到名的_token_才算失效(hms_on):
    """部分失效时失效清单在 msg 里。没点到名的不许下线。"""
    import asyncio

    def handler(req):
        if "oauth" in str(req.url):
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600})
        return httpx.Response(200, json={
            "code": "80100000",
            "msg": json.dumps({"success": 0, "failure": 1, "illegal_tokens": ["BAD"]}),
        })

    fake("hms", handler)
    assert asyncio.run(hms.send("BAD", "a", "b")).gone is True
    assert asyncio.run(hms.send("GOOD", "a", "b")).gone is False


def test_华为_别的错码一律不算失效(hms_on):
    import asyncio

    def handler(req):
        if "oauth" in str(req.url):
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600})
        return httpx.Response(200, json={"code": "80300002", "msg": "没有权限"})

    fake("hms", handler)
    r = asyncio.run(hms.send("TOK", "a", "b"))
    assert r.ok is False and r.gone is False, "权限问题是我们自己的,下线设备只会掩盖它"


def test_华为_401_清掉令牌缓存_下一条重新换(hms_on):
    import asyncio

    calls = {"oauth": 0}

    def handler(req):
        if "oauth" in str(req.url):
            calls["oauth"] += 1
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600})
        return httpx.Response(401, json={"code": "80200001"})

    fake("hms", handler)
    asyncio.run(hms.send("T", "a", "b"))
    asyncio.run(hms.send("T", "a", "b"))
    assert calls["oauth"] == 2, "401 之后要重新换令牌,不然会一直用一个过期的"


def test_华为_令牌在有效期内复用(hms_on):
    import asyncio

    calls = {"oauth": 0}

    def handler(req):
        if "oauth" in str(req.url):
            calls["oauth"] += 1
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600})
        return httpx.Response(200, json={"code": "80000000"})

    fake("hms", handler)
    asyncio.run(hms.send("T", "a", "b"))
    asyncio.run(hms.send("T", "a", "b"))
    assert calls["oauth"] == 1, "一小时的令牌不该每条都换 —— 换太勤会被限流"


# ---------------- 小米 ----------------

@pytest.fixture
def mi_on(monkeypatch):
    monkeypatch.setattr(settings, "xiaomi_app_secret", "SEC", raising=False)
    monkeypatch.setattr(settings, "xiaomi_package_user", "cc.chaojizan.user", raising=False)


def test_小米_表单形状_系统弹通知而不是透传(mi_on):
    f = xiaomi.form("REG", "晚风", "在吗", {"type": "chat"})
    assert f["registration_id"] == "REG"
    assert f["pass_through"] == 0, "透传在 App 被杀掉时收不到,那就失去接厂商通道的意义了"
    assert f["notify_type"] == -1, "铃声震动按系统设置来,不替用户做主"
    assert json.loads(f["payload"])["type"] == "chat"
    assert f["restricted_package_name"] == "cc.chaojizan.user"


def test_小米_成功(mi_on):
    import asyncio

    def handler(req):
        assert req.headers["authorization"] == "key=SEC"
        return httpx.Response(200, json={"result": "ok", "code": 0})

    fake("xiaomi", handler)
    assert asyncio.run(xiaomi.send("REG", "a", "b")).ok is True


def test_小米_regid_不合法才算失效(mi_on):
    import asyncio

    fake("xiaomi", lambda req: httpx.Response(200, json={
        "result": "error", "code": 22022, "reason": "invalid registration_id"}))
    assert asyncio.run(xiaomi.send("REG", "a", "b")).gone is True

    fake("xiaomi", lambda req: httpx.Response(200, json={
        "result": "error", "code": 10008, "reason": "系统繁忙"}))
    assert asyncio.run(xiaomi.send("REG", "a", "b")).gone is False


# ---------------- OPPO ----------------

@pytest.fixture
def oppo_on(monkeypatch):
    monkeypatch.setattr(settings, "oppo_app_key", "K", raising=False)
    monkeypatch.setattr(settings, "oppo_master_secret", "S", raising=False)


def test_oppo_时间戳是毫秒(oppo_on):
    """用秒签名永远对不上,而回来的只是一句笼统的鉴权失败 —— 这一家最容易卡在这儿。"""
    import asyncio

    seen = {}

    def handler(req):
        if req.url.path.endswith("/auth"):
            body = req.content.decode()
            seen["ts"] = dict(p.split("=") for p in body.split("&"))["timestamp"]
            return httpx.Response(200, json={"code": 0, "data": {"auth_token": "AT"}})
        return httpx.Response(200, json={"code": 0})

    fake("oppo", handler)
    asyncio.run(oppo.send("T", "a", "b"))
    assert len(seen["ts"]) == 13, f"毫秒是 13 位,拿到的是 {seen['ts']}"


def test_oppo_消息体是_message_字段里的一段_json(oppo_on):
    import asyncio

    seen = {}

    def handler(req):
        if req.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 0, "data": {"auth_token": "AT"}})
        from urllib.parse import parse_qs
        seen["msg"] = json.loads(parse_qs(req.content.decode())["message"][0])
        assert req.headers["auth_token"] == "AT"
        return httpx.Response(200, json={"code": 0})

    fake("oppo", handler)
    asyncio.run(oppo.send("REG", "晚风", "在吗", {"type": "chat"}))
    assert seen["msg"]["target_type"] == 2 and seen["msg"]["target_value"] == "REG"
    assert seen["msg"]["notification"]["title"] == "晚风"


# ---------------- vivo ----------------

@pytest.fixture
def vivo_on(monkeypatch):
    monkeypatch.setattr(settings, "vivo_app_id", "A", raising=False)
    monkeypatch.setattr(settings, "vivo_app_key", "K", raising=False)
    monkeypatch.setattr(settings, "vivo_app_secret", "S", raising=False)
    monkeypatch.setattr(settings, "vivo_classification", 1, raising=False)


def test_vivo_消息体_类别可配_requestId每条唯一(vivo_on):
    a = vivo.message("R", "标题", "正文", {"k": 1})
    b = vivo.message("R", "标题", "正文", {"k": 1})
    assert a["regId"] == "R"
    assert a["classification"] == 1, "乱标系统消息会被处罚,所以做成配置"
    assert a["clientCustomMap"]["k"] == "1", "自定义字段要是字符串"
    assert a["requestId"] != b["requestId"], "vivo 靠 requestId 去重,每条必须不一样"


def test_vivo_成功与失败(vivo_on):
    import asyncio

    def ok_handler(req):
        if req.url.path.endswith("/auth"):
            return httpx.Response(200, json={"result": 0, "authToken": "AT"})
        assert req.headers["authtoken"] == "AT"
        return httpx.Response(200, json={"result": 0, "desc": "success"})

    fake("vivo", ok_handler)
    assert asyncio.run(vivo.send("R", "a", "b")).ok is True

    def bad_handler(req):
        if req.url.path.endswith("/auth"):
            return httpx.Response(200, json={"result": 0, "authToken": "AT"})
        return httpx.Response(200, json={"result": 10302, "desc": "regId 失效"})

    vivo.reset_token_for_test()
    fake("vivo", bad_handler)
    r = asyncio.run(vivo.send("R", "a", "b"))
    assert r.ok is False and r.gone is True


# ---------------- 共用的东西 ----------------

def test_令牌缓存_提前过期不卡点():
    c = base.TokenCache("t", margin=300)
    c.put("V", ttl=3600, now=1000)
    assert c.peek(1000) == "V"
    assert c.peek(1000 + 3600 - 301) == "V"
    assert c.peek(1000 + 3600 - 299) == "", "要提前换,卡着点换会在路上过期"


def test_令牌缓存_清掉之后要重新换():
    c = base.TokenCache("t")
    c.put("V", ttl=3600, now=0)
    c.clear()
    assert c.peek(0) == ""
