"""苹果推送直连(services/push_channels/apns.py,#384)。

守的是四件容易出错、而且**错了不报错只是收不到**的事:

1. 令牌是 ES256 签的、头里带 kid、体里带 iss —— 苹果只认这一种形状;
2. 令牌**缓存但会过期**:换太勤苹果回 429 TooManyProviderTokenUpdates,
   换太晚(超过 1 小时)直接 403 ExpiredProviderToken;
3. 哪个端推给哪个 bundle id —— apns-topic 填错是静默收不到,没有任何报错;
4. 什么样的回复算「这个 token 永远没用了」。宽了会把好设备下线,窄了会一直往死 token 发。
"""
import time

import pytest

from app.config import settings
from app.services.push_channels import apns

# 测试用的 P-256 私钥。**不是任何真实凭据** —— 现场生成,只用来验签名形状
_KEY = None


def key() -> str:
    global _KEY
    if _KEY is None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        k = ec.generate_private_key(ec.SECP256R1())
        _KEY = k.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()).decode()
    return _KEY


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "apns_key_p8", key(), raising=False)
    monkeypatch.setattr(settings, "apns_key_id", "ABCDE12345", raising=False)
    monkeypatch.setattr(settings, "apns_team_id", "TEAM123456", raising=False)
    monkeypatch.setattr(settings, "apns_topic_user", "cc.chaojizan.user", raising=False)
    monkeypatch.setattr(settings, "apns_topic_merchant", "cc.chaojizan.merchant", raising=False)
    monkeypatch.setattr(settings, "apns_topic_rider", "cc.chaojizan.rider", raising=False)
    apns.reset_token_for_test()
    yield
    apns.reset_token_for_test()
    # 假传输层用完要收掉:留着会漏给同进程里后面的用例,表现成"它怎么不出网了"
    apns._client = None


def test_没配齐就当没配(monkeypatch):
    monkeypatch.setattr(settings, "apns_key_p8", "", raising=False)
    assert apns.configured() is False


def test_配齐了才算配好(configured):
    assert apns.configured() is True


def test_令牌是_ES256_头里有_kid_体里有_iss(configured):
    import jwt

    tok = apns.auth_token()
    head = jwt.get_unverified_header(tok)
    assert head["alg"] == "ES256", "苹果只认 ES256"
    assert head["kid"] == "ABCDE12345"
    body = jwt.decode(tok, options={"verify_signature": False})
    assert body["iss"] == "TEAM123456"
    assert isinstance(body["iat"], int)


def test_令牌在有效期内复用_到点才换(configured):
    t0 = time.time()
    a = apns.auth_token(t0)
    assert apns.auth_token(t0 + 60) == a, "一分钟就换一次会被苹果当滥用(429)"
    assert apns.auth_token(t0 + 49 * 60) == a
    assert apns.auth_token(t0 + 51 * 60) != a, "超过 50 分钟必须换,不然会 403 过期"


def test_哪个端推给哪个_bundle_id(configured):
    assert apns.topic_for("user") == "cc.chaojizan.user"
    assert apns.topic_for("merchant") == "cc.chaojizan.merchant"
    assert apns.topic_for("rider") == "cc.chaojizan.rider"
    # 认不出的端按用户端算,而不是回空串 —— 空的 apns-topic 是 400,整条推没了
    assert apns.topic_for("什么端") == "cc.chaojizan.user"


def test_载荷形状(configured):
    p = apns.payload("晚风", "李四: 在吗", {"type": "chat", "chat_id": "7"})
    assert p["aps"]["alert"] == {"title": "晚风", "body": "李四: 在吗"}
    assert p["aps"]["sound"] == "default"
    assert p["aps"]["mutable-content"] == 1
    assert "content-available" not in p["aps"], "静默推送被苹果限流,我们每条都是要弹出来的"
    assert p["type"] == "chat" and p["chat_id"] == "7"


def test_badge_只有传了才带(configured):
    assert "badge" not in apns.payload("a", "b", None)["aps"]
    assert apns.payload("a", "b", None, badge=3)["aps"]["badge"] == 3


@pytest.mark.parametrize("status,reason,gone", [
    (410, "Unregistered", True),          # 苹果明说这个 token 没了
    (400, "BadDeviceToken", True),        # 多半是沙箱 / 生产发反了,这个 token 在这个环境永远不对
    (400, "DeviceTokenNotForTopic", True),
    (403, "ExpiredProviderToken", False),  # 我们自己的令牌过期 —— 是我们的问题,别下线人家设备
    (400, "PayloadTooLarge", False),       # 同上
    (429, "TooManyRequests", False),
    (500, "InternalServerError", False),
])
def test_什么样的回复才算这个_token_永远没用了(status, reason, gone):
    assert (status == 410 or reason in apns.GONE_REASONS) is gone, (
        f"{status} {reason} 判成 gone={not gone} 了:"
        "宽了会把好设备下线,窄了会一直往死 token 发")


@pytest.mark.parametrize("bad", ["", "   "])
def test_没配时发送不抛异常_只是回失败(bad, monkeypatch):
    monkeypatch.setattr(settings, "apns_key_p8", bad, raising=False)
    import asyncio

    r = asyncio.run(apns.send("abc", "标题", "正文"))
    assert r.ok is False and r.gone is False
    assert "没配" in r.error


# ---------------- 真发一条(用假的传输层,不出网) ----------------

def _fake_apns(handler):
    """把 apns 的连接池换成一个假的传输层,handler 收到请求、决定回什么。"""
    import httpx

    apns._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return apns._client


def test_发一条_地址和头都对(configured):
    import asyncio

    seen = {}

    def handler(request):
        import json as _json
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = _json.loads(request.content)
        import httpx
        return httpx.Response(200)

    _fake_apns(handler)
    r = asyncio.run(apns.send("DEVTOKEN123", "晚风", "李四: 在吗",
                              {"type": "chat", "chat_id": "7"},
                              app="rider", collapse_id="7"))
    assert r.ok is True and r.error == ""
    assert seen["url"] == "https://api.push.apple.com/3/device/DEVTOKEN123"
    h = seen["headers"]
    assert h["apns-topic"] == "cc.chaojizan.rider", "推给骑手端就得用骑手端的 bundle id"
    assert h["apns-push-type"] == "alert"
    assert h["apns-priority"] == "10", "聊天消息要立刻送,不能让系统攒着"
    assert int(h["apns-expiration"]) > time.time(), "过期时间要在将来"
    assert h["apns-collapse-id"] == "7", "同一个会话的多条在锁屏上合成一条"
    assert h["authorization"].startswith("bearer ")
    assert seen["body"]["aps"]["alert"]["title"] == "晚风"


def test_沙箱发到沙箱那台服务器(configured):
    """这是「开发机怎么收不到推送」的头号原因:沙箱和生产是两台服务器,token 不通用。"""
    import asyncio

    import httpx

    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200)

    _fake_apns(handler)
    asyncio.run(apns.send("T", "a", "b", sandbox=True))
    assert seen["url"].startswith("https://api.sandbox.push.apple.com/"), seen["url"]


def test_苹果说_token_没了_就标成_gone(configured):
    import asyncio

    import httpx

    _fake_apns(lambda req: httpx.Response(410, json={"reason": "Unregistered"}))
    r = asyncio.run(apns.send("T", "a", "b"))
    assert r.ok is False and r.gone is True and "Unregistered" in r.error


def test_我们自己的令牌过期_不许把人家设备下线(configured):
    import asyncio

    import httpx

    _fake_apns(lambda req: httpx.Response(403, json={"reason": "ExpiredProviderToken"}))
    r = asyncio.run(apns.send("T", "a", "b"))
    assert r.ok is False
    assert r.gone is False, "这是我们的问题,下线设备只会掩盖它"


def test_网络炸了不抛异常_只回失败(configured):
    import asyncio

    import httpx

    def boom(request):
        raise httpx.ConnectError("连不上")

    _fake_apns(boom)
    r = asyncio.run(apns.send("T", "a", "b"))
    assert r.ok is False and r.gone is False
    assert "ConnectError" in r.error
