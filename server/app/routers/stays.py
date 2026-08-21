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


async def _my_hotel(db: AsyncSession, user: User, *,
                    need_owner: bool = False) -> Merchant:
    """当前商家可操作的酒店。餐饮商家会被拦下。

    [need_owner] 改价/改房型/改酒店资料这类**敏感端点**传 True,店员一律拒。
    services/staff.py 定的规矩是「运营端点用 operable_shop,敏感端点用
    owned_shop」,餐饮侧照做了(merchants.py 的 _my_shop_or_404),
    住宿侧原先把 is_owner 直接丢掉 —— 于是前台店员能改房价,
    而房价是这门生意里唯一的价格。

    品牌层仍算店主级(与餐饮侧一致:区域经理能改价改设置);
    钱的边界另在 money_shop,不走这里。
    """
    from ..services.staff import operable_shop
    shop, is_owner = await operable_shop(db, user)
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "还没有已过审的店铺")
    if shop.biz_type != "hotel":
        raise HTTPException(403, "此功能仅酒店业态可用")
    if need_owner and not is_owner:
        raise HTTPException(403, "只有店主能改房价/房型/酒店资料,店员不行")
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
    shop = await _my_hotel(db, user, need_owner=True)
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
    shop = await _my_hotel(db, user, need_owner=True)
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
    shop = await _my_hotel(db, user, need_owner=True)
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
    # 酒店评分:近 180 天滚动均分,<3 条不出分(与终身累计的外卖口径不同)
    ratings = await hotel_ratings(db, list(id_dist))
    cards = []
    for mid, dist in id_dist.items():
        m, hp = merchants.get(mid), profiles.get(mid)
        if m is None or hp is None:
            continue
        r_avg, r_count = ratings.get(mid, (None, 0))
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
            rating_avg=r_avg, rating_count=r_count,
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
    r_avg, r_count = (await hotel_ratings(db, [m.id])).get(m.id, (None, 0))
    return HotelDetailOut(
        id=m.id, name=m.name, description=m.description,
        tier=hp.tier if hp else "economy", address=m.address,
        lat=m.lat, lng=m.lng,
        front_desk_phone=hp.front_desk_phone if hp else "",
        checkin_from=hp.checkin_from if hp else "14:00",
        checkout_until=hp.checkout_until if hp else "12:00",
        facilities=hp.facilities if hp else [],
        logo_url=m.logo_url, photo_urls=m.photo_urls or [],
        rating_avg=r_avg, rating_count=r_count,
        checkin_date=checkin, checkout_date=checkout, rooms=rooms)


# ---------- 住宿订单(下单/支付/取消/商家处理) ----------

import uuid
from datetime import datetime, timezone as _tz, timedelta as _td
from decimal import Decimal

from ..config import settings
from ..models import CancelPolicy, HotelProfile, StayOrder
from ..ratelimit import check_rate_limit
from ..schemas import RejectIn, StayCancelPreviewOut, StayOrderIn, StayOrderOut
from ..services.stay_inventory import InventoryError, occupy, release
from ..state_machine import (
    STAY_STATUS_LABELS,
    StayOrderStatus,
    TransitionError,
    assert_stay_transition,
)

_BJ = _tz(_td(hours=8))  # 取消时限按北京时间

import logging

logger = logging.getLogger("superz.stays")


async def _notify_stay(db: AsyncSession, order: StayOrder, kind: str) -> None:
    """住宿订单事件通知(推送/WS 失败绝不阻塞主流程)。"""
    try:
        from ..services.push import push_to_user
        from ..ws import manager
        tail = order.order_no[-6:]
        stay_desc = (f"{order.room_type_name}×{order.rooms_qty} "
                     f"{order.checkin_date.month}月{order.checkin_date.day}日"
                     f"入住{order.nights}晚")
        if kind == "paid":  # 新单 → 商家(WS 走语音循环播报同通道 + 推送)
            await manager.broadcast(
                f"merchant:{order.merchant_id}",
                {"type": "new_stay_order", "order_no": order.order_no,
                 "summary": stay_desc, "total_cents": order.total_cents})
            m = await db.get(Merchant, order.merchant_id)
            if m:
                await push_to_user(
                    m.owner_id, "新住宿订单",
                    f"{stay_desc},¥{order.total_cents / 100:g},请及时确认",
                    {"type": "stay_order", "order_no": order.order_no})
        elif kind == "confirmed":
            m = await db.get(Merchant, order.merchant_id)
            await push_to_user(
                order.customer_id, "酒店已确认你的预订",
                f"{m.name if m else ''} {stay_desc};入住凭证见订单详情",
                {"type": "stay_order", "order_no": order.order_no})
        elif kind == "rejected":
            await push_to_user(
                order.customer_id, "预订未成功,已全额退款",
                f"订单#{tail} 商家拒单:{order.reject_reason};"
                f"¥{order.refund_cents / 100:g} 将原路退回",
                {"type": "stay_order", "order_no": order.order_no})
        elif kind == "cancelled":
            await push_to_user(
                order.customer_id, "取消成功",
                f"订单#{tail} {order.refund_note},"
                f"退款 ¥{order.refund_cents / 100:g} 将原路退回",
                {"type": "stay_order", "order_no": order.order_no})
    except Exception:
        logger.exception("住宿订单通知失败: %s %s", order.order_no, kind)


def _transit(order: StayOrder, target: StayOrderStatus, role: str) -> None:
    """状态跃迁统一入口:非法迁移 409,越权 403。"""
    try:
        assert_stay_transition(order.status, target, role)
    except TransitionError as e:
        raise HTTPException(403 if e.forbidden else 409, e.message)
    order.status = target


def _first_night_cents(order: StayOrder) -> int:
    return order.nightly_prices[0]["price_cents"] * order.rooms_qty


def cancel_refund_cents(order: StayOrder, now: datetime) -> tuple[int, str]:
    """按取消政策快照算退款(纯函数,试算与实退共用)。返回 (退款分, 说明)。"""
    policy = order.cancel_policy.value if hasattr(order.cancel_policy, "value") \
        else order.cancel_policy
    total = order.total_cents
    if policy == CancelPolicy.limited_free.value:
        hh, mm = map(int, order.free_cancel_until.split(":"))
        deadline = datetime(order.checkin_date.year, order.checkin_date.month,
                            order.checkin_date.day, hh, mm, tzinfo=_BJ)
        if now < deadline:
            return total, "免费取消时限内,全额退款"
        return max(total - _first_night_cents(order), 0), \
            "已过免费取消时限,按政策扣首晚"
    if policy == CancelPolicy.first_night.value:
        return max(total - _first_night_cents(order), 0), "按取消政策扣首晚"
    return 0, "该房型不可退(可在订单页与酒店协商)"


def _stay_out(order: StayOrder, m: Merchant | None = None,
              hp: HotelProfile | None = None) -> StayOrderOut:
    out = StayOrderOut.model_validate(order)
    status = order.status if isinstance(order.status, StayOrderStatus) \
        else StayOrderStatus(order.status)
    out.status_label = STAY_STATUS_LABELS[status]
    out.cancel_policy_text = cancel_policy_text(
        order.cancel_policy, order.free_cancel_until, order.checkin_date)
    if m is not None:
        out.hotel_name = m.name
        out.hotel_address = m.address
    if hp is not None:
        out.hotel_phone = hp.front_desk_phone
    return out


@router.post("/orders", response_model=StayOrderOut)
async def create_stay_order(
    payload: StayOrderIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """下单:锁定区间库存 + 快照每晚价与取消政策。15 分钟未支付自动关闭。"""
    await check_rate_limit("stay_order", str(user.id), 10)
    checkin, checkout = _parse_range(payload.checkin_date, payload.checkout_date)
    rt = await db.get(RoomType, payload.room_type_id)
    if rt is None or not rt.is_on_sale:
        raise HTTPException(404, "房型不存在或已下架")
    m = await db.get(Merchant, rt.merchant_id)
    if m is None or m.biz_type != "hotel" \
            or m.status != MerchantStatus.approved or not m.is_open:
        raise HTTPException(409, "酒店暂停营业,暂时不能预订")
    try:
        cal_rows = await occupy(db, rt.id, checkin, checkout, payload.rooms_qty)
    except InventoryError as e:
        await db.rollback()
        raise HTTPException(409, e.message)
    nightly = [{"date": str(r.date), "price_cents": r.price_cents}
               for r in cal_rows]
    order = StayOrder(
        order_no="S" + uuid.uuid4().hex[:19],
        customer_id=user.id,
        merchant_id=m.id,
        room_type_id=rt.id,
        checkin_date=checkin,
        checkout_date=checkout,
        nights=(checkout - checkin).days,
        rooms_qty=payload.rooms_qty,
        guest_name=payload.guest_name.strip(),
        guest_phone=payload.guest_phone,
        arrival_note=payload.arrival_note.strip(),
        room_type_name=rt.name,
        nightly_prices=nightly,
        total_cents=sum(x["price_cents"] for x in nightly) * payload.rooms_qty,
        cancel_policy=rt.cancel_policy,
        free_cancel_until=rt.free_cancel_until,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    hp = await db.scalar(select(HotelProfile).where(
        HotelProfile.merchant_id == m.id))
    return _stay_out(order, m, hp)


async def _customer_order(db: AsyncSession, user: User, order_no: str,
                          lock: bool = False) -> StayOrder:
    stmt = select(StayOrder).where(StayOrder.order_no == order_no)
    if lock:
        stmt = stmt.with_for_update()
    order = await db.scalar(stmt)
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    return order


@router.post("/orders/{order_no}/pay/mock", response_model=StayOrderOut)
async def pay_stay_mock(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """模拟支付(与外卖/团购同语义;微信支付联调时替换为统一下单+回调)。幂等。

    生产 MOCK_PAY_ENABLED=false 封死。外卖那条早就有这道闸门
    (orders.py 的 mock_pay),住宿这条一直漏着 —— 真实收款上线后
    这个口子等于白送房间。
    """
    if not settings.mock_pay_enabled:
        raise HTTPException(403, "模拟支付已关闭,请使用微信支付")
    order = await _customer_order(db, user, order_no, lock=True)
    if order.status == StayOrderStatus.PAID:
        return _stay_out(order)
    _transit(order, StayOrderStatus.PAID, "customer")
    order.paid_at = datetime.now(_tz.utc)
    await db.commit()
    await db.refresh(order)
    await _notify_stay(db, order, "paid")
    return _stay_out(order)


@router.get("/orders/mine", response_model=list[StayOrderOut])
async def my_stay_orders(
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(StayOrder, Merchant)
        .join(Merchant, Merchant.id == StayOrder.merchant_id)
        .where(StayOrder.customer_id == user.id)
        .order_by(StayOrder.created_at.desc())
        .limit(100))).all()
    return [_stay_out(o, m) for o, m in rows]


@router.get("/orders/{order_no}", response_model=StayOrderOut)
async def stay_order_detail(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    order = await _customer_order(db, user, order_no)
    m = await db.get(Merchant, order.merchant_id)
    hp = await db.scalar(select(HotelProfile).where(
        HotelProfile.merchant_id == order.merchant_id))
    return _stay_out(order, m, hp)


@router.get("/orders/{order_no}/cancel-preview",
            response_model=StayCancelPreviewOut)
async def cancel_preview(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """取消试算(无副作用):确认弹层展示预计退款。"""
    order = await _customer_order(db, user, order_no)
    if order.status not in (StayOrderStatus.PAID, StayOrderStatus.CONFIRMED):
        raise HTTPException(409, "当前状态不能取消")
    refund, note = cancel_refund_cents(order, datetime.now(_tz.utc))
    return StayCancelPreviewOut(
        refund_cents=refund, penalty_cents=order.total_cents - refund,
        note=note)


@router.post("/orders/{order_no}/cancel", response_model=StayOrderOut)
async def cancel_stay_order(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """取消:待支付直接关;已支付按取消政策退款,扣款归商家(平台不抽佣)。
    库存即回补(不可退档也回补,商家可二次售卖)。
    """
    order = await _customer_order(db, user, order_no, lock=True)
    if order.status == StayOrderStatus.CREATED:
        _transit(order, StayOrderStatus.CLOSED, "customer")
        await release(db, order.room_type_id, order.checkin_date,
                      order.checkout_date, order.rooms_qty)
        order.cancelled_at = datetime.now(_tz.utc)
        await db.commit()
        await db.refresh(order)
        return _stay_out(order)
    now = datetime.now(_tz.utc)
    refund, note = cancel_refund_cents(order, now)
    _transit(order, StayOrderStatus.CANCELLED, "customer")
    order.cancelled_at = now
    order.refund_cents = refund
    order.refund_note = note
    # 扣款部分归商家,平台分文不取(fee=0);入商家流水在结算服务统一处理
    order.fee_cents = 0
    order.net_cents = order.total_cents - refund
    await release(db, order.room_type_id, order.checkin_date,
                  order.checkout_date, order.rooms_qty)
    await db.commit()
    await db.refresh(order)
    await _notify_stay(db, order, "cancelled")
    return _stay_out(order)


# ---------- 商家侧订单处理 ----------

@router.get("/me/orders", response_model=list[StayOrderOut])
async def merchant_stay_orders(
    state: str = Query(default="all",
                       pattern="^(all|pending|arriving|inhouse|leaving)$"),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家订单列表:pending 待确认 / arriving 今日预抵 / inhouse 在住 /
    leaving 今日预离 / all 全部(近 100 条)。
    """
    shop = await _my_hotel(db, user)
    query = select(StayOrder).where(StayOrder.merchant_id == shop.id)
    today = date.today()
    if state == "pending":
        query = query.where(StayOrder.status == StayOrderStatus.PAID)
    elif state == "arriving":
        query = query.where(StayOrder.status == StayOrderStatus.CONFIRMED,
                            StayOrder.checkin_date == today)
    elif state == "inhouse":
        query = query.where(StayOrder.status == StayOrderStatus.CHECKED_IN)
    elif state == "leaving":
        query = query.where(StayOrder.status == StayOrderStatus.CHECKED_IN,
                            StayOrder.checkout_date == today)
    rows = (await db.scalars(
        query.order_by(StayOrder.created_at.desc()).limit(100))).all()
    return [_stay_out(o) for o in rows]


async def _merchant_order(db: AsyncSession, shop: Merchant,
                          order_no: str) -> StayOrder:
    order = await db.scalar(
        select(StayOrder).where(StayOrder.order_no == order_no)
        .with_for_update())
    if order is None or order.merchant_id != shop.id:
        raise HTTPException(404, "订单不存在")
    return order


@router.post("/me/orders/{order_no}/confirm", response_model=StayOrderOut)
async def confirm_stay_order(
    order_no: str,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_hotel(db, user)
    order = await _merchant_order(db, shop, order_no)
    _transit(order, StayOrderStatus.CONFIRMED, "merchant")
    order.confirmed_at = datetime.now(_tz.utc)
    await db.commit()
    await db.refresh(order)
    await _notify_stay(db, order, "confirmed")
    return _stay_out(order)


@router.post("/me/orders/{order_no}/reject", response_model=StayOrderOut)
async def reject_stay_order(
    order_no: str,
    payload: RejectIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """拒单(需填原因,会展示给用户):全额退款 + 回补库存,平台不抽佣。"""
    shop = await _my_hotel(db, user)
    order = await _merchant_order(db, shop, order_no)
    _transit(order, StayOrderStatus.REJECTED, "merchant")
    order.reject_reason = payload.reason
    order.refund_cents = order.total_cents
    order.refund_note = f"商家拒单全额退款:{payload.reason}"
    order.cancelled_at = datetime.now(_tz.utc)
    await release(db, order.room_type_id, order.checkin_date,
                  order.checkout_date, order.rooms_qty)
    await db.commit()
    await db.refresh(order)
    await _notify_stay(db, order, "rejected")
    return _stay_out(order)


@router.post("/me/orders/{order_no}/checkin", response_model=StayOrderOut)
async def checkin_stay_order(
    order_no: str,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """办理入住(核销)。"""
    shop = await _my_hotel(db, user)
    order = await _merchant_order(db, shop, order_no)
    _transit(order, StayOrderStatus.CHECKED_IN, "merchant")
    order.checked_in_at = datetime.now(_tz.utc)
    await db.commit()
    await db.refresh(order)
    return _stay_out(order)


@router.post("/me/orders/{order_no}/checkout", response_model=StayOrderOut)
async def checkout_stay_order(
    order_no: str,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """办理离店 = 结算触发点:佣金 5% 在此产生,商家实收 = 房费 - 佣金。"""
    shop = await _my_hotel(db, user)
    order = await _merchant_order(db, shop, order_no)
    _transit(order, StayOrderStatus.COMPLETED, "merchant")
    order.completed_at = datetime.now(_tz.utc)
    order.fee_cents = int(
        Decimal(order.total_cents)
        * Decimal(str(settings.stay_commission_rate)))
    order.net_cents = order.total_cents - order.fee_cents
    await db.commit()
    await db.refresh(order)
    return _stay_out(order)


# ---------- 住宿点评 ----------

from datetime import timedelta as _rtd

from ..models import STAY_REVIEW_TAGS, StayReview
from ..schemas import StayReviewIn, StayReviewOut

REVIEW_WINDOW_DAYS = 15   # 离店后可评窗口
APPEND_WINDOW_DAYS = 7    # 追评窗口
RATING_ROLL_DAYS = 180    # 评分滚动窗口
RATING_MIN_COUNT = 3      # 少于 3 条不出分


async def hotel_ratings(db: AsyncSession, merchant_ids: list[int]) -> dict[int, tuple[float, int]]:
    """酒店滚动评分:{merchant_id: (均分, 条数)},条数 < 3 的不返回。"""
    if not merchant_ids:
        return {}
    from sqlalchemy import func as sa_func
    since = datetime.now(_tz.utc) - _rtd(days=RATING_ROLL_DAYS)
    rows = await db.execute(
        select(StayReview.merchant_id,
               sa_func.avg(StayReview.rating),
               sa_func.count(StayReview.id))
        .where(StayReview.merchant_id.in_(merchant_ids),
               StayReview.hidden.is_(False),
               StayReview.created_at >= since)
        .group_by(StayReview.merchant_id))
    return {mid: (round(float(avg), 1), int(n))
            for mid, avg, n in rows if n >= RATING_MIN_COUNT}


def _review_out(r: StayReview, name: str = "", order_no: str = "") -> StayReviewOut:
    out = StayReviewOut.model_validate(r)
    out.reviewer_name = "匿名住客" if r.is_anonymous else (name or "住客")
    out.order_no = order_no
    return out


@router.post("/orders/{order_no}/review", response_model=StayReviewOut)
async def create_stay_review(
    order_no: str,
    payload: StayReviewIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """离店后 15 天内可评,一单一评。"""
    order = await _customer_order(db, user, order_no)
    if order.status != StayOrderStatus.COMPLETED:
        raise HTTPException(409, "离店后才能评价")
    if order.completed_at is not None and \
            datetime.now(_tz.utc) - order.completed_at > _rtd(days=REVIEW_WINDOW_DAYS):
        raise HTTPException(409, f"离店超过 {REVIEW_WINDOW_DAYS} 天,评价通道已关闭")
    existing = await db.scalar(
        select(StayReview).where(StayReview.stay_order_id == order.id))
    if existing:
        raise HTTPException(409, "这一单已经评价过了")
    for tag in payload.tags:
        if tag not in STAY_REVIEW_TAGS:
            raise HTTPException(422, "存在无效标签")
    if payload.comment.strip():
        from ..services.moderation import guard_text
        await guard_text(db, payload.comment, "评价内容")
    review = StayReview(
        stay_order_id=order.id,
        customer_id=user.id,
        merchant_id=order.merchant_id,
        rating=payload.rating,
        comment=payload.comment.strip(),
        image_urls=payload.image_urls,
        tags=payload.tags,
        is_anonymous=payload.is_anonymous,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    if payload.image_urls:
        from ..services.moderation import submit_images
        await submit_images(db, "stay_review", review.id, payload.image_urls)
    return _review_out(review, user.name, order.order_no)


@router.get("/orders/{order_no}/review", response_model=StayReviewOut)
async def my_stay_review(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    order = await _customer_order(db, user, order_no)
    review = await db.scalar(
        select(StayReview).where(StayReview.stay_order_id == order.id))
    if review is None:
        raise HTTPException(404, "还没有评价")
    return _review_out(review, user.name, order.order_no)


@router.post("/reviews/{review_id}/append", response_model=StayReviewOut)
async def append_stay_review(
    review_id: int,
    payload: dict,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """追评:首评后 7 天内一次。"""
    review = await db.get(StayReview, review_id)
    if review is None or review.customer_id != user.id:
        raise HTTPException(404, "评价不存在")
    if review.append_content:
        raise HTTPException(409, "已经追评过了")
    if datetime.now(_tz.utc) - review.created_at > _rtd(days=APPEND_WINDOW_DAYS):
        raise HTTPException(409, f"首评超过 {APPEND_WINDOW_DAYS} 天,不能再追评")
    content = str(payload.get("content", "")).strip()[:500]
    if not content:
        raise HTTPException(422, "追评内容不能为空")
    from ..services.moderation import guard_text
    await guard_text(db, content, "追评内容")
    review.append_content = content
    review.append_at = datetime.now(_tz.utc)
    await db.commit()
    await db.refresh(review)
    return _review_out(review, user.name)


@router.get("/hotels/{hotel_id}/reviews", response_model=list[StayReviewOut])
async def hotel_reviews(
    hotel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """酒店点评列表(公开,匿名保护)。"""
    rows = (await db.execute(
        select(StayReview, User.name)
        .join(User, User.id == StayReview.customer_id)
        .where(StayReview.merchant_id == hotel_id,
               StayReview.hidden.is_(False))
        .order_by(StayReview.created_at.desc())
        .limit(100))).all()
    return [_review_out(r, name) for r, name in rows]


@router.get("/me/reviews", response_model=list[StayReviewOut])
async def merchant_stay_reviews(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_hotel(db, user)
    rows = (await db.execute(
        select(StayReview, StayOrder.order_no)
        .join(StayOrder, StayOrder.id == StayReview.stay_order_id)
        .where(StayReview.merchant_id == shop.id,
               StayReview.hidden.is_(False))
        .order_by(StayReview.created_at.desc())
        .limit(100))).all()
    return [_review_out(r, "", no) for r, no in rows]


@router.post("/me/reviews/{review_id}/reply", response_model=StayReviewOut)
async def reply_stay_review(
    review_id: int,
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_hotel(db, user)
    review = await db.get(StayReview, review_id)
    if review is None or review.merchant_id != shop.id:
        raise HTTPException(404, "评价不存在")
    reply = str(payload.get("reply", "")).strip()[:300]
    if not reply:
        raise HTTPException(422, "回复内容不能为空")
    from ..services.moderation import guard_text
    await guard_text(db, reply, "评价回复")
    # 首评未回复 → 回复首评;首评已回复且有追评 → 回复追评;否则视为修改首评回复
    if not review.reply:
        review.reply = reply
    elif review.append_content and not review.append_reply:
        review.append_reply = reply
    else:
        review.reply = reply
    await db.commit()
    await db.refresh(review)
    return _review_out(review)


# ---------- 住宿售后(到店无房赔付 + 协商退) ----------

from ..models import (
    StayAfterSale,
    StayAfterSaleKind,
    StayAfterSaleStatus,
)
from ..schemas import (
    StayAfterSaleIn,
    StayAfterSaleOut,
    StayAfterSaleRespondIn,
)

NO_ROOM_PENALTY_RATE = 0.3      # 违约金 = 首晚房费 × 30%
AFTERSALE_AUTO_HOURS = 2        # 商家响应窗口,超时按成立处理


def _aftersale_out(a: StayAfterSale,
                   order: StayOrder | None = None) -> StayAfterSaleOut:
    out = StayAfterSaleOut.model_validate(a)
    if order is not None:
        out.order_no = order.order_no
        out.guest_name = order.guest_name
        out.total_cents = order.total_cents
    return out


async def resolve_stay_aftersale(db: AsyncSession, a: StayAfterSale,
                                 order: StayOrder, accept: bool,
                                 merchant_note: str = "",
                                 nego_refund_cents: int | None = None,
                                 auto: bool = False) -> None:
    """售后裁决统一入口(商家响应与超时自动成立共用,调用方持有行锁并 commit)。

    到店无房成立:refund = 房费 + 首晚×30% 违约金,net = -违约金(商家余额扣),
    fee = 0——审计恒等式 net + refund == total 依然成立,平台分文不取。
    """
    now = datetime.now(_tz.utc)
    a.merchant_note = merchant_note
    a.resolved_at = now
    if not accept:
        a.status = StayAfterSaleStatus.rejected
        return
    a.status = (StayAfterSaleStatus.auto_accepted if auto
                else StayAfterSaleStatus.accepted)
    if a.kind == StayAfterSaleKind.no_room:
        penalty = int(_first_night_cents(order) * NO_ROOM_PENALTY_RATE)
        a.penalty_cents = penalty
        a.refund_cents = order.total_cents + penalty
        _transit(order, StayOrderStatus.CANCELLED, "system")
        order.cancelled_at = now
        order.fee_cents = 0
        order.net_cents = -penalty
        order.refund_cents = order.total_cents + penalty
        # 微信支付联调后:房费原路退,违约金改走「转账到零钱」(退款不能超支付额)
        order.refund_note = "到店无房:全额退款+商家违约金(首晚30%)"
    else:  # 协商退:商家填多少退多少
        refund = min(max(nego_refund_cents or 0, 0), order.total_cents)
        a.refund_cents = refund
        _transit(order, StayOrderStatus.CANCELLED, "system")
        order.cancelled_at = now
        order.fee_cents = 0
        order.net_cents = order.total_cents - refund
        order.refund_cents = refund
        order.refund_note = "协商退款(商家同意)"
    await release(db, order.room_type_id, order.checkin_date,
                  order.checkout_date, order.rooms_qty)


@router.post("/orders/{order_no}/aftersale", response_model=StayAfterSaleOut)
async def create_stay_aftersale(
    order_no: str,
    payload: StayAfterSaleIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """发起售后。到店无房:已确认且到了入住日仍没房;
    协商退:不可退(strict)房型行程有变,商家同意才动钱。
    设施不符/卫生问题请走「我的-联系客服」工单。
    """
    order = await _customer_order(db, user, order_no, lock=True)
    kind = StayAfterSaleKind(payload.kind)
    if kind == StayAfterSaleKind.no_room:
        if order.status != StayOrderStatus.CONFIRMED:
            raise HTTPException(409, "只有已确认待入住的订单能发起「到店无房」")
        if date.today() < order.checkin_date:
            raise HTTPException(409, "还没到入住日;到店后确实无房再发起")
    else:
        if order.status not in (StayOrderStatus.PAID,
                                StayOrderStatus.CONFIRMED):
            raise HTTPException(409, "当前状态不能申请协商退")
        policy = order.cancel_policy.value \
            if hasattr(order.cancel_policy, "value") else order.cancel_policy
        if policy != CancelPolicy.strict.value:
            raise HTTPException(409, "该房型可直接取消,不需要协商(见订单页取消按钮)")
    existing = await db.scalar(
        select(StayAfterSale).where(
            StayAfterSale.stay_order_id == order.id,
            StayAfterSale.status == StayAfterSaleStatus.pending))
    if existing:
        raise HTTPException(409, "已有处理中的售后申请,请等商家响应")
    a = StayAfterSale(
        stay_order_id=order.id,
        customer_id=user.id,
        merchant_id=order.merchant_id,
        kind=kind,
        note=payload.note.strip(),
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    # 推送商家(2 小时不响应按成立处理)
    try:
        from ..services.push import push_to_user
        m = await db.get(Merchant, order.merchant_id)
        if m:
            label = "到店无房" if kind == StayAfterSaleKind.no_room else "协商退款"
            await push_to_user(
                m.owner_id, f"住宿售后:{label}",
                f"订单#{order.order_no[-6:]} 客人发起{label},"
                f"请在 {AFTERSALE_AUTO_HOURS} 小时内处理",
                {"type": "stay_aftersale", "order_no": order.order_no})
    except Exception:
        logger.exception("售后推送失败")
    return _aftersale_out(a, order)


@router.get("/orders/{order_no}/aftersale", response_model=StayAfterSaleOut)
async def my_stay_aftersale(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    order = await _customer_order(db, user, order_no)
    a = await db.scalar(
        select(StayAfterSale)
        .where(StayAfterSale.stay_order_id == order.id)
        .order_by(StayAfterSale.created_at.desc()).limit(1))
    if a is None:
        raise HTTPException(404, "没有售后记录")
    return _aftersale_out(a, order)


@router.get("/me/aftersales", response_model=list[StayAfterSaleOut])
async def merchant_stay_aftersales(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_hotel(db, user)
    rows = (await db.execute(
        select(StayAfterSale, StayOrder)
        .join(StayOrder, StayOrder.id == StayAfterSale.stay_order_id)
        .where(StayAfterSale.merchant_id == shop.id)
        .order_by(StayAfterSale.created_at.desc()).limit(100))).all()
    return [_aftersale_out(a, o) for a, o in rows]


@router.post("/me/aftersales/{aftersale_id}/respond",
             response_model=StayAfterSaleOut)
async def respond_stay_aftersale(
    aftersale_id: int,
    payload: StayAfterSaleRespondIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家响应售后。到店无房同意 = 认罚(全额退+违约金);
    协商退同意时必须带退款金额。对判罚有异议走客服工单人工复核。
    """
    shop = await _my_hotel(db, user)
    a = await db.scalar(
        select(StayAfterSale).where(StayAfterSale.id == aftersale_id)
        .with_for_update())
    if a is None or a.merchant_id != shop.id:
        raise HTTPException(404, "售后申请不存在")
    if a.status != StayAfterSaleStatus.pending:
        raise HTTPException(409, "该申请已处理过")
    if payload.accept and a.kind == StayAfterSaleKind.nego_refund \
            and payload.refund_cents is None:
        raise HTTPException(422, "同意协商退需要填写退款金额")
    order = await db.scalar(
        select(StayOrder).where(StayOrder.id == a.stay_order_id)
        .with_for_update())
    await resolve_stay_aftersale(
        db, a, order, payload.accept,
        merchant_note=payload.note.strip(),
        nego_refund_cents=payload.refund_cents)
    await db.commit()
    await db.refresh(a)
    # 通知用户结果
    try:
        from ..services.push import push_to_user
        if payload.accept:
            await push_to_user(
                a.customer_id, "售后已通过",
                f"订单#{order.order_no[-6:]} 退款 ¥{a.refund_cents / 100:g}"
                " 将原路退回",
                {"type": "stay_order", "order_no": order.order_no})
        else:
            await push_to_user(
                a.customer_id, "售后未通过",
                f"订单#{order.order_no[-6:]} 商家回应:{a.merchant_note or '未说明'};"
                "如有异议可联系平台客服",
                {"type": "stay_order", "order_no": order.order_no})
    except Exception:
        logger.exception("售后结果推送失败")
    return _aftersale_out(a, order)


# ---------- 商家自助:酒店资料(#90 网页工作台补充) ----------

@router.get("/me/profile")
async def my_hotel_profile(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """酒店专属资料(网页设置页用):证照只读,联系与时刻可自改。"""
    shop = await _my_hotel(db, user)
    hp = await db.scalar(
        select(HotelProfile).where(HotelProfile.merchant_id == shop.id))
    if hp is None:
        raise HTTPException(404, "酒店资料不存在")
    return {
        "tier": hp.tier,
        "front_desk_phone": hp.front_desk_phone,
        "checkin_from": hp.checkin_from,
        "checkout_until": hp.checkout_until,
        "facilities": hp.facilities,
        # 证照只读展示;变更资质走客服工单人工核验
        "special_license_no": hp.special_license_no,
    }


@router.patch("/me/profile")
async def update_hotel_profile(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """酒店自改:前台电话/入退房时刻/设施标签。档次与两证不可自改
    (资质与展示口径需平台核验,变更走客服工单)。"""
    import re

    shop = await _my_hotel(db, user, need_owner=True)
    hp = await db.scalar(
        select(HotelProfile).where(HotelProfile.merchant_id == shop.id))
    if hp is None:
        raise HTTPException(404, "酒店资料不存在")
    hhmm = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
    if "front_desk_phone" in payload:
        hp.front_desk_phone = str(payload["front_desk_phone"]).strip()[:20]
    if "checkin_from" in payload:
        value = str(payload["checkin_from"])
        if not hhmm.match(value):
            raise HTTPException(422, "入住时刻格式应为 HH:MM")
        hp.checkin_from = value
    if "checkout_until" in payload:
        value = str(payload["checkout_until"])
        if not hhmm.match(value):
            raise HTTPException(422, "退房时刻格式应为 HH:MM")
        hp.checkout_until = value
    if "facilities" in payload:
        items = payload["facilities"]
        if not isinstance(items, list) or len(items) > 20:
            raise HTTPException(422, "设施标签最多 20 个")
        hp.facilities = [str(x).strip()[:20] for x in items if str(x).strip()]
    await db.commit()
    return {"ok": True}
