"""接自己的大模型(#385)。

## 为什么配置在后台不在 .env

换模型、改地址、调提示词是**运营会反复做的事**,做成环境变量意味着每改一次都要
改部署机上的文件再重启 —— 那不是这类配置该有的成本。所以和「首页显示哪些业务」
「文案与显示」一样,放进平台开关(`platform_flags`),后台改完立即生效。

## 只认 OpenAI 兼容的接口

`POST {base}/chat/completions`,`{"model": …, "messages": [...]}`。
本机跑的 llama.cpp、vLLM、Ollama、LM Studio 都提供这个形状,一个地址就接上了。
**不为任何一家写专门的适配** —— 那是把自己绑在某一家上。

## API key 的存法和别的开关不一样

它是密钥:存密文(services/crypto),后台读回来只说「已设置 / 未设置」,不回明文。
本机跑的模型多半根本不需要 key,留空就是不带这个头。

## 一条硬规矩:不配就什么都不发生

`configured()` 为假时,上层一个字都不会生成。这和推送、OCR 那几处同一个口径 ——
半配的状态最难查,所以缺任何一样都当没配。
"""
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PlatformFlag

logger = logging.getLogger("superz.ai")

#: 后台可配的几项。值都存在 platform_flags 里,改完立即生效、不用发版
ENDPOINT = "ai_endpoint"
MODEL = "ai_model"
API_KEY = "ai_api_key"          # 存密文,后台读回来只说有没有
SYSTEM_PROMPT = "ai_system_prompt"
TIMEOUT = "ai_timeout_seconds"

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


async def config(db: AsyncSession) -> Config:
    rows = {r.key: r.value for r in await db.scalars(select(PlatformFlag).where(
        PlatformFlag.key.in_([ENDPOINT, MODEL, API_KEY, SYSTEM_PROMPT, TIMEOUT])))}
    key = rows.get(API_KEY) or ""
    if key:
        from . import crypto
        try:
            key = crypto.decrypt(key)
        except Exception:
            # 换过 FERNET 密钥、值被手工改过:当没配,而不是拿一串密文去当 key 发出去
            logger.warning("AI 的 api key 解不开,当没配")
            key = ""
    try:
        timeout = float(rows.get(TIMEOUT) or DEFAULT_TIMEOUT)
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    return Config(endpoint=rows.get(ENDPOINT) or "", model=rows.get(MODEL) or "",
                  api_key=key, system_prompt=rows.get(SYSTEM_PROMPT) or "",
                  timeout=max(1.0, min(timeout, 120.0)))


async def configured(db: AsyncSession) -> bool:
    return (await config(db)).ok


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


async def complete(db: AsyncSession, prompt: str, *, system: str = "",
                   cfg: Config | None = None) -> Reply:
    """让模型答一段。返回 [Reply];失败只回错误,不抛。"""
    cfg = cfg or await config(db)
    if not cfg.ok:
        return Reply(error="没配大模型(后台「开关」页填地址和模型名)")
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
