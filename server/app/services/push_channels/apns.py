"""苹果推送(APNs)直连 —— 不经过任何第三方(#384)。

## 为什么自己接

推送原本走极光:一个第三方拿到「谁在什么时候收到了什么标题」,还要按量付费。
苹果这一端**根本不需要中间商**:APNs 是系统级通道,免费、无配额,认证只要一个
`.p8` 密钥(一个开发者账号下所有 App 共用)。中间商在这里买不到任何东西。

## 认证:JWT,不是证书

苹果两种认证都支持。用 token(JWT)那种:

- 一个 `.p8` 私钥 + Key ID + Team ID,**不会过期**(证书每年要换,换晚了全站收不到推送);
- 令牌自己有效期最长 1 小时,苹果还要求**不要比 20 分钟更频繁地换** ——
  换太勤会被当成滥用直接回 429 TooManyProviderTokenUpdates。所以这里缓存 50 分钟。

## 只有 HTTP/2

APNs 没有 HTTP/1.1 的路。httpx 要装 `h2` 这个额外依赖才开得了 HTTP/2 ——
没装的话表现是连接直接失败,而不是"降级成 1.1 还能用"。requirements 里写死了。

## 沙箱和生产是两台服务器,token 不通用

Xcode 装的包、TestFlight 的包拿到的是**沙箱** token,App Store 的是生产。
发错环境回 400 BadDeviceToken —— 这是"为什么开发机收不到推送"的头号原因,
所以设备表里存了 `sandbox`,按设备选地址,不靠猜。
"""
import json
import logging
import time

import httpx

from ...config import settings
from .base import Result

logger = logging.getLogger("superz.push.apns")

PROD_HOST = "https://api.push.apple.com"
SANDBOX_HOST = "https://api.sandbox.push.apple.com"

#: 苹果要求别比 20 分钟更勤地换令牌,上限 1 小时。取中间偏后
_TOKEN_TTL = 50 * 60

_token: tuple[str, float] | None = None
_client: httpx.AsyncClient | None = None


def configured() -> bool:
    """配齐了没有。缺任何一样都当没配 —— 半配的状态最难查"""
    return bool(settings.apns_key_p8 and settings.apns_key_id and settings.apns_team_id)


def auth_token(now: float | None = None) -> str:
    """当前的提供者令牌(JWT,ES256 签名)。到点自动换,没到点复用。"""
    global _token
    now = now or time.time()
    if _token is not None and now - _token[1] < _TOKEN_TTL:
        return _token[0]
    import jwt  # 惰性导入:没配 APNs 的部署不该为这个多加载一个库

    token = jwt.encode(
        {"iss": settings.apns_team_id, "iat": int(now)},
        settings.apns_key_p8.replace("\\n", "\n"),
        algorithm="ES256",
        headers={"kid": settings.apns_key_id},
    )
    _token = (token, now)
    return token


def reset_token_for_test() -> None:
    global _token
    _token = None


def topic_for(app: str) -> str:
    """哪个端推给哪个 bundle id。**apns-topic 必须是 bundle id**,填错是静默不到。"""
    return {
        "user": settings.apns_topic_user,
        "merchant": settings.apns_topic_merchant,
        "rider": settings.apns_topic_rider,
    }.get(app, settings.apns_topic_user)


def payload(title: str, content: str, extras: dict | None, *, badge: int | None = None) -> dict:
    """APNs 的载荷。

    `mutable-content` 开着,客户端才能在通知扩展里改内容(比如把头像下下来);
    `content-available` **不开** —— 那是静默推送,苹果对它限流,而我们这里每一条都是
    要弹出来给人看的。
    """
    aps: dict = {"alert": {"title": title, "body": content}, "sound": "default",
                 "mutable-content": 1}
    if badge is not None:
        aps["badge"] = badge
    return {"aps": aps, **(extras or {})}


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(http2=True, timeout=10)
    return _client


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


#: 这几种回复意味着这个 token 永远不会再收到东西了,别再发
GONE_REASONS = {"Unregistered", "BadDeviceToken", "DeviceTokenNotForTopic", "ExpiredToken"}


async def send(token: str, title: str, content: str, extras: dict | None = None, *,
               app: str = "user", sandbox: bool = False,
               collapse_id: str | None = None) -> Result:
    """推一条。返回 [Result];**不抛异常** —— 推送失败不该把调用方的流程带倒。"""
    if not configured():
        return Result(False, "没配 APNs")
    host = SANDBOX_HOST if sandbox else PROD_HOST
    headers = {
        "authorization": f"bearer {auth_token()}",
        "apns-topic": topic_for(app),
        "apns-push-type": "alert",
        # 5 = 系统可以攒着省电;10 = 立刻送。聊天消息要立刻
        "apns-priority": "10",
        # 一天后还没送到就别送了 —— 昨天的"你有一条新消息"弹出来只会让人困惑
        "apns-expiration": str(int(time.time()) + 86400),
    }
    if collapse_id:
        # 同一个会话的多条在锁屏上合成一条(苹果只保留最后一条)
        headers["apns-collapse-id"] = collapse_id[:64]
    try:
        client = await _get_client()
        r = await client.post(f"{host}/3/device/{token}",
                              headers=headers,
                              content=json.dumps(payload(title, content, extras),
                                                 ensure_ascii=False).encode())
    except Exception as e:  # 网络、TLS、HTTP/2 协商失败
        logger.warning("APNs 发送异常 token=%s…: %s", token[:8], e)
        return Result(False, f"{type(e).__name__}")
    if r.status_code == 200:
        return Result(True)
    reason = ""
    try:
        reason = (r.json() or {}).get("reason", "")
    except Exception:
        reason = r.text[:100]
    # 410 是苹果明说"这个 token 已经没了";400 里只有那几种 reason 才是永久失效,
    # 别的(载荷太大、topic 写错)是我们自己的问题,下线设备只会掩盖它
    gone = r.status_code == 410 or reason in GONE_REASONS
    if not gone:
        logger.warning("APNs %s %s token=%s…", r.status_code, reason, token[:8])
    return Result(False, f"{r.status_code} {reason}".strip(), gone=gone)
