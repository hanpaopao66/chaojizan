"""骑手每日汇总(#310)。**只用来看清运力和成本,不做考核。**

## 这个模块解决的两个问题

1. **有些数过了那一刻就没了。** 抢单池里「被你自己的偏好挡掉几单」
   是每次请求现算的,不落库就永远还原不出来 —— 而它能回答一个
   很要紧的问题:骑手是真的没单跑,还是被自己两个月前设的开关挡住了。
2. **可重算的那些会越来越慢,而且会断。** 单量/收入/里程靠扫 orders
   现算,订单表只会长大;一旦对订单做归档,历史统计就直接断掉。

## 红线

这张表不许进派单、限流、封禁的判据。判断标准和评价体系那条一样:
**这个数字会不会影响他能看到的单?** 会,就是绳索;不会,才是数据。
"""
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    DeliveryIssue,
    Order,
    OrderEvent,
    RiderDailyStat,
    RiderEarning,
    RiderSession,
)
from ..redis_client import get_redis
from ..state_machine import OrderStatus

logger = logging.getLogger("superz.rider_stats")

#: 北京时区偏移。全库统一按北京自然日切 —— 跨零点的单算到前一天,
#: 骑手会觉得数字不对
_BJ_OFFSET = timedelta(hours=8)

#: 「被偏好挡掉」的当日计数键。**只在 Redis 里攒一天,当天汇总落库**;
#: 汇总跑完就没用了,给 3 天过期是留出补跑的余地
_FILTERED_KEY = "rider:filtered:{rider_id}:{day}"
_FILTERED_TTL = 3 * 86400


def bj_day(dt: datetime | None = None) -> date:
    """某个 UTC 时刻落在哪个北京自然日。"""
    d = dt or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (d + _BJ_OFFSET).date()


def day_window(day: date) -> tuple[datetime, datetime]:
    """北京自然日 → UTC 的 [起, 止)。"""
    start = datetime(day.year, day.month, day.day,
                     tzinfo=timezone.utc) - _BJ_OFFSET
    return start, start + timedelta(days=1)


async def bump_filtered(rider_id: int, count: int) -> None:
    """记一次「被偏好挡掉了几单」。**失败静默** —— 它是统计,
    不能让统计把抢单接口拖挂。"""
    if count <= 0:
        return
    try:
        redis = get_redis()
        key = _FILTERED_KEY.format(rider_id=rider_id, day=bj_day().isoformat())
        await redis.incrby(key, count)
        await redis.expire(key, _FILTERED_TTL)
    except Exception:
        logger.debug("记录 filtered 失败(不影响抢单)", exc_info=True)


async def _filtered_of(rider_id: int, day: date) -> int:
    try:
        v = await get_redis().get(
            _FILTERED_KEY.format(rider_id=rider_id, day=day.isoformat()))
        return int(v) if v else 0
    except Exception:
        return 0


async def rollup_day(db: AsyncSession, day: date) -> int:
    """汇总某个北京自然日,返回写了几行。**幂等** —— 重跑覆盖不叠加。

    只汇总那天真的跑过或上过线的人:一个平台几万骑手,
    给没上线的人也写一行零,表会白白涨几十倍。
    """
    start, end = day_window(day)

    # 完成单量 / 里程 / 等餐时长:都从订单来,一次查完
    order_rows = (await db.execute(
        select(
            Order.rider_id,
            func.count(Order.id),
            func.coalesce(func.sum(Order.bill_distance_m), 0),
            func.coalesce(func.sum(
                func.extract("epoch",
                             Order.picked_up_at - Order.arrived_shop_at) / 60
            ).filter(Order.arrived_shop_at.is_not(None)
                     & Order.picked_up_at.is_not(None)), 0),
        )
        .where(Order.rider_id.is_not(None),
               Order.status.in_([OrderStatus.DELIVERED,
                                 OrderStatus.COMPLETED]),
               Order.delivered_at >= start, Order.delivered_at < end)
        .group_by(Order.rider_id))).all()

    # 入账:和订单分开查 —— 赔付、等餐补偿这些不挂在订单完成时刻上
    earn_rows = (await db.execute(
        select(RiderEarning.rider_id,
               func.coalesce(func.sum(RiderEarning.amount_cents), 0))
        .where(RiderEarning.created_at >= start,
               RiderEarning.created_at < end)
        .group_by(RiderEarning.rider_id))).all()

    # 在线时长:会话可能跨天,只算落在这一天里的那段
    sessions = (await db.scalars(
        select(RiderSession).where(
            RiderSession.online_at < end,
            func.coalesce(RiderSession.offline_at,
                          datetime.now(timezone.utc)) > start))).all()

    # 转单 / 异常上报
    transfer_rows = (await db.execute(
        select(OrderEvent.actor_id, func.count(OrderEvent.id))
        .where(OrderEvent.to_status == "transferred",
               OrderEvent.actor_role == "rider",
               OrderEvent.created_at >= start, OrderEvent.created_at < end)
        .group_by(OrderEvent.actor_id))).all()
    issue_rows = (await db.execute(
        select(DeliveryIssue.rider_id, func.count(DeliveryIssue.id))
        .where(DeliveryIssue.created_at >= start,
               DeliveryIssue.created_at < end)
        .group_by(DeliveryIssue.rider_id))).all()

    acc: dict[int, dict] = {}

    def slot(rid: int) -> dict:
        return acc.setdefault(rid, {
            "orders": 0, "earned_cents": 0, "online_minutes": 0,
            "meters": 0, "wait_minutes": 0, "transfers": 0, "issues": 0,
        })

    for rid, n, meters, wait in order_rows:
        s = slot(rid)
        s["orders"] = int(n or 0)
        s["meters"] = int(meters or 0)
        s["wait_minutes"] = int(wait or 0)
    for rid, cents in earn_rows:
        slot(rid)["earned_cents"] = int(cents or 0)
    for sess in sessions:
        on = sess.online_at
        if on.tzinfo is None:
            on = on.replace(tzinfo=timezone.utc)
        off = sess.offline_at or datetime.now(timezone.utc)
        if off.tzinfo is None:
            off = off.replace(tzinfo=timezone.utc)
        lo, hi = max(on, start), min(off, end)
        if hi > lo:
            slot(sess.rider_id)["online_minutes"] += int(
                (hi - lo).total_seconds() / 60)
    for rid, n in transfer_rows:
        if rid is not None:
            slot(rid)["transfers"] = int(n or 0)
    for rid, n in issue_rows:
        slot(rid)["issues"] = int(n or 0)

    for rid in list(acc):
        acc[rid]["filtered_by_prefs"] = await _filtered_of(rid, day)

    if not acc:
        return 0
    # 幂等:一人一天一行,重跑覆盖。汇总是可以补跑的,
    # 补跑一次多出一行就等于数据被污染了
    for rid, vals in acc.items():
        stmt = pg_insert(RiderDailyStat).values(
            rider_id=rid, day=day, **vals)
        await db.execute(stmt.on_conflict_do_update(
            constraint="uq_rider_daily_stats",
            set_={**vals, "updated_at": func.now()}))
    await db.commit()
    logger.info("骑手日汇总 %s:%s 人", day, len(acc))
    return len(acc)


async def rollup_recent(db: AsyncSession, days: int = 2) -> int:
    """汇总最近几天(含今天)。

    今天也算是有意的:统计页看当天要能有数,不用等到第二天。
    昨天重算一遍是因为**跨零点的单会在零点后才完成** ——
    只跑今天的话昨天最后那几单永远漏掉。
    """
    today = bj_day()
    total = 0
    for i in range(days):
        total += await rollup_day(db, today - timedelta(days=i))
    return total
