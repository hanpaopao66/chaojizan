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
