"""大模型的后台配置(services/ai.py,#385)。

守的是三件事:

1. **缺一样就当没配**。地址或模型名缺一个都不生成 —— 半配的状态最难查,
   表现是"AI 一个字都不发"而后台看上去是配好的;
2. **API key 不回明文**。后台那一页任何管理员都打得开,截图、录屏、肩后看都算泄露;
   变更留痕(对外公示的那张表)里也只记「设了 / 清了」;
3. **只认 OpenAI 兼容的形状**,不给任何一家写专门适配 —— 那是把自己绑在某一家上;
4. **没有"平台的模型"这回事**(#386):配置必须由调用方给,`complete` 不会去库里找兜底。

不测的:内容审核。那是发布那一层的事(违禁词、先审后发都在原路径上),
这里只收拾形状。
"""
import httpx
import pytest

from app.services import ai


@pytest.fixture(autouse=True)
def clean():
    yield
    ai.set_client_for_test(None)  # type: ignore[arg-type]


def cfg(**kw) -> ai.Config:
    base = {"endpoint": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b"}
    return ai.Config(**{**base, **kw})


# ---------------- 配没配 ----------------

def test_地址和模型名缺一个都当没配():
    assert cfg().ok is True
    assert ai.Config(endpoint="", model="m").ok is False
    assert ai.Config(endpoint="http://x/v1", model="").ok is False


def test_本机模型不需要_key_也算配好了():
    assert cfg(api_key="").ok is True


def test_地址结尾的斜杠会去掉_免得拼出两个斜杠():
    assert ai.Config(endpoint="http://x/v1/", model="m").endpoint == "http://x/v1"


# ---------------- 生成 ----------------

def fake(handler):
    ai.set_client_for_test(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_没配时不发请求_只回错():
    import asyncio

    called = {"n": 0}

    def handler(req):
        called["n"] += 1
        return httpx.Response(200)

    fake(handler)
    r = asyncio.run(ai.complete(ai.Config(), "你好"))
    assert r.ok is False and "没填模型地址" in r.error
    assert called["n"] == 0, "没配就不该出网"


def test_请求形状是_openai_兼容的():
    import asyncio

    seen = {}

    def handler(req):
        import json
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "今天适合吃面"}}]})

    fake(handler)
    r = asyncio.run(ai.complete(cfg(api_key="K"), "吃什么",
                                system="你是本地生活社区的一位成员"))
    assert r.ok and r.text == "今天适合吃面"
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert seen["body"]["model"] == "qwen2.5:7b"
    assert seen["body"]["messages"][0] == {"role": "system",
                                           "content": "你是本地生活社区的一位成员"}
    assert seen["body"]["messages"][1] == {"role": "user", "content": "吃什么"}
    assert seen["auth"] == "Bearer K"


def test_没有_key_时不带那个头():
    import asyncio

    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "好"}}]})

    fake(handler)
    asyncio.run(ai.complete(cfg(api_key=""), "x"))
    assert seen["auth"] is None


@pytest.mark.parametrize("resp,why", [
    (httpx.Response(500, text="boom"), "服务端错"),
    (httpx.Response(200, json={"choices": []}), "回复形状不对"),
    (httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]}), "回了空"),
])
def test_各种不顺都只回错_不抛(resp, why):
    import asyncio

    fake(lambda req: resp)
    r = asyncio.run(ai.complete(cfg(), "x"))
    assert r.ok is False and r.error, why


def test_网络炸了也不抛():
    import asyncio

    def boom(req):
        raise httpx.ConnectError("模型没起来")

    fake(boom)
    r = asyncio.run(ai.complete(cfg(), "x"))
    assert r.ok is False and "ConnectError" in r.error


# ---------------- 收拾形状 ----------------

@pytest.mark.parametrize("raw,want", [
    ('  "今天吃面"  ', "今天吃面"),
    ("“今天吃面”", "今天吃面"),
    ("「今天吃面」", "今天吃面"),
    ("今天吃面", "今天吃面"),
    ('"', '"'),  # 只有一个引号别把它吃掉
])
def test_模型爱加的引号去掉(raw, want):
    assert ai.clean(raw) == want


def test_太长的截掉():
    assert len(ai.clean("啊" * 1000)) == ai.MAX_CHARS


def test_超时有上下界_填多大都不会一直等():
    c = ai.Config(endpoint="http://x/v1", model="m", timeout=9999)
    assert c.timeout == 9999, "Config 自己不夹"
    # 夹在从库里读那一层(config()):这里只确认常量在合理范围
    assert 1 <= ai.DEFAULT_TIMEOUT <= 120


# ---------------- 配置跟着**每个机器人**走(#386) ----------------

class P:
    """一行 ai_personas。"""

    def __init__(self, **kw):
        self.user_id = 1
        self.mode = "server"
        self.endpoint = "https://api.example.com/v1"
        self.model = "qwen2.5-7b-instruct"
        self.api_key_enc = ""
        self.timeout_seconds = 30
        self.persona = "你是一位爱做饭的成都上班族"
        for k, v in kw.items():
            setattr(self, k, v)


def test_本机模式在服务端永远是没配():
    """**这一条是 #386 的地基。** 本机那一档的模型在主人自己的设备上,
    服务端连地址都不该有 —— 就算库里那几列被填上了(手工改的、从 server 切回来的),
    也不许拿去请求:那多半是他家里的 127.0.0.1,替他请求就成了我们在探自己的内网。"""
    cfg = ai.config_of(P(mode="client"))
    assert cfg.ok is False and cfg.endpoint == "" and cfg.api_key == ""


def test_公网模式读这个机器人自己的地址和模型名():
    cfg = ai.config_of(P())
    assert cfg.ok and cfg.endpoint == "https://api.example.com/v1"
    assert cfg.model == "qwen2.5-7b-instruct"
    assert cfg.system_prompt == "你是一位爱做饭的成都上班族", "人设就是 system"


def test_密钥是解密出来的_库里存的是密文():
    from app.services import crypto

    cfg = ai.config_of(P(api_key_enc=crypto.encrypt("sk-real")))
    assert cfg.api_key == "sk-real"


def test_密钥解不开时当没配_而不是把密文当密钥发出去():
    """换过 FERNET 密钥、或者那一列被手工改过。**把一串密文当 Bearer 发给对方**
    比不发更糟 —— 它会以我们的名义出现在别人的日志里。"""
    cfg = ai.config_of(P(api_key_enc="这不是密文"))
    assert cfg.api_key == "" and cfg.ok is True, "地址和模型名还在,照样算配好了"


@pytest.mark.parametrize("raw,want", [(0, ai.DEFAULT_TIMEOUT), (None, ai.DEFAULT_TIMEOUT),
                                      (5, 5.0), (9999, 120.0)])
def test_超时在这一层夹住_填多大都不会一直占着连接(raw, want):
    assert ai.config_of(P(timeout_seconds=raw)).timeout == want


def test_没有平台兜底的模型():
    """`complete` 不去库里找"平台的模型" —— 调用方给什么就是什么。
    有兜底的话,一个没配模型的用户级机器人会悄悄花着平台的钱。"""
    import inspect

    src = inspect.getsource(ai.complete)
    for bad in ("await config(", "config()", "PlatformFlag", "settings."):
        assert bad not in src, f"complete 里不该出现 {bad!r} —— 配置必须由调用方给"
