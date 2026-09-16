"""OPPO 推送直连(#384 第二步)。

## 两步:先换 auth_token,再发

1. `POST api.push.oppomobile.com/server/v1/auth`,表单 `app_key` / `timestamp` /
   `sign = SHA256(app_key + timestamp + master_secret)`,拿 `data.auth_token`(约 24 小时);
2. `POST .../server/v1/message/notification/unicast`,请求头带 `auth_token`,
   表单里一个 `message` 字段装 JSON。

**timestamp 是毫秒。** 用秒的话签名永远对不上,而返回的是一句笼统的鉴权失败 ——
这是这一家最容易卡住的地方。

## 「这个 token 没用了」怎么判

判得很窄:只有明确说这个 registration_id 不合法时才算 gone。
拿不准一律不下线 —— 少下线一台只是多发几次无用请求,下线错一台是真丢用户。
"""
import hashlib
import json
import logging
import time

from ...config import settings
from .base import NOT_CONFIGURED, Result, TokenCache, client

logger = logging.getLogger("superz.push.oppo")

AUTH_URL = "https://api.push.oppomobile.com/server/v1/auth"
SEND_URL = "https://api.push.oppomobile.com/server/v1/message/notification/unicast"

#: OPPO 说「这个注册 id 不合法 / 不存在」的几种说法
GONE_HINTS = ("registration_id", "regid", "invalid target", "token")

_token = TokenCache("oppo", margin=3600)  # 24 小时的令牌,提前一小时换


def configured() -> bool:
    return bool(settings.oppo_app_key and settings.oppo_master_secret)


def sign(app_key: str, timestamp_ms: str, master_secret: str) -> str:
    """OPPO 的签名:SHA256(app_key + timestamp + master_secret),十六进制小写。"""
    return hashlib.sha256(f"{app_key}{timestamp_ms}{master_secret}".encode()).hexdigest()


async def auth_token(now: float | None = None) -> str:
    now = now or time.time()
    cached = _token.peek(now)
    if cached:
        return cached
    async with _token.lock:
        cached = _token.peek(now)
        if cached:
            return cached
        ts = str(int(now * 1000))  # 毫秒 —— 用秒签名永远对不上
        c = await client("oppo")
        r = await c.post(AUTH_URL, data={
            "app_key": settings.oppo_app_key,
            "timestamp": ts,
            "sign": sign(settings.oppo_app_key, ts, settings.oppo_master_secret),
        }, headers={"content-type": "application/x-www-form-urlencoded"})
        r.raise_for_status()
        data = r.json()
        tok = ((data.get("data") or {}).get("auth_token")) or ""
        if not tok:
            raise RuntimeError(f"OPPO 没给 auth_token: {str(data)[:200]}")
        _token.put(tok, 24 * 3600, now)
        return tok


def reset_token_for_test() -> None:
    _token.clear()


def message(token: str, title: str, content: str, extras: dict | None) -> dict:
    """单推的消息体。

    `click_action_type = 0` = 点击打开应用首页。和华为那边同一个道理:
    不用深链(要在清单里登记),打开首页之后 App 自己按 `action_parameters` 跳。
    """
    return {
        "target_type": 2,          # 2 = 按 registration_id 单推
        "target_value": token,
        "notification": {
            "title": title,
            "content": content,
            "click_action_type": 0,
            "action_parameters": json.dumps(extras or {}, ensure_ascii=False),
        },
    }


def _gone(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in GONE_HINTS) and ("invalid" in low or "不合法" in text
                                                  or "不存在" in text)


async def send(token: str, title: str, content: str, extras: dict | None = None, *,
               app: str = "user", **_ignored) -> Result:
    if not configured():
        return NOT_CONFIGURED
    try:
        tok = await auth_token()
        c = await client("oppo")
        r = await c.post(SEND_URL,
                         data={"message": json.dumps(message(token, title, content, extras),
                                                     ensure_ascii=False)},
                         headers={"auth_token": tok,
                                  "content-type": "application/x-www-form-urlencoded"})
    except Exception as e:
        logger.warning("OPPO 推送异常 token=%s…: %s", token[:8], e)
        return Result(False, f"oppo {type(e).__name__}")
    try:
        data = r.json()
    except Exception:
        return Result(False, f"oppo {r.status_code} {r.text[:100]}")
    if str(data.get("code")) == "0":
        return Result(True)
    detail = str(data.get("message") or data.get("errMsg") or "")
    if str(data.get("code")) in ("11", "-2"):
        # 鉴权类:令牌过期 / 被作废。清缓存,下一条重新换(**不重试这一条**)
        _token.clear()
    logger.warning("OPPO 推送失败 code=%s %s", data.get("code"), detail[:200])
    return Result(False, f"oppo {data.get('code')} {detail[:80]}".strip(), gone=_gone(detail))
