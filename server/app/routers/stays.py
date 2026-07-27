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
    HotelCardOut,
    HotelDetailOut,
    RoomCalendarRowOut,
    RoomCalendarSetIn,
    RoomDayOut,
    RoomQuoteOut,
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


# ---------- 消费端:搜索 / 详情 / 报价 ----------

_HOTEL_SORTS = {"comprehensive", "distance", "price", "rating"}
_MAX_NIGHTS = 28


def _parse_range(checkin: date | None, checkout: date | None) -> tuple[date, date]:
    """入住区间:默认今住明退;最长 28 晚;不能订过去。"""
    ci = checkin or date.today()
    co = checkout or (ci + timedelta(days=1))
    if ci < date.today():
        raise HTTPException(422, "入住日期不能早于今天")
    if co <= ci:
        raise HTTPException(422, "退房日期要晚于入住日期")
    if (co - ci).days > _MAX_NIGHTS:
        raise HTTPException(422, f"最多连住 {_MAX_NIGHTS} 晚")
    return ci, co


def cancel_policy_text(policy, free_cancel_until: str, checkin: date) -> str:
    """取消政策文案,后端统一生成保证三端一致。"""
    from ..models import CancelPolicy
    p = policy.value if hasattr(policy, "value") else policy
    if p == CancelPolicy.limited_free.value:
        return (f"{checkin.month}月{checkin.day}日 {free_cancel_until} 前"
                "免费取消,之后取消扣首晚")
    if p == CancelPolicy.first_night.value:
        return "取消扣首晚房费,其余退回"
    return "支付后不可退(可与酒店协商)"


async def _quotes_for(db: AsyncSession, room_types: list[RoomType],
                      checkin: date, checkout: date) -> dict[int, dict]:
    """批量算报价:{room_type_id: {total, nightly, left, bookable}}。

    可订 = 区间内每晚都已设价、未关房且有余量。一次查询,内存组装,避免 N+1。
    """
    from ..services.stay_inventory import nights_of
    days = nights_of(checkin, checkout)
    if not room_types:
        return {}
    rows = (await db.scalars(
        select(RoomCalendar)
        .where(RoomCalendar.room_type_id.in_([r.id for r in room_types]),
               RoomCalendar.date.in_(days))
        .order_by(RoomCalendar.date))).all()
    by_rt: dict[int, dict] = {}
    for r in rows:
        by_rt.setdefault(r.room_type_id, {})[r.date] = r
    quotes: dict[int, dict] = {}
    for rt in room_types:
        cal = by_rt.get(rt.id, {})
        nightly, left, ok = [], None, True
        for d in days:
            row = cal.get(d)
            if row is None or row.closed:
                ok = False
                break
            day_left = row.total_qty - row.sold_qty
            if day_left <= 0:
                ok = False
                break
            left = day_left if left is None else min(left, day_left)
            nightly.append(row)
        quotes[rt.id] = {
            "bookable": ok,
            "total": sum(r.price_cents for r in nightly) if ok else None,
            "nightly": nightly if ok else [],
            "left": left if ok else None,
        }
    return quotes


@router.get("/hotels", response_model=list[HotelCardOut])
async def list_hotels(
    lat: float | None = None,
    lng: float | None = None,
    checkin: date | None = None,
    checkout: date | None = None,
    q: str = Query(default="", max_length=50),
    sort: str = "comprehensive",
    tier: str | None = Query(default=None, pattern="^(economy|comfort|premium|luxury)$"),
    min_price_cents: int | None = Query(default=None, ge=0),
    max_price_cents: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """酒店列表:按入住区间给出「¥X 起」与满房标记。

    排序 comprehensive(评分×距离衰减)/distance/price/rating——无竞价位,
    权重只用真实评分与距离,商家花钱买不到靠前。满房仍展示(置灰),
    用户改日期还能订。
    """
    checkin, checkout = _parse_range(checkin, checkout)
    if sort in ("comprehensive", "distance") and (lat is None or lng is None):
        sort = "rating"
    if sort not in _HOTEL_SORTS:
        raise HTTPException(422, "sort 仅支持 comprehensive/distance/price/rating")

    from sqlalchemy import text
    from ..models import HotelProfile
    params: dict = {}
    where = ["m.biz_type = 'hotel'", "m.status = 'approved'",
             "m.is_open = true"]
    if q.strip():
        params["pattern"] = f"%{q.strip()}%"
        where.append("(m.name ILIKE :pattern OR m.address ILIKE :pattern)")
    if tier:
        params["tier"] = tier
        where.append("hp.tier = :tier")
    dist_expr = "NULL"
    if lat is not None and lng is not None:
        params["lat"], params["lng"] = lat, lng
        dist_expr = ("(ST_SetSRID(ST_MakePoint(m.lng,m.lat),4326)::geography"
                     " <-> ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography)")
    rows = await db.execute(text(f"""
        SELECT m.id, {dist_expr} AS dist
        FROM merchants m
        JOIN hotel_profiles hp ON hp.merchant_id = m.id
        WHERE {' AND '.join(where)}
        LIMIT 200
    """), params)
    id_dist = {r[0]: (int(r[1]) if r[1] is not None else None) for r in rows}
    if not id_dist:
        return []

    merchants = {m.id: m for m in (await db.scalars(
        select(Merchant).where(Merchant.id.in_(id_dist)))).all()}
    profiles = {p.merchant_id: p for p in (await db.scalars(
        select(HotelProfile).where(HotelProfile.merchant_id.in_(id_dist)))).all()}
    room_types = (await db.scalars(
        select(RoomType).where(RoomType.merchant_id.in_(id_dist),
                               RoomType.is_on_sale.is_(True)))).all()
    quotes = await _quotes_for(db, room_types, checkin, checkout)

    nights = (checkout - checkin).days
    cards = []
    for mid, dist in id_dist.items():
        m, hp = merchants.get(mid), profiles.get(mid)
        if m is None or hp is None:
            continue
        prices = [quotes[rt.id]["total"] for rt in room_types
                  if rt.merchant_id == mid and quotes[rt.id]["bookable"]]
        min_night = min(prices) // nights if prices else None
        if min_price_cents is not None and \
                (min_night is None or min_night < min_price_cents):
            continue
        if max_price_cents is not None and \
                (min_night is None or min_night > max_price_cents):
            continue
        cards.append(HotelCardOut(
            id=m.id, name=m.name, tier=hp.tier, address=m.address,
            lat=m.lat, lng=m.lng, logo_url=m.logo_url,
            photo_urls=m.photo_urls or [],
            rating_avg=m.rating_avg, rating_count=m.rating_count,
            distance_m=dist, min_night_price_cents=min_night,
            full=min_night is None))

    def _key(c: HotelCardOut):
        if sort == "distance":
            return (c.distance_m is None, c.distance_m or 0)
        if sort == "price":
            return (c.min_night_price_cents is None,
                    c.min_night_price_cents or 0)
        if sort == "rating":
            return (-(c.rating_avg or 0), c.rating_count * -1)
        # comprehensive:评分(缺省 3 分)×20 - 距离(km)×2,大者靠前
        score = (c.rating_avg or 3) * 20 - (c.distance_m or 0) / 1000 * 2
        return -score
    cards.sort(key=_key)
    return cards[:50]


@router.get("/hotels/{hotel_id}", response_model=HotelDetailOut)
async def hotel_detail(
    hotel_id: int,
    checkin: date | None = None,
    checkout: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    """酒店详情+房型报价。改日期即重新报价;满房房型仍展示(置灰)。"""
    checkin, checkout = _parse_range(checkin, checkout)
    from ..models import HotelProfile
    m = await db.get(Merchant, hotel_id)
    if m is None or m.biz_type != "hotel" \
            or m.status != MerchantStatus.approved or not m.is_open:
        raise HTTPException(404, "酒店不存在或暂停营业")
    hp = await db.scalar(
        select(HotelProfile).where(HotelProfile.merchant_id == m.id))
    room_types = (await db.scalars(
        select(RoomType).where(RoomType.merchant_id == m.id,
                               RoomType.is_on_sale.is_(True))
        .order_by(RoomType.sort, RoomType.id))).all()
    quotes = await _quotes_for(db, room_types, checkin, checkout)
    rooms = []
    for rt in room_types:
        qt = quotes[rt.id]
        left = qt["left"]
        rooms.append(RoomQuoteOut(
            room_type=RoomTypeOut.model_validate(rt),
            total_cents=qt["total"],
            nightly=[RoomDayOut(date=r.date, price_cents=r.price_cents,
                                total_qty=r.total_qty, sold_qty=r.sold_qty,
                                closed=r.closed) for r in qt["nightly"]],
            bookable=qt["bookable"],
            left_qty=left if (left is not None and left <= 3) else None,
            cancel_policy_text=cancel_policy_text(
                rt.cancel_policy, rt.free_cancel_until, checkin),
        ))
    return HotelDetailOut(
        id=m.id, name=m.name, description=m.description,
        tier=hp.tier if hp else "economy", address=m.address,
        lat=m.lat, lng=m.lng,
        front_desk_phone=hp.front_desk_phone if hp else "",
        checkin_from=hp.checkin_from if hp else "14:00",
        checkout_until=hp.checkout_until if hp else "12:00",
        facilities=hp.facilities if hp else [],
        logo_url=m.logo_url, photo_urls=m.photo_urls or [],
        rating_avg=m.rating_avg, rating_count=m.rating_count,
        checkin_date=checkin, checkout_date=checkout, rooms=rooms)
