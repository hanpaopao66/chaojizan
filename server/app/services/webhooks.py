"""商家系统回调:来单就推过去,而不是让商家轮询。

此前开放接口只有两个 GET,商家的收银系统只能轮询 —— 要么慢(轮询间隔
就是延迟),要么把我们的接口打爆(为了快就 1 秒一次)。

## 安全:商家填的 URL 是任意的,不拦就是一个 SSRF

我们拿着服务端的网络位置去访问一个**用户提供的地址**。不做校验的话,
有人填 `http://169.254.169.254/latest/meta-data/` 就能把云厂商的
实例元数据(含临时凭证)读出来,填 `http://127.0.0.1:8010/admin/...`
就能借我们的身份打内网。

所以三道:
1. 只允许 http/https,只允许默认端口(80/443) —— 非默认端口基本都是内网服务;
2. **解析出 IP 之后**再判(光看域名没用:攻击者可以把自己的域名解析到
   127.0.0.1,这叫 DNS rebinding 的入门版);拒绝回环、私有段、链路本地、
   保留段;
3. 不跟随重定向 —— 跟随的话第一跳合法、第二跳跳内网,前两道全白做。

## 重试:1/5/30/300/1800 秒,五次

退避到半小时是给商家的服务器留出重启和修复的时间。全失败进死信,
商家在设置页能看到"哪几单没推过去",可以手动补推 ——
**不能只是丢掉**:商家以为收到了、实际没有,比明确失败糟得多。

连续失败到阈值自动停用整个 webhook:一直推一个死地址既浪费我们的连接,
也让商家以为还在收单。
"""
import hashlib
import hmac
import ipaddress
import logging
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# 重试节奏(秒)。到半小时为止 —— 再久的话商家修好了也等太久
RETRY_DELAYS = (1, 5, 30, 300, 1800)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
# 连续失败多少次自动停用整个 webhook
DISABLE_AFTER = 20

EVENTS = {
    "order.paid": "支付成功(新单)",
    "order.accepted": "商家接单",
    "order.ready": "出餐完成",
    "order.delivered": "订单送达",
    "order.cancelled": "订单取消",
    "order.refunded": "订单退款",
}


class UnsafeUrl(ValueError):
    """URL 指向内网/回环/元数据服务,拒绝投递。"""


def validate_url(url: str) -> None:
    """回调地址校验。不通过抛 UnsafeUrl(文案直接给商家看)。

    **每次投递前都要再校验一次**,不能只在保存时校验:域名对应的 IP
    是会变的,保存时指向公网、投递时指向 127.0.0.1 是最经典的绕法。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrl("回调地址必须是 http:// 或 https://")
    if not parsed.hostname:
        raise UnsafeUrl("回调地址缺少域名")
    if parsed.port not in (None, 80, 443):
        # 非默认端口的基本都是内网服务(8080 的管理后台、6379 的 Redis)
        raise UnsafeUrl("回调地址只支持默认端口(http 80 / https 443)")

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise UnsafeUrl("回调地址的域名解析不了")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # 逐条列出来而不是只判 is_private:链路本地(169.254.169.254 是
        # 云厂商的元数据地址)不在 is_private 里,而它恰恰是最该拦的那个
        if (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise UnsafeUrl(
                f"回调地址解析到内网地址({ip}),出于安全不能投递 —— "
                "请填一个公网可访问的地址")


def sign(secret: str, body: bytes, timestamp: str) -> str:
    """HMAC-SHA256(timestamp.body)。

    **把时间戳纳入签名**:只签 body 的话,攻击者录下一个合法请求就能
    无限重放 —— 商家侧看到的是"这单又来了一次"。商家应当拒绝
    时间戳偏差超过 5 分钟的请求,这一点写进对接文档。
    """
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body,
                   hashlib.sha256)
    return mac.hexdigest()


def build_payload(event: str, order, delivery_id: str) -> dict:
    """推给商家的订单体。

    **不含顾客真实手机号**:推的是隐私号或打码号,与小票、开放接口
    同一个口径 —— 顾客的号码不因为商家接了个系统就变成明文流出去。
    """
    from .privacy_phone import mask_phone

    return {
        "event": event,
        "delivery_id": delivery_id,
        "order_no": order.order_no,
        "status": order.status.value if hasattr(order.status, "value")
        else str(order.status),
        "merchant_id": order.merchant_id,
        "created_at": (order.created_at.isoformat()
                       if order.created_at else None),
        "pickup": order.pickup,
        "pickup_code": order.pickup_code or "",
        "items": [{"name": i.get("name"), "quantity": i.get("quantity"),
                   "price_cents": i.get("price_cents")}
                  for i in (order.items or [])],
        "food_cents": order.food_cents,
        "packing_fee_cents": order.packing_fee_cents,
        "discount_cents": order.discount_cents,
        "delivery_fee_cents": order.delivery_fee_cents,
        "total_cents": order.total_cents,
        "remark": order.remark or "",
        "contact_name": order.contact_name or "",
        # 隐私号优先,没有就给打码号 —— 真号永不出站
        "contact_phone": order.privacy_phone
        or mask_phone(order.contact_phone or ""),
        "address": order.address or "",
    }


async def deliver(delivery, webhook, secret: str) -> tuple[bool, int, str]:
    """投一次。返回 (是否成功, 状态码, 错误文案)。"""
    import json

    try:
        validate_url(webhook.url)
    except UnsafeUrl as exc:
        return False, 0, str(exc)

    body = json.dumps(delivery.payload, ensure_ascii=False).encode()
    ts = str(int(datetime.now(timezone.utc).timestamp()))
    headers = {
        "Content-Type": "application/json",
        "X-SuperZ-Event": delivery.event,
        "X-SuperZ-Delivery": delivery.delivery_id,
        "X-SuperZ-Timestamp": ts,
        "X-SuperZ-Signature": sign(secret, body, ts),
    }
    try:
        async with httpx.AsyncClient(
                timeout=8, follow_redirects=False) as client:
            resp = await client.post(webhook.url, content=body,
                                     headers=headers)
        ok = 200 <= resp.status_code < 300
        return ok, resp.status_code, "" if ok else resp.text[:200]
    except httpx.HTTPError as exc:
        return False, 0, str(exc)[:200]


def next_retry(attempts: int) -> datetime | None:
    """下一次重试的时刻;重试用尽返回 None。"""
    if attempts >= MAX_ATTEMPTS:
        return None
    return (datetime.now(timezone.utc)
            + timedelta(seconds=RETRY_DELAYS[attempts - 1]))


async def enqueue(db, merchant_id: int, event: str, order) -> int:
    """把一个事件排进这家店所有订阅了它的 webhook。返回排了几条。

    **只入队不投递**:投递走清扫任务。在下单/支付的主流程里同步 POST
    一个外部地址,对方慢 8 秒我们就卡 8 秒 —— 商家的服务器不该有能力
    拖慢我们的支付回调。
    """
    import uuid

    from sqlalchemy import select

    from ..models import MerchantWebhook, WebhookDelivery

    hooks = list(await db.scalars(select(MerchantWebhook).where(
        MerchantWebhook.merchant_id == merchant_id,
        MerchantWebhook.active.is_(True))))
    n = 0
    for h in hooks:
        if h.events and event not in h.events:
            continue
        did = uuid.uuid4().hex
        db.add(WebhookDelivery(
            webhook_id=h.id, event=event, delivery_id=did,
            order_no=order.order_no, status="pending", attempts=0,
            next_retry_at=datetime.now(timezone.utc),
            payload=build_payload(event, order, did)))
        n += 1
    return n


async def sweep_webhooks(limit: int = 50) -> dict[str, int]:
    """投递 + 重试。每轮清扫跑一次。

    一次最多处理 limit 条:回调是给商家的便利,不能让它挤占清扫循环里
    的订单流转(那是钱和体验)。积压时下一轮继续。
    """
    from sqlalchemy import select

    from ..db import SessionLocal
    from ..models import MerchantWebhook, WebhookDelivery

    now = datetime.now(timezone.utc)
    sent = failed = dead = 0
    async with SessionLocal() as db:
        rows = list(await db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.status == "pending",
                   WebhookDelivery.next_retry_at <= now)
            .order_by(WebhookDelivery.id).limit(limit)))
        if not rows:
            return {}
        hooks = {h.id: h for h in await db.scalars(
            select(MerchantWebhook).where(MerchantWebhook.id.in_(
                {r.webhook_id for r in rows})))}
        from ..redis_client import get_redis
        redis = get_redis()
        for d in rows:
            h = hooks.get(d.webhook_id)
            if h is None or not h.active:
                d.status = "failed"
                d.last_error = "回调已停用"
                dead += 1
                continue
            # 明文密钥只在创建时给过商家一次,签名要用它 —— 存在 Redis,
            # 库里存的是哈希(库被拖走时签不出有效请求)
            secret = await redis.get(f"webhook:secret:{h.id}")
            if not secret:
                d.status = "failed"
                d.last_error = "回调密钥已失效,请在设置页重置"
                dead += 1
                continue
            d.attempts += 1
            ok, code, err = await deliver(d, h, secret)
            d.last_status_code = code
            d.last_error = err[:200]
            if ok:
                d.status = "ok"
                d.next_retry_at = None
                h.fail_streak = 0
                h.last_ok_at = now
                h.last_error = ""
                sent += 1
                continue
            nxt = next_retry(d.attempts)
            if nxt is None:
                d.status = "failed"      # 进死信,商家可在设置页手动补推
                d.next_retry_at = None
                dead += 1
            else:
                d.next_retry_at = nxt
                failed += 1
            h.fail_streak += 1
            h.last_error = err[:200]
            if h.fail_streak >= DISABLE_AFTER:
                # 一直推一个死地址,既浪费我们的连接,也让商家
                # 以为还在收单。停掉并在设置页显红,让他知道要修
                h.active = False
                h.last_error = (f"连续失败 {h.fail_streak} 次已自动停用:"
                                f"{err[:120]}")
        await db.commit()
    return {"sent": sent, "retry": failed, "dead": dead}
