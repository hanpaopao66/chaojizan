"""vivo 推送直连(#384 第二步)。

## 两步:先换 authToken,再发

1. `POST api-push.vivo.com.cn/message/auth`,JSON `{appId, appKey, timestamp,
   sign = MD5(appId + appKey + timestamp + appSecret)}`,拿 `authToken`(约 24 小时);
2. `POST .../message/send`,请求头带 `authToken`,JSON 里给 `regId`。

**timestamp 是毫秒**,和 OPPO 一样;签名是 **MD5** 不是 SHA256(两家不一样,很容易抄串)。

## classification 这一项

vivo 把推送分成「运营消息」(0)和「系统消息」(1),两类的到达策略和配额不一样,
**乱标系统消息会被处罚**。我们发的是聊天、订单这类用户自己要的消息,按 vivo 的口径
属于系统消息 —— 但这件事要以你在 vivo 后台申请到的类别为准,所以做成配置
(`VIVO_CLASSIFICATION`,默认 1),不写死。

## 「这个 token 没用了」怎么判

同样判得很窄:只有明确说 regId 不合法 / 已失效时才算 gone。
"""
import hashlib
import json
import logging
import time
import uuid

from ...config import settings
from .base import NOT_CONFIGURED, Result, TokenCache, client

logger = logging.getLogger("superz.push.vivo")

AUTH_URL = "https://api-push.vivo.com.cn/message/auth"
SEND_URL = "https://api-push.vivo.com.cn/message/send"

GONE_HINTS = ("regid", "reg_id", "invalid", "失效", "不合法", "不存在")

_token = TokenCache("vivo", margin=3600)


def configured() -> bool:
    return bool(settings.vivo_app_id and settings.vivo_app_key and settings.vivo_app_secret)


def sign(app_id: str, app_key: str, timestamp_ms: str, app_secret: str) -> str:
    """vivo 的签名:MD5(appId + appKey + timestamp + appSecret),十六进制小写。

    注意是 **MD5**,不是 OPPO 那家的 SHA256 —— 两家挨着写最容易抄串。
    """
    return hashlib.md5(
        f"{app_id}{app_key}{timestamp_ms}{app_secret}".encode()).hexdigest()


async def auth_token(now: float | None = None) -> str:
    now = now or time.time()
    cached = _token.peek(now)
    if cached:
        return cached
    async with _token.lock:
        cached = _token.peek(now)
        if cached:
            return cached
        ts = str(int(now * 1000))
        c = await client("vivo")
        r = await c.post(AUTH_URL, json={
            "appId": settings.vivo_app_id,
            "appKey": settings.vivo_app_key,
            "timestamp": ts,
            "sign": sign(settings.vivo_app_id, settings.vivo_app_key, ts,
                         settings.vivo_app_secret),
        })
        r.raise_for_status()
        data = r.json()
        tok = data.get("authToken") or ""
        if not tok:
            raise RuntimeError(f"vivo 没给 authToken: {str(data)[:200]}")
        _token.put(tok, 24 * 3600, now)
        return tok


def reset_token_for_test() -> None:
    _token.clear()


def message(token: str, title: str, content: str, extras: dict | None) -> dict:
    """单推的消息体。

    `skipType = 1` = 点击打开应用首页;`requestId` 每条唯一(vivo 靠它去重)。
    """
    return {
        "regId": token,
        "notifyType": 4,   # 铃声 + 震动
        "title": title[:40],
        "content": content[:100],
        "classification": settings.vivo_classification,
        "skipType": 1,
        "clientCustomMap": {k: str(v) for k, v in (extras or {}).items()},
        "requestId": uuid.uuid4().hex,
    }


def _gone(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in GONE_HINTS)


async def send(token: str, title: str, content: str, extras: dict | None = None, *,
               app: str = "user", **_ignored) -> Result:
    if not configured():
        return NOT_CONFIGURED
    try:
        tok = await auth_token()
        c = await client("vivo")
        r = await c.post(SEND_URL,
                         content=json.dumps(message(token, title, content, extras),
                                            ensure_ascii=False).encode(),
                         headers={"authToken": tok,
                                  "content-type": "application/json; charset=UTF-8"})
    except Exception as e:
        logger.warning("vivo 推送异常 token=%s…: %s", token[:8], e)
        return Result(False, f"vivo {type(e).__name__}")
    try:
        data = r.json()
    except Exception:
        return Result(False, f"vivo {r.status_code} {r.text[:100]}")
    if str(data.get("result")) == "0":
        return Result(True)
    detail = str(data.get("desc") or "")
    if str(data.get("result")) in ("10000", "10003"):
        # 鉴权类:令牌过期。清缓存,下一条重新换
        _token.clear()
    logger.warning("vivo 推送失败 result=%s %s", data.get("result"), detail[:200])
    return Result(False, f"vivo {data.get('result')} {detail[:80]}".strip(), gone=_gone(detail))
