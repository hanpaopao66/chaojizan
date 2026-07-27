"""住宿(酒店垂类):房型/房价房态/订单。三场景愿景的第三块。

资金姿态与外卖/团购一致:佣金 5% 只在离店时收——
取消/拒单/未入住,平台分文不取。方案见 docs/HOTEL_PLAN.md。
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    Merchant,
    MerchantStatus,
    RoomCalendar,
    RoomType,
    User,
)
from ..schemas import (
    RoomCalendarRowOut,
    RoomCalendarSetIn,
    RoomDayOut,
    RoomTypeIn,
    RoomTypeOut,
    RoomTypePatch,
)
from ..security import require_role

router = APIRouter(prefix="/stays", tags=["住宿"])


async def _my_hotel(db: AsyncSession, user: User) -> Merchant:
    """当前商家(店主或店员)可操作的酒店。餐饮商家会被拦下。"""
    from ..services.staff import operable_shop
    shop, _ = await operable_shop(db, user)
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "还没有已过审的店铺")
    if shop.biz_type != "hotel":
        raise HTTPException(403, "此功能仅酒店业态可用")
    return shop


async def _own_room_type(db: AsyncSession, shop: Merchant, rt_id: int) -> RoomType:
    rt = await db.get(RoomType, rt_id)
    if rt is None or rt.merchant_id != shop.id:
        raise HTTPException(404, "房型不存在")
    return rt


# ---------- 商家自助:房型 ----------

@router.get("/me/room-types", response_model=list[RoomTypeOut])
async def my_room_types(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_hotel(db, user)
    rows = await db.scalars(
        select(RoomType).where(RoomType.merchant_id == shop.id)
        .order_by(RoomType.sort, RoomType.id))
    return [RoomTypeOut.model_validate(r) for r in rows]


@router.post("/me/room-types", response_model=RoomTypeOut)
async def create_room_type(
    payload: RoomTypeIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_hotel(db, user)
    from ..services.moderation import guard_text
    await guard_text(db, payload.name, "房型名称")
    rt = RoomType(merchant_id=shop.id, **payload.model_dump())
    db.add(rt)
    await db.commit()
    await db.refresh(rt)
    return RoomTypeOut.model_validate(rt)


@router.patch("/me/room-types/{rt_id}", response_model=RoomTypeOut)
async def update_room_type(
    rt_id: int,
    payload: RoomTypePatch,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """编辑房型。下架(is_on_sale=false)不删——历史订单还引用着它。
    取消政策改动只影响新订单,已有订单按下单时的快照执行。
    """
    shop = await _my_hotel(db, user)
    rt = await _own_room_type(db, shop, rt_id)
    changes = payload.model_dump(exclude_none=True)
    if changes.get("name"):
        from ..services.moderation import guard_text
        await guard_text(db, changes["name"], "房型名称")
    for key, value in changes.items():
        setattr(rt, key, value)
    await db.commit()
    await db.refresh(rt)
    return RoomTypeOut.model_validate(rt)


# ---------- 商家自助:房价房态日历 ----------

def _day_range(from_date: date, to_date: date) -> list[date]:
    return [from_date + timedelta(days=i)
            for i in range((to_date - from_date).days + 1)]


@router.put("/me/calendar")
async def set_calendar(
    payload: RoomCalendarSetIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """批量设置日历:日期区间 × 多房型,统一改价/改总量/开关房。

    过去日期只读;新开日期(此前无记录)必须带价格;
    总量不能下调到低于该日已售。
    """
    shop = await _my_hotel(db, user)
    if payload.from_date < date.today():
        raise HTTPException(422, "过去的日期不能修改")
    for rt_id in payload.room_type_ids:
        await _own_room_type(db, shop, rt_id)

    days = _day_range(payload.from_date, payload.to_date)
    existing = (await db.scalars(
        select(RoomCalendar)
        .where(RoomCalendar.room_type_id.in_(payload.room_type_ids),
               RoomCalendar.date.in_(days))
        .with_for_update())).all()
    by_key = {(r.room_type_id, r.date): r for r in existing}

    created = updated = 0
    for rt_id in payload.room_type_ids:
        for d in days:
            row = by_key.get((rt_id, d))
            if row is None:
                if payload.price_cents is None:
                    raise HTTPException(
                        422, f"{d.month}月{d.day}日还未设价,首次开放请带上价格")
                db.add(RoomCalendar(
                    room_type_id=rt_id, date=d,
                    price_cents=payload.price_cents,
                    total_qty=payload.total_qty or 0,
                    sold_qty=0,
                    closed=payload.closed or False,
                ))
                created += 1
                continue
            if payload.total_qty is not None \
                    and payload.total_qty < row.sold_qty:
                raise HTTPException(
                    422, f"{d.month}月{d.day}日已售 {row.sold_qty} 间,"
                         f"总量不能调到 {payload.total_qty}")
            if payload.price_cents is not None:
                row.price_cents = payload.price_cents
            if payload.total_qty is not None:
                row.total_qty = payload.total_qty
            if payload.closed is not None:
                row.closed = payload.closed
            updated += 1
    await db.commit()
    return {"created": created, "updated": updated}


@router.get("/me/calendar", response_model=list[RoomCalendarRowOut])
async def my_calendar(
    from_date: date | None = None,
    days: int = Query(default=14, ge=1, le=90),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """日历网格:每房型一行,只返回已设价的日期(缺的客户端显示「未设价」)。"""
    shop = await _my_hotel(db, user)
    start = from_date or date.today()
    end = start + timedelta(days=days - 1)
    room_types = (await db.scalars(
        select(RoomType).where(RoomType.merchant_id == shop.id)
        .order_by(RoomType.sort, RoomType.id))).all()
    if not room_types:
        return []
    rows = (await db.scalars(
        select(RoomCalendar)
        .where(RoomCalendar.room_type_id.in_([r.id for r in room_types]),
               RoomCalendar.date >= start, RoomCalendar.date <= end)
        .order_by(RoomCalendar.date))).all()
    by_rt: dict[int, list[RoomDayOut]] = {}
    for r in rows:
        by_rt.setdefault(r.room_type_id, []).append(RoomDayOut(
            date=r.date, price_cents=r.price_cents, total_qty=r.total_qty,
            sold_qty=r.sold_qty, closed=r.closed))
    return [RoomCalendarRowOut(room_type_id=rt.id, room_type_name=rt.name,
                               days=by_rt.get(rt.id, []))
            for rt in room_types]
