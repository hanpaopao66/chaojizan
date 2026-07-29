"""极光推送(JPush)服务端直推。

未配置 Key 时静默跳过(返回 False),所有调用点都不感知。
客户端集成(setAlias 绑定 u{user_id})见 docs/INTEGRATIONS.md。
"""
import logging

import httpx

from ..config import settings

logger = logging.getLogger("superz.push")

JPUSH_URL = "https://api.jpush.cn/v3/push"


async def _record(user_id: int, title: str, content: str, ok: bool, error: str) -> None:
    """写 push_logs;记录失败不能反过来影响推送主流程。"""
    from ..db import SessionLocal
    from ..models import PushLog

    try:
        async with SessionLocal() as db:
            db.add(PushLog(user_id=user_id, title=title,
                           content=content[:200], ok=ok, error=error[:300]))
            await db.commit()
    except Exception:
        logger.exception("push_logs 写入失败")


async def push_to_user(user_id: int, title: str, content: str,
                       extras: dict | None = None,
                       record_skip: bool = False) -> bool:
    """按别名推给单个用户(客户端登录后 setAlias('u{user_id}'))。

    record_skip:未配置 JPush 时是否仍写 push_logs(error=未配置)。
    订单状态类高频推送保持静默跳过;回复/收藏/召回等触达类传 True——
    低频、值得留痕,配好 Key 前就能验证触发链路,配好后无缝变真实发送。
    """
    if not settings.jpush_configured:
        logger.debug("jpush 未配置,跳过推送: u%s %s", user_id, title)
        if record_skip:
            await _record(user_id, title, content, False, "jpush 未配置(仅记录意图)")
        return False
    payload = {
        "platform": "all",
        "audience": {"alias": [f"u{user_id}"]},
        "notification": {
            "android": {"alert": content, "title": title, "extras": extras or {}},
            "ios": {"alert": {"title": title, "body": content},
                    "sound": "default", "extras": extras or {}},
        },
        "options": {"apns_production": True, "time_to_live": 3600},
    }
    ok, error = False, ""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                JPUSH_URL,
                json=payload,
                auth=(settings.jpush_app_key, settings.jpush_master_secret),
            )
        if resp.status_code == 200:
            ok = True
        else:
            error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.warning("jpush 推送失败 %s", error)
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("jpush 请求异常: %s", exc)
    await _record(user_id, title, content, ok, error)
    return ok


async def notify_order_status(customer_id: int, order_no: str, status_label: str) -> None:
    """订单状态变更推给用户。推送失败不影响主流程。"""
    await push_to_user(
        customer_id,
        "订单状态更新",
        f"你的订单{status_label}",
        {"order_no": order_no},
    )


async def notify_new_order(merchant_owner_id: int, order_no: str, summary: str) -> None:
    """新订单推给商家老板(离线也能听到,替代只在前台有效的 WebSocket)。"""
    await push_to_user(
        merchant_owner_id,
        "新订单来了",
        summary,
        {"order_no": order_no, "type": "new_order"},
    )


async def notify_riders_new_grab(db, order, shop_name: str) -> int:
    """新单进抢单池 → 推给附近在线的骑手(#114),返回触达人数。

    抢单模式最怕的不是没人抢,是没人知道有单可抢:骑手端只能靠轮询,
    锁屏了就彻底静默 —— 于是出现「单子挂在池里 30 分钟无人接,
    平台按无人接单兜底赔付商家餐损」的局面,骑手也白等一场。

    只推给在线骑手,且按各自的抢单半径过滤(骑手自己设的,不是平台派的):
    抢单仍是广播制,这里只是把广播送到耳边,不改成强制派单。
    同一单每人只推一次(Redis nx),不做「催抢单」的二次轰炸 ——
    真正的兜底催单在 no_rider_alert_minutes 那条线上,各司其职。
    """
    from sqlalchemy import select

    from ..models import Merchant, User, UserRole
    from ..redis_client import RIDER_LOC_KEY, get_redis
    from ..services.pricing import haversine_m

    try:
        merchant = await db.get(Merchant, order.merchant_id)
        if merchant is None:
            return 0
        riders = (await db.scalars(select(User).where(
            User.role == UserRole.rider,
            User.is_online.is_(True)))).all()
        if not riders:
            return 0
        redis = get_redis()
        sent = 0
        for rider in riders:
            # 多城市隔离:骑手标了城市就只推本城的单(商家没标城市的不隔离)
            if rider.city and merchant.city and rider.city != merchant.city:
                continue
            # 骑手位置取不到(没上报/已过期)就不推:宁可漏推,
            # 也不把 20 公里外的单推到人脸上
            loc = await redis.hgetall(RIDER_LOC_KEY.format(rider_id=rider.id))
            try:
                rider_lat = float(loc["lat"])
                rider_lng = float(loc["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            if merchant.lat is None or merchant.lng is None:
                continue
            distance = haversine_m(rider_lat, rider_lng,
                                   merchant.lat, merchant.lng)
            radius_m = (rider.grab_radius_km or 0) * 1000
            if radius_m and distance > radius_m:
                continue
            if not await redis.set(f"grab_push:{order.order_no}:{rider.id}", 1,
                                   ex=3600, nx=True):
                continue
            # record_skip:留痕。骑手是最可能事后追问"我怎么没收到这单"的一方,
            # push_logs 让这件事可查而不是各执一词;也让 JPush Key 落地前
            # 就能验证触发链路
            await push_to_user(
                rider.id, "有新单可抢",
                f"{shop_name} · 距你 {round(distance / 1000, 1)}km · "
                f"配送费 {order.delivery_fee_cents / 100:g} 元(全额归你)",
                {"type": "new_grab", "order_no": order.order_no},
                record_skip=True)
            sent += 1
        return sent
    except Exception:
        logger.exception("骑手新单推送失败(不影响主流程): order=%s",
                         getattr(order, "order_no", "?"))
        return 0


async def notify_review_reply(customer_id: int, shop_name: str, reply: str) -> None:
    """商家回复了评价 → 推给写评价的用户(回复不触达 = 白写)。"""
    await push_to_user(
        customer_id,
        f"「{shop_name}」回复了你的评价",
        reply[:80],
        {"type": "review_reply"},
        record_skip=True,
    )


async def notify_favorites(db, merchant_id: int, shop_name: str,
                           title: str, content: str) -> int:
    """收藏触达:收藏了该店的用户逐个推送,返回触达人数。

    防打扰:每店每天最多一条(Redis nx 键),商家连发三张券用户只收到第一条。
    调用方失败不感知——触达是锦上添花,绝不能影响发券/改菜主流程。
    """
    from sqlalchemy import select

    from ..models import Favorite
    from ..redis_client import get_redis

    try:
        if not await get_redis().set(f"fav_push:{merchant_id}", 1,
                                     ex=86400, nx=True):
            return 0
        user_ids = (await db.scalars(
            select(Favorite.user_id)
            .where(Favorite.merchant_id == merchant_id).limit(500))).all()
        for uid in user_ids:
            await push_to_user(uid, title, content,
                               {"type": "favorite", "merchant_id": merchant_id},
                               record_skip=True)
        return len(user_ids)
    except Exception:
        logger.exception("收藏触达失败(不影响主流程): merchant=%s", merchant_id)
        return 0
