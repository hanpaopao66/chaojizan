"""接大模型:**用户自己的**(#385、#386)。

## 配置跟着**每个机器人**走,不在平台那儿

2026-09-16 运营方定:**平台不做大模型级别的机器人,所有接入都是用户级别的,
平台只负责搭建平台。** 所以这里没有"平台的模型" —— 每个机器人自己带地址和密钥
(`ai_personas`),平台永远不用自己的凭据去调任何模型。

两种接法:

- `client` 本机模型:App 自己调 127.0.0.1,**这个模块根本不参与** ——
  key 和模型不离开那台设备;
- `server` 公网地址:平台按节奏去调用户填的地址。地址要过内网守卫
  (`bots._ip_ok`,那套已经考虑了云厂商元数据和运营商 NAT),密钥加密存。

## 只认 OpenAI 兼容的接口

`POST {base}/chat/completions`,`{"model": …, "messages": [...]}`。
本机跑的 llama.cpp、vLLM、Ollama、LM Studio 都提供这个形状,一个地址就接上了。
**不为任何一家写专门的适配** —— 那是把自己绑在某一家上。

## API key 存密文,而且只跟着那一个机器人

存 `ai_personas.api_key_enc`(services/crypto 加密),接口读回来只说「已设置 / 未设置」。
本机模式根本不用交 key。

## 一条硬规矩:不配就什么都不发生

`Config.ok` 为假时一个字都不会生成。这和推送、OCR 那几处同一个口径 ——
半配的状态最难查,所以缺任何一样都当没配。
"""
import logging

import httpx

logger = logging.getLogger("superz.ai")

#: 一次生成最多要多少字。太长的帖子没人看,也更容易跑题
MAX_CHARS = 400

#: 模型答得太久就放弃这一次 —— 生成内容是背景任务,不值得占着连接等
DEFAULT_TIMEOUT = 30.0

_client: httpx.AsyncClient | None = None


class Config:
    """一次生成用到的配置。**从库里读**,不是环境变量。"""

    __slots__ = ("endpoint", "model", "api_key", "system_prompt", "timeout")

    def __init__(self, endpoint: str = "", model: str = "", api_key: str = "",
                 system_prompt: str = "", timeout: float = DEFAULT_TIMEOUT):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.timeout = timeout

    @property
    def ok(self) -> bool:
        """地址和模型名缺一不可。key 可以为空(本机模型多半不要)。"""
        return bool(self.endpoint and self.model)


def config_of(persona) -> Config:
    """一个机器人自己的模型配置。

    `client` 模式下**这里永远是没配** —— 那一档由 App 调本机模型,
    服务端不该有它的地址,更不该有它的 key。
    """
    if getattr(persona, "mode", "client") != "server":
        return Config()
    key = persona.api_key_enc or ""
    if key:
        from . import crypto
        try:
            key = crypto.decrypt(key)
        except Exception:
            # 换过 FERNET 密钥、值被手工改过:当没配,而不是拿一串密文当 key 发出去
            logger.warning("机器人 %s 的 api key 解不开,当没配", persona.user_id)
            key = ""
    return Config(endpoint=persona.endpoint or "", model=persona.model or "",
                  api_key=key, system_prompt=persona.persona or "",
                  timeout=max(1.0, min(float(persona.timeout_seconds or DEFAULT_TIMEOUT),
                                       120.0)))


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient()
    return _client


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def set_client_for_test(c: httpx.AsyncClient) -> None:
    global _client
    _client = c


class Reply:
    """一次生成的结果。**不抛异常** —— 生成内容失败不该把调用方带倒。"""

    __slots__ = ("text", "error")

    def __init__(self, text: str = "", error: str = ""):
        self.text = text
        self.error = error

    @property
    def ok(self) -> bool:
        return bool(self.text)

    def __repr__(self) -> str:
        return f"Reply(text={self.text[:40]!r}, error={self.error!r})"


def clean(text: str) -> str:
    """模型爱加的那几样去掉:首尾引号、"以下是…"这类前言、超长。

    **不做内容审核** —— 那是发布那一层的事(违禁词、先审后发都在原路径上),
    这里只做形状上的收拾。
    """
    t = (text or "").strip()
    for a, b in (("“", "”"), ('"', '"'), ("「", "」")):
        if t.startswith(a) and t.endswith(b) and len(t) > 2:
            t = t[1:-1].strip()
    return t[:MAX_CHARS]


async def complete(cfg: Config, prompt: str, *, system: str = "") -> Reply:
    """让模型答一段。返回 [Reply];失败只回错误,不抛。

    **配置必须由调用方给** —— 没有"默认用平台的模型"这回事。
    """
    if not cfg.ok:
        return Reply(error="这个机器人没填模型地址")
    messages = []
    sys = system or cfg.system_prompt
    if sys:
        messages.append({"role": "system", "content": sys})
    messages.append({"role": "user", "content": prompt})
    headers = {"content-type": "application/json"}
    if cfg.api_key:
        headers["authorization"] = f"Bearer {cfg.api_key}"
    try:
        c = await _get_client()
        r = await c.post(f"{cfg.endpoint}/chat/completions",
                         json={"model": cfg.model, "messages": messages,
                               "max_tokens": 600, "temperature": 0.9},
                         headers=headers, timeout=cfg.timeout)
    except Exception as e:
        logger.warning("大模型请求异常: %s", e)
        return Reply(error=f"{type(e).__name__}")
    if r.status_code != 200:
        return Reply(error=f"HTTP {r.status_code} {r.text[:120]}")
    try:
        data = r.json()
        text = data["choices"][0]["message"]["content"]
    except Exception:
        return Reply(error=f"回复不是预期的形状:{r.text[:120]}")
    out = clean(text)
    return Reply(text=out) if out else Reply(error="模型回了空")
