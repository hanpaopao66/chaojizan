from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from ..categories import MERCHANT_CATEGORIES
from ..config import settings
from ..db import get_db
from ..services import cloud_print
from ..models import (
    Coupon,
    CouponBatch,
    Dish,
    EarningKind,
    Merchant,
    MerchantEarning,
    MerchantStatus,
    Order,
    User,
    VoucherPurchase,
    VoucherPurchaseStatus,
    Withdrawal,
    WithdrawalStatus,
)

CN_TZ = ZoneInfo("Asia/Shanghai")
from ..state_machine import OrderStatus
from ..schemas import (
    DayStatOut,
    DishIn,
    DishOut,
    DishPatch,
    FinanceOrderOut,
    MerchantIn,
    MerchantOut,
    MerchantPatch,
    PrinterBindIn,
    PrinterOut,
    PrinterPatch,
    RestIn,
    ShopCouponBatchIn,
    ShopCouponBatchOut,
    ClaimableCouponOut,
    WalletOut,
    WithdrawalIn,
    WithdrawalOut,
)
from ..security import require_role

router = APIRouter(prefix="/merchants", tags=["商家"])

# 附近商家 + 近 30 天完成单数(月售),按指定方式排序
_NEARBY_SQL_TMPL = """
    SELECT m.id, count(o.id) AS sales
    FROM merchants m
    LEFT JOIN orders o
           ON o.merchant_id = m.id
          AND o.status = 'completed'
          AND o.created_at >= now() - interval '30 days'
          AND coalesce(o.risk_flags->>'status', '') != 'confirmed'
    WHERE m.is_open = true
      AND m.status = 'approved'
      {category_clause}
      AND ST_DWithin(
            ST_SetSRID(ST_MakePoint(m.lng, m.lat), 4326)::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            :radius_m
          )
    GROUP BY m.id
    ORDER BY {order_by}
    LIMIT 50
"""

_DIST_EXPR = (
    "ST_SetSRID(ST_MakePoint(m.lng, m.lat), 4326)::geography "
    "<-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography"
)

# 排序白名单(拼 SQL 前必须查表,防注入)
_SORTS = {
    "distance": _DIST_EXPR,
    "rating": (
        "(m.rating_sum::float / NULLIF(m.rating_count, 0)) DESC NULLS LAST, "
        + _DIST_EXPR
    ),
    "sales": "count(o.id) DESC, " + _DIST_EXPR,
}



async def _fill_top_dishes(db: AsyncSession, outs: list[MerchantOut]) -> None:
    """列表页招牌菜(每店最多 3 个:有图优先)。一次查询,无 N+1。"""
    ids = [o.id for o in outs]
    if not ids:
        return
    rows = await db.execute(text("""
        SELECT merchant_id, name, price_cents, image_url FROM (
          SELECT merchant_id, name, price_cents, image_url,
                 row_number() OVER (
                   PARTITION BY merchant_id
                   ORDER BY (image_url <> '') DESC, id
                 ) AS rn
          FROM dishes WHERE is_on_sale AND merchant_id = ANY(:ids)
        ) t WHERE rn <= 3
    """), {"ids": ids})
    by_merchant: dict[int, list] = {}
    for mid, name, price, img in rows:
        by_merchant.setdefault(mid, []).append(
            {"name": name, "price_cents": price, "image_url": img})
    for out in outs:
        out.top_dishes = by_merchant.get(out.id, [])


@router.get("", response_model=list[MerchantOut])
async def list_merchants(
    lat: float | None = None,
    lng: float | None = None,
    radius_m: int = 5000,
    sort: str = "distance",
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """附近营业中的商家(带月售),sort=distance|rating|sales,category 按品类筛选。"""
    if sort not in _SORTS:
        raise HTTPException(422, "sort 仅支持 distance / rating / sales")
    if category is not None and category not in MERCHANT_CATEGORIES:
        raise HTTPException(422, "未知品类")
    if lat is not None and lng is not None:
        rows = await db.execute(
            text(_NEARBY_SQL_TMPL.format(
                order_by=_SORTS[sort],
                category_clause=(
                    "AND m.category = :category" if category else ""))),
            {"lat": lat, "lng": lng, "radius_m": radius_m,
             **({"category": category} if category else {})},
        )
        id_sales = [(r[0], r[1]) for r in rows]
        if not id_sales:
            return []
        result = await db.scalars(
            select(Merchant).where(Merchant.id.in_([i for i, _ in id_sales]))
        )
        by_id = {m.id: m for m in result}
        outs = []
        for mid, sales in id_sales:
            if mid not in by_id:
                continue
            out = MerchantOut.model_validate(by_id[mid])
            out.monthly_sales = sales
            outs.append(out)
        await _fill_top_dishes(db, outs)
        return outs
    query = select(Merchant).where(
        Merchant.is_open.is_(True), Merchant.status == MerchantStatus.approved)
    if category:
        query = query.where(Merchant.category == category)
    result = await db.scalars(query.limit(50))
    outs = [MerchantOut.model_validate(m) for m in result]
    await _fill_top_dishes(db, outs)
    return outs


@router.get("/categories")
async def merchant_categories():
    """外卖品类清单(slug -> 中文名),管理后台下拉与三端展示共用。"""
    return MERCHANT_CATEGORIES


@router.get("/hot-keywords")
async def hot_keywords(db: AsyncSession = Depends(get_db)):
    """热搜词 = 近 30 天销量最高的在售菜名(去重取前 10)。

    没有搜索日志也能冷启动:用真实销量当热度,天然反刷。
    """
    rows = await db.execute(text("""
        SELECT d.name, count(*) AS n
        FROM orders o, jsonb_array_elements(o.items) it
        JOIN dishes d ON d.id = (it->>'dish_id')::int AND d.is_on_sale
        WHERE o.status = 'completed'
          AND o.created_at >= now() - interval '30 days'
        GROUP BY d.name ORDER BY n DESC LIMIT 10
    """))
    return {"keywords": [r[0] for r in rows]}


# 搜索排序白名单(拼 SQL 前必须查表,防注入)。综合=评分×销量×距离衰减
_SEARCH_SORTS = {
    "comprehensive": (
        "(coalesce(m.rating_sum::float / NULLIF(m.rating_count,0), 3) * 20"
        " + ln(1 + count(o.id)) * 10"
        " - {dist_km} * 2) DESC"),
    "distance": "{dist} ASC",
    "rating": ("(m.rating_sum::float / NULLIF(m.rating_count,0)) "
               "DESC NULLS LAST"),
    "sales": "count(o.id) DESC",
}
_SEARCH_DIST = ("(ST_SetSRID(ST_MakePoint(m.lng,m.lat),4326)::geography "
                "<-> ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography)")
_SEARCH_DIST_KM = f"({_SEARCH_DIST} / 1000)"


@router.get("/search", response_model=list[MerchantOut])
async def search_merchants(
    q: str = Query(min_length=1, max_length=50),
    lat: float | None = None,
    lng: float | None = None,
    sort: str = "comprehensive",
    max_distance_m: int | None = Query(default=None, ge=100, le=20000),
    min_rating: float | None = Query(default=None, ge=0, le=5),
    has_promo: bool = False,          # 有满减或满赠
    max_min_order_cents: int | None = Query(default=None, ge=0, le=100_000),
    db: AsyncSession = Depends(get_db),
):
    """搜索营业中的商家:店名或在售菜名命中。

    排序 sort=comprehensive(评分×销量×距离衰减,默认)/distance/rating/sales;
    筛选:max_distance_m 距离上限、min_rating 评分下限、has_promo 有优惠、
    max_min_order_cents 起送价上限。综合/距离排序需要 lat/lng,缺则退化按评分。
    绝不做竞价排名——排序只用真实评分/销量/距离,商家花钱买不到靠前。
    """
    has_pos = lat is not None and lng is not None
    if sort in ("comprehensive", "distance") and not has_pos:
        sort = "rating"  # 没定位无法算距离,退化到评分
    if sort not in _SEARCH_SORTS:
        raise HTTPException(422, "sort 仅支持 comprehensive/distance/rating/sales")

    params: dict = {"pattern": f"%{q.strip()}%"}
    where = ["m.is_open = true", "m.status = 'approved'",
             "(m.name ILIKE :pattern OR EXISTS ("
             " SELECT 1 FROM dishes d WHERE d.merchant_id = m.id"
             " AND d.is_on_sale AND d.name ILIKE :pattern))"]
    if has_pos:
        params["lat"], params["lng"] = lat, lng
        if max_distance_m is not None:
            params["radius_m"] = max_distance_m
            where.append(
                "ST_DWithin(ST_SetSRID(ST_MakePoint(m.lng,m.lat),4326)::geography,"
                " ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography, :radius_m)")
    if min_rating is not None:
        params["min_rating"] = min_rating
        where.append(
            "coalesce(m.rating_sum::float / NULLIF(m.rating_count,0), 0)"
            " >= :min_rating")
    if has_promo:
        where.append("(m.promo_rules <> '[]'::jsonb"
                     " OR m.gift_rules <> '[]'::jsonb)")
    if max_min_order_cents is not None:
        params["max_min_order"] = max_min_order_cents
        where.append("m.min_order_cents <= :max_min_order")

    order_by = _SEARCH_SORTS[sort].format(
        dist=_SEARCH_DIST if has_pos else "0",
        dist_km=_SEARCH_DIST_KM if has_pos else "0")
    sql = text(f"""
        SELECT m.id, count(o.id) AS sales
        FROM merchants m
        LEFT JOIN orders o
               ON o.merchant_id = m.id AND o.status = 'completed'
              AND o.created_at >= now() - interval '30 days'
        WHERE {' AND '.join(where)}
        GROUP BY m.id
        ORDER BY {order_by}
        LIMIT 30
    """)
    rows = await db.execute(sql, params)
    id_sales = [(r[0], r[1]) for r in rows]
    if not id_sales:
        return []
    by_id = {m.id: m for m in await db.scalars(
        select(Merchant).where(Merchant.id.in_([i for i, _ in id_sales])))}
    outs = []
    for mid, sales in id_sales:  # 保持 SQL 已排好的顺序
        if mid in by_id:
            out = MerchantOut.model_validate(by_id[mid])
            out.monthly_sales = sales
            outs.append(out)
    await _fill_top_dishes(db, outs)
    return outs


@router.get("/suggest")
async def search_suggest(
    q: str = Query(min_length=1, max_length=30),
    db: AsyncSession = Depends(get_db),
):
    """搜索联想:匹配的店名 + 热门在售菜名(前缀优先),各最多 6 条。"""
    pattern = f"%{q.strip()}%"
    prefix = f"{q.strip()}%"
    shops = (await db.scalars(
        select(Merchant.name).where(
            Merchant.is_open.is_(True),
            Merchant.status == MerchantStatus.approved,
            Merchant.name.ilike(pattern))
        .order_by(Merchant.name.ilike(prefix).desc(),
                  Merchant.rating_sum.desc())
        .limit(6))).all()
    # 菜名去重放到 Python(SELECT DISTINCT 不允许 ORDER BY 非 select 列),
    # 多取一些再按前缀优先去重截断
    dishes = (await db.scalars(
        select(Dish.name).where(
            Dish.is_on_sale.is_(True), Dish.name.ilike(pattern))
        .order_by(Dish.name.ilike(prefix).desc())
        .limit(30))).all()
    return {"shops": list(dict.fromkeys(shops)),
            "dishes": list(dict.fromkeys(dishes))[:6]}


@router.post("", response_model=MerchantOut)
async def apply_shop(
    payload: MerchantIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """提交开店申请,进入待审核。证照号+证照照片是硬要求(食品安全法,监管留存影像)。"""
    if not payload.license_no.strip():
        raise HTTPException(422, "请填写食品经营许可证号")
    if not payload.license_image_url.strip():
        raise HTTPException(422, "请上传食品经营许可证照片")
    if payload.category not in MERCHANT_CATEGORIES:
        raise HTTPException(422, "未知品类")
    existing = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if existing:
        raise HTTPException(409, "你已提交过申请,一个账号一家店")
    shop = Merchant(
        owner_id=user.id,
        status=MerchantStatus.pending,
        is_open=False,
        **payload.model_dump(),
    )
    # 所在城市:坐标逆地理解析(天地图;失败留空,管理后台人工补填)
    from ..services.geo_city import city_of
    shop.city = await city_of(payload.lat, payload.lng)
    db.add(shop)
    await db.commit()
    await db.refresh(shop)
    return shop


@router.get("/me", response_model=MerchantOut)
async def my_shop(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    # 店主或店员都能看店(店员据此听单接单);viewer_is_staff 供客户端隐藏敏感入口
    from ..services.staff import operable_shop
    shop, is_owner = await operable_shop(db, user)
    if shop is None:
        raise HTTPException(404, "还没开店")
    out = MerchantOut.model_validate(shop)
    out.viewer_is_staff = not is_owner
    return out


@router.patch("/me", response_model=MerchantOut)
async def update_my_shop(
    payload: MerchantPatch,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")

    changes = payload.model_dump(exclude_none=True)
    if "category" in changes and changes["category"] not in MERCHANT_CATEGORIES:
        raise HTTPException(422, "未知品类")
    if changes.get("is_open") and shop.status != MerchantStatus.approved:
        raise HTTPException(403, "店铺还未通过审核,暂时不能营业")
    # 开城清单:配置了 open_cities 时,清单外城市不可营业(可入驻待审,
    # 抢先注册留资;空 city 未标注不拦,避免误伤存量)
    if changes.get("is_open"):
        from ..services.flags import open_cities
        cities = await open_cities(db)
        if cities is not None and shop.city and shop.city not in cities:
            raise HTTPException(
                409, f"你的城市({shop.city})即将开通,菜单先备好,"
                     "开城第一时间通知你")

    # 面向用户的文本过敏感词(店名/公告)
    from ..services.moderation import guard_text
    if changes.get("name"):
        await guard_text(db, changes["name"], "店铺名称")
    if changes.get("announcement"):
        await guard_text(db, changes["announcement"], "店铺公告")

    # 节假日计划:HolidayPlan 校验后归一化为 {from,to,closed,open,close} 存储
    if "holiday_plans" in changes:
        changes["holiday_plans"] = [
            {"from": p["from_date"], "to": p["to_date"], "closed": p["closed"],
             "open": p["open"], "close": p["close"]}
            for p in changes["holiday_plans"]
        ]
    # 手动开店 = 结束临时歇业(商家改主意提前恢复,清扫任务不再干预)
    if changes.get("is_open"):
        shop.closed_until = None

    # 满赠规则:赠品必须是本店在售菜品;名字以库里为准存快照(展示不再查菜)
    if "gift_rules" in changes:
        for rule in changes["gift_rules"]:
            dish = await db.scalar(select(Dish).where(
                Dish.id == rule["dish_id"], Dish.merchant_id == shop.id))
            if dish is None or not dish.is_on_sale:
                raise HTTPException(422, "赠品必须是本店在售菜品")
            rule["name"] = dish.name

    info_changed = any(k != "is_open" for k in changes)
    for field, value in changes.items():
        setattr(shop, field, value)
    # 被驳回后修改资料 = 重新提交审核
    if info_changed and shop.status == MerchantStatus.rejected:
        shop.status = MerchantStatus.pending
        shop.reject_reason = ""
        shop.is_open = False
    await db.commit()
    await db.refresh(shop)
    return shop


@router.get("/me/dishes", response_model=list[DishOut])
async def my_dishes(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家管理视角:含已下架菜品。注意必须注册在 /{merchant_id}/dishes 之前。"""
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    result = await db.scalars(
        select(Dish)
        .where(Dish.merchant_id == shop.id)
        .order_by(Dish.category, Dish.id)
    )
    dishes = list(result)
    # 带上近 30 天销量:商家端销量榜/滞销提示的数据源
    sales_rows = await db.execute(_DISH_SALES_SQL, {"merchant_id": shop.id})
    sales = {row.dish_id: row.sold for row in sales_rows}
    outs = []
    for dish in dishes:
        out = DishOut.model_validate(dish)
        out.monthly_sales = sales.get(dish.id, 0)
        outs.append(out)
    return outs


# 每个菜近 30 天卖了多少份:从完成订单的 items 快照(JSONB)聚合
_DISH_SALES_SQL = text(
    """
    SELECT (item->>'dish_id')::int AS dish_id,
           sum((item->>'quantity')::int)::int AS sold
    FROM orders o
    CROSS JOIN LATERAL jsonb_array_elements(o.items) AS item
    WHERE o.merchant_id = :merchant_id
      AND o.status = 'completed'
      AND o.created_at >= now() - interval '30 days'
      AND coalesce(o.risk_flags->>'status', '') != 'confirmed'
    GROUP BY 1
    """
)


@router.get("/{merchant_id}/dishes", response_model=list[DishOut])
async def menu(merchant_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.scalars(
        select(Dish).where(Dish.merchant_id == merchant_id, Dish.is_on_sale.is_(True))
    )
    dishes = list(result)
    sales_rows = await db.execute(_DISH_SALES_SQL, {"merchant_id": merchant_id})
    sales = {row.dish_id: row.sold for row in sales_rows}
    outs = []
    for dish in dishes:
        out = DishOut.model_validate(dish)
        out.monthly_sales = sales.get(dish.id, 0)
        outs.append(out)
    return outs


@router.get("/{merchant_id}/frequent-dishes", response_model=list[DishOut])
async def frequent_dishes(
    merchant_id: int,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """我常买:该用户近 90 天在本店完成单里出现 ≥2 次的在售菜(按出现单数降序)。

    只回当前在售且未下架的菜,失效的自动从常买消失;赠品行(0元)不计。
    """
    since = datetime.now(timezone.utc) - timedelta(days=90)
    orders = (await db.scalars(
        select(Order).where(
            Order.customer_id == user.id,
            Order.merchant_id == merchant_id,
            Order.status == OrderStatus.COMPLETED,
            Order.created_at > since))).all()
    # 每个 dish_id 出现在多少张单里(同单多份算一次;赠品行不计)
    order_count: dict[int, int] = {}
    for o in orders:
        seen = {it["dish_id"] for it in o.items
                if it.get("price_cents", 0) > 0 and it.get("dish_id")}
        for did in seen:
            order_count[did] = order_count.get(did, 0) + 1
    frequent_ids = [did for did, n in order_count.items() if n >= 2]
    if not frequent_ids:
        return []
    dishes = (await db.scalars(
        select(Dish).where(Dish.id.in_(frequent_ids),
                           Dish.merchant_id == merchant_id,
                           Dish.is_on_sale.is_(True)))).all()
    # 按出现单数降序,便于客户端把最常买的排前面
    dishes.sort(key=lambda d: order_count.get(d.id, 0), reverse=True)
    return [DishOut.model_validate(d) for d in dishes]


@router.post("/me/dishes", response_model=DishOut)
async def add_dish(
    payload: DishIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "先开店再上菜")
    from ..services.moderation import guard_text, submit_images
    await guard_text(db, payload.name, "菜品名称")
    dish = Dish(merchant_id=shop.id, **payload.model_dump())
    db.add(dish)
    await db.flush()
    if dish.image_url:  # 菜品图先发后审
        await submit_images(db, "dish", dish.id, [dish.image_url])
    await db.commit()
    await db.refresh(dish)
    return dish


@router.patch("/me/dishes/{dish_id}", response_model=DishOut)
async def update_dish(
    dish_id: int,
    payload: DishPatch,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """改价/改库存/上下架/限时折扣。已有订单存的是快照,不受影响。"""
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    dish = await db.get(Dish, dish_id)
    if shop is None or dish is None or dish.merchant_id != shop.id:
        raise HTTPException(404, "菜品不存在")
    flash_was_off = dish.flash_price_cents is None
    # exclude_unset:没传的字段不动,显式传 null 用于关闭限时折扣
    changes = payload.model_dump(exclude_unset=True)
    from ..services.moderation import guard_text, submit_images
    if changes.get("name"):
        await guard_text(db, changes["name"], "菜品名称")
    if changes.get("image_url") and changes["image_url"] != dish.image_url:
        await submit_images(db, "dish", dish.id, [changes["image_url"]])
    for field, value in changes.items():
        setattr(dish, field, value)
    # 手动补了库存 = 估清态自然解除(避免"有货却显示今日售罄")
    if changes.get("stock", 0) and dish.sold_out_today:
        dish.sold_out_today = False
        dish.stock_before_soldout = None
    # 限时折扣自洽:要么两者都有且折扣价低于现价,要么都空
    if (dish.flash_price_cents is None) != (dish.flash_until is None):
        raise HTTPException(422, "限时折扣需同时设置折扣价和截止时间(或同时清除)")
    if (dish.flash_price_cents is not None
            and dish.flash_price_cents >= dish.price_cents):
        raise HTTPException(422, "折扣价必须低于原价,否则不叫折扣")
    await db.commit()
    await db.refresh(dish)
    # 收藏触达:新开限时折扣推给收藏者(仅"关→开"触发,改价/续期不重复推)
    if flash_was_off and dish.flash_price_cents is not None:
        from ..services.push import notify_favorites

        await notify_favorites(
            db, shop.id, shop.name,
            f"你收藏的「{shop.name}」开了限时折扣",
            f"{dish.name}:¥{dish.price_cents / 100:g} → "
            f"¥{dish.flash_price_cents / 100:g},手快有手慢无")
    return dish


@router.post("/me/rest", response_model=MerchantOut)
async def rest_temporarily(
    payload: RestIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """临时歇业:关店并记下恢复时刻,到点清扫任务自动恢复营业。

    区别于手动关店(容易忘了开):忙不过来/临时有事点一下,不影响后面生意。
    提前想恢复直接开店即可(开店动作会清掉歇业标记)。
    """
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    now = datetime.now(timezone.utc)
    if payload.until_close:
        if not shop.close_time:
            raise HTTPException(422, "没有设置每日打烊时间,请选择歇业时长")
        hour, minute = shop.close_time.split(":")
        until = datetime.now(CN_TZ).replace(
            hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if until <= datetime.now(CN_TZ):
            until += timedelta(days=1)  # 已过今天打烊点 = 歇到明天打烊
    else:
        until = now + timedelta(hours=payload.hours)
    shop.is_open = False
    shop.closed_until = until
    await db.commit()
    await db.refresh(shop)
    return shop


@router.post("/me/dishes/{dish_id}/sell-out", response_model=DishOut)
async def sell_out_dish(
    dish_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """一键估清(今日售罄):库存清零 + 打标,次日 04:00 自动恢复。

    与下架的区别:估清是临时态,用户端灰态展示「今日售罄」而不是消失;
    估清前库存存档,未启用每日回满的菜恢复时回到原值。
    """
    from ..services.staff import operable_shop
    shop, _ = await operable_shop(db, user)  # 估清是运营操作,店员可做
    dish = await db.get(Dish, dish_id)
    if shop is None or dish is None or dish.merchant_id != shop.id:
        raise HTTPException(404, "菜品不存在")
    if dish.sold_out_today:
        raise HTTPException(409, "已经是估清状态")
    dish.stock_before_soldout = dish.stock
    dish.stock = 0
    dish.sold_out_today = True
    await db.commit()
    await db.refresh(dish)
    return dish


@router.post("/me/dishes/{dish_id}/sell-out/cancel", response_model=DishOut)
async def cancel_sell_out(
    dish_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """撤销估清:恢复估清前库存(或每日回满目标),当天就能继续卖。"""
    from ..services.staff import operable_shop
    shop, _ = await operable_shop(db, user)  # 估清是运营操作,店员可做
    dish = await db.get(Dish, dish_id)
    if shop is None or dish is None or dish.merchant_id != shop.id:
        raise HTTPException(404, "菜品不存在")
    if not dish.sold_out_today:
        raise HTTPException(409, "该菜品不在估清状态")
    if dish.stock_before_soldout is not None:
        dish.stock = dish.stock_before_soldout
    elif dish.daily_stock is not None:
        dish.stock = dish.daily_stock
    dish.sold_out_today = False
    dish.stock_before_soldout = None
    await db.commit()
    await db.refresh(dish)
    return dish


# ---------- 商家子账号(店员分权:能接单出餐估清,不能提现改价)----------

@router.get("/me/staff")
async def list_staff(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """店主查看自己店的子账号列表。店员访问返回空(自己非店主)。"""
    from ..models import MerchantStaff
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        return []
    rows = (await db.execute(
        select(MerchantStaff, User)
        .join(User, User.id == MerchantStaff.user_id)
        .where(MerchantStaff.merchant_id == shop.id)
        .order_by(MerchantStaff.created_at))).all()
    return [{"user_id": s.user_id, "name": s.name or u.name,
             "phone": u.phone[:3] + "****" + u.phone[-4:]}
            for s, u in rows]


@router.post("/me/staff")
async def add_staff(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """按手机号添加店员(该号需已注册过)。仅店主可操作。

    店员账号设为 merchant 角色但不拥有店铺;不能是店主本人、不能已拥有店、
    不能已是别家店员。
    """
    from ..models import MerchantStaff, UserRole
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(403, "只有店主可以管理子账号")
    phone = str(payload.get("phone", "")).strip()
    name = str(payload.get("name", "")).strip()[:50]
    target = await db.scalar(select(User).where(User.phone == phone))
    if target is None:
        raise HTTPException(404, "该手机号还没注册过,请对方先下载 App 登录一次")
    if target.id == user.id:
        raise HTTPException(409, "不能把自己加为店员")
    owns = await db.scalar(select(Merchant).where(Merchant.owner_id == target.id))
    if owns is not None:
        raise HTTPException(409, "对方已是某店店主,不能作为子账号")
    existing = await db.scalar(
        select(MerchantStaff).where(MerchantStaff.user_id == target.id))
    if existing is not None:
        raise HTTPException(409, "对方已是某店店员")
    target.role = UserRole.merchant  # 子账号需 merchant 角色才能进商家端
    db.add(MerchantStaff(merchant_id=shop.id, user_id=target.id, name=name))
    await db.commit()
    return {"ok": True, "user_id": target.id}


@router.delete("/me/staff/{user_id}")
async def remove_staff(
    user_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """移除店员。仅店主可操作。"""
    from ..models import MerchantStaff
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(403, "只有店主可以管理子账号")
    link = await db.scalar(select(MerchantStaff).where(
        MerchantStaff.merchant_id == shop.id,
        MerchantStaff.user_id == user_id))
    if link is None:
        raise HTTPException(404, "该店员不存在")
    await db.delete(link)
    await db.commit()
    return {"ok": True}


# ---------- 商家店铺券(成本商家承担,平台不补贴)----------

def _shop_batch_out(b: CouponBatch) -> ShopCouponBatchOut:
    return ShopCouponBatchOut(
        id=b.id, name=b.name, threshold_cents=b.min_spend_cents,
        off_cents=b.amount_cents, total=b.total, issued=b.issued,
        per_user_limit=b.per_user_limit, valid_days=b.valid_days,
        active=b.active)


@router.post("/me/coupon-batches", response_model=ShopCouponBatchOut)
async def create_shop_coupon_batch(
    payload: ShopCouponBatchIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家自建店铺券批次。成本 100% 商家承担(下单走满减同口径),
    平台佣金按券后实收计——你让利,平台跟着少收,与满减一致。"""
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    batch = CouponBatch(
        name=payload.name, trigger="shop", merchant_id=shop.id,
        amount_cents=payload.off_cents, min_spend_cents=payload.threshold_cents,
        total=payload.total, per_user_limit=payload.per_user_limit,
        valid_days=payload.valid_days, active=True)
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return _shop_batch_out(batch)


@router.get("/me/coupon-batches", response_model=list[ShopCouponBatchOut])
async def list_shop_coupon_batches(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        return []
    rows = (await db.scalars(
        select(CouponBatch).where(CouponBatch.merchant_id == shop.id)
        .order_by(CouponBatch.created_at.desc()))).all()
    return [_shop_batch_out(b) for b in rows]


@router.post("/me/coupon-batches/{batch_id}/toggle",
             response_model=ShopCouponBatchOut)
async def toggle_shop_coupon_batch(
    batch_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    batch = await db.get(CouponBatch, batch_id)
    if shop is None or batch is None or batch.merchant_id != shop.id:
        raise HTTPException(404, "券批次不存在")
    batch.active = not batch.active
    await db.commit()
    await db.refresh(batch)
    return _shop_batch_out(batch)


@router.get("/{merchant_id}/coupons", response_model=list[ClaimableCouponOut])
async def claimable_shop_coupons(
    merchant_id: int,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """用户在某店可领的店铺券(含已领数与是否可再领)。"""
    batches = (await db.scalars(
        select(CouponBatch).where(
            CouponBatch.merchant_id == merchant_id,
            CouponBatch.active.is_(True)))).all()
    out = []
    for b in batches:
        mine = await db.scalar(
            select(func.count(Coupon.id)).where(
                Coupon.user_id == user.id,
                Coupon.source.like(f"shop:{b.id}:%")))
        remaining = b.total - b.issued
        out.append(ClaimableCouponOut(
            batch_id=b.id, name=b.name, threshold_cents=b.min_spend_cents,
            off_cents=b.amount_cents, remaining=max(0, remaining),
            claimed_by_me=mine or 0,
            can_claim=(remaining > 0 and (mine or 0) < b.per_user_limit)))
    return out


@router.post("/{merchant_id}/coupons/{batch_id}/claim")
async def claim_shop_coupon(
    merchant_id: int,
    batch_id: int,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """领取店铺券:发一张 funder=merchant 的券(限定本店使用)。"""
    # 反作弊软限制:limit/frozen 用户暂停领券(下单不拦),给可见提示可申诉
    if user.risk_level in ("limit", "frozen"):
        raise HTTPException(
            403, "账号存在异常,已暂停领券;如有疑问可在「我的-客服」申诉")
    batch = await db.get(CouponBatch, batch_id, with_for_update=True)
    if (batch is None or batch.merchant_id != merchant_id
            or not batch.active or batch.trigger != "shop"):
        raise HTTPException(404, "券不存在或已停止发放")
    if batch.issued >= batch.total:
        raise HTTPException(409, "该券已被领完")
    mine = await db.scalar(
        select(func.count(Coupon.id)).where(
            Coupon.user_id == user.id,
            Coupon.source.like(f"shop:{batch.id}:%")))
    if (mine or 0) >= batch.per_user_limit:
        raise HTTPException(409, f"每人限领 {batch.per_user_limit} 张,已领完")
    batch.issued += 1
    now = datetime.now(timezone.utc)
    seq = (mine or 0) + 1
    coupon = Coupon(
        user_id=user.id, amount_cents=batch.amount_cents,
        min_spend_cents=batch.min_spend_cents,
        expires_at=now + timedelta(days=batch.valid_days),
        source=f"shop:{batch.id}:{user.id}:{seq}",
        funder="merchant", merchant_id=merchant_id, batch_id=batch.id,
        note=f"店铺券:{batch.name}")
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)
    return {"coupon_id": coupon.id, "off_cents": coupon.amount_cents,
            "min_spend_cents": coupon.min_spend_cents,
            "expires_at": coupon.expires_at.isoformat()}


# ---------- 对账 ----------
# 时间戳按 UTC 存储,对账日按东八区(北京时间)分界
DAILY_FINANCE_SQL = text(
    """
    SELECT date(created_at AT TIME ZONE 'Asia/Shanghai') AS day,
           count(*) FILTER (WHERE kind = 'earning') AS order_count,
           coalesce(sum(food_cents), 0)       AS food_cents,
           coalesce(sum(commission_cents), 0) AS commission_cents,
           coalesce(sum(net_cents), 0)        AS net_cents
    FROM merchant_earnings
    WHERE merchant_id = :merchant_id
      AND created_at >= now() - make_interval(days => :days)
    GROUP BY 1
    ORDER BY 1 DESC
    """
)


async def _my_shop_or_404(db: AsyncSession, user: User) -> Merchant:
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    return shop


@router.get("/me/quality")
async def my_quality(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """经营质量(近 30 天):出餐超时率、拒单次数。只统计展示,不做处罚。"""
    shop = await _my_shop_or_404(db, user)
    row = (await db.execute(text("""
        SELECT count(*) FILTER (WHERE status = 'completed') AS completed,
               count(*) FILTER (WHERE status = 'completed' AND ready_late) AS late
        FROM orders
        WHERE merchant_id = :mid AND created_at >= now() - interval '30 days'
    """), {"mid": shop.id})).first()
    rejects = await db.scalar(text("""
        SELECT count(*) FROM order_events e
        JOIN orders o ON o.id = e.order_id
        WHERE o.merchant_id = :mid AND e.to_status = 'cancelled'
          AND e.actor_role = 'merchant'
          AND e.created_at >= now() - interval '30 days'
    """), {"mid": shop.id})
    completed, late = row.completed, row.late
    return {
        "completed_30d": completed,
        "ready_late_30d": late,
        "ready_late_rate": round(late / completed, 4) if completed else None,
        "rejects_30d": rejects,
        "promise_ready_minutes": shop.promise_ready_minutes,
    }


@router.get("/me/commission-tier")
async def my_commission_tier(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """阶梯佣金:当前费率/档位、上月与当月完成单量、距下一档还差多少。

    每月 1 日按上月单量重算;重算取 min(档位, 现费率),只降不升。
    """
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    from ..services.auto_flow import completed_counts, tier_rate_for

    shop = await _my_shop_or_404(db, user)
    now_bj = datetime.now(ZoneInfo("Asia/Shanghai"))
    month_start = now_bj.replace(day=1, hour=0, minute=0, second=0,
                                 microsecond=0)
    prev_start = (month_start - timedelta(days=1)).replace(day=1)
    last_month = (await completed_counts(
        db, prev_start.astimezone(timezone.utc),
        month_start.astimezone(timezone.utc))).get(shop.id, 0)
    this_month = (await completed_counts(
        db, month_start.astimezone(timezone.utc),
        datetime.now(timezone.utc))).get(shop.id, 0)

    tiers = [{"from_orders": int(t), "rate": float(r)}
             for t, r in settings.commission_tiers]
    # 下一档:当月单量决定下月费率,差多少按当月量算
    next_tier = next((t for t in tiers if t["from_orders"] > this_month), None)
    return {
        "commission_rate": float(shop.commission_rate),
        "tier_rate": float(tier_rate_for(last_month)),  # 档位价(现费率可能更低)
        "tiers": tiers,
        "last_month_completed": last_month,
        "this_month_completed": this_month,
        "next_tier_from": next_tier["from_orders"] if next_tier else None,
        "next_tier_rate": next_tier["rate"] if next_tier else None,
        "orders_to_next": (next_tier["from_orders"] - this_month
                           if next_tier else None),
    }


# ---------- 商家钱包与提现 ----------
# 余额是算出来的,不是存出来的:外卖净额(merchant_earnings,含售后冲账负数行)
# + 团购核销净额 - 提现(冻结中+已打款)。与骑手钱包同一套语义和 T+1 打款流程。


async def _merchant_wallet(db: AsyncSession, shop: Merchant, owner_id: int) -> WalletOut:
    # 只计平台代收口径:profit_sharing 行的钱已直达商家微信商户号,
    # 不进平台侧可提现余额(否则一笔钱发两遍)
    food_net = await db.scalar(
        select(func.coalesce(func.sum(MerchantEarning.net_cents), 0)).where(
            MerchantEarning.merchant_id == shop.id,
            MerchantEarning.settle_mode == "platform",
        )
    )
    voucher_net = await db.scalar(
        select(func.coalesce(func.sum(VoucherPurchase.net_cents), 0)).where(
            VoucherPurchase.merchant_id == shop.id,
            VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
        )
    )
    earned = food_net + voucher_net
    pending = await db.scalar(
        select(func.coalesce(func.sum(Withdrawal.amount_cents), 0)).where(
            Withdrawal.user_id == owner_id,
            Withdrawal.role == "merchant",
            Withdrawal.status == WithdrawalStatus.pending,
        )
    )
    paid = await db.scalar(
        select(func.coalesce(func.sum(Withdrawal.amount_cents), 0)).where(
            Withdrawal.user_id == owner_id,
            Withdrawal.role == "merchant",
            Withdrawal.status == WithdrawalStatus.paid,
        )
    )
    balance = earned - pending - paid
    deposit_required = shop.deposit_required_cents
    return WalletOut(
        balance_cents=balance,
        total_earned_cents=earned,
        pending_withdrawal_cents=pending,
        withdrawn_cents=paid,
        deposit_required_cents=deposit_required,
        deposit_held_cents=max(0, min(balance, deposit_required)),
        withdrawable_cents=max(0, balance - deposit_required),
    )


@router.get("/me/wallet", response_model=WalletOut)
async def merchant_wallet(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_shop_or_404(db, user)
    return await _merchant_wallet(db, shop, user.id)


@router.get("/me/withdrawals", response_model=list[WithdrawalOut])
async def merchant_withdrawals(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    await _my_shop_or_404(db, user)
    result = await db.scalars(
        select(Withdrawal)
        .where(Withdrawal.user_id == user.id, Withdrawal.role == "merchant")
        .order_by(Withdrawal.created_at.desc())
        .limit(100)
    )
    return list(result)


@router.post("/me/withdrawals", response_model=WithdrawalOut)
async def request_merchant_withdrawal(
    payload: WithdrawalIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家提现,T+1 打款、零手续费。锁店主行串行化并发申请,余额不可能被双花。"""
    if payload.amount_cents < settings.min_withdrawal_cents:
        raise HTTPException(
            422, f"最低提现 ¥{settings.min_withdrawal_cents / 100:.0f}"
        )
    shop = await _my_shop_or_404(db, user)
    from ..models import PayoutAccount
    from .payout import account_recently_changed
    account = await db.scalar(
        select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    if account is None:
        raise HTTPException(422, "请先在对账页登记收款账户(建议对公户),再申请提现")
    await db.execute(select(User).where(User.id == user.id).with_for_update())
    current = await _merchant_wallet(db, shop, user.id)
    if payload.amount_cents > current.withdrawable_cents:
        raise HTTPException(
            409,
            f"可提现 ¥{current.withdrawable_cents / 100:.2f}"
            f"(余额 ¥{current.balance_cents / 100:.2f},"
            f"其中保证金留存 ¥{current.deposit_held_cents / 100:.2f},"
            f"应留 ¥{current.deposit_required_cents / 100:.0f})"
        )
    withdrawal = Withdrawal(
        user_id=user.id, role="merchant", amount_cents=payload.amount_cents,
        account_snapshot={
            "kind": account.kind,
            "holder_name": account.holder_name,
            "bank_name": account.bank_name,
            "account_tail": account.account_tail,
            "account_no_encrypted": account.account_no_encrypted,
            "recently_changed": account_recently_changed(account),
        })
    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal


# ---------- 云打印小票(飞鹅):绑定/开关/测试/补打 ----------

_FEIE_DISABLED = "云打印未启用:平台还未配置打印服务商账号,可先用商家端的蓝牙小票机直连"


@router.get("/me/printer", response_model=PrinterOut)
async def my_printer(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_shop_or_404(db, user)
    return PrinterOut(enabled=settings.feie_configured,
                      sn=shop.printer_sn, auto=shop.printer_auto)


@router.post("/me/printer", response_model=PrinterOut)
async def bind_my_printer(
    payload: PrinterBindIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """绑定云打印机(机身贴纸上的 SN 与 KEY)。绑定即代表以后支付成功自动出票。"""
    if not settings.feie_configured:
        raise HTTPException(503, _FEIE_DISABLED)
    shop = await _my_shop_or_404(db, user)
    try:
        await cloud_print.bind_printer(payload.sn, payload.key,
                                       payload.remark or shop.name[:20])
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except httpx.HTTPError:
        raise HTTPException(502, "云打印服务暂时不可用,请稍后再试")
    shop.printer_sn = payload.sn
    shop.printer_auto = True
    await db.commit()
    return PrinterOut(enabled=True, sn=shop.printer_sn, auto=shop.printer_auto)


@router.patch("/me/printer", response_model=PrinterOut)
async def patch_my_printer(
    payload: PrinterPatch,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_shop_or_404(db, user)
    shop.printer_auto = payload.auto
    await db.commit()
    return PrinterOut(enabled=settings.feie_configured,
                      sn=shop.printer_sn, auto=shop.printer_auto)


@router.delete("/me/printer", response_model=PrinterOut)
async def unbind_my_printer(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_shop_or_404(db, user)
    if shop.printer_sn and settings.feie_configured:
        await cloud_print.unbind_printer(shop.printer_sn)
    shop.printer_sn = ""
    await db.commit()
    return PrinterOut(enabled=settings.feie_configured, sn="", auto=shop.printer_auto)


@router.post("/me/printer/test")
async def test_my_printer(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    if not settings.feie_configured:
        raise HTTPException(503, _FEIE_DISABLED)
    shop = await _my_shop_or_404(db, user)
    if not shop.printer_sn:
        raise HTTPException(422, "还没绑定云打印机")
    content = ("<CB>超级赞 测试页</CB><BR>"
               f"<C>{shop.name}</C><BR>"
               "--------------------------------<BR>"
               "看到这张小票,说明云打印一切正常。<BR>"
               "新订单支付成功后会自动出票。<BR>"
               "--------------------------------<BR>"
               "<C>平台只抽5% 账目公开可查</C>")
    try:
        await cloud_print.print_content(shop.printer_sn, content)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except httpx.HTTPError:
        raise HTTPException(502, "云打印服务暂时不可用,请稍后再试")
    return {"ok": True}


@router.post("/me/orders/{order_no}/print")
async def reprint_order(
    order_no: str,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """补打小票:自动出票失败、纸打完了、单据丢了,都从这里再打一张。"""
    if not settings.feie_configured:
        raise HTTPException(503, _FEIE_DISABLED)
    shop = await _my_shop_or_404(db, user)
    if not shop.printer_sn:
        raise HTTPException(422, "还没绑定云打印机")
    order = await db.scalar(select(Order).where(
        Order.order_no == order_no, Order.merchant_id == shop.id))
    if order is None:
        raise HTTPException(404, "订单不存在")
    try:
        await cloud_print.print_content(
            shop.printer_sn, cloud_print.build_ticket(order, shop.name))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except httpx.HTTPError:
        raise HTTPException(502, "云打印服务暂时不可用,请稍后再试")
    return {"ok": True}


@router.get("/me/finance/daily", response_model=list[DayStatOut])
async def finance_daily(
    days: int = 30,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """按日对账单:订单数、菜品流水、平台佣金、净收入。"""
    shop = await _my_shop_or_404(db, user)
    rows = await db.execute(
        DAILY_FINANCE_SQL, {"merchant_id": shop.id, "days": min(days, 90)}
    )
    return [
        DayStatOut(
            day=row.day,
            order_count=row.order_count,
            food_cents=row.food_cents,
            commission_cents=row.commission_cents,
            net_cents=row.net_cents,
        )
        for row in rows
    ]


@router.get("/me/finance/orders", response_model=list[FinanceOrderOut])
async def finance_orders(
    day: date,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """某一天的入账明细,逐单可查,和日汇总能对上。"""
    shop = await _my_shop_or_404(db, user)
    result = await db.scalars(
        select(MerchantEarning)
        .where(
            MerchantEarning.merchant_id == shop.id,
            text("date(created_at AT TIME ZONE 'Asia/Shanghai') = :day").bindparams(
                day=day
            ),
        )
        .order_by(MerchantEarning.created_at.desc())
        .limit(500)
    )
    return list(result)


@router.get("/me/finance/statement.csv")
async def finance_statement_csv(
    days: int = 30,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """对账单 CSV 导出:外卖入账/冲账 + 团购核销,按时间合并(透明三原则)。"""
    from ..models import Voucher, VoucherPurchase, VoucherPurchaseStatus

    shop = await _my_shop_or_404(db, user)
    since = datetime.now(timezone.utc) - timedelta(days=min(days, 90))
    earnings = (
        await db.scalars(
            select(MerchantEarning)
            .where(
                MerchantEarning.merchant_id == shop.id,
                MerchantEarning.created_at >= since,
            )
        )
    ).all()
    redeems = (
        await db.execute(
            select(VoucherPurchase, Voucher.title)
            .join(Voucher, Voucher.id == VoucherPurchase.voucher_id)
            .where(
                VoucherPurchase.merchant_id == shop.id,
                VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
                VoucherPurchase.redeemed_at >= since,
            )
        )
    ).all()

    def yuan(cents: int) -> str:
        return f"{cents / 100:.2f}"

    # 外卖行与团购行统一成 (时间, 单号, 类型, 应收, 佣金, 实收, 备注),按时间排
    lines = [
        (e.created_at, e.order_no,
         "外卖入账" if e.kind == EarningKind.earning else "外卖冲账",
         e.food_cents, e.commission_cents, e.net_cents,
         e.note.replace(",", ";").replace("\n", " "))
        for e in earnings
    ] + [
        (p.redeemed_at, p.purchase_no, "团购核销",
         p.sell_price_cents, p.commission_cents, p.net_cents,
         title.replace(",", ";"))
        for p, title in redeems
    ]
    lines.sort(key=lambda x: x[0])

    def generate():
        yield "﻿"  # BOM:Excel 直接打开不乱码
        yield "日期,单号,类型,应收金额(元),平台服务费(元),商家实收(元),备注\n"
        for at, no, kind, gross, comm, net, note in lines:
            day = at.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M")
            yield f"{day},{no},{kind},{yuan(gross)},{yuan(comm)},{yuan(net)},{note}\n"
        total_net = sum(x[5] for x in lines)
        total_comm = sum(x[4] for x in lines)
        yield f"合计,,,,{yuan(total_comm)},{yuan(total_net)},近{min(days, 90)}天(外卖+团购)\n"

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="statement-{shop.id}-{days}d.csv"'},
    )


# ---------- 店铺详情(点单页头部用) ----------
@router.get("/{merchant_id}", response_model=MerchantOut)
async def merchant_detail(merchant_id: int, db: AsyncSession = Depends(get_db)):
    """单店详情:比列表多算一个「月售」(近 30 天完成单数)。"""
    shop = await db.get(Merchant, merchant_id)
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "商家不存在")
    monthly = await db.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.merchant_id == merchant_id,
            Order.status == OrderStatus.COMPLETED,
            Order.created_at >= func.now() - text("interval '30 days'"),
            # 确认刷单的单不计入月售(资金结算照常,只影响运营口径)
            text("coalesce(risk_flags->>'status', '') != 'confirmed'"),
        )
    )
    out = MerchantOut.model_validate(shop)
    out.monthly_sales = monthly or 0
    return out


# ---------- 经营分析(只读统计,不做排名对比不制造焦虑) ----------

@router.get("/me/analytics")
async def my_analytics(
    days: int = 7,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """近 7/30 天经营分析。口径与对账一致:完成单;0 元赠品行不计销量金额。

    ①24 小时下单分布 ②菜品销量 TOP10(含估清损失估算)③客单价趋势
    ④复购率(窗口内下过 ≥2 单的用户占比)⑤配送/自取占比。
    """
    from datetime import datetime, timedelta, timezone

    if days not in (7, 30):
        raise HTTPException(422, "days 只支持 7 或 30")
    shop = await _my_shop_or_404(db, user)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(Order.items, Order.total_cents, Order.customer_id,
               Order.created_at, Order.pickup).where(
            Order.merchant_id == shop.id,
            Order.status == OrderStatus.COMPLETED,
            Order.created_at >= since))).all()

    hourly = [0] * 24
    dish_stat: dict[str, dict] = {}
    day_stat: dict[str, dict] = {}
    per_customer: dict[int, int] = {}
    pickup_n = delivery_n = 0
    for items, total, customer_id, created, pickup in rows:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        bj = created + timedelta(hours=8)
        hourly[bj.hour] += 1
        day = bj.strftime("%m-%d")
        d = day_stat.setdefault(day, {"orders": 0, "cents": 0})
        d["orders"] += 1
        d["cents"] += total
        per_customer[customer_id] = per_customer.get(customer_id, 0) + 1
        if pickup:
            pickup_n += 1
        else:
            delivery_n += 1
        for item in items or []:
            if item.get("price_cents", 0) <= 0:
                continue  # 0 元赠品行:后厨要备货,但不算销量金额
            s = dish_stat.setdefault(
                item["name"], {"qty": 0, "amount_cents": 0})
            s["qty"] += item.get("quantity", 0)
            s["amount_cents"] += (item.get("price_cents", 0)
                                  * item.get("quantity", 0))

    # 估清损失估算(粗口径,标注"估算"):今日售罄的菜,
    # 错过单量 ≈ 窗口日均销量 - 今日已卖(负数记 0)
    sold_out = {d.name: d for d in (await db.scalars(
        select(Dish).where(Dish.merchant_id == shop.id,
                           Dish.sold_out_today.is_(True)))).all()}
    today_bj = (datetime.now(timezone.utc)
                + timedelta(hours=8)).strftime("%m-%d")
    top = sorted(dish_stat.items(), key=lambda kv: -kv[1]["qty"])[:10]
    top_dishes = []
    for name, s in top:
        entry = {"name": name, "qty": s["qty"],
                 "amount_cents": s["amount_cents"],
                 "sold_out_today": name in sold_out}
        if name in sold_out:
            daily_avg = s["qty"] / days
            entry["missed_estimate"] = max(0, round(daily_avg))
        top_dishes.append(entry)

    trend = [{"date": day, "orders": d["orders"],
              "avg_cents": d["cents"] // d["orders"]}
             for day, d in sorted(day_stat.items())]
    repeat = sum(1 for n in per_customer.values() if n >= 2)
    return {
        "days": days,
        "orders": len(rows),
        "hourly": hourly,
        "top_dishes": top_dishes,
        "ticket_trend": trend,
        "repurchase_rate": (round(repeat / len(per_customer), 3)
                            if per_customer else 0.0),
        "pickup_orders": pickup_n,
        "delivery_orders": delivery_n,
        "today": today_bj,
    }


# ---------- 高峰备货(纯建议,不自动改库存) ----------

@router.get("/me/stocking")
async def my_stocking(
    meal: str = "",
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """备货建议:近 14 天同餐段销量 P80 vs 当前库存。meal 缺省按当前时刻。"""
    from datetime import datetime, timedelta, timezone

    from ..services.stocking import (
        MEAL_LABELS, current_meal, meal_suggestions, shortlist)
    shop = await _my_shop_or_404(db, user)
    if meal not in ("lunch", "dinner"):
        meal = current_meal(datetime.now(timezone.utc) + timedelta(hours=8))
    suggestions = await meal_suggestions(db, shop.id, meal)
    return {
        "meal": meal,
        "meal_label": MEAL_LABELS[meal],
        "suggestions": suggestions,
        "shortlist": shortlist(suggestions),
    }


@router.post("/me/dishes/batch-stock")
async def batch_stock(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """一键按建议补库存(可单菜调整)。补货自动解除估清,防「有货却显示售罄」。"""
    shop = await _my_shop_or_404(db, user)
    items = payload.get("items") or []
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise HTTPException(422, "items 需为 1-100 条 {dish_id, stock}")
    updated = 0
    for row in items:
        try:
            dish_id, stock = int(row["dish_id"]), int(row["stock"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "每条需包含整数 dish_id 与 stock")
        if not 0 <= stock <= 9999:
            raise HTTPException(422, "库存需在 0-9999 之间")
        dish = await db.scalar(select(Dish).where(
            Dish.id == dish_id, Dish.merchant_id == shop.id))
        if dish is None:
            raise HTTPException(422, f"菜品(id={dish_id})不是本店的")
        dish.stock = stock
        if stock > 0:  # 与手动补库存同口径:解除估清态
            dish.sold_out_today = False
            dish.stock_before_soldout = None
        updated += 1
    await db.commit()
    return {"updated": updated}


# ---------- 对账单导出(记账/贷款/报税都用得上) ----------

@router.get("/me/statement.csv")
async def my_statement_csv(
    month: str,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家月度对账单 CSV:逐单明细(含售后冲账负数行)+ 按日小计 + 合计。

    口径与钱包/平台税表完全同源(merchant_earnings 直接求和=净口径);
    带 BOM,Excel 直接打开;每天限导 10 次(防脚本滥用)。
    """
    import re as _re

    from fastapi.responses import StreamingResponse

    from ..models import MerchantEarning
    from ..redis_client import get_redis
    from .invoices import CN_TZ, _period_bounds_utc

    if not _re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "月份格式:YYYY-MM")
    shop = await _my_shop_or_404(db, user)
    redis = get_redis()
    key = f"stmt:{shop.id}:{month}:{__import__('datetime').date.today()}"
    n = await redis.incr(key)
    await redis.expire(key, 86400)
    if n > 10:
        raise HTTPException(429, "今天导出次数已达上限(10 次),明天再试")

    start, end = _period_bounds_utc(month)
    rows = (await db.scalars(
        select(MerchantEarning).where(
            MerchantEarning.merchant_id == shop.id,
            MerchantEarning.created_at >= start,
            MerchantEarning.created_at < end)
        .order_by(MerchantEarning.created_at))).all()

    def _y(cents: int) -> str:
        return f"{cents / 100:.2f}"

    def generate():
        yield "﻿"
        if shop.invoice_title:
            yield f"发票抬头:{shop.invoice_title},税号:{shop.invoice_tax_no}\n"
        yield f"{shop.name} {month} 对账单(与钱包同源;负数行=售后冲账)\n"
        yield "日期,单号,类型,应收(菜品+打包-满减),平台佣金,净额,备注\n"
        daily: dict[str, list[int]] = {}
        total_food = total_comm = total_net = 0
        for e in rows:
            day = e.created_at.astimezone(CN_TZ).strftime("%Y-%m-%d")
            kind = "入账" if e.kind.value == "earning" else "冲账"
            note = (e.note or "").replace(",", ";").replace("\n", " ")
            yield (f"{e.created_at.astimezone(CN_TZ):%Y-%m-%d %H:%M},"
                   f"{e.order_no},{kind},{_y(e.food_cents)},"
                   f"{_y(e.commission_cents)},{_y(e.net_cents)},{note}\n")
            d = daily.setdefault(day, [0, 0, 0])
            d[0] += e.food_cents
            d[1] += e.commission_cents
            d[2] += e.net_cents
            total_food += e.food_cents
            total_comm += e.commission_cents
            total_net += e.net_cents
        yield "\n按日小计,,,应收,佣金,净额,\n"
        for day in sorted(daily):
            f, c, nn = daily[day]
            yield f"{day},,,{_y(f)},{_y(c)},{_y(nn)},\n"
        yield (f"合计,,({len(rows)} 行),{_y(total_food)},"
               f"{_y(total_comm)},{_y(total_net)},净口径可直接记账\n")

    return StreamingResponse(
        generate(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename=statement-{month}.csv"})
