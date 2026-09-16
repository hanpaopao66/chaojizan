"""华为推送(HMS Push Kit)直连(#384 第二步)。

国内安卓上 App 被杀掉之后,**只有手机厂商自己的通道叫得醒它**。华为这条覆盖
华为和部分荣耀机型,是国内份额最大的一条。

## 两步:先换令牌,再发

1. `POST oauth-login.cloud.huawei.com/oauth2/v3/token`,client_credentials,
   拿 `access_token`(默认 1 小时);
2. `POST push-api.cloud.huawei.com/v1/{appId}/messages:send`,Bearer 上面那个令牌。

令牌缓存见 base.TokenCache:提前 5 分钟续期,并且同一时刻只换一次 ——
一批推送同时发现令牌过期、并发去换 N 次,是会被对方限流的。

## 「这个 token 没用了」怎么判

华为**不是用 HTTP 状态码**表达这件事:整体成功回 `80000000`;部分 token 失效时
回 `80100000`,失效的那些在 `msg` 里(一段 JSON,`illegal_tokens` 数组)。
所以这里按业务码判,并且**只有在失效清单里点到名的 token 才算 gone** ——
判宽了会把好设备下线,而用户从此收不到推送、不会来报这个 bug。

其余各种码(权限、参数、限流)一律不算 gone:那些是我们自己的问题,
下线设备只会把问题藏起来。
"""
import json
import logging
import time

from ...config import settings
from .base import NOT_CONFIGURED, Result, TokenCache, client

logger = logging.getLogger("superz.push.hms")

OAUTH_URL = "https://oauth-login.cloud.huawei.com/oauth2/v3/token"
SEND_URL = "https://push-api.cloud.huawei.com/v1/{app_id}/messages:send"

#: 整体成功
OK_CODE = "80000000"
#: 部分 token 失效(失效清单在 msg 里)
PARTIAL_CODE = "80100000"

_token = TokenCache("hms")


def configured() -> bool:
    return bool(settings.hms_app_id and settings.hms_app_secret)


def package_for(app: str) -> str:
    """哪个端对应哪个安卓包名。点击通知要拉起对应的 App,填错就拉不起来。"""
    return {
        "user": settings.hms_package_user,
        "merchant": settings.hms_package_merchant,
        "rider": settings.hms_package_rider,
    }.get(app, settings.hms_package_user)


async def access_token(now: float | None = None) -> str:
    now = now or time.time()
    cached = _token.peek(now)
    if cached:
        return cached
    async with _token.lock:
        cached = _token.peek(now)  # 等锁的时候别人可能已经换好了
        if cached:
            return cached
        c = await client("hms")
        r = await c.post(OAUTH_URL, data={
            "grant_type": "client_credentials",
            "client_id": settings.hms_app_id,
            "client_secret": settings.hms_app_secret,
        }, headers={"content-type": "application/x-www-form-urlencoded"})
        r.raise_for_status()
        data = r.json()
        tok = data.get("access_token") or ""
        if not tok:
            raise RuntimeError(f"华为没给 access_token: {str(data)[:200]}")
        _token.put(tok, float(data.get("expires_in") or 3600), now)
        return tok


def reset_token_for_test() -> None:
    _token.clear()


def message(token: str, title: str, content: str, extras: dict | None, *,
            app: str = "user") -> dict:
    """华为的消息体。

    `click_action.type = 3` = 点击打开应用首页 —— 我们不用深链(那要在
    AndroidManifest 里登记 intent),打开首页之后 App 自己按 extras 跳转。
    """
    return {
        "validate_only": False,
        "message": {
            "token": [token],
            "android": {
                "notification": {
                    "title": title,
                    "body": content,
                    "click_action": {"type": 3},
                },
                # 自定义字段:客户端点开之后按它跳转。华为要求是字符串
                "data": json.dumps(extras or {}, ensure_ascii=False),
            },
        },
    }


def _illegal(msg: str) -> set[str]:
    """从 `msg` 里挑出失效的 token。解析不出来就当空 —— 宁可不下线。"""
    try:
        data = json.loads(msg)
    except Exception:
        return set()
    out = data.get("illegal_tokens")
    return set(out) if isinstance(out, list) else set()


async def send(token: str, title: str, content: str, extras: dict | None = None, *,
               app: str = "user", **_ignored) -> Result:
    if not configured():
        return NOT_CONFIGURED
    try:
        tok = await access_token()
        c = await client("hms")
        r = await c.post(
            SEND_URL.format(app_id=settings.hms_app_id),
            headers={"authorization": f"Bearer {tok}",
                     "content-type": "application/json; charset=UTF-8"},
            content=json.dumps(message(token, title, content, extras, app=app),
                               ensure_ascii=False).encode(),
        )
    except Exception as e:
        logger.warning("华为推送异常 token=%s…: %s", token[:8], e)
        return Result(False, f"hms {type(e).__name__}")
    if r.status_code == 401:
        # 令牌过期了(或者被作废)。清掉缓存,下一条会重新换 —— 但**不重试这一条**:
        # 重试要处理"重试也失败"的分支,而下一条推送马上就来
        _token.clear()
        return Result(False, "hms 401 令牌失效,已清缓存")
    try:
        data = r.json()
    except Exception:
        return Result(False, f"hms {r.status_code} {r.text[:100]}")
    code = str(data.get("code") or "")
    if code == OK_CODE:
        return Result(True)
    msg = str(data.get("msg") or "")
    if code == PARTIAL_CODE:
        # 只有点到名的才算没用了
        return Result(False, f"hms {code}", gone=token in _illegal(msg))
    logger.warning("华为推送失败 code=%s msg=%s", code, msg[:200])
    return Result(False, f"hms {code} {msg[:80]}".strip())
