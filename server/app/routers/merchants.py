from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import mimetypes
import secrets

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
    StayOrder,
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
    MerchantMeOut,
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
      AND m.biz_type = 'food'
      {category_clause}
      {filter_clause}
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
    min_rating: float | None = Query(default=None, ge=0, le=5),
    has_promo: bool = False,          # 有满减或满赠
    max_min_order_cents: int | None = Query(default=None, ge=0, le=100_000),
    db: AsyncSession = Depends(get_db),
):
    """附近营业中的商家(带月售),sort=distance|rating|sales,category 按品类筛选。

    筛选与 /merchants/search 同口径:min_rating 评分下限、has_promo 有优惠、
    max_min_order_cents 起送价上限。首页和搜索页给的是同一套条件,
    用户不用在两个地方学两遍。距离上限直接用已有的 radius_m。
    """
    if sort not in _SORTS:
        raise HTTPException(422, "sort 仅支持 distance / rating / sales")
    if category is not None and category not in MERCHANT_CATEGORIES:
        raise HTTPException(422, "未知品类")

    # 筛选条件三端共用:拼进 SQL 的只有固定串,取值一律走绑定参数
    filters: list[str] = []
    filter_params: dict = {}
    if min_rating is not None:
        filters.append("AND coalesce(m.rating_sum::float"
                       " / NULLIF(m.rating_count, 0), 0) >= :min_rating")
        filter_params["min_rating"] = min_rating
    if has_promo:
        filters.append("AND (m.promo_rules <> '[]'::jsonb"
                       " OR m.gift_rules <> '[]'::jsonb)")
    if max_min_order_cents is not None:
        filters.append("AND m.min_order_cents <= :max_min_order")
        filter_params["max_min_order"] = max_min_order_cents

    if lat is not None and lng is not None:
        rows = await db.execute(
            text(_NEARBY_SQL_TMPL.format(
                order_by=_SORTS[sort],
                category_clause=(
                    "AND m.category = :category" if category else ""),
                filter_clause="\n      ".join(filters))),
            {"lat": lat, "lng": lng, "radius_m": radius_m,
             **({"category": category} if category else {}),
             **filter_params},
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
    # 无定位兜底:同样要认筛选条件,否则用户一关定位筛选就静默失效
    query = select(Merchant).where(
        Merchant.is_open.is_(True), Merchant.status == MerchantStatus.approved,
        Merchant.biz_type == "food")
    if category:
        query = query.where(Merchant.category == category)
    if min_rating is not None:
        query = query.where(
            func.coalesce(Merchant.rating_sum
                          / func.nullif(Merchant.rating_count, 0), 0)
            >= min_rating)
    if has_promo:
        query = query.where(or_(Merchant.promo_rules != [],
                                Merchant.gift_rules != []))
    if max_min_order_cents is not None:
        query = query.where(Merchant.min_order_cents <= max_min_order_cents)
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
             "m.biz_type = 'food'",  # 酒店走 /stays 频道,不混进外卖搜索
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
            Merchant.biz_type == "food",
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
    """提交开店申请,进入待审核。证照是硬要求(监管留存影像),按业态分叉:

    餐饮 = 食品经营许可证;酒店 = 营业执照 + 特种行业许可证(旅馆业,公安核发)。
    """
    if payload.biz_type == "hotel":
        if not payload.license_no.strip():
            raise HTTPException(422, "请填写营业执照注册号")
        if not payload.license_image_url.strip():
            raise HTTPException(422, "请上传营业执照照片")
        if payload.hotel is None or not payload.hotel.special_license_no.strip():
            raise HTTPException(422, "请填写特种行业许可证号(旅馆业)")
        if not payload.hotel.special_license_image_url.strip():
            raise HTTPException(422, "请上传特种行业许可证照片")
    else:
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
        **payload.model_dump(exclude={"hotel"}),
    )
    # 所在城市:坐标逆地理解析(天地图;失败留空,管理后台人工补填)
    from ..services.geo_city import city_of
    shop.city = await city_of(payload.lat, payload.lng)
    db.add(shop)
    await db.flush()
    if payload.biz_type == "hotel":
        from ..models import HotelProfile
        db.add(HotelProfile(merchant_id=shop.id,
                            **payload.hotel.model_dump()))
    await db.commit()
    await db.refresh(shop)
    return shop


@router.get("/me", response_model=MerchantMeOut)
async def my_shop(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    # 店主或店员都能看店(店员据此听单接单);viewer_is_staff 供客户端隐藏敏感入口
    from ..services.staff import operable_shop
    shop, is_owner = await operable_shop(db, user)
    if shop is None:
        raise HTTPException(404, "还没开店")
    out = MerchantMeOut.model_validate(shop)
    out.viewer_is_staff = not is_owner
    # 证照只给店主(驳回后回填重提表单用);店员清空 —— 资质材料不是接单要用的
    if not is_owner:
        out.license_no = ""
        out.license_image_url = ""
    elif shop.biz_type == "hotel":
        from ..models import HotelProfile
        hp = await db.scalar(
            select(HotelProfile).where(HotelProfile.merchant_id == shop.id))
        if hp is not None:
            out.special_license_no = hp.special_license_no
            out.special_license_image_url = hp.special_license_image_url
            out.hygiene_image_url = hp.hygiene_image_url
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
    # 食安停业期间商家自己开不回来 —— 否则"暂停营业待人工复核"只是一句话
    if changes.get("is_open") and shop.food_safety_hold:
        raise HTTPException(
            403, "因食品安全问题暂停营业中,完成整改后联系平台客服复核恢复")
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
            # 赠品不能是套餐:赠品走的是独立的一条扣库存语句(orders.py),
            # 没有子项循环 —— 赠出去只扣套餐自己,子项静默漏扣,
            # 小票上也只有套餐名,后厨不知道要做什么
            if dish.combo_items:
                raise HTTPException(422, "赠品不能是套餐,请直接选一道单品")
            rule["name"] = dish.name

    # 主证照与酒店第二证照同一口径:只有**被驳回重提**时可改,
    # 平时资质变更走客服人工核验 —— 通过审核的店随手改证号不重审,
    # 等于让「亮照公示」页给假证号背书;改 image_url 还能把无鉴权的
    # 公示出口指到私密桶里的任意文件
    if (("license_no" in changes or "license_image_url" in changes)
            and shop.status != MerchantStatus.rejected):
        raise HTTPException(403, "资质变更需平台核验,请联系客服")

    # 酒店第二证照(特种行业许可证/卫生许可证)只在**被驳回重提**时随表单更新;
    # 平时资质变更走客服人工核验(见 stays.update_hotel_profile 的口径)
    hotel_fields = {
        k: changes.pop(k)
        for k in ("special_license_no", "special_license_image_url",
                  "hygiene_image_url")
        if k in changes
    }
    if hotel_fields:
        if shop.biz_type != "hotel":
            raise HTTPException(422, "特种行业许可证是酒店业态的资质项")
        if shop.status != MerchantStatus.rejected:
            raise HTTPException(403, "资质变更需平台核验,请联系客服")
        from ..models import HotelProfile
        hp = await db.scalar(
            select(HotelProfile).where(HotelProfile.merchant_id == shop.id))
        if hp is None:
            raise HTTPException(404, "酒店资料不存在")
        for field, value in hotel_fields.items():
            setattr(hp, field, value)

    info_changed = bool(hotel_fields) or any(k != "is_open" for k in changes)
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
        # 与用户端菜单同口径:分类顺序按该分类首道菜的建立顺序,组内按 sort
        .order_by(func.min(Dish.id).over(partition_by=Dish.category),
                  Dish.sort, Dish.id)
    )
    dishes = list(result)
    # 带上近 30 天销量:商家端销量榜/滞销提示的数据源
    sales_rows = await db.execute(_DISH_SALES_SQL, {"merchant_id": shop.id})
    sales = {row.dish_id: row.sold for row in sales_rows}
    outs = []
    combo_ref = await _combo_reference(db, shop.id, dishes)
    now_hhmm = datetime.now(CN_TZ).strftime("%H:%M")
    for dish in dishes:
        out = DishOut.model_validate(dish)
        out.monthly_sales = sales.get(dish.id, 0)
        _fill_combo_and_window(out, dish, combo_ref, now_hhmm)
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
        select(Dish)
        .where(Dish.merchant_id == merchant_id, Dish.is_on_sale.is_(True))
        # 分类之间的先后 = 该分类第一道菜的建立顺序(与加 sort 之前的
        # 行为一致)。**不能直接按 category 字符串排** —— 未分类的菜
        # category 是空串,一排就把"其他"顶到分类栏第一个并默认选中。
        # 组内再按 sort(商家排的顺序,用户端照着看)
        .order_by(func.min(Dish.id).over(partition_by=Dish.category),
                  Dish.sort, Dish.id)
    )
    dishes = list(result)
    sales_rows = await db.execute(_DISH_SALES_SQL, {"merchant_id": merchant_id})
    sales = {row.dish_id: row.sold for row in sales_rows}
    outs = []
    combo_ref = await _combo_reference(db, merchant_id, dishes)
    now_hhmm = datetime.now(CN_TZ).strftime("%H:%M")
    for dish in dishes:
        out = DishOut.model_validate(dish)
        out.monthly_sales = sales.get(dish.id, 0)
        _fill_combo_and_window(out, dish, combo_ref, now_hhmm)
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


async def _combo_reference(db: AsyncSession, merchant_id: int,
                           dishes: list) -> dict[int, dict]:
    """套餐子项的名字/单价/可售状态。子项可能已下架或估清(菜单查询只取在售),
    所以单独查一次,不从 dishes 里捞 —— 否则套餐里少一样东西却不说。"""
    ids = {it.get("dish_id") for d in dishes for it in (d.combo_items or [])}
    ids.discard(None)
    if not ids:
        return {}
    rows = (await db.execute(
        select(Dish.id, Dish.name, Dish.price_cents, Dish.stock,
               Dish.is_on_sale, Dish.sold_out_today).where(
            Dish.id.in_(ids), Dish.merchant_id == merchant_id))).all()
    return {r[0]: {"name": r[1], "price": r[2], "stock": r[3],
                   "on_sale": r[4], "sold_out": r[5]} for r in rows}


def _fill_combo_and_window(out, dish, combo_ref: dict, now_hhmm: str) -> None:
    """填套餐明细与供应时段的派生字段。

    **套餐的可售量由子项决定**:套餐自己的 stock 是虚的,真正扣的是子项。
    子项估清/下架而套餐还显示"有货",用户会一路加购到结算才吃 409。
    这里把 stock 收敛成"按子项最多还能配几份",让既有的售罄展示逻辑
    自动生效(客户端不用改)。
    """
    if dish.combo_items:
        detail, original = [], 0
        available = out.stock
        for it in dish.combo_items:
            ref = combo_ref.get(it.get("dish_id"))
            if ref is None:
                available = 0   # 子项被删了,这个套餐配不出来
                continue
            qty = max(int(it.get("quantity", 1)), 1)
            detail.append({"name": ref["name"], "quantity": qty})
            original += ref["price"] * qty
            if not ref["on_sale"] or ref["sold_out"]:
                available = 0
                out.sold_out_today = out.sold_out_today or ref["sold_out"]
            else:
                available = min(available, ref["stock"] // qty)
        out.combo_dishes = detail
        out.combo_original_cents = original
        out.stock = max(available, 0)
    if dish.serve_window:
        from ..services.flags import in_hhmm_range
        out.servable_now = in_hhmm_range(dish.serve_window, now_hhmm)


async def _validate_combo(db: AsyncSession, merchant_id: int, items: list,
                          self_id: int | None = None) -> None:
    """套餐子项校验:必须是本店的、非套餐的菜,且不能把自己装进自己。

    禁套娃不是洁癖:套餐嵌套会让下单时的库存扣减变成递归,
    一个环就能把下单请求打挂。
    """
    ids = [it.dish_id for it in items]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "套餐里同一道菜只能出现一次(用份数表示多份)")
    if self_id is not None and self_id in ids:
        raise HTTPException(422, "套餐不能包含它自己")
    rows = (await db.execute(
        select(Dish.id, Dish.combo_items).where(
            Dish.id.in_(ids), Dish.merchant_id == merchant_id))).all()
    found = {r[0] for r in rows}
    missing = set(ids) - found
    if missing:
        raise HTTPException(422, "套餐子项必须是本店已有的菜品")
    nested = [r[0] for r in rows if r[1]]
    if nested:
        raise HTTPException(422, "套餐里不能再放套餐")
    # 反向也要拦:**先把 B 当子项放进套餐 C,再把 B 自己改成套餐**,
    # 一样能造出两层嵌套。扣库存循环是非递归的,不会打挂,
    # 但第二层子项会被静默漏扣,后厨也不知道要做它
    if self_id is not None:
        parent = await db.scalar(
            select(Dish.name).where(
                Dish.merchant_id == merchant_id,
                Dish.combo_items.contains([{"dish_id": self_id}])))
        if parent:
            raise HTTPException(
                422, f"这道菜是套餐「{parent}」的组成部分,不能再做成套餐")


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
    # 描述同样是面向用户的自由文本,和店铺公告/评价一个口径过审 ——
    # 全站每一处自由文本都过 guard_text,这里漏掉就是引流话术的入口
    if payload.description:
        await guard_text(db, payload.description, "菜品描述")
    if payload.combo_items:
        await _validate_combo(db, shop.id, payload.combo_items)
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
    # **显式传 null 的非空列要归一化成空值**。JSONB 列的 none_as_null
    # 默认是 False —— 写进去的是 JSON `null` 而不是 SQL NULL,NOT NULL
    # 约束拦不住;读回来 Python 是 None,DishOut 校验直接抛,
    # 结果是**整店菜单 500**(顾客点不了单,商家也在列表里找不到这道菜自救)。
    # 只有 daily_stock / flash_* 的 None 是有语义的(关闭该功能)
    _EMPTY_FOR_NULL = {
        "badges": [], "options": [], "combo_items": [],
        "name": None, "category": "", "description": "",
        "image_url": "", "serve_window": "",
    }
    for field, empty in _EMPTY_FOR_NULL.items():
        if changes.get(field, "") is None:
            if empty is None:      # 名字不能被清空
                raise HTTPException(422, "菜品名称不能为空")
            changes[field] = empty
    from ..services.moderation import guard_text, submit_images
    if changes.get("name"):
        await guard_text(db, changes["name"], "菜品名称")
    if changes.get("description"):
        await guard_text(db, changes["description"], "菜品描述")
    if changes.get("combo_items"):
        await _validate_combo(db, dish.merchant_id, payload.combo_items or [],
                              self_id=dish.id)
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
    # 账号按角色分立:店员用的是对方的商家端账号(商家端 App 登录即自动注册)
    target = await db.scalar(select(User).where(
        User.phone == phone, User.role == UserRole.merchant))
    if target is None:
        raise HTTPException(404, "该手机号还没有商家端账号,请对方先用商家端 App 登录一次")
    if target.id == user.id:
        raise HTTPException(409, "不能把自己加为店员")
    owns = await db.scalar(select(Merchant).where(Merchant.owner_id == target.id))
    if owns is not None:
        raise HTTPException(409, "对方已是某店店主,不能作为子账号")
    existing = await db.scalar(
        select(MerchantStaff).where(MerchantStaff.user_id == target.id))
    if existing is not None:
        raise HTTPException(409, "对方已是某店店员")
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
        id=b.id, name=b.name, trigger=b.trigger,
        threshold_cents=b.min_spend_cents,
        off_cents=b.amount_cents, total=b.total, issued=b.issued,
        per_user_limit=b.per_user_limit, valid_days=b.valid_days,
        active=b.active)


@router.post("/me/coupon-batches", response_model=ShopCouponBatchOut)
async def create_shop_coupon_batch(
    payload: ShopCouponBatchIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家自建券批次。成本 100% 商家承担(下单走满减同口径),
    平台佣金按券后实收计——你让利,平台跟着少收,与满减一致。

    trigger=shop 是顾客主动领;referral/birthday/winback 是系统按条件自动发,
    这三类原先由平台掏钱,#115 起归位给商家。同一家店同一 trigger
    只保留一个启用中的批次(建新的会停掉旧的),免得两个批次互相打架。
    """
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    if payload.trigger != "shop":
        # 自动发放类:同店同类型只留一个启用中的
        await db.execute(
            update(CouponBatch)
            .where(CouponBatch.merchant_id == shop.id,
                   CouponBatch.trigger == payload.trigger,
                   CouponBatch.active.is_(True))
            .values(active=False))
    batch = CouponBatch(
        name=payload.name, trigger=payload.trigger, merchant_id=shop.id,
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


@router.get("/me/promo")
async def my_promo_material(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """推广物料:店铺短码 + 海报要印的内容。

    零补贴模式下,商家自愿推广是唯一能规模化的获客渠道——他们在这里
    每单多赚十几个点,有动力把老客带过来。平台只提供物料,不出钱。

    海报由商家端离屏渲染(照 share_card 的做法),这里只给数据。
    """
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    # 懒生成:第一次要用时才建号,不给可能永远不用的店占号段
    if not shop.short_code:
        for _ in range(10):
            code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
                           for _ in range(6))  # 去掉易混的 I/O/0/1
            if not await db.scalar(select(Merchant.id).where(
                    Merchant.short_code == code)):
                shop.short_code = code
                await db.commit()
                break
        else:
            raise HTTPException(500, "店铺码生成失败,请重试")
    # 海报上是否印"扫码领券":只有真有在领的店铺券才印,不做空头承诺
    coupon = await db.scalar(
        select(CouponBatch).where(
            CouponBatch.merchant_id == shop.id,
            CouponBatch.trigger == "shop",
            CouponBatch.active.is_(True),
            CouponBatch.issued < CouponBatch.total)
        .order_by(CouponBatch.amount_cents.desc()).limit(1))
    return {
        "short_code": shop.short_code,
        "url": f"{settings.public_base_url}/s/{shop.short_code}",
        "shop_name": shop.name,
        # 费率取这家店的真实值:阶梯佣金下可能已经降到 4.5%,别写死 5%
        "commission_rate": float(shop.commission_rate),
        "coupon_off_cents": coupon.amount_cents if coupon else 0,
        "coupon_threshold_cents": coupon.min_spend_cents if coupon else 0,
    }


@router.get("/me/winback")
async def my_winback_overview(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """老客召回概览(#117):这家店有多少人好久没来了。

    只给计数,不给任何顾客身份信息——商家看不到是谁、手机号、更看不到
    能导出的名单。要召回就建一批 winback 券,平台按名单发,券钱商家出。
    这是刻意的:名单一旦落到商家手里就再也收不回来了。

    召回本身也不由商家逐个触发——那等于把骚扰权交出去。系统每天按
    每人每店每月一次、全局每周两条的频控自动发。
    """
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")

    from ..services.marketing import dormant_customer_ids

    # 30 天没来的(实际召回口径)与 90 天没来的(参考,更冷)
    dormant30 = len(await dormant_customer_ids(db, shop.id, dormant_days=30))
    dormant90 = len(await dormant_customer_ids(db, shop.id, dormant_days=90))
    # 半年内在本店下过完成单的总人数,给个分母
    total = await db.scalar(
        select(func.count(func.distinct(Order.customer_id))).where(
            Order.merchant_id == shop.id,
            Order.status == "completed",
            Order.created_at >= datetime.now(timezone.utc)
            - timedelta(days=180))) or 0

    batch = await db.scalar(
        select(CouponBatch).where(
            CouponBatch.merchant_id == shop.id,
            CouponBatch.trigger == "winback",
            CouponBatch.active.is_(True))
        .order_by(CouponBatch.created_at.desc()).limit(1))
    return {
        "dormant_30d": dormant30,
        "dormant_90d": dormant90,
        "customers_180d": total,
        "batch": _shop_batch_out(batch) if batch else None,
    }


@router.get("/by-code/{code}")
async def merchant_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """短码解析成店铺(落地页与 App 深链共用)。"""
    shop = await db.scalar(select(Merchant).where(
        Merchant.short_code == code.upper()))
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "店铺不存在或已下架")
    return {"id": shop.id, "name": shop.name, "address": shop.address,
            "description": shop.description, "logo_url": shop.logo_url}


@router.get("/{merchant_id}/coupons", response_model=list[ClaimableCouponOut])
async def claimable_shop_coupons(
    merchant_id: int,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """用户在某店可领的店铺券(含已领数与是否可再领)。

    只列 trigger=shop 的:referral/birthday/winback 是系统按条件自动发的,
    列在这里会变成"人人可主动领",商家的预算立刻被薅空。
    """
    batches = (await db.scalars(
        select(CouponBatch).where(
            CouponBatch.merchant_id == merchant_id,
            CouponBatch.trigger == "shop",
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


@router.get("/me/trend")
async def my_trend(
    weeks: int = 8,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """经营趋势与流失诊断(#151/#152)。

    ## 为什么按周不按天

    外卖有很强的**周内节律**(周末 ≠ 周三)。按天做环比会把节律当成趋势,
    得出「周一生意变差了」这种废话 —— 每个周一都比周日差,那不是趋势。

    ## 诊断:单量掉了,掉在哪一环

    商家真正的问题不是「这是你的数据」,是「我该改什么」。
    所以除了趋势,还把可归因的流失拆开:拒单、歇业、缺货、出餐超时。

    每条都标 `estimated: true` —— 这些是**估算**,不是精确值。
    给一个精确到个位的假数字,比给区间更坏。
    """
    shop = await _my_shop_or_404(db, user)
    n = min(max(weeks, 2), 26)

    # 按自然周聚合(北京时间)。date_trunc 用 UTC 会把周界切在周日早八点,
    # 对商家来说那是周日营业中,不是新的一周
    rows = (await db.execute(text("""
        SELECT date_trunc('week', created_at AT TIME ZONE 'Asia/Shanghai') AS wk,
               count(*) AS orders,
               coalesce(sum(food_cents), 0) AS food,
               count(DISTINCT customer_id) AS customers
        FROM orders
        WHERE merchant_id = :mid AND status = 'completed'
          AND created_at >= now() - make_interval(days => :days)
        GROUP BY wk ORDER BY wk
    """), {"mid": shop.id, "days": n * 7})).all()

    by_week = {r[0].date(): r for r in rows}

    # **把没有订单的周补齐**。GROUP BY 只会返回有单的周,直接拿去画折线,
    # 图会把 6/22 和 7/13 之间的两个空周**连成一条直线** ——
    # 商家看到的是"这几周挺平稳",实际是"这几周一单没有"。
    # 补 0 是如实的:那几周确实是 0 单,不是"没数据"。
    # 本周还没过完。周一(北京时间)是周界
    today_bj = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    this_week = today_bj - timedelta(days=today_bj.weekday())

    series: list[dict] = []
    if rows:
        wk = rows[0][0].date()
        last = rows[-1][0].date()
        while wk <= last:
            r = by_week.get(wk)
            orders = r[1] if r else 0
            food = int(r[2]) if r else 0
            series.append({
                "week": wk.isoformat(),
                "orders": orders,
                "food_cents": food,
                "customers": r[3] if r else 0,
                # 客单价:没有单就不给 0,给 None —— 0 会被读成"客单价跌到零",
                # 而实际是"这周没单,客单价无从谈起"。图上应该断线,不是落到 0
                "avg_cents": int(food // orders) if orders else None,
                # 本周还没过完,单量天然偏低 —— 图上要标出来
                "partial": wk >= this_week,
            })
            wk += timedelta(days=7)

    def delta(cur, prev):
        """环比。前一周为 0 时不给百分比 —— 除零和「增长 ∞%」都没意义。"""
        if prev in (None, 0) or cur is None:
            return None
        return round((cur - prev) / prev * 100, 1)

    # **环比只拿完整的周比。**
    #
    # 直接拿 series[-1] 比 series[-2] 是个陷阱:series[-1] 是本周,还没过完。
    # 周二拿两天的数据去比上周整七天,每个周一、周二商家都会看到
    # 「单量比上周少了 70%」然后白慌一场 —— 这跟"按天比会把周内节律当趋势"
    # 是同一类错误,只是换了个尺度。
    #
    # 所以比的是**最近两个完整周**,本周照常画在图上但标成 partial。
    compare = None
    full = [w for w in series if not w["partial"]]
    if len(full) >= 2:
        a, b = full[-1], full[-2]
        compare = {
            "week": a["week"],
            "prev_week": b["week"],
            "orders": {"cur": a["orders"], "prev": b["orders"],
                       "pct": delta(a["orders"], b["orders"])},
            "food_cents": {"cur": a["food_cents"], "prev": b["food_cents"],
                           "pct": delta(a["food_cents"], b["food_cents"])},
            "avg_cents": {"cur": a["avg_cents"], "prev": b["avg_cents"],
                          "pct": delta(a["avg_cents"], b["avg_cents"])},
            "customers": {"cur": a["customers"], "prev": b["customers"],
                          "pct": delta(a["customers"], b["customers"])},
        }

    # ---- 流失诊断:把已有信号串成解释 ----
    #
    # 归因**不猜 cancel_reason 的文本** —— 那是自由文本(「牛肉卖完了,抱歉」
    # 这种商家随手写的),按关键词分类今天能对、明天商家换个说法就错。
    # 用 order_events 的结构化信号:
    #   - actor_role='merchant'         → 商家主动拒单
    #   - actor_role='system' 且 from='paid' → 商家一直没接,系统超时替他取消
    #     (停在 paid 说明这单商家连看都没看,这才是最该让他知道的一类)
    diag = (await db.execute(text("""
        SELECT
          count(*) FILTER (WHERE e.actor_role = 'merchant')          AS rejected,
          count(*) FILTER (WHERE e.actor_role = 'system'
                             AND e.from_status = 'paid')             AS timeout
        FROM order_events e JOIN orders o ON o.id = e.order_id
        WHERE o.merchant_id = :mid
          AND e.to_status = 'cancelled'
          AND e.created_at >= now() - interval '7 days'
    """), {"mid": shop.id})).first()

    late = await db.scalar(text("""
        SELECT count(*) FROM orders
        WHERE merchant_id = :mid AND status = 'completed' AND ready_late
          AND created_at >= now() - interval '7 days'
    """), {"mid": shop.id})

    # 用 sold_out_today 而**不是** is_on_sale=false:后者包含商家主动永久
    # 下架的菜(换季、停售),那是正常菜单管理不是流失原因。
    # 今天卖光的菜才是"你还想卖但顾客搜不到"
    sold_out = await db.scalar(text("""
        SELECT count(*) FROM dishes
        WHERE merchant_id = :mid AND sold_out_today = true
    """), {"mid": shop.id})

    causes = []
    if diag and diag[0]:
        causes.append({"key": "rejected", "name": "商家拒单",
                       "orders": int(diag[0]), "estimated": False,
                       "hint": "拒单会直接丢掉这一单,且顾客大概率不再回来"})
    if diag and diag[1]:
        causes.append({"key": "timeout", "name": "超时未接单",
                       "orders": int(diag[1]), "estimated": False,
                       "hint": "这些单你还没点过就被系统取消了 —— "
                               "开着提示音,或在「店铺」里把自动接单打开"})
    if late:
        causes.append({"key": "late", "name": "出餐超时",
                       "orders": int(late), "estimated": False,
                       "hint": "超时的安抚券由平台承担,但顾客的体验损失在你这边"})
    if sold_out:
        causes.append({"key": "sold_out", "name": "菜品下架/售罄",
                       "dishes": int(sold_out), "estimated": True,
                       "hint": "下架的菜顾客搜不到;主力菜下架影响最大"})

    return {
        "weeks": series,
        "compare": compare,
        "causes": causes,
        "note": "按自然周聚合(北京时间)。外卖周内节律强,"
                "按天做环比会把节律当成趋势。",
        "estimate_note": "标了「估算」的条目是根据现有信号推算的,不是精确值。",
    }


@router.get("/me/prep-time")
async def my_prep_time(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """我的实测出餐时长(#150)。

    ## 为什么必须有这个

    在此之前链路是断的:商家在店铺设置里**自己填**「承诺出餐时长」、没人核;
    骑手抢单看到的等待预期已经用上**实测 P80**;超时赔付**由平台承担**;
    而商家**零反馈** —— 他不知道自己实际比承诺慢多少,
    更不知道这让平台掏了多少钱。

    **平台掏钱、商家无感、问题不改。** 这个闭环不通,治理就无从谈起。

    ## 红线(承接 #144)

    这个数**只用于**:给商家反馈、给骑手更准的等待预期、给用户更准的 ETA。

    **不用于**给商家排名、扣分、或影响用户端曝光 ——
    一旦分数影响生意,商家就会开始为分数经营(比如提前点「出餐」而实际没好),
    数据反而失真。同品类中位数是**参照系,不是排名**。
    """
    from ..services import prep_time

    shop = await _my_shop_or_404(db, user)
    stat = await prep_time.stat_for(db, shop.id)

    # 同品类参照系:取同品类其他店的 P50 中位数。
    # **不返回名次、不返回店名** —— 只给一个「大家大概多久」的参照
    peer_ids = [r for r in (await db.scalars(
        select(Merchant.id).where(
            Merchant.category == shop.category,
            Merchant.id != shop.id,
            Merchant.status == MerchantStatus.approved).limit(80)))]
    peer_median = None
    if peer_ids:
        peers = await prep_time.stats_for(db, peer_ids)
        vals = sorted(x.p50 for x in peers.values()
                      if x.enough and x.p50 is not None)
        if vals:
            peer_median = round(vals[len(vals) // 2], 1)

    promised = shop.promise_ready_minutes
    gap = None
    if stat.enough and stat.p80 is not None:
        # 商家最该看到的一个数:实际(P80)比承诺慢多少
        gap = round(stat.p80 - promised, 1)

    # 样本不足时**一个分位数都不给**。3 单算出来的 P80 是噪声,
    # 而商家会拿它去跟承诺值比、去改后厨流程 —— 给一个假装精确的数
    # 比不给更坏。这跟 prep_time 自己的契约(MIN_SAMPLES)是一致的:
    # 那边样本不足就回退商家自报值,这边就不该把生数据端出来
    def q(v: float | None) -> float | None:
        return None if (v is None or not stat.enough) else round(v, 1)

    return {
        "samples": stat.samples,
        "enough": stat.enough,
        "p50": q(stat.p50),
        "p80": q(stat.p80),
        "p95": q(stat.p95),
        "promised_minutes": promised,
        # 正数 = 实际比承诺慢;负数 = 比承诺快
        "gap_minutes": gap,
        "peer_median_p50": peer_median,
        "window_days": prep_time.WINDOW_DAYS,
        "min_samples": prep_time.MIN_SAMPLES,
        "note": ("样本还少,下面的数只作参考;骑手看到的等待预期仍用你填的承诺值"
                 if not stat.enough else
                 "骑手抢单时看到的等待预期用的是这里的 P80"),
        "never_used_for": "出餐时长不用于给商家排名、不作为扣分依据、"
                          "不影响你在用户端的曝光。同品类中位数是参照系,不是排名。",
    }


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
# + 团购核销净额 + 住宿净额(离店结算/取消扣款/noshow 首晚,net 落在 stay_orders)
# - 提现(冻结中+已打款)。与骑手钱包同一套语义和 T+1 打款流程。

# 住宿资金已落定的状态(net_cents 生效):离店/取消(扣款部分)/未入住(首晚)
_STAY_SETTLED = ("completed", "cancelled", "noshow")


async def _stay_net(db: AsyncSession, merchant_id: int) -> int:
    from ..state_machine import StayOrderStatus
    return await db.scalar(
        select(func.coalesce(func.sum(StayOrder.net_cents), 0)).where(
            StayOrder.merchant_id == merchant_id,
            StayOrder.status.in_([StayOrderStatus(s) for s in _STAY_SETTLED]),
        )
    )


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
    earned = food_net + voucher_net + await _stay_net(db, shop.id)
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
    before: str | None = None,
    #: 与 before 同一行的 id。**两个一起传才是正确的分页** ——
    #: 见下面对"同秒多行会被整组跳过"的说明
    before_id: int | None = None,
    limit: int = 200,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """某一天的入账明细,逐单可查,和日汇总能对上。

    **游标分页**:before 传上一页最后一条的 created_at(ISO),不传取最新一页。

    老口径是写死 limit(500) 不分页 —— 一天入账超过 500 条的商家
    (每单可能产生入账/冲账/调整多行,忙店很容易到)看到的明细**加不出日汇总**,
    而平台的招牌就是「每一单的账都可查」。实测演示店一天 545 条时就对不上了。
    """
    limit = max(1, min(limit, 500))
    shop = await _my_shop_or_404(db, user)
    query = (
        select(MerchantEarning)
        .where(
            MerchantEarning.merchant_id == shop.id,
            text("date(created_at AT TIME ZONE 'Asia/Shanghai') = :day").bindparams(
                day=day
            ),
        )
        .order_by(MerchantEarning.created_at.desc(), MerchantEarning.id.desc())
        .limit(limit)
    )
    if before:
        # **游标必须带全排序键。**
        #
        # 排序是 (created_at DESC, id DESC) 两列,而老游标只带 created_at
        # 并用严格 `<` —— 页边界落在同一秒的多行中间时,
        # 这一秒剩下的行会被**整组跳过**。
        #
        # 实测演示库:一天 1030 行入账里同秒最多 9 行,翻页只取到 1029 行,
        # 漏掉的恰好是一条 -¥30 的冲账 —— 于是商家看到的明细
        # **比他实际到手的钱多 ¥30**。对账页漏行比慢更严重。
        #
        # 兼容老调用方:只传 created_at 时退化为原行为(仍可能漏,
        # 但不会更糟);带上 before_id 才是正确的 keyset 分页。
        try:
            cursor = datetime.fromisoformat(before)
        except ValueError:
            raise HTTPException(422, "分页游标格式不对")
        if before_id is not None:
            query = query.where(or_(
                MerchantEarning.created_at < cursor,
                and_(MerchantEarning.created_at == cursor,
                     MerchantEarning.id < before_id),
            ))
        else:
            query = query.where(MerchantEarning.created_at < cursor)
    result = await db.scalars(query)
    return list(result)


@router.get("/me/finance/statement.csv")
async def finance_statement_csv(
    days: int = 30,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """对账单 CSV 导出:外卖入账/冲账 + 团购核销 + 住宿,按时间合并(透明三原则)。"""
    from ..models import Voucher, VoucherPurchase, VoucherPurchaseStatus
    from ..state_machine import StayOrderStatus

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

    stay_kind = {StayOrderStatus.COMPLETED: "住宿离店",
                 StayOrderStatus.CANCELLED: "住宿取消扣款",
                 StayOrderStatus.NOSHOW: "住宿未入住"}
    stays = (
        await db.scalars(
            select(StayOrder).where(
                StayOrder.merchant_id == shop.id,
                StayOrder.status.in_(list(stay_kind)),
                StayOrder.net_cents != 0,  # 全额退的取消没有资金流,不进对账
                func.coalesce(StayOrder.completed_at, StayOrder.cancelled_at)
                >= since,
            )
        )
    ).all()

    def yuan(cents: int) -> str:
        return f"{cents / 100:.2f}"

    # 外卖/团购/住宿行统一成 (时间, 单号, 类型, 应收, 佣金, 实收, 备注),按时间排
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
    ] + [
        (o.completed_at or o.cancelled_at, o.order_no,
         # 负净额 = 到店无房违约金赔付(商家承担,平台分文不取)
         "住宿违约金赔付" if o.net_cents < 0 else stay_kind[o.status],
         o.total_cents, o.fee_cents, o.net_cents,
         f"{o.room_type_name}×{o.rooms_qty} {o.nights}晚")
        for o in stays
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
        yield f"合计,,,,{yuan(total_comm)},{yuan(total_net)},近{min(days, 90)}天(外卖+团购+住宿)\n"

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


# ---------- 忙碌模式(高峰压单:不闭店,先把预期说清楚) ----------

@router.post("/me/busy", response_model=MerchantMeOut)
async def set_busy(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """开/关忙碌模式。{minutes: 30|60|120, extra_minutes: 10|15|20}
    或 {off: true} 提前结束。到点自动失效,不需要记得来关。"""
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    if payload.get("off"):
        shop.busy_until = None
    else:
        try:
            minutes = int(payload.get("minutes", 60))
            extra = int(payload.get("extra_minutes", shop.busy_extra_minutes))
        except (TypeError, ValueError):
            raise HTTPException(422, "minutes / extra_minutes 需为整数")
        if not 10 <= minutes <= 240:
            raise HTTPException(422, "忙碌时长需在 10-240 分钟之间")
        if not 5 <= extra <= 30:
            raise HTTPException(422, "出餐加时需在 5-30 分钟之间")
        shop.busy_until = (datetime.now(timezone.utc)
                           + timedelta(minutes=minutes))
        shop.busy_extra_minutes = extra
    await db.commit()
    await db.refresh(shop)
    return shop


# ---------- 证照公示(亮照经营,电商法要求) ----------

# 公示只放行**本就该公示**的证照类型。身份证/健康证这类绝不能出现在这里
_PUBLIC_LICENSE_KINDS = ("license", "special", "hygiene")


async def _license_url_of(db: AsyncSession, shop: Merchant,
                          kind: str) -> str:
    """某类证照的存储 URL;酒店第二证照在 HotelProfile 上。"""
    if kind == "license":
        return shop.license_image_url or ""
    if shop.biz_type != "hotel":
        return ""
    from ..models import HotelProfile
    hp = await db.scalar(
        select(HotelProfile).where(HotelProfile.merchant_id == shop.id))
    if hp is None:
        return ""
    return (hp.special_license_image_url if kind == "special"
            else hp.hygiene_image_url) or ""


def _watermark_license(data: bytes) -> bytes:
    """公示图加半透明平铺水印:公示是义务,但公示出去的图不该能被
    原样拿去二次使用(冒充资质)。字体只有内置拉丁位图,所以水印
    用域名而不是中文 —— 一样能表明出处。失败原图返回,公示义务优先。"""
    try:
        from io import BytesIO

        from PIL import Image, ImageDraw, ImageFont

        img = Image.open(BytesIO(data)).convert("RGBA")
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        font = ImageFont.load_default(size=max(img.width // 18, 16))
        text = "chaojizan.cc"
        step_x, step_y = img.width // 2 + 1, max(img.height // 4, 60)
        for y in range(0, img.height, step_y):
            for x in range(0, img.width, step_x):
                draw.text((x + 10, y + 10), text, font=font,
                          fill=(120, 120, 120, 90))
        out = BytesIO()
        Image.alpha_composite(img, layer).convert("RGB").save(
            out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception:
        return data


@router.get("/{merchant_id}/licenses")
async def merchant_licenses(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """店铺证照公示(公开):证号 + 公示图入口。仅审核通过的店。
    老库存量商家可能没传图(入驻早于强制上传),只公示证号不报错。"""
    shop = await db.get(Merchant, merchant_id)
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "店铺不存在")
    items = []
    labels = ({"license": "营业执照", "special": "特种行业许可证(旅馆业)",
               "hygiene": "卫生许可证"} if shop.biz_type == "hotel"
              else {"license": "食品经营许可证"})
    for kind, label in labels.items():
        no = ""
        if kind == "license":
            no = shop.license_no or ""
        elif kind == "special" and shop.biz_type == "hotel":
            from ..models import HotelProfile
            hp = await db.scalar(select(HotelProfile).where(
                HotelProfile.merchant_id == shop.id))
            no = (hp.special_license_no or "") if hp else ""
        url = await _license_url_of(db, shop, kind)
        if not no and not url:
            continue
        items.append({
            "kind": kind,
            "label": label,
            "no": no,
            "image_url": (f"/merchants/{merchant_id}/licenses/{kind}"
                          if url else ""),
        })
    return {"items": items}


@router.get("/{merchant_id}/licenses/{kind}")
async def merchant_license_image(
    merchant_id: int,
    kind: str,
    db: AsyncSession = Depends(get_db),
):
    """公示证照图(公开出口,服务端回读私密桶并加水印)。
    这是私密桶除 /files/ 鉴权出口之外唯一的放行口,且只认三类公示证照。"""
    from fastapi.responses import Response

    from ..services import storage
    if kind not in _PUBLIC_LICENSE_KINDS:
        raise HTTPException(404, "文件不存在")
    shop = await db.get(Merchant, merchant_id)
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "店铺不存在")
    url = await _license_url_of(db, shop, kind)
    if not url:
        raise HTTPException(404, "该店未上传此证照")
    if url.startswith("/files/"):
        key, private = url[len("/files/"):], True
    elif url.startswith("/img/"):
        key, private = url[len("/img/"):], False
    else:
        raise HTTPException(404, "文件不存在")
    # 私密桶只放行 license/ 目录:license_image_url 终归是个可写字段,
    # 没有这道前缀闸门,这个**无鉴权**出口就能被指到桶里任何文件
    # (身份证/健康证/送达留证都在同一个桶)。老 /uploads/ 存量同理不放行,
    # 公示页对无图的店只展示证号
    if private and not key.startswith("license/"):
        raise HTTPException(404, "文件不存在")

    # 水印结果进 Redis 缓存:这是个无鉴权出口,每次请求都做
    # 存储回读 + PIL 解码合成,等于白送一个 CPU 消耗面
    from ..redis_client import get_redis
    cache_key = f"license_wm:{key}"
    redis = get_redis()
    try:
        cached = await redis.get(cache_key)
    except Exception:
        cached = None
    if cached:
        return Response(cached, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    try:
        data = storage.read(key, private=private)
    except storage.StorageError as e:
        raise HTTPException(503, f"存储暂时不可用({e})")
    if data is None:
        raise HTTPException(404, "文件不存在")
    marked = _watermark_license(data)
    # 水印失败原图直出时,类型按原文件猜,别把 PNG 硬标成 JPEG
    media = ("image/jpeg" if marked is not data
             else mimetypes.guess_type(key)[0] or "image/jpeg")
    try:
        await redis.set(cache_key, marked, ex=86400)
    except Exception:
        pass  # 缓存挂了照常出图
    return Response(marked, media_type=media,
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------- 今日看板 + 待办聚合(工作台第一眼) ----------

def _bj_day_bounds(offset_days: int = 0) -> tuple[datetime, datetime]:
    """北京时间某天的 UTC 起止(offset_days=0 今天,-1 昨天)。"""
    now_bj = datetime.now(timezone.utc).astimezone(CN_TZ)
    day = (now_bj + timedelta(days=offset_days)).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=CN_TZ)
    return start.astimezone(timezone.utc), \
        (start + timedelta(days=1)).astimezone(timezone.utc)


async def _day_summary(db: AsyncSession, merchant_id: int,
                       start: datetime, end: datetime) -> dict:
    """某天的下单口径汇总。**这是「生意热度」,不是「实际入账」**:
    对账页(finance/daily)按 merchant_earnings 结算口径,未完成的单不在里面;
    这里按 created_at 数今天发生了什么,两边数字对不上是正常的。"""
    rows = await db.execute(
        select(Order.status, Order.total_cents, Order.refund_cents,
               Order.pickup)
        .where(Order.merchant_id == merchant_id,
               Order.created_at >= start, Order.created_at < end,
               Order.status != OrderStatus.PENDING_PAYMENT))
    ongoing_states = {OrderStatus.PAID, OrderStatus.ACCEPTED,
                      OrderStatus.READY, OrderStatus.PICKED_UP}
    done_states = {OrderStatus.DELIVERED, OrderStatus.COMPLETED}
    orders = ongoing = done = cancelled = pickup_n = 0
    gmv = 0
    for status, total, refund, pickup in rows:
        if status == OrderStatus.CANCELLED:
            cancelled += 1
            continue
        orders += 1
        gmv += total - refund
        pickup_n += 1 if pickup else 0
        if status in ongoing_states:
            ongoing += 1
        elif status in done_states:
            done += 1
    return {"orders": orders, "gmv_cents": gmv, "ongoing": ongoing,
            "done": done, "cancelled": cancelled, "pickup_orders": pickup_n}


@router.get("/me/today")
async def my_today(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """今日实时经营(下单口径,北京时区),附昨日全天做参照。"""
    shop = await _my_shop_or_404(db, user)
    today = await _day_summary(db, shop.id, *_bj_day_bounds(0))
    yesterday = await _day_summary(db, shop.id, *_bj_day_bounds(-1))
    return {"today": today, "yesterday": yesterday}


@router.get("/me/todos")
async def my_todos(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """待办聚合:商家当下欠着的事,数字非零才值得展示。
    只聚合已有数据,不引入新状态 —— 每一项点进去都有现成的处理界面。"""
    from ..models import AfterSale, AfterSaleStatus, Review
    shop = await _my_shop_or_404(db, user)
    now = datetime.now(timezone.utc)

    pending_orders = await db.scalar(
        select(func.count(Order.id)).where(
            Order.merchant_id == shop.id,
            Order.status == OrderStatus.PAID)) or 0
    after_sales = await db.scalar(
        select(func.count(AfterSale.id)).where(
            AfterSale.merchant_id == shop.id,
            AfterSale.status == AfterSaleStatus.pending)) or 0
    # 差评待回复:近 7 天 ≤3 星还没回应的 —— 回应越快挽回余地越大
    bad_unreplied = await db.scalar(
        select(func.count(Review.id)).where(
            Review.merchant_id == shop.id,
            Review.merchant_rating <= 3,
            Review.reply == "",
            Review.hidden.is_(False),
            Review.created_at > now - timedelta(days=7))) or 0
    # 临期营销:店铺券快发完(余量 <10% 或已发完但还挂着)
    batches = (await db.scalars(
        select(CouponBatch).where(
            CouponBatch.merchant_id == shop.id,
            CouponBatch.active.is_(True)))).all()
    coupon_low = sum(
        1 for b in batches
        if b.total > 0 and (b.total - b.issued) <= max(b.total // 10, 0))
    # 限时折扣 24h 内到期(到期自动失效,提醒续期或收手)
    flash_expiring = await db.scalar(
        select(func.count(Dish.id)).where(
            Dish.merchant_id == shop.id,
            Dish.flash_price_cents.is_not(None),
            Dish.flash_until.is_not(None),
            Dish.flash_until > now,
            Dish.flash_until < now + timedelta(hours=24))) or 0

    # 未读消息(评价/系统触达;订单类与公告不计):与消息中心同一口径
    messages_unread = await _unread_count(db, user.id)

    # 超过 24 小时还没回的差评:行业里"差评 24 小时内必回"是常识,
    # 拖过一天再回,顾客早就走了。单列出来而不是混在 bad_reviews_unreplied 里
    bad_overdue = await db.scalar(
        select(func.count(Review.id)).where(
            Review.merchant_id == shop.id,
            Review.merchant_rating <= 3,
            Review.reply == "",
            Review.hidden.is_(False),
            Review.created_at < now - timedelta(hours=24),
            Review.created_at > now - timedelta(days=7))) or 0

    return {
        "pending_orders": pending_orders,
        "after_sales": after_sales,
        "bad_reviews_unreplied": bad_unreplied,
        "bad_reviews_overdue": bad_overdue,  # 其中超 24 小时的
        "coupon_batches_low": coupon_low,
        "flash_expiring": flash_expiring,
        "messages_unread": messages_unread,
    }


# ---------- 营销效果(花出去的钱换回了什么) ----------

@router.get("/me/marketing-stats")
async def my_marketing_stats(
    days: int = Query(default=30, ge=7, le=90),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """满减 / 店铺券 / 限时折扣各带来多少单、让利多少。

    ## 口径(踩过的坑写在这里)

    **店铺券和满减共用 `Order.discount_cents`** —— 下单时二选一取最优
    (见 orders.py 的 shop_off 分支),券生效时 `discount = shop_off`
    并在 promo_note 里留「店铺券-N元(商家)」。所以:
    - 直接 `Σ discount_cents` 当"满减让利"会把券算进去;
    - 再单独加一遍券面额,商家看到的让利总额就翻倍了。
    这里按 promo_note 把两者拆开,**总额只数一遍**。

    **退款单不算生意**:售后全额退款不改订单状态(状态机里没有 refunded
    这一态),只累加 refund_cents —— 只按状态过滤会把全退单算成有效单。

    最后:这是**相关性不是因果性**。"用了活动的单客单价更高"不等于
    "活动让客单价变高",也可能是本来就买得多的人才够得着门槛。
    """
    from ..models import Coupon, CouponBatch
    shop = await _my_shop_or_404(db, user)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (await db.execute(
        select(Order.discount_cents, Order.food_cents, Order.packing_fee_cents,
               Order.refund_cents, Order.promo_note)
        .where(Order.merchant_id == shop.id,
               Order.created_at > since,
               Order.status.in_([OrderStatus.DELIVERED,
                                 OrderStatus.COMPLETED])))).all()
    promo_orders = promo_give = promo_food = 0
    coupon_orders = coupon_give = 0
    plain_orders = plain_food = 0
    for discount, food, packing, refund, note in rows:
        # 商家实收口径(与佣金基数同源),再扣掉退款
        gross = max(food + packing - discount, 0)
        if refund >= gross:
            continue  # 全额退款:这单没做成,不算任何一类的生意
        net = gross - refund
        if discount <= 0:
            plain_orders += 1
            plain_food += net
            continue
        # 券与满减共用 discount_cents,按 promo_note 分流,各数各的
        if "店铺券" in (note or ""):
            coupon_orders += 1
            coupon_give += discount
        else:
            promo_orders += 1
            promo_give += discount
        promo_food += net  # 客单价对比按"用了活动"整体算

    # 店铺券批次与发放量(**批次是全时段的**,核销才按窗口算 ——
    # 已在上面按订单时间统计,这里只给发放面)
    batches = (await db.scalars(
        select(CouponBatch).where(CouponBatch.merchant_id == shop.id))).all()
    coupon_issued = await db.scalar(
        select(func.count(Coupon.id)).where(
            Coupon.merchant_id == shop.id,
            Coupon.funder == "merchant",
            Coupon.created_at > since)) or 0
    coupon_used = coupon_orders

    # 限时折扣:当前在跑的折扣菜及其近 N 天销量
    now = datetime.now(timezone.utc)
    flash_dishes = (await db.scalars(
        select(Dish).where(
            Dish.merchant_id == shop.id,
            Dish.flash_price_cents.is_not(None),
            Dish.flash_until.is_not(None),
            Dish.flash_until > now))).all()
    sales_rows = await db.execute(_DISH_SALES_SQL, {"merchant_id": shop.id})
    sales = {row.dish_id: row.sold for row in sales_rows}

    def avg(total: int, count: int) -> int:
        return int(total / count) if count else 0

    active_orders = promo_orders + coupon_orders
    return {
        "days": days,
        "promo": {
            "orders": promo_orders,
            "give_cents": promo_give,
            # 客单价按"用了活动的单"整体算(满减 + 券),与 plain 同基准
            "avg_ticket_cents": avg(promo_food, active_orders),
        },
        "plain": {
            "orders": plain_orders,
            "avg_ticket_cents": avg(plain_food, plain_orders),
        },
        "coupon": {
            "batches": len(batches),
            "issued": coupon_issued,   # 窗口内发出的张数
            "used": coupon_used,       # 窗口内核销的张数(按订单时间)
            "use_rate": (round(coupon_used / coupon_issued, 3)
                         if coupon_issued else 0.0),
            "give_cents": coupon_give,
        },
        "flash": [{
            "dish_id": d.id, "name": d.name,
            "price_cents": d.price_cents,
            "flash_price_cents": d.flash_price_cents,
            "until": d.flash_until,
            "monthly_sales": sales.get(d.id, 0),
        } for d in flash_dishes],
        # 商家最该知道的一句话:让利总额与它换回的营业额
        "total_give_cents": promo_give + coupon_give,
        "note": "这里给的是相关性不是因果:用了活动的单客单价更高,"
                "不等于活动让客单价变高。判断值不值得,还要看你的毛利。",
    }


# ---------- 开放接口凭证(POS/收银系统对接) ----------

_MAX_API_KEYS = 5


@router.get("/me/api-keys")
async def list_api_keys(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """本店的 API Key 列表。**只回前缀,不回明文** ——
    库里存的就是哈希,明文只在创建那一刻给过一次。"""
    from ..models import MerchantApiKey
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    rows = await db.scalars(
        select(MerchantApiKey)
        .where(MerchantApiKey.merchant_id == shop.id)
        # **有效的排前面**:吊销记录永久保留,按 id 倒序取 20 条时
        # 会把仍然有效的老 Key 挤出列表 —— 商家从此看不到、也吊销不了它
        .order_by(MerchantApiKey.revoked_at.is_not(None),
                  MerchantApiKey.id.desc()).limit(20))
    return [{
        "id": k.id, "name": k.name, "prefix": k.prefix,
        "revoked": k.revoked_at is not None,
        "created_at": k.created_at,
    } for k in rows]


@router.post("/me/api-keys")
async def create_api_key(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """生成新 Key。返回体里的 token 是**唯一一次**能看到明文的机会。"""
    from ..models import MerchantApiKey
    from .open_api import new_key
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    if shop.status != MerchantStatus.approved:
        raise HTTPException(403, "店铺通过审核后才能对接收银系统")
    # 上限校验与插入之间上店铺行锁:并发两个 POST 都读到 4 就都能插进来
    await db.refresh(shop, with_for_update=True)
    alive = await db.scalar(
        select(func.count(MerchantApiKey.id)).where(
            MerchantApiKey.merchant_id == shop.id,
            MerchantApiKey.revoked_at.is_(None))) or 0
    if alive >= _MAX_API_KEYS:
        raise HTTPException(
            409, f"最多同时保留 {_MAX_API_KEYS} 把有效 Key,请先吊销不用的")
    raw, token_hash, prefix = new_key()
    name = payload.get("name")
    key = MerchantApiKey(
        merchant_id=shop.id,
        name=(str(name)[:30] if isinstance(name, str) else ""),
        token_hash=token_hash,
        prefix=prefix,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return {"id": key.id, "name": key.name, "prefix": key.prefix,
            "token": raw, "created_at": key.created_at}


@router.delete("/me/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """吊销:立即失效,不可撤销。记录留着(谁在什么时候用过要查得到)。"""
    from ..models import MerchantApiKey
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    key = await db.get(MerchantApiKey, key_id)
    if shop is None or key is None or key.merchant_id != shop.id:
        raise HTTPException(404, "Key 不存在")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    return {"ok": True}


# ---------- 消息中心(公告 + 触达记录,订单类不进这里) ----------

# 已读水位存 Redis:一人一条时间戳。Redis 无持久化卷,水位可能整体丢失 ——
# 丢了不能退化成"未读=开店以来全部推送",见 _unread_since
_MSG_READ_KEY = "msg:read:merchant:{user_id}"
# 没有水位时(新商家/Redis 重建)只看最近这些天,免得徽标显示"新消息 8342"
_MSG_FALLBACK_DAYS = 7

# 订单类推送**不进消息中心**:订单页本身就是它们的家,
# 一家日 300 单的店配好推送后,消息中心第一页会全是"新订单来了"。
# 按标题关键词排除 —— push 的标题是我们自己写死的常量(services/push.py),
# 不是用户输入,匹配稳定
_ORDER_TITLE_KEYWORDS = ("订单", "新单", "催单", "骑手", "配送", "送达",
                         "售后", "退款", "取餐")
_REVIEW_TITLE_KEYWORDS = ("评价", "回复", "点评")


def _message_filters():
    """SQL 层过滤条件(排除订单类)。**必须在 SQL 里做**:
    在 Python 里对取回的一页做 filter,会出现"这一页恰好全被过滤掉 →
    客户端拿到空列表 → 没有游标可以继续翻"的死局。"""
    from ..models import PushLog
    conds = [PushLog.title.notlike(f"%{kw}%")
             for kw in _ORDER_TITLE_KEYWORDS]
    return conds


def _classify_message(title: str) -> str:
    """按标题归类:评价类要醒目,其余归系统。"""
    return ("review" if any(kw in title for kw in _REVIEW_TITLE_KEYWORDS)
            else "system")


async def _unread_since(user_id: int) -> datetime:
    """未读统计的起点:有水位用水位,没有(新商家/Redis 重建)退回最近 N 天。
    Redis 故障时同样退回 —— 未读数偏大可以忍,首屏 500 不行。"""
    from ..redis_client import get_redis
    fallback = datetime.now(timezone.utc) - timedelta(days=_MSG_FALLBACK_DAYS)
    try:
        raw = await get_redis().get(_MSG_READ_KEY.format(user_id=user_id))
    except Exception:
        return fallback
    if not raw:
        return fallback
    try:
        return datetime.fromisoformat(
            raw.decode() if isinstance(raw, bytes) else raw)
    except ValueError:
        return fallback


async def _unread_count(db: AsyncSession, user_id: int) -> int:
    from ..models import PushLog
    since = await _unread_since(user_id)
    return await db.scalar(
        select(func.count(PushLog.id)).where(
            PushLog.user_id == user_id,
            PushLog.created_at > since,
            *_message_filters())) or 0


@router.get("/me/messages")
async def my_messages(
    category: str | None = None,   # review / system;缺省全部
    before: int | None = None,     # push_logs 游标(上一页最后一条 id)
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """消息中心:置顶当前生效的平台公告 + 本人触达记录(评价/系统)。"""
    from ..models import Announcement, PushLog
    from ..redis_client import get_redis
    await _my_shop_or_404(db, user)

    now = datetime.now(timezone.utc)
    ann_rows = await db.scalars(
        select(Announcement).where(
            Announcement.is_active.is_(True),
            Announcement.audience.in_(["merchant", "all"]),
            or_(Announcement.starts_at.is_(None), Announcement.starts_at <= now),
            or_(Announcement.ends_at.is_(None), Announcement.ends_at >= now),
        ).order_by(Announcement.created_at.desc()).limit(10))
    announcements = [{
        "id": a.id, "title": a.title, "content": a.content,
        "created_at": a.created_at,
    } for a in ann_rows]

    # 分类过滤下推到 SQL:在 Python 里过滤取回的一页,会出现
    # "这页恰好全被滤掉 → 返回空 → 客户端没有游标可翻"的死局
    stmt = select(PushLog).where(PushLog.user_id == user.id,
                                 *_message_filters())
    if category == "review":
        stmt = stmt.where(or_(*[PushLog.title.like(f"%{kw}%")
                                for kw in _REVIEW_TITLE_KEYWORDS]))
    elif category == "system":
        stmt = stmt.where(*[PushLog.title.notlike(f"%{kw}%")
                            for kw in _REVIEW_TITLE_KEYWORDS])
    if before is not None:
        stmt = stmt.where(PushLog.id < before)
    rows = (await db.scalars(
        stmt.order_by(PushLog.id.desc()).limit(50))).all()
    messages = [{
        "id": log.id, "kind": _classify_message(log.title),
        "title": log.title, "content": log.content,
        "created_at": log.created_at,
    } for log in rows]

    # 未读 = 水位之后的触达条数(公告不计未读:横幅本来就常驻)
    unread = await _unread_count(db, user.id)

    return {"announcements": announcements, "messages": messages,
            "unread": unread, "page_size": 50}


@router.post("/me/messages/read")
async def mark_messages_read(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """记已读水位到当前时刻。Redis 挂了不报错 ——
    看消息这个动作本身成功了,未读数下次再对齐就是。"""
    from ..redis_client import get_redis
    await _my_shop_or_404(db, user)
    try:
        await get_redis().set(
            _MSG_READ_KEY.format(user_id=user.id),
            datetime.now(timezone.utc).isoformat())
    except Exception:
        return {"ok": False, "reason": "缓存暂时不可用,未读数稍后自动对齐"}
    return {"ok": True}


# ---------- 合规档案(不是违规积分) ----------

@router.get("/me/compliance")
async def my_compliance(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """我的合规档案:平台记在你名下的事,一次看全。

    **这里刻意不做"违规积分"**。代码里三处写死的承诺是同一个立场:
    出餐时长「不用于排名、扣分、影响曝光」(见 /me/prep-time 的
    never_used_for)、/me/quality「只统计不处罚」、明厨亮灶「不做 AI 打分」。
    一旦有了分数,它迟早会影响谁被看见,而误判会落到具体的人身上。

    所以这一页只做两件事:把已经存在的记录摊开给你看,
    并告诉你每一条能不能申诉、申诉到哪一步了。
    """
    from ..models import Appeal, ContentReview, FoodSafetyReport
    shop = await _my_shop_or_404(db, user)
    now = datetime.now(timezone.utc)

    # 食安投诉:只给商家看得到的部分 —— 投诉人是谁、哪个管理员处理的都不给
    reports = (await db.scalars(
        select(FoodSafetyReport)
        .where(FoodSafetyReport.merchant_id == shop.id)
        .order_by(FoodSafetyReport.id.desc()).limit(50))).all()
    food_safety = [{
        "id": r.id,
        "kind": r.kind,
        "status": r.status,
        "order_no": r.order_no,
        "created_at": r.created_at,
        # 处置动作对商家公开,但抹掉 admin_id 与投诉人信息
        "actions": [{"action": a.get("action"), "note": a.get("note", ""),
                     "at": a.get("at")}
                    for a in (r.actions or [])],
    } for r in reports]

    # 菜品图被驳回的(先发后审):商家往往不知道自己的图被隐藏了
    dish_ids = [d for d in (await db.scalars(
        select(Dish.id).where(Dish.merchant_id == shop.id).limit(500)))]
    rejected_images = []
    if dish_ids:
        rejected_images = [{
            "id": c.id, "url": c.url, "note": c.note,
            "created_at": c.created_at,
        } for c in (await db.scalars(
            select(ContentReview).where(
                ContentReview.kind == "dish",
                ContentReview.ref_id.in_(dish_ids),
                ContentReview.status == "rejected")
            .order_by(ContentReview.id.desc()).limit(30)))]

    # 已提交的申诉(让商家知道自己申诉到哪一步了)
    appeals = [{
        "target_type": a.target_type, "target_id": a.target_id,
        "status": a.status, "created_at": a.created_at,
    } for a in (await db.scalars(
        select(Appeal).where(Appeal.user_id == user.id)
        .order_by(Appeal.id.desc()).limit(50)))]

    # 近 30 天经营质量(与 /me/quality 同源,这里只取结论)
    since30 = now - timedelta(days=30)
    rejects = await db.scalar(
        select(func.count(Order.id)).where(
            Order.merchant_id == shop.id,
            Order.status == OrderStatus.CANCELLED,
            Order.created_at > since30)) or 0
    late = await db.scalar(
        select(func.count(Order.id)).where(
            Order.merchant_id == shop.id,
            Order.ready_late.is_(True),
            Order.created_at > since30)) or 0

    return {
        "shop_status": shop.status.value,
        "reject_reason": shop.reject_reason or "",
        "food_safety": food_safety,
        "rejected_images": rejected_images,
        "appeals": appeals,
        "quality_30d": {"cancelled": rejects, "ready_late": late},
        # 说清楚这些数用来干什么、不用来干什么(与 prep-time 同款做法)
        "used_for": "让你知道平台记了什么、哪些可以申诉。食安投诉的处置"
                    "(下架/停业)会直接影响经营,其余仅供你自查。",
        "never_used_for": "不折算成分数、不用于排名、不影响你在用户端的曝光。"
                          "平台没有「违规积分」这种东西。",
    }


# ---------- 规则中心(数字从代码里的真实常量算出来) ----------

@router.get("/me/rules")
async def my_rules(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """平台规则:什么算违规、后果是什么、怎么申诉。

    **每个数字都从代码里的真实常量算出来**,不是后台可编辑的文案 ——
    公示 30 天 3 起自动停业、代码里写的却是 5 起,这种事只要可能发生
    就迟早会发生。与 pledge.* 那套承诺文案同一个做法。
    """
    from ..routers.admin import FS_AUTO_SUSPEND_COUNT
    from ..routers.appeals import APPEAL_WINDOW
    from ..services.staff import operable_shop
    # 店员也该看得到"什么算违规"——这一页没有任何敏感数据
    shop, _ = await operable_shop(db, user)
    if shop is None:
        raise HTTPException(404, "还没开店")
    # 与 platform._pledge_copy 同款兜底:误配成空清单也不该让规则页 500
    tiers = settings.commission_tiers or [[0, "0.050"]]
    top_rate = max(float(r[1]) for r in tiers)
    appeal_hours = int(APPEAL_WINDOW.total_seconds() // 3600)
    return {
        "sections": [
            {
                "title": "抽成",
                "items": [
                    f"总负担 {top_rate * 100:g}% 封顶,单量越大费率越低"
                    f"(当前你是 {float(shop.commission_rate) * 100:g}%)",
                    "平台配送的配送费 100% 归骑手,平台一分不抽;"
                    "自配送的单配送费归你",
                    "没有竞价排名,不存在花钱买曝光",
                ],
            },
            {
                "title": "食品安全(唯一会直接影响经营的红线)",
                "items": [
                    f"30 天内成立 {FS_AUTO_SUSPEND_COUNT} 起食安投诉,"
                    "系统自动暂停营业并转人工复核",
                    "投诉直达平台不经商家,处置动作全部留痕(你在合规档案里看得到)",
                    "先行赔付由平台垫付,判定商家责任的才向你追偿",
                ],
            },
            {
                "title": "申诉",
                "items": [
                    f"售后判责、差评(≤3 星)可在 {appeal_hours} 小时内申诉,每项一次",
                    "申诉成立:差评隐藏且评分同步扣回、被冲的净额补回来",
                    "改判的钱平台认亏,不向用户追讨",
                ],
            },
            {
                "title": "配送责任",
                "items": [
                    "配送由平台负责;评价里的配送标签(送得慢/餐洒了)"
                    "只挂骑手评分,不进商家维度",
                    "但**星级是用户给的**:配送不好导致的低星仍会计入店铺评分。"
                    "遇到这种,72 小时内申诉,系统会自动附上这单的"
                    "接单/出餐/送达时间线供审核 —— 出餐正常而配送晚了,证据替你说话",
                    "超时安抚券由平台承担,不扣你也不扣骑手",
                    "骑手到店等餐超时有补偿,同样平台出",
                ],
            },
            {
                "title": "排序怎么来的",
                "items": [
                    "用户端排序只用真实评分、销量、距离 —— 没有可以买的位置",
                    "**评分会影响你的曝光**:「评分优先」按评分排,综合排序里"
                    "评分是权重最大的一项,用户还能按最低评分筛选。"
                    "这不是处罚机制,是用户在选店 —— 但它确实决定谁被看见",
                    "出餐时长不参与任何排序与筛选:只给你自己看、"
                    "让骑手知道大概等多久、给用户更准的送达时间",
                ],
            },
            {
                "title": "不会发生的事",
                "items": [
                    "平台没有「违规积分」这种东西,任何指标都不折算成分数",
                    "评价不能删也不能花钱删,唯一例外是申诉成立后隐藏(评分同步扣回)",
                    "自配送的单配送费归你;平台配送的配送费全归骑手,平台一分不抽",
                ],
            },
        ],
        "note": "这一页的数字直接来自代码里的常量,后台改不了 ——"
                "公示的和实际执行的必须是同一个数。",
    }


# ---------- 顾客分层(我的客人是谁) ----------

@router.get("/me/customers")
async def my_customers(
    days: int = Query(default=30, ge=7, le=90),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """新客 / 回头客 / 流失客各多少人、各贡献多少。

    口径(只有一套定义,不留歧义):
    - **新客**:窗口内下过单,且此前从没在本店买过(拉新 ROI 看这个)
    - **回头客**:窗口内下过单,且窗口之前也买过
    - **流失客**:窗口前 90 天内买过、窗口内一单没有(可召回的那批;
      两年前买过一次的人不是召回对象,所以要有下界)

    只数完成的单,且**全额退款的单不算**(与营销效果同口径:
    退光了的单没有做成生意,算进去会让回头客数虚高一倍)。
    金额按商家实收(扣掉让利与退款);已确认的刷单不计。
    """
    shop = await _my_shop_or_404(db, user)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    churn_floor = since - timedelta(days=90)
    done = [OrderStatus.DELIVERED, OrderStatus.COMPLETED]
    # 与用户端月售、经营分析同口径:确认过的刷单不计
    # **必须 coalesce**:risk_flags 里没有 status 键时 ->>'status' 是 NULL,
    # 而 NULL != 'confirmed' 的结果是 NULL 不是 TRUE —— 整行会被静默滤掉,
    # 实测把回头客与流失客直接算成 0。库里其它三处都是这么写的
    not_fraud = text("coalesce(risk_flags->>'status', '') != 'confirmed'")
    # 全额退款(退款 >= 商家实收)的单不算生意
    gross = Order.food_cents + Order.packing_fee_cents - Order.discount_cents
    real_deal = Order.refund_cents < func.greatest(gross, 0)

    # 窗口内:每人的净贡献(DB 侧聚合,不把订单行拉进 Python)
    rows = (await db.execute(
        select(Order.customer_id,
               func.sum(func.greatest(gross - Order.refund_cents, 0)))
        .where(Order.merchant_id == shop.id, Order.created_at > since,
               Order.status.in_(done), real_deal, not_fraud)
        .group_by(Order.customer_id))).all()
    per_user = {cid: int(net or 0) for cid, net in rows}

    # 窗口之前买过的人(区分新客/回头客)
    before_ids = set(await db.scalars(
        select(func.distinct(Order.customer_id)).where(
            Order.merchant_id == shop.id, Order.created_at <= since,
            Order.status.in_(done), real_deal, not_fraud)))
    # 可召回的流失客:只看窗口前 90 天,不是"生涯买过的所有人"
    recent_before = set(await db.scalars(
        select(func.distinct(Order.customer_id)).where(
            Order.merchant_id == shop.id,
            Order.created_at > churn_floor, Order.created_at <= since,
            Order.status.in_(done), real_deal, not_fraud)))

    groups = {"new": [0, 0], "repeat": [0, 0]}
    for cid, net in per_user.items():
        key = "repeat" if cid in before_ids else "new"
        groups[key][0] += 1
        groups[key][1] += net
    churned = len(recent_before - set(per_user))

    return {
        "days": days,
        "new": {"customers": groups["new"][0], "net_cents": groups["new"][1]},
        "repeat": {"customers": groups["repeat"][0],
                   "net_cents": groups["repeat"][1]},
        "churned": {"customers": churned, "window_days": 90},
        "total_customers": len(per_user),
        "note": "新客=此前从没在本店买过;流失客=前 90 天买过、这段时间没再来的人,"
                "店内营销里的「老客召回」正是发给他们的。"
                "全额退款的单不计入(那单没做成)。",
    }


# ---------- 流量转化漏斗 ----------

@router.get("/me/funnel")
async def my_funnel(
    days: int = Query(default=7, ge=1, le=30),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """曝光 → 进店 → 结算 → 下单,每一级有多少人。

    **这是"不做竞价排名"的正面替代**:我们不卖曝光位,
    但把真实的漏斗给商家看 —— 哪一环在漏,自己就知道该改什么。

    口径:按**人**去重(同一个人看十次算一个),不是按次。
    埋点只记登录用户的产品行为,不采设备指纹(见 models.AppEvent),
    所以未登录的浏览不在其中,绝对值会低于真实流量,看趋势和转化率更有意义。
    """
    from ..models import AppEvent
    shop = await _my_shop_or_404(db, user)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    mid = str(shop.id)

    async def uniq(event: str) -> int:
        return await db.scalar(
            select(func.count(func.distinct(AppEvent.user_id))).where(
                AppEvent.event == event,
                AppEvent.created_at > since,
                AppEvent.props["merchant_id"].astext == mid)) or 0

    impression = await uniq("impression_shop")
    visit = await uniq("view_menu")
    checkout = await uniq("checkout_view")

    # **四级必须是同一批人**。前三级来自客户端埋点(只有登录用户、
    # 只有装了新版 App 的人),第四级如果直接数全部订单,分母分子不是
    # 一个总体 —— 埋点刚上线那几天必然是"曝光 3 / 下单 843",
    # 前端一算就是 28100%。所以这里只数**被埋点覆盖到的那批人**里下单的,
    # 另外单给一个 ordered_all 让商家仍能看到真实下单人数
    tracked = select(AppEvent.user_id).where(
        AppEvent.created_at > since,
        AppEvent.props["merchant_id"].astext == mid)
    ordered = await db.scalar(
        select(func.count(func.distinct(Order.customer_id))).where(
            Order.merchant_id == shop.id,
            Order.created_at > since,
            Order.status != OrderStatus.PENDING_PAYMENT,
            Order.customer_id.in_(tracked))) or 0
    ordered_all = await db.scalar(
        select(func.count(func.distinct(Order.customer_id))).where(
            Order.merchant_id == shop.id,
            Order.created_at > since,
            Order.status != OrderStatus.PENDING_PAYMENT)) or 0

    def rate(a: int, b: int) -> float:
        # 上钳到 1:埋点覆盖不全时(如从搜索/收藏直接进店只发 view_menu)
        # 下一级可能大于上一级,显示 120% 只会让人以为数据是错的
        return round(min(a / b, 1.0), 3) if b else 0.0

    return {
        "days": days,
        "impression": impression,
        "visit": visit,
        "checkout": checkout,
        "ordered": ordered,
        "ordered_all": ordered_all,   # 真实下单人数(不限于被埋点覆盖的)
        "visit_rate": rate(visit, impression),      # 看到 → 进店
        "checkout_rate": rate(checkout, visit),     # 进店 → 结算
        "order_rate": rate(ordered, checkout),      # 结算 → 下单
        "overall_rate": rate(ordered, impression),
        "note": "漏斗四级都只数「App 上报过浏览的那批登录用户」,"
                "口径才可比;真实下单人数见 ordered_all(通常更高)。"
                "平台不采设备指纹,也不卖曝光位——这些数字只给你自己看,不影响排序。",
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


@router.post("/me/dishes/reorder")
async def reorder_dishes(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """批量写菜单顺序:{items: [{dish_id, sort}]}。
    只认本店的菜(混进别家的直接 404),一次最多 200 条。"""
    shop = await _my_shop_or_404(db, user)
    items = payload.get("items") or []
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise HTTPException(422, "items 需为 1-200 条 {dish_id, sort}")
    ids: dict[int, int] = {}
    for row in items:
        try:
            ids[int(row["dish_id"])] = int(row["sort"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "每条需包含整数 dish_id 与 sort")
    if any(not -9999 <= v <= 9999 for v in ids.values()):
        raise HTTPException(422, "sort 需在 -9999 到 9999 之间")
    dishes = (await db.scalars(select(Dish).where(
        Dish.id.in_(ids.keys()), Dish.merchant_id == shop.id))).all()
    if len(dishes) != len(ids):
        raise HTTPException(404, "有菜品不属于本店")
    for dish in dishes:
        dish.sort = ids[dish.id]
    await db.commit()
    return {"updated": len(dishes)}


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


# ---------------------------------------------------------------------------
# 明厨亮灶(#155/#156/#157)
#
# 这不是产品选择,是法定义务:总局令第 123 号第十三条,2026-06-01 已施行。
# 平台的三项义务 —— 要求商家设链接标识、在列表页展示「有/无」、提供技术支持。
#
# 完整背景与红线见 services/kitchen_cam.py 的模块文档。
# ---------------------------------------------------------------------------


class KitchenCamIn(BaseModel):
    """接入明厨亮灶。"""
    url: str = Field(max_length=300)
    vendor: str = Field(default="", max_length=20)
    #: 商家自己拍的画面截图。人工核验时对着它看两件事:
    #: ① 镜头对的是不是操作区;② 有没有拍到不该拍的(#157)
    shot_url: str = Field(default="", max_length=300)
    #: 已告知后厨全体员工该区域有对外直播的摄像头。
    #: **必须为 true 才能提交** —— 后厨里站着的也是劳动者,
    #: 个保法第二十六条的精神是"先告知,再采集"
    notified: bool = False


def _cam_out(shop: Merchant) -> dict:
    from ..services import kitchen_cam as kc
    return {
        "status": shop.kitchen_cam_status,
        "listed_label": kc.listed_label(shop.kitchen_cam_status),
        "url": shop.kitchen_cam_url,
        "vendor": shop.kitchen_cam_vendor,
        "shot_url": shop.kitchen_cam_shot_url,
        "notified": shop.kitchen_cam_notified,
        "reason": shop.kitchen_cam_reason,
        "note": shop.kitchen_cam_note,
        "verified_at": shop.kitchen_cam_verified_at,
        "checked_at": shop.kitchen_cam_checked_at,
        "capabilities": kc.capabilities(),
        "should_cover": kc.SHOULD_COVER,
        "must_not_cover": kc.MUST_NOT_COVER,
        "probe_interval_minutes": kc.PROBE_INTERVAL_MINUTES,
    }


@router.get("/me/kitchen-cam")
async def my_kitchen_cam(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """我的明厨亮灶状态。"""
    return _cam_out(await _my_shop_or_404(db, user))


@router.put("/me/kitchen-cam")
async def set_kitchen_cam(
    payload: KitchenCamIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """接入或更新明厨亮灶地址。

    提交后进 pending,等平台看一眼首帧再放行 —— 这一步**不能省**:
    行业里「摄像头对着天花板」的乱象,就是因为没人看过一眼就发标识了。
    平台标了「有明厨亮灶」而实际是天花板,用户因此下单出了事,
    平台是要负连带责任的(食品安全法第一百三十一条)。
    """
    from ..services import kitchen_cam as kc

    shop = await _my_shop_or_404(db, user)
    try:
        url = kc.normalize_url(payload.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    if not payload.notified:
        # 这一条不是走过场。后厨里站着的是劳动者,他们有权知道自己在被拍
        raise HTTPException(
            422, "请先确认已告知后厨全体员工该区域有对外直播的摄像头 —— "
                 "接入说明里有可打印的告知牌")

    shop.kitchen_cam_url = url
    shop.kitchen_cam_vendor = payload.vendor.strip()[:20]
    shop.kitchen_cam_shot_url = payload.shot_url.strip()[:300]
    shop.kitchen_cam_notified = True
    shop.kitchen_cam_status = kc.STATUS_PENDING
    shop.kitchen_cam_reason = ""
    shop.kitchen_cam_note = "已提交,平台会看一眼画面再放行(通常 1 个工作日内)"
    shop.kitchen_cam_fail_streak = 0
    shop.kitchen_cam_ok_streak = 0
    shop.kitchen_cam_sequence = None
    shop.kitchen_cam_verified_at = None
    await db.commit()
    await db.refresh(shop)
    return _cam_out(shop)


@router.delete("/me/kitchen-cam")
async def remove_kitchen_cam(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """撤下明厨亮灶。商家随时可以撤 —— 法规对商家是「倡导」不是强制。"""
    from ..services import kitchen_cam as kc

    shop = await _my_shop_or_404(db, user)
    shop.kitchen_cam_status = kc.STATUS_NONE
    shop.kitchen_cam_url = ""
    shop.kitchen_cam_reason = ""
    shop.kitchen_cam_note = ""
    shop.kitchen_cam_sequence = None
    shop.kitchen_cam_verified_at = None
    await db.commit()
    await db.refresh(shop)
    return _cam_out(shop)


@router.get("/{merchant_id}/kitchen-cam")
async def public_kitchen_cam(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """顾客看的明厨亮灶(公开,无需登录 —— 法规要的是"接受社会监督")。

    **只有 active 才给播放地址。** pending/degraded 一律按「无明厨亮灶」对外,
    并且如实告诉用户为什么现在看不了 —— 转圈转到天荒地老比直说更糟。
    """
    from ..services import kitchen_cam as kc

    shop = await db.get(Merchant, merchant_id)
    if shop is None:
        raise HTTPException(404, "店铺不存在")

    active = shop.kitchen_cam_status == kc.STATUS_ACTIVE
    return {
        "merchant_id": shop.id,
        "has_kitchen_cam": active,
        "label": kc.listed_label(shop.kitchen_cam_status),
        # 不 active 就不给地址,连"你自己试试"的机会都不给 ——
        # 给了等于把一个我们判定为不可用的流推给用户
        "url": shop.kitchen_cam_url if active else "",
        "checked_at": shop.kitchen_cam_checked_at,
        "message": ("" if active else _cam_public_message(shop)),
        "coverage_note": "画面只覆盖加工制作的关键环节;"
                         "休息区、更衣区、卫生间不在拍摄范围内",
        "no_playback": "只提供实时画面,不提供历史录像回看",
    }


def _cam_public_message(shop: Merchant) -> str:
    """不可用时给用户的人话。**不甩锅给商家,也不含糊。**"""
    from ..services import kitchen_cam as kc

    if shop.kitchen_cam_status == kc.STATUS_NONE:
        return "这家店还没有接入明厨亮灶"
    if shop.kitchen_cam_status == kc.STATUS_PENDING:
        return "这家店刚接入,平台还在核验画面,暂时按「无明厨亮灶」显示"
    return ("这家店的摄像头现在连不上,我们已经把标识改回「无明厨亮灶」。"
            "等它恢复了会自动改回来")
