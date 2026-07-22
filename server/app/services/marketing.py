"""轻量营销触达三合一:生日券 / 复购提醒 / 收藏店上新。

共同的克制原则:
- 总频控:营销推送每人每自然周 ≤2 条(Redis mkt:freq:{uid}:{年-周});
- 用户可在「我的」一键关闭营销推送(users.marketing_push);
- 发券全部走 #49 批次(admin 建 trigger=birthday/winback 的批次,
  预算封顶),没有启用中的批次就只推不发/不推;
- 每个任务每天只跑一次(Redis 防重,照 #43 备货提醒)。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Coupon, CouponBatch, Dish, Favorite, Merchant, Order,
                      User, UserRole)
from ..redis_client import get_redis
from ..state_machine import OrderStatus
from .push import push_to_user

logger = logging.getLogger("superz.marketing")

WEEKLY_CAP = 2


async def _under_cap(user_id: int) -> bool:
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    key = f"mkt:freq:{user_id}:{now.strftime('%G-%V')}"
    n = int(await get_redis().get(key) or 0)
    return n < WEEKLY_CAP


async def _count_send(user_id: int) -> None:
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    key = f"mkt:freq:{user_id}:{now.strftime('%G-%V')}"
    redis = get_redis()
    await redis.incr(key)
    await redis.expire(key, 14 * 86400)


async def _active_batch(db: AsyncSession, trigger: str) -> CouponBatch | None:
    return await db.scalar(select(CouponBatch).where(
        CouponBatch.trigger == trigger, CouponBatch.active.is_(True))
        .order_by(CouponBatch.created_at.desc()).limit(1))


async def run_birthday(db: AsyncSession, today_mmdd: str, year: int) -> int:
    """生日当天发券+推送(一年一张:source=birthday:{uid}:{年})。"""
    batch = await _active_batch(db, "birthday")
    if batch is None:
        return 0
    users = (await db.scalars(select(User).where(
        User.birthday == today_mmdd, User.role == UserRole.customer,
        User.marketing_push.is_(True)))).all()
    sent = 0
    for user in users:
        source = f"birthday:{user.id}:{year}"
        if await db.scalar(select(Coupon.id).where(Coupon.source == source)):
            continue
        if not await _under_cap(user.id):
            continue
        from .coupons import issue_from_batch
        coupon = await issue_from_batch(db, batch, user.id, note="生日快乐")
        if coupon is None:
            continue
        coupon.source = source  # 覆盖为按年唯一(一年一张)
        await db.commit()
        await _count_send(user.id)
        try:
            await push_to_user(user.id, "生日快乐 🎂",
                               f"送你 {batch.amount_cents / 100:g} 元生日券"
                               f"({batch.valid_days} 天内有效),今天想吃点好的",
                               {"type": "coupon"}, record_skip=True)
        except Exception:
            pass
        sent += 1
    return sent


async def run_winback(db: AsyncSession) -> int:
    """复购提醒:30 天前有完成单、近 30 天没下过单的用户,
    每月最多一次(Redis),推送带券(winback 批次,每批次每人一张)。"""
    batch = await _active_batch(db, "winback")
    if batch is None:
        return 0
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    # 最近一个非取消单在 30 天前的用户
    last_order = (await db.execute(
        select(Order.customer_id, func.max(Order.created_at))
        .where(Order.status == OrderStatus.COMPLETED)
        .group_by(Order.customer_id))).all()
    dormant_ids = [uid for uid, last in last_order
                   if (last.replace(tzinfo=timezone.utc)
                       if last.tzinfo is None else last) < cutoff]
    if not dormant_ids:
        return 0
    redis = get_redis()
    month = (now + timedelta(hours=8)).strftime("%Y%m")
    users = (await db.scalars(select(User).where(
        User.id.in_(dormant_ids), User.marketing_push.is_(True)))).all()
    sent = 0
    for user in users[:200]:  # 每天最多触达 200 人,细水长流
        if not await redis.set(f"mkt:winback:{user.id}:{month}", 1,
                               ex=35 * 86400, nx=True):
            continue
        if not await _under_cap(user.id):
            continue
        from .coupons import issue_from_batch
        coupon = await issue_from_batch(db, batch, user.id, note="好久不见")
        if coupon is None:
            continue
        await db.commit()
        await _count_send(user.id)
        try:
            await push_to_user(user.id, "好久不见",
                               f"送你 {batch.amount_cents / 100:g} 元券"
                               f"({batch.valid_days} 天内有效),"
                               "回来看看有什么新店新菜",
                               {"type": "coupon"}, record_skip=True)
        except Exception:
            pass
        sent += 1
    return sent


async def run_new_dish(db: AsyncSession) -> int:
    """收藏店上新:当天上架的新菜,汇总推给收藏了这些店的用户;
    同店 7 天内不重复推(Redis),不发券只提醒。"""
    day_start = datetime.now(timezone.utc) - timedelta(hours=24)
    new_dishes = (await db.execute(
        select(Dish.merchant_id, func.count(Dish.id))
        .where(Dish.created_at >= day_start, Dish.is_on_sale.is_(True))
        .group_by(Dish.merchant_id))).all()
    if not new_dishes:
        return 0
    merchant_ids = [mid for mid, _ in new_dishes]
    shops = {m.id: m.name for m in (await db.scalars(
        select(Merchant).where(Merchant.id.in_(merchant_ids)))).all()}
    favs = (await db.execute(
        select(Favorite.user_id, Favorite.merchant_id).where(
            Favorite.merchant_id.in_(merchant_ids)))).all()
    by_user: dict[int, list[int]] = {}
    for uid, mid in favs:
        by_user.setdefault(uid, []).append(mid)
    redis = get_redis()
    sent = 0
    for uid, mids in by_user.items():
        user = await db.get(User, uid)
        if user is None or not user.marketing_push:
            continue
        fresh_mids = []
        for mid in mids:
            if await redis.set(f"mkt:favnew:{uid}:{mid}", 1,
                               ex=7 * 86400, nx=True):
                fresh_mids.append(mid)
        if not fresh_mids:
            continue
        if not await _under_cap(uid):
            continue
        await _count_send(uid)
        names = "、".join(shops.get(m, "") for m in fresh_mids[:3])
        try:
            await push_to_user(uid, "你收藏的店上新了",
                               f"{names} 上了新菜,去看看?",
                               {"type": "favorite"}, record_skip=True)
        except Exception:
            pass
        sent += 1
    return sent


async def maybe_run_marketing(now_beijing: datetime) -> dict[str, int]:
    """10:00 跑生日+复购,18:00 跑收藏上新(各自 Redis 每日防重)。"""
    from ..db import SessionLocal
    from .auto_flow import _in_window
    from .flags import marketing_on
    redis = get_redis()
    result = {"birthday": 0, "winback": 0, "new_dish": 0}
    async with SessionLocal() as db:
        if not await marketing_on(db):
            return result  # 营销总开关关:一条不推、一张不发
    if _in_window("10:00", now_beijing, window_seconds=300):
        if await redis.set(f"mkt:morning:{now_beijing.date()}", 1,
                           ex=86400, nx=True):
            async with SessionLocal() as db:
                result["birthday"] = await run_birthday(
                    db, now_beijing.strftime("%m-%d"), now_beijing.year)
                result["winback"] = await run_winback(db)
    elif _in_window("18:00", now_beijing, window_seconds=300):
        if await redis.set(f"mkt:evening:{now_beijing.date()}", 1,
                           ex=86400, nx=True):
            async with SessionLocal() as db:
                result["new_dish"] = await run_new_dish(db)
    if any(result.values()):
        logger.info("营销触达:%s", result)
    return result
