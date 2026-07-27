"""住宿库存引擎:房价房态日历的原子占用与回补。

每晚一行是刻意设计——连住 = 区间内逐行原子扣减,任一晚不满足整体回滚。
occupy/release 必须在调用方事务内使用;幂等由调用方靠订单状态跃迁保证
(状态机拦住重复调用,这里不做判重)。
"""
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RoomCalendar


def nights_of(checkin: date, checkout: date) -> list[date]:
    """入住区间覆盖的每一晚(含入住日,不含退房日)。"""
    return [checkin + timedelta(days=i) for i in range((checkout - checkin).days)]


class InventoryError(Exception):
    """占用失败(满房/关房/未开放),message 直接给用户看。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def occupy(db: AsyncSession, room_type_id: int,
                 checkin: date, checkout: date, qty: int) -> list[RoomCalendar]:
    """区间内逐晚原子扣减 qty 间,返回按日期排序的日历行(供下单快照每晚价)。
    任一晚不满足抛 InventoryError,调用方事务回滚后已扣的晚自动还原。
    """
    days = nights_of(checkin, checkout)
    # 行锁住区间内每晚,并发下单在此排队,校验通过才扣减——不会超卖
    rows = (await db.scalars(
        select(RoomCalendar)
        .where(RoomCalendar.room_type_id == room_type_id,
               RoomCalendar.date.in_(days))
        .with_for_update())).all()
    by_day = {r.date: r for r in rows}
    for d in days:
        row = by_day.get(d)
        if row is None or row.closed:
            raise InventoryError(f"{d.month}月{d.day}日未开放预订,换个日期试试")
        left = row.total_qty - row.sold_qty
        if left < qty:
            raise InventoryError(
                f"{d.month}月{d.day}日仅剩 {max(left, 0)} 间,不够订 {qty} 间")
    await db.execute(
        update(RoomCalendar)
        .where(RoomCalendar.room_type_id == room_type_id,
               RoomCalendar.date.in_(days))
        .values(sold_qty=RoomCalendar.sold_qty + qty)
    )
    return sorted(rows, key=lambda r: r.date)


async def release(db: AsyncSession, room_type_id: int,
                  checkin: date, checkout: date, qty: int) -> None:
    """回补区间内每晚 qty 间(取消/拒单/超时关单)。sold 不减成负数。"""
    days = nights_of(checkin, checkout)
    await db.execute(
        update(RoomCalendar)
        .where(
            RoomCalendar.room_type_id == room_type_id,
            RoomCalendar.date.in_(days),
            RoomCalendar.sold_qty >= qty,
        )
        .values(sold_qty=RoomCalendar.sold_qty - qty)
    )
