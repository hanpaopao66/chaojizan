from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from sqlalchemy import (and_, func, literal_column, or_, select, text,
                        update)
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import logging

import httpx
import mimetypes
import secrets

from ..categories import CATEGORIES_BY_BIZ, FOOD_CATEGORIES, categories_of
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
    APPLYMENT_LOCKED_STATUSES,
    ApplymentIn,
    ApplymentOut,
    applyment_missing,
    applyment_out,
    next_applyment_status,
    DayStatOut,
    DishIn,
    DishOut,
    MerchantDishOut,
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
from ..services.staff import owned_shop

router = APIRouter(prefix="/merchants", tags=["商家"])

logger = logging.getLogger(__name__)

# 附近商家 + 近 30 天完成单数(月售),按指定方式排序
_NEARBY_SQL_TMPL = """
    -- 先挑出这一页的店,**再**给这一页算月售。
    --
    -- 原来是反过来的:LEFT JOIN orders → GROUP BY → ORDER BY → LIMIT 20。
    -- 也就是为了返回 20 家,给半径内**所有**店都算了 30 天月售和人均。
    -- 实测 863 家店 join 出 7610 行再分组排序,一次 14.5ms,占整个首页
    -- 接口 81%;而店越多这个数涨得越快 —— 恰恰是生意做起来之后。
    --
    -- distance / rating 的排序键只跟 merchants 自己有关,所以能把 LIMIT
    -- 推到聚合前面。sales 不行(排序键就是聚合结果本身),走另一个模板。
    WITH page AS (
        -- rn 是给外层复用排序用的:CTE 里的顺序不保证传到外层,而
        -- rating 排序的键(评分)并不在 CTE 的输出列里。用 row_number
        -- 一次覆盖所有排序方式,不用给每种排序各自把列拖出来。
        -- 窗口函数在 LIMIT 之前算,所以 rn 就是"按这个排序的第几名"。
        SELECT m.id, {dist_expr} AS distance_m,
               row_number() OVER (ORDER BY {order_by}, m.id) AS rn
        FROM merchants m
        WHERE m.is_open = true
          AND m.status = 'approved'
          AND m.biz_type = :biz_type
          {category_clause}
          {filter_clause}
          AND ST_DWithin(
                ST_SetSRID(ST_MakePoint(m.lng, m.lat), 4326)::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius_m
              )
        ORDER BY {order_by}, m.id
        LIMIT :limit OFFSET :offset
    )
    -- 聚合和取整行分两层:**聚合这一层只带 id/距离/名次**,
    -- 商家的 85 列在聚合之后才按主键 join 进来。
    -- 直接 `SELECT m.*` + `GROUP BY m.id` 也对,但那样 85 列要跟着
    -- 整个 GROUP BY 走一遍,省下的那趟往返正好被它吃掉(实测是平的)。
    SELECT m.*, agg.sales, agg.distance_m, agg.avg_spend_cents
    FROM (
      SELECT p.id, p.distance_m, p.rn, count(o.id) AS sales,
             -- 人均:近 30 天已完成单的**餐费**均价,不含配送费和打包费。
             -- 用户比的是"这家菜多少钱",配送费在卡片上本来就单列了。
             --
             -- 样本不足时给 NULL,由调用方决定不显示 —— 三五单算出来的
             -- 均价没有意义(一单 50 和一单 10 差得离谱),而一个瞎编的
             -- "人均"会让人按错误的价位预期点进去。和评分「暂无评价」
             -- 一个道理:不知道就说不知道。
             CASE WHEN count(o.id) >= :avg_min_orders
                  THEN round(avg(o.food_cents))::int END AS avg_spend_cents
      FROM page p
      LEFT JOIN orders o
             ON o.merchant_id = p.id
            AND o.status = 'completed'
            AND o.created_at >= now() - interval '30 days'
            AND coalesce(o.risk_flags->>'status', '') != 'confirmed'
      GROUP BY p.id, p.distance_m, p.rn
    ) agg
    JOIN merchants m ON m.id = agg.id
    ORDER BY agg.rn
"""

#: 按销量排序**只能**用这个:排序键就是聚合结果,没法把 LIMIT 推到
#: 聚合前面。所以这条路径照旧要给半径内所有店算月售 —— 首页默认的
#: distance 不走这里,影响面小
_NEARBY_SQL_BY_SALES = """
    SELECT m.*, agg.sales, agg.distance_m, agg.avg_spend_cents
    FROM (
      SELECT m.id, count(o.id) AS sales, min({dist_expr}) AS distance_m,
             -- 名次和 _NEARBY_SQL_TMPL 同一套路:外层只按 rn 排,
             -- 不把排序键在外层再抄一遍 —— 抄漏一个 m.id 就不是全序了,
             -- 翻页会重店漏店。窗口函数在 GROUP BY 之后、LIMIT 之前算
             row_number() OVER (ORDER BY {order_by}, m.id) AS rn,
             CASE WHEN count(o.id) >= :avg_min_orders
                  THEN round(avg(o.food_cents))::int END AS avg_spend_cents
      FROM merchants m
      LEFT JOIN orders o
             ON o.merchant_id = m.id
            AND o.status = 'completed'
            AND o.created_at >= now() - interval '30 days'
            AND coalesce(o.risk_flags->>'status', '') != 'confirmed'
      WHERE m.is_open = true
        AND m.status = 'approved'
        AND m.biz_type = :biz_type
        {category_clause}
        {filter_clause}
        AND ST_DWithin(
              ST_SetSRID(ST_MakePoint(m.lng, m.lat), 4326)::geography,
              ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
              :radius_m
            )
      GROUP BY m.id
      ORDER BY {order_by}, m.id
      LIMIT :limit OFFSET :offset
    ) agg
    JOIN merchants m ON m.id = agg.id
    ORDER BY agg.rn
"""

#: 算「人均」至少要几单。
#:
#: 三五单算出来的均价没有意义 —— 一单 50 和一单 10 差得离谱,而用户会
#: 按这个数形成价位预期,点进去发现对不上。10 单是个折中:够抹平个别
#: 大单小单,又不至于让新店永远显示不出来。不够就给 NULL,
#: 客户端显示「新店」,和评分的「暂无评价」一个道理。
AVG_SPEND_MIN_ORDERS = 10

_DIST_EXPR = (
    "ST_SetSRID(ST_MakePoint(m.lng, m.lat), 4326)::geography "
    "<-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography"
)

# 排序白名单(拼 SQL 前必须查表,防注入)。
# 每个排序后面都再跟一个 m.id(见 SQL 模板):评分/月售有大量并列,
# 并列组内的顺序不定 —— 翻页时同一家店会在第 1 页和第 2 页各出现一次,
# 而另一家一次都不出现。分页要成立,排序必须是全序
_SORTS = {
    "distance": _DIST_EXPR,
    "rating": (
        "(m.rating_sum::float / NULLIF(m.rating_count, 0)) DESC NULLS LAST, "
        + _DIST_EXPR
    ),
    "sales": "count(o.id) DESC, " + _DIST_EXPR,
}

# 列表一页最多给这么多家:再多首帧就卡,也没人一屏看得完
_PAGE_MAX = 50


def _browse_radius_m(requested: int | None) -> int:
    """浏览半径的唯一口径 = 配送上限(config.delivery_max_km)。

    此前列表默认 5000 而配送上限是 4000:4–5km 的店进得了列表、进得了店、
    加得了购物车,提交时被 orders.py 以「超出配送范围」409 打回。
    用户看到的是"这店明明在列表里,凭什么不给我送" —— 这是信任伤害,
    不是体验瑕疵,所以宁可少给几家也不给下不了单的。

    传进来的值一律向下收敛到上限:老客户端(搜索页还挂着「5km 内」)
    和第三方调用方不会因为多传一个数就把超范围的店放回列表里。
    """
    cap = int(settings.delivery_max_km * 1000)
    return cap if requested is None else min(requested, cap)


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
    radius_m: int | None = Query(default=None, ge=100),
    sort: str = "distance",
    category: str | None = None,
    min_rating: float | None = Query(default=None, ge=0, le=5),
    has_promo: bool = False,          # 有满减或满赠
    max_min_order_cents: int | None = Query(default=None, ge=0, le=100_000),
    limit: int = Query(default=_PAGE_MAX, ge=1, le=_PAGE_MAX),
    offset: int = Query(default=0, ge=0),
    biz_type: str = "food",
    db: AsyncSession = Depends(get_db),
):
    """附近营业中的商家(带月售),sort=distance|rating|sales,category 按品类筛选。

    `biz_type` 选业态:food 外卖 / retail 零售(超市、水果店)。
    **同一套卡片、同一套排序**,零售和外卖的区别只在货架上,不在这个接口 ——
    所以不另起一个 /retail 接口。默认 food 是为了老客户端原样能用。
    住宿不在这里:它没有配送、按夜计价,走 /stays。

    筛选与 /merchants/search 同口径:min_rating 评分下限、has_promo 有优惠、
    max_min_order_cents 起送价上限。首页和搜索页给的是同一套条件,
    用户不用在两个地方学两遍。

    距离上限 radius_m 不传就取配送上限,传了也不会超过配送上限
    (见 _browse_radius_m:列表里出现的每一家店都必须下得了配送单)。

    分页 limit/offset:**返回体仍是纯 list,不包 {items,total}** ——
    翻页是新加的能力,不该让所有老调用方跟着改解析。
    没有下一页的信号就是"这一页不足 limit 家"。
    """
    if sort not in _SORTS:
        raise HTTPException(422, "sort 仅支持 distance / rating / sales")
    if biz_type not in CATEGORIES_BY_BIZ:
        raise HTTPException(422, "biz_type 仅支持 food / retail")
    # 品类要**按业态**校验:水果店不该选得到「川湘菜」。
    # 只查合并表的话两个业态的品类互相串,而 category 只有一列,
    # 串进去之后光看这一列解释不了它属于哪个业态
    if category is not None and category not in CATEGORIES_BY_BIZ[biz_type]:
        raise HTTPException(422, "该业态没有这个品类")

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
        # 按销量排必须先聚合才知道谁在前 —— 只有那一种走全量模板
        tmpl = _NEARBY_SQL_BY_SALES if sort == "sales" else _NEARBY_SQL_TMPL
        stmt = text(tmpl.format(
            order_by=_SORTS[sort],
            # 距离本来就为排序算了一次(_DIST_EXPR),顺手取出来返回 ——
            # 不返回的话客户端只能拿两点直线再算一遍,而那份更糙
            dist_expr=_DIST_EXPR,
            category_clause=(
                "AND m.category = :category" if category else ""),
            filter_clause="\n      ".join(filters)))
        # 一趟拿完:商家整行 + 月售 + 距离 + 人均。
        #
        # 老写法是两趟 —— 第一趟只取 id/月售/距离/人均,第二趟再
        # `WHERE id IN (那 20 个)` 把商家 85 列取回来。第二趟纯属多余
        # 往返:同一个页码,同一批 id,库里刚扫过的行。实测一页 20 家
        # 0.52ms、一页 50 家 0.99ms,占函数本体的 12~14%。
        #
        # from_statement 让 ORM 直接吃这条原生 SQL 的结果:回来的仍是
        # 真的 Merchant 实体,kitchen_cam / busy_active 这些挂在模型上的
        # @property 照常可用 —— 不能改成手搓字典,那等于把这些口径
        # 复制一份出来,迟早和模型对不上
        rows = (await db.execute(
            select(Merchant,
                   literal_column("sales"),
                   literal_column("distance_m"),
                   literal_column("avg_spend_cents")).from_statement(stmt),
            {"lat": lat, "lng": lng, "biz_type": biz_type,
             "radius_m": _browse_radius_m(radius_m),
             "avg_min_orders": AVG_SPEND_MIN_ORDERS,
             "limit": limit, "offset": offset,
             **({"category": category} if category else {}),
             **filter_params},
        )).all()
        if not rows:
            return []
        outs = []
        for shop, sales, dist, avg_spend in rows:
            out = MerchantOut.model_validate(shop)
            out.monthly_sales = sales
            # PostGIS geography 的 <-> 是**球面**距离(米),比客户端的
            # haversine 准;但它仍是直线不是骑行路径 —— 字段名和文案
            # 都不许说成「骑行 X 公里」
            out.distance_m = int(dist) if dist is not None else None
            # 样本不足时 SQL 已经给了 NULL —— 原样透传,不补默认值。
            # 补一个数就等于编造价位预期
            out.avg_spend_cents = avg_spend
            outs.append(out)
        await _fill_top_dishes(db, outs)
        return outs
    # 无定位兜底:同样要认筛选条件,否则用户一关定位筛选就静默失效
    query = select(Merchant).where(
        Merchant.is_open.is_(True), Merchant.status == MerchantStatus.approved,
        Merchant.biz_type == biz_type)
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
    # 排序在这条兜底路径上此前是缺的:没有 ORDER BY 时 Postgres 的返回顺序
    # 不作保证,加了 offset 就会漏店和重店。按 id 是任意但**稳定**的全序
    result = await db.scalars(query.order_by(Merchant.id)
                              .limit(limit).offset(offset))
    outs = [MerchantOut.model_validate(m) for m in result]
    await _fill_top_dishes(db, outs)
    return outs


@router.get("/categories")
async def merchant_categories(biz_type: str | None = None):
    """品类清单(slug -> 中文名),管理后台下拉与三端展示共用。

    带 `biz_type` 给该业态的品类;**不带给餐饮**,和加零售之前一字不差。

    这个默认值不是随手定的。这个接口喂的是商家端的品类下拉,
    所以它必须是**某一个业态**的清单,不能是合并表 —— 合并表意味着
    一家快餐店的下拉里出现「母婴玩具」,选了之后服务端才报错。
    默认给餐饮既保住了存量客户端,又不会让它们看见不该看见的选项。
    (e2e_category 守着这条:它断言这里正好 23 个。)
    """
    if biz_type is None:
        return FOOD_CATEGORIES
    if biz_type not in CATEGORIES_BY_BIZ:
        raise HTTPException(422, "biz_type 仅支持 food / retail")
    return CATEGORIES_BY_BIZ[biz_type]


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
    biz_type: str = "food",
    db: AsyncSession = Depends(get_db),
):
    """搜索营业中的商家:店名或在售菜名命中。

    排序 sort=comprehensive(评分×销量×距离衰减,默认)/distance/rating/sales;
    筛选:max_distance_m 距离上限、min_rating 评分下限、has_promo 有优惠、
    max_min_order_cents 起送价上限。综合/距离排序需要 lat/lng,缺则退化按评分。
    绝不做竞价排名——排序只用真实评分/销量/距离,商家花钱买不到靠前。

    距离口径与首页列表同一个数(配送上限):此前搜索**不传就完全不限距离**,
    搜出来的店比首页还远,一样是点进去下不了单。
    """
    has_pos = lat is not None and lng is not None
    if sort in ("comprehensive", "distance") and not has_pos:
        sort = "rating"  # 没定位无法算距离,退化到评分
    if sort not in _SEARCH_SORTS:
        raise HTTPException(422, "sort 仅支持 comprehensive/distance/rating/sales")

    # **二元组预筛 + ILIKE 精确复核。**
    #
    # `sz_bigrams(name) @> sz_bigrams(:q)` 走得动 GIN 索引(迁移 0115),
    # 负责把候选从几万缩到几个;ILIKE 负责判对错。
    # 「name 含 q」⇒「q 的每个二元组都在 name 里」,所以预筛**不会漏**;
    # 反过来会有假阳性,由 ILIKE 兜住。
    #
    # 单字查询时 sz_bigrams 是空数组,`@> '{}'` 对所有行成立 ——
    # 自然退化成全表扫,结果仍然正确,只是没有索引收益。
    #
    # 为什么不用 pg_trgm:实测三元组要 3 个字符才有选择性,
    # 而中文搜索多是两个字(烧烤/火锅/奶茶),那种情况它比全表扫还慢。
    if biz_type not in CATEGORIES_BY_BIZ:
        raise HTTPException(422, "biz_type 仅支持 food / retail")
    params: dict = {"pattern": f"%{q.strip()}%", "q": q.strip(),
                    "biz_type": biz_type}
    where = ["m.is_open = true", "m.status = 'approved'",
             # 酒店走 /stays 频道,不混进这里;零售与外卖各搜各的业态
             "m.biz_type = :biz_type",
             "((sz_bigrams(m.name) @> sz_bigrams(:q) AND m.name ILIKE :pattern)"
             " OR EXISTS ("
             " SELECT 1 FROM dishes d WHERE d.merchant_id = m.id"
             " AND d.is_on_sale AND sz_bigrams(d.name) @> sz_bigrams(:q)"
             " AND d.name ILIKE :pattern))"]
    if has_pos:
        params["lat"], params["lng"] = lat, lng
        # 不传 max_distance_m 也要卡住:默认无限远等于把"搜得到但送不到"
        # 做成了常态。传了则收敛到配送上限,和首页列表同一个数
        params["radius_m"] = _browse_radius_m(max_distance_m)
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
        SELECT m.id, count(o.id) AS sales,
               {'min(' + _SEARCH_DIST + ')' if has_pos else 'NULL'} AS distance_m
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
    id_sales = [(r[0], r[1], r[2]) for r in rows]
    if not id_sales:
        return []
    by_id = {m.id: m for m in await db.scalars(
        select(Merchant).where(Merchant.id.in_([i for i, _, _ in id_sales])))}
    outs = []
    for mid, sales, dist in id_sales:  # 保持 SQL 已排好的顺序
        if mid in by_id:
            out = MerchantOut.model_validate(by_id[mid])
            out.monthly_sales = sales
            # 搜索没带定位时 distance_m 是 NULL —— 那时客户端也不该显示距离
            out.distance_m = int(dist) if dist is not None else None
            outs.append(out)
    await _fill_top_dishes(db, outs)
    return outs


@router.get("/suggest")
async def search_suggest(
    q: str = Query(min_length=1, max_length=30),
    biz_type: str = "food",
    db: AsyncSession = Depends(get_db),
):
    """搜索联想:匹配的店名 + 热门在售菜名(前缀优先),各最多 6 条。"""
    pattern = f"%{q.strip()}%"
    prefix = f"{q.strip()}%"
    shops = (await db.scalars(
        select(Merchant.name).where(
            Merchant.is_open.is_(True),
            Merchant.status == MerchantStatus.approved,
            Merchant.biz_type == biz_type,
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
        # **按申请的业态校验**,不查合并表 —— 查合并表的话一家快餐店
        # 能把自己归到「母婴玩具」,而 category 只有一列,之后光看它
        # 解释不了这个值属于哪个业态
        if payload.category not in categories_of(payload.biz_type):
            raise HTTPException(422, f"{payload.biz_type} 业态没有这个品类")
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
    out.viewer_is_owner = shop.owner_id == user.id
    # 证照档位:客户端据此决定横幅的轻重(unknown 不出横幅)
    from ..services.licenses import days_left, stage
    out.license_stage = stage(shop.license_expires_at)
    out.license_days_left = days_left(shop.license_expires_at)
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
    shop = await owned_shop(db, user)
    if shop is None:
        raise HTTPException(404, "还没开店")

    changes = payload.model_dump(exclude_none=True)
    # 同入驻:按**这家店的**业态校验,不查合并表
    if ("category" in changes
            and changes["category"] not in categories_of(shop.biz_type)):
        raise HTTPException(422, f"{shop.biz_type} 业态没有这个品类")
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
    if changes.get("license_subject"):
        await guard_text(db, changes["license_subject"], "证照主体名称")

    # 换了新证 = 重新起算提醒。**必须清水位** —— 不清的话
    # "2026-08-05:soon" 这条记录还在,新证到期前 30 天那次提醒会被去重掉,
    # 商家再也收不到第一次提醒(而这恰恰是最有用的那一次)
    if ("license_expires_at" in changes
            and changes["license_expires_at"] != shop.license_expires_at):
        changes["license_notified"] = []
        # **不在这里自动解除 food_safety_hold**。证换了理由确实没了,
        # 但"新证是真的吗"只有人看得出来 —— 自动解除等于让商家
        # 随手填一个未来日期就把停业解开,那这道闸门就白设了。
        # 换证后的店会出现在 admin 的 /admin/merchants/license-alerts 里,
        # 核验通过后走既有的 food-safety-hold/release

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
    # 有效期/主体名称/营业执照号同属资质,同一道闸:
    # 到期日要是能随手改成 2099,整个到期闸门就白设了 ——
    # 续证走 POST /me/license-renewal 的复审通道
    _LICENSE_FIELDS = ("license_no", "license_image_url",
                       "license_expires_at", "business_license_no",
                       "license_subject")
    if (any(k in changes for k in _LICENSE_FIELDS)
            and shop.status != MerchantStatus.rejected):
        raise HTTPException(
            403, "资质变更需平台核验:续证请在「证照」页提交新证,"
                 "平台核验后自动生效")

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
    if payload.promise_ready_minutes is not None:
        from ..services import prep_time
        await prep_time.invalidate(shop.id)
    return shop


@router.get("/me/dishes", response_model=list[MerchantDishOut])
async def my_dishes(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家管理视角:含已下架菜品。注意必须注册在 /{merchant_id}/dishes 之前。"""
    shop = await owned_shop(db, user)
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
        # **必须构造 MerchantDishOut**:这里造 DishOut 的话,
        # response_model 再套一层 MerchantDishOut 时 cost_cents 拿不到值,
        # 只剩默认的 0 —— 库里是对的,是序列化这一步丢的
        out = MerchantDishOut.model_validate(dish)
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


#: 菜品月售的缓存时长(秒)。
#:
#: 这条聚合要扫 30 天的 orders 再把 items(JSONB)逐行展开,
#: 实测 **19.7ms 一次,而且和拉多少个菜无关** —— 它是按商家算的。
#:
#: 分页之前一次菜单只算一次,无所谓;分页之后客户端**每切一个分类就调一次**,
#: 十个分类的超市就要白付十遍。这是分页顺手引入的开销,得一起解决。
#:
#: 敢缓存的理由和 prep_time 一样:这是 30 天的累计销量,一分钟里多一单
#: 少一单挪不动它。代价是新上架的菜"月售 0"最多晚一分钟变成 1。
_DISH_SALES_TTL_SECONDS = 60
_DISH_SALES_PREFIX = "dishsales:v1:"


async def _dish_sales(db: AsyncSession, merchant_id: int) -> dict[int, int]:
    """菜品 → 近 30 天售出份数。带缓存,见 _DISH_SALES_TTL_SECONDS。"""
    import json as _json

    from ..redis_client import get_redis

    key = f"{_DISH_SALES_PREFIX}{merchant_id}"
    redis = get_redis()
    try:
        raw = await redis.get(key)
        if raw is not None:
            return {int(k): v for k, v in _json.loads(raw).items()}
    except Exception:
        pass  # 缓存挂了照常现算,只是慢一点

    rows = await db.execute(_DISH_SALES_SQL, {"merchant_id": merchant_id})
    sales = {row.dish_id: row.sold for row in rows}
    try:
        await redis.set(key, _json.dumps({str(k): v for k, v in sales.items()}),
                        ex=_DISH_SALES_TTL_SECONDS)
    except Exception:
        pass  # 写不进去只是下次还得现算,不影响正确性
    return sales


#: 分类清单的排序 = 该分类第一道菜的建立顺序,和菜单接口同一条规则。
#: **不能按 category 字符串排** —— 未分类的菜 category 是空串,
#: 一排就把它顶到分类栏第一个并默认选中。
_DISH_CATEGORIES_SQL = text(
    """
    SELECT category AS name, count(*)::int AS count, min(id) AS ord
    FROM dishes
    WHERE merchant_id = :merchant_id AND is_on_sale = true
    GROUP BY category
    ORDER BY ord
    """
)


@router.get("/{merchant_id}/dish-categories")
async def dish_categories(merchant_id: int,
                          db: AsyncSession = Depends(get_db)):
    """点单页左侧的分类栏(名称 + 每类多少个),按菜单同一条顺序。

    ## 为什么要单独一个接口

    分类栏原先是客户端从**整份菜单**里推出来的。餐馆几十道菜没问题,
    超市不行:实测演示店 2837 个在售商品一次拉完是 1.25 MB,
    而即时零售的前置仓 SKU 是 5000–10000。

    有了它,客户端就能只拉当前分类的商品(见 menu 的 category 参数),
    而分类栏照样一次拿全 —— 分类数是个位数,这个接口很轻。

    空字符串是「未分类」,原样返回,不在服务端改写成"其他" ——
    客户端本来就有这个映射,两边各写一份迟早对不上。
    """
    rows = (await db.execute(
        _DISH_CATEGORIES_SQL, {"merchant_id": merchant_id})).all()
    return [{"name": r.name, "count": r.count} for r in rows]


@router.get("/{merchant_id}/dishes", response_model=list[DishOut])
async def menu(
    merchant_id: int,
    category: str | None = None,
    ids: list[int] = Query(default=[]),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """商家在售商品。`category` 只取这一类,`ids` 按 id 取,`limit`/`offset` 翻页。

    `ids` 是**分页的配套**,不是可有可无的便利:购物车里只存
    `{dish_id, quantity, choices}`,进店时要靠菜单把 id 映射回商品对象才能
    还原。不分页时整份菜单里什么都有;一分页,跨分类的购物车就还原不了 ——
    用户会发现"我加的东西没了"。所以按 id 取这条路必须有。

    ⚠️ **limit 默认不限,而且不许改成有默认值**。这个接口的老调用方
    (存量 App)不传参数、拿的是整份菜单;加一个默认上限的话它们会
    **静默地少几道菜**,而界面上看不出任何异常 —— 用户只会觉得
    "这家店怎么没有那道菜了"。宁可老客户端慢,不能让它错。

    新客户端按分类拉(见 /dish-categories),超市才不会一次吞几 MB。
    """
    result = await db.scalars(
        select(Dish)
        .where(Dish.merchant_id == merchant_id, Dish.is_on_sale.is_(True),
               *([Dish.category == category] if category is not None else []),
               # 上限和 limit 同一个数:这条路径也是客户端能直接控制条数的,
               # 不封顶就等于给了一个绕过分页的口子
               *([Dish.id.in_(ids[:200])] if ids else []))
        # 分类之间的先后 = 该分类第一道菜的建立顺序(与加 sort 之前的
        # 行为一致)。**不能直接按 category 字符串排** —— 未分类的菜
        # category 是空串,一排就把"其他"顶到分类栏第一个并默认选中。
        # 组内再按 sort(商家排的顺序,用户端照着看)
        .order_by(func.min(Dish.id).over(partition_by=Dish.category),
                  Dish.sort, Dish.id)
        .limit(limit).offset(offset)
    )
    dishes = list(result)
    sales = await _dish_sales(db, merchant_id)
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


@router.post("/me/dishes", response_model=MerchantDishOut)
async def add_dish(
    payload: DishIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await owned_shop(db, user)
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


@router.patch("/me/dishes/{dish_id}", response_model=MerchantDishOut)
async def update_dish(
    dish_id: int,
    payload: DishPatch,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """改价/改库存/上下架/限时折扣。已有订单存的是快照,不受影响。"""
    shop = await owned_shop(db, user)
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
    # packing_fee_cents 的 None 是**有语义的**(清掉菜品额外打包费,
    # 退回店铺的每单打包费),所以不在这张表里 —— 它和 daily_stock /
    # flash_* 一样是真 nullable 列。cost_cents 则是 NOT NULL,
    # 显式传 null 会在 flush 时炸 IntegrityError,归一化成 0(= 没录过)
    _EMPTY_FOR_NULL = {
        "badges": [], "options": [], "combo_items": [],
        "name": None, "category": "", "description": "",
        "image_url": "", "serve_window": "", "cost_cents": 0,
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
    shop = await owned_shop(db, user)
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
    shop = await owned_shop(db, user)
    if shop is None:
        return []
    from ..services.privacy_phone import mask_phone
    # 已注销的店员不该还挂在名单上。注销时会删 merchant_staff 行,
    # 这里再加一道 where 兜住存量(修复脚本跑之前的那些行)
    rows = (await db.execute(
        select(MerchantStaff, User)
        .join(User, User.id == MerchantStaff.user_id)
        .where(MerchantStaff.merchant_id == shop.id,
               User.deleted_at.is_(None))
        .order_by(MerchantStaff.created_at))).all()
    # mask_phone 而不是手写切片:墓碑行的 phone 是 `del{id}_{hex}`,
    # `phone[:3] + "****" + phone[-4:]` 会把它渲染成 `del****9af0`
    return [{"user_id": s.user_id, "name": s.name or u.name,
             "phone": mask_phone(u.dial_phone)}
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
    shop = await owned_shop(db, user)
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
    shop = await owned_shop(db, user)
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
    shop = await owned_shop(db, user)
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
    shop = await owned_shop(db, user)
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
    shop = await owned_shop(db, user)
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
    shop = await owned_shop(db, user)
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
    shop = await owned_shop(db, user)
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
    # 被处置的账号暂停领券(**下单不拦**),给可见提示可申诉。
    # 走 level_for:目录计次和人工直接处置两条通道都要认,理由同 orders.py
    from ..services.enforcement import LEVEL_NONE, level_for
    if await level_for(user, db) != LEVEL_NONE:
        raise HTTPException(
            403, "账号存在处置中,已暂停领券;"
                 "原因和申诉入口在「我的 - 账号状态」")
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


async def _my_shop_or_404(db: AsyncSession, user: User,
                          merchant_id: int | None = None) -> Merchant:
    """当前请求要操作的店(店主级权限)。

    **单店商家行为一字不变**:不传 merchant_id 时取"我唯一的那家店"。
    连锁场景由客户端显式传 merchant_id,权限校验收敛在
    services.staff.resolve_shop 里 —— 判定只写一遍,
    才不会每加一个端点就多一次"A 店店长能改 B 店"的机会。
    """
    from ..services.staff import resolve_shop
    shop, is_owner = await resolve_shop(db, user, merchant_id,
                                        need_owner=True)
    if shop is None or not is_owner:
        raise HTTPException(404, "还没开店")
    return shop


async def _money_shop_or_403(db: AsyncSession, user: User,
                             merchant_id: int | None = None) -> Merchant:
    """资金动作的店(必须是登记的 owner 本人)。

    品牌 manager 在别处算"店主级权限"(改价、改设置都放行),
    但钱不走那条线 —— 运营授权不等于可以把店里的钱提到自己卡上。
    """
    from ..services.staff import money_shop
    shop = await money_shop(db, user, merchant_id)
    if shop is None:
        raise HTTPException(
            403, "只有店铺登记的经营者本人能操作资金(提现、收款账户)")
    return shop


# ---------- 微信特约商户进件资料(#203/#206) ----------
#
# 为什么走 _money_shop_or_403 而不是 _my_shop_or_404:
# 这里填的是「微信把货款结到哪张卡」。品牌 manager 在别处算店主级权限
# (改价、改设置都放行),但改结算账户不是运营动作 ——
# 运营授权不等于可以把这家店的货款改到自己卡上。口径与提现/收款账户一致。
#
# 另一半原因是**入口收敛**:身份证号和银行账号明文只经过这两个端点,
# 能碰它们的人越少,泄露面越小。


@router.get("/me/applyment", response_model=ApplymentOut)
async def my_applyment(
    merchant_id: int | None = None,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """我的进件资料 + 完整度 + 状态。敏感字段只回尾 4 位。

    `missing` 是给前端画「还差什么」的**唯一口径** —— 别在客户端再抄一份
    必填清单:抄了就会有一天服务端加了字段而某个端没跟上,
    商家在那个端上看着 100% 却怎么也提交不成功。
    """
    shop = await _money_shop_or_403(db, user, merchant_id)
    return applyment_out(shop)


@router.put("/me/applyment", response_model=ApplymentOut)
async def save_applyment(
    payload: ApplymentIn,
    merchant_id: int | None = None,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """提交/更新进件资料。**这一版只落库,不调微信。**

    调不了:进件走 `/v3/applyment4sub/` 还是 `/v3/ecommerce/applyments/`
    取决于服务商类目,两套 API 完全不通用,类目答案没下来之前写哪套都可能白写。
    但资料现在就得收 —— 没有商家配合,一家特约商户都开不出来,
    这是整条链路里最耗时的一环。

    只写这次传了的字段(None = 没动):商家分几次填是常态,
    营业执照在抽屉里、银行账号要翻网银、身份证要拍两张,
    强制一次填完的结果是填到一半退出去就全丢。
    """
    from ..services.crypto import encrypt

    shop = await _money_shop_or_403(db, user, merchant_id)

    # 微信侧已经在处理的单子不让改。
    # 改了库里也报不上去(报送的是当时那一版),只会让商家以为"我已经改好了"
    # 而实际卡在原来的驳回上。要改先让平台侧退回 rejected/not_submitted
    if shop.applyment_status in APPLYMENT_LOCKED_STATUSES:
        raise HTTPException(
            409, f"当前状态({shop.applyment_status})不能修改资料;"
                 "如需变更请联系平台客服")

    # exclude_unset:没传的字段不动。**再滤掉显式的 null** ——
    # 这些列都是 NOT NULL(默认 ""),把 None 写进去会在 commit 时炸成 500。
    # 想清空某项就传空串 ""(语义也更明确:"我把它清了",而不是"我没提这事")
    data = {k: v for k, v in payload.model_dump(exclude_unset=True).items()
            if v is not None}
    # 明文字段单独处理:落库前换成密文 + 尾号,明文不进库、不出任何接口
    id_no = data.pop("legal_person_id_no", None)
    account_no = data.pop("settle_account_no", None)
    for field, value in data.items():
        setattr(shop, field, value.strip() if isinstance(value, str) else value)
    if id_no is not None:
        id_no = id_no.strip().upper()
        shop.legal_person_id_encrypted = encrypt(id_no) if id_no else ""
        shop.legal_person_id_tail = id_no[-4:] if id_no else ""
    if account_no is not None:
        # 粘贴过来的卡号常带空格,入参校验时按去空格判的,落库也去
        account_no = account_no.replace(" ", "")
        shop.settle_account_no_encrypted = encrypt(account_no) if account_no else ""
        shop.settle_account_tail = account_no[-4:] if account_no else ""

    # 状态流转规则抽在 schemas.next_applyment_status 里(纯函数,单测覆盖),
    # 不散在这个已经很长的处理函数里
    nxt = next_applyment_status(shop.applyment_status,
                                complete=not applyment_missing(shop))
    if nxt is not None:
        shop.applyment_status = nxt
        if nxt == "submitted":
            # 驳回原因一并清掉 —— 留着会让商家以为改完还是被驳回的
            shop.applyment_reject_reason = ""
        shop.applyment_updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shop)
    return applyment_out(shop)


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
        # 末端补到**本周**,不是补到"最后一个有单的周"。
        #
        # 原来是 `last = rows[-1][0].date()`:本周一单都还没有的时候,
        # 本周就整个不出现在图上 —— 商家看到的折线停在上周,
        # 而这和上面那段"空周被连成直线"是同一个毛病,只是发生在最后一格。
        #
        # 最容易撞上的时刻:周一刚过零点。CI 在 UTC 16:17 跑
        # (北京时间周一 00:17),本周确实还没有单,于是图上没有 partial 那格,
        # 环比也就失去了"本周不参与比较"的那个标记。
        last = max(rows[-1][0].date(), this_week)
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


async def _merchant_wallet(db: AsyncSession, shop: Merchant) -> WalletOut:
    """店铺钱包。

    **已提现一律按 shop.owner_id 减,不按调用者。** 余额是拿
    merchant_id 算出来的整店营收,两边口径不是同一个人的话,
    非店主看到的"可提现"里不含店主已经提走的部分 —— 同一笔钱能被算两遍。
    """
    owner_id = shop.owner_id
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
    shop = await _money_shop_or_403(db, user)
    return await _merchant_wallet(db, shop)


@router.get("/me/withdrawals", response_model=list[WithdrawalOut])
async def merchant_withdrawals(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    await _money_shop_or_403(db, user)
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
    shop = await _money_shop_or_403(db, user)
    from ..models import PayoutAccount
    from .payout import account_recently_changed
    account = await db.scalar(
        select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    if account is None:
        raise HTTPException(422, "请先在对账页登记收款账户(建议对公户),再申请提现")
    await db.execute(select(User).where(User.id == user.id).with_for_update())
    current = await _merchant_wallet(db, shop)
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


# ---------- 定时改价 / 定时上下架 ----------

# 过期多久就不再补跑。把三天前该降的价降下来,商家会莫名其妙亏一笔 ——
# 而他早就忘了自己设过这个
_SCHEDULE_GRACE_MINUTES = 30


@router.get("/me/dish-schedules")
async def my_dish_schedules(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """待执行与最近执行过的定时动作。"""
    from ..models import DishSchedule

    shop = await _my_shop_or_404(db, user)
    rows = (await db.execute(
        select(DishSchedule, Dish.name)
        .join(Dish, Dish.id == DishSchedule.dish_id)
        .where(DishSchedule.merchant_id == shop.id)
        .order_by(DishSchedule.status.desc(), DishSchedule.run_at)
        .limit(200))).all()
    return {
        "items": [{
            "id": r.id, "dish_id": r.dish_id, "dish_name": name,
            "action": r.action, "price_cents": r.price_cents,
            "run_at": r.run_at, "status": r.status, "note": r.note,
        } for r, name in rows],
        "note": "到点自动执行。**错过太久的不会补跑** —— "
                "把三天前该降的价降下来,你会莫名其妙亏一笔。"
                "与「供应时段」不是一回事:那个是每天重复、只灰不改价。",
    }


@router.post("/me/dish-schedules")
async def add_dish_schedule(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """加一条定时动作。action: price 改价 / on 上架 / off 下架。"""
    from ..models import DishSchedule

    shop = await owned_shop(db, user)
    if shop is None:
        raise HTTPException(404, "还没开店")
    dish = await db.get(Dish, int(payload.get("dish_id") or 0))
    if dish is None or dish.merchant_id != shop.id:
        raise HTTPException(404, "菜品不存在")
    action = str(payload.get("action") or "")
    if action not in ("price", "on", "off"):
        raise HTTPException(422, "动作只支持:改价 / 上架 / 下架")
    price = None
    if action == "price":
        try:
            price = int(payload["price_cents"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "改价要填新价格")
        if not 1 <= price <= 1_000_000:
            raise HTTPException(422, "价格超出范围")
    try:
        run_at = datetime.fromisoformat(str(payload["run_at"]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, "执行时间格式不对")
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)
    if run_at <= datetime.now(timezone.utc):
        # 定过去的时间等于"立刻执行",但商家想要的多半是明天同一时刻 ——
        # 与其猜,不如让他重填
        raise HTTPException(422, "执行时间必须晚于现在")

    n = await db.scalar(select(func.count(DishSchedule.id)).where(
        DishSchedule.merchant_id == shop.id,
        DishSchedule.status == "pending"))
    if n >= 100:
        raise HTTPException(422, "待执行的定时任务最多 100 条")

    row = DishSchedule(merchant_id=shop.id, dish_id=dish.id, action=action,
                       price_cents=price, run_at=run_at,
                       note=str(payload.get("note", "")).strip()[:100])
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "run_at": row.run_at, "status": row.status}


@router.delete("/me/dish-schedules/{schedule_id}")
async def cancel_dish_schedule(
    schedule_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import DishSchedule

    shop = await owned_shop(db, user)
    row = await db.get(DishSchedule, schedule_id)
    if shop is None or row is None or row.merchant_id != shop.id:
        raise HTTPException(404, "定时任务不存在")
    if row.status != "pending":
        raise HTTPException(409, "这条已经执行过了")
    row.status = "cancelled"
    await db.commit()
    return {"ok": True}


# ---------- 顾客备注与口味标签 ----------

@router.get("/me/customers/{user_id}/note")
async def get_customer_note(
    user_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """这位顾客在**本店**的备注。不跨店 —— 换一家店就是干净的。"""
    from ..models import CustomerNote

    shop = await _my_shop_or_404(db, user)
    row = await db.scalar(select(CustomerNote).where(
        CustomerNote.merchant_id == shop.id, CustomerNote.user_id == user_id))
    return {
        "note": row.note if row else "",
        "tags": row.tags if row else [],
        "updated_at": row.updated_at if row else None,
    }


@router.put("/me/customers/{user_id}/note")
async def set_customer_note(
    user_id: int,
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """记一条备注。**必须这位顾客真的在本店下过单** ——
    否则这就成了一个可以给任意用户 id 写字的接口。"""
    from ..models import CustomerNote
    from ..services.moderation import guard_text

    shop = await _my_shop_or_404(db, user)
    ordered = await db.scalar(select(Order.id).where(
        Order.merchant_id == shop.id, Order.customer_id == user_id).limit(1))
    if ordered is None:
        raise HTTPException(404, "这位顾客没在本店下过单")

    note = str(payload.get("note", "")).strip()[:200]
    if note:
        await guard_text(db, note, "顾客备注")
    tags = [str(t).strip()[:10] for t in (payload.get("tags") or [])][:8]
    for t in tags:
        await guard_text(db, t, "口味标签")

    row = await db.scalar(select(CustomerNote).where(
        CustomerNote.merchant_id == shop.id, CustomerNote.user_id == user_id))
    if row is None:
        row = CustomerNote(merchant_id=shop.id, user_id=user_id)
        db.add(row)
    row.note = note
    row.tags = tags
    await db.commit()
    return {"ok": True, "note": note, "tags": tags}


# ---------- 开放接口的用量与日志(开发者后台) ----------

@router.get("/me/api-usage")
async def my_api_usage(
    days: int = Query(default=7, ge=1, le=30),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """我的 API Key 最近的用量:调用量、错误率、被限流次数。

    **错误率和限流分开报**,因为它们要做的事完全不同:
    错误率高多半是集成写错了(看日志改代码),
    限流高是调得太密(改成退避重试)。混成一个"失败率"两边都指导不了。
    """
    from datetime import timedelta

    from ..models import ApiCall

    shop = await _my_shop_or_404(db, user)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    row = (await db.execute(text("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE status >= 400 AND status <> 429) AS errors,
               count(*) FILTER (WHERE status = 429) AS throttled,
               coalesce(round(avg(duration_ms)), 0) AS avg_ms,
               coalesce(max(duration_ms), 0) AS max_ms
        FROM api_calls
        WHERE kind = 'key' AND merchant_id = :m AND created_at >= :s
    """), {"m": shop.id, "s": since})).first()
    total = int(row.total or 0)
    by_day = [{"day": str(r[0]), "calls": r[1]} for r in (await db.execute(
        text("""
        SELECT created_at::date AS d, count(*) FROM api_calls
        WHERE kind = 'key' AND merchant_id = :m AND created_at >= :s
        GROUP BY 1 ORDER BY 1
    """), {"m": shop.id, "s": since})).all()]
    return {
        "days": days,
        "total": total,
        "errors": int(row.errors or 0),
        "throttled": int(row.throttled or 0),
        "error_ratio": round((row.errors or 0) / total, 3) if total else 0.0,
        "avg_ms": int(row.avg_ms or 0),
        "max_ms": int(row.max_ms or 0),
        "by_day": by_day,
        "note": ("错误率高多半是集成写错了,看下面的日志改代码;"
                 "限流高是调得太密,改成退避重试。限流额度公开在 docs/API.md。"),
    }


@router.get("/me/api-logs")
async def my_api_logs(
    limit: int = Query(default=100, ge=1, le=500),
    status_min: int = Query(default=0, ge=0, le=599),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """最近的调用记录。**不含请求体和响应体。**

    里面是收货地址、手机号、备注里的忌口 —— 为了让开发者好排查而把这些
    多存一份,是拿用户的隐私补贴开发体验。方法、路径、状态码、耗时,
    足够回答「我的集成为什么失败」;答不了的那部分,复现一次比长期存着划算。
    """
    from ..models import ApiCall

    shop = await _my_shop_or_404(db, user)
    q = select(ApiCall).where(ApiCall.kind == "key",
                              ApiCall.merchant_id == shop.id)
    if status_min:
        q = q.where(ApiCall.status >= status_min)   # 只看出错的
    rows = (await db.scalars(
        q.order_by(ApiCall.id.desc()).limit(limit))).all()
    return {
        "items": [{
            "method": r.method, "path": r.path, "status": r.status,
            "duration_ms": r.duration_ms,
            "at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows],
        "note": "不记请求体和响应体 —— 那里面有顾客的地址和手机号。",
    }


# ---------- 异常订单标记(只上报,不给拉黑权) ----------

@router.post("/me/orders/{order_no}/flag")
async def flag_order(
    order_no: str,
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """标记疑似职业索赔 / 恶意差评。

    ## 标记之后会发生什么(界面上必须原样说清楚)

    **只上报给平台核查,不会自动对这位顾客做任何处置。** 我们不给商家
    拉黑顾客的权力 —— 给了的话它会变成报复工具(差评了就拉黑)。
    而真正的职业索赔是**跨店行为**:一个人在十家店用同样的话术要退款,
    单店老板永远发现不了,只有平台看得到全局。

    所以商家标记完不会立刻发生任何事。这一点必须诚实告诉他,
    否则他会以为按下去就解决了。
    """
    from ..models import OrderFlag
    from ..services.moderation import guard_text

    shop = await _my_shop_or_404(db, user)
    order = await db.scalar(select(Order).where(
        Order.order_no == order_no, Order.merchant_id == shop.id))
    if order is None:
        raise HTTPException(404, "订单不存在")
    kind = str(payload.get("kind") or "other")
    if kind not in ("claim", "review", "other"):
        raise HTTPException(422, "类型只支持:疑似职业索赔 / 疑似恶意差评 / 其他")
    reason = str(payload.get("reason", "")).strip()[:300]
    if len(reason) < 5:
        raise HTTPException(422, "请写清楚为什么可疑(至少 5 个字),"
                                 "平台要靠这段话去核查")
    await guard_text(db, reason, "标记说明")

    dup = await db.scalar(select(OrderFlag).where(
        OrderFlag.merchant_id == shop.id, OrderFlag.order_no == order_no))
    if dup is not None:
        raise HTTPException(409, "这一单已经标记过了")

    db.add(OrderFlag(merchant_id=shop.id, order_no=order_no,
                     user_id=order.customer_id, kind=kind, reason=reason))
    await db.commit()
    return {
        "ok": True,
        "note": "已上报平台核查。**不会自动对这位顾客做任何处置** —— "
                "我们不给商家拉黑顾客的权力,那会变成报复工具。"
                "职业索赔是跨店行为,平台会把多家店的标记放在一起看;"
                "核查有结果会在消息中心通知你。",
    }


@router.get("/me/order-flags")
async def my_order_flags(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """我标记过的单与核查进度。"""
    from ..models import OrderFlag

    shop = await _my_shop_or_404(db, user)
    rows = (await db.scalars(
        select(OrderFlag).where(OrderFlag.merchant_id == shop.id)
        .order_by(OrderFlag.id.desc()).limit(100))).all()
    return {
        "items": [{
            "id": r.id, "order_no": r.order_no, "kind": r.kind,
            "reason": r.reason, "status": r.status,
            "created_at": r.created_at,
        } for r in rows],
        "note": "标记只用于平台核查,不会自动处置顾客。"
                "职业索赔是跨店行为 —— 单店看不出来的,放在一起才看得出。",
    }


# ---------- 菜单批量导入 ----------

_IMPORT_COLUMNS = ("名称", "分类", "价格(元)", "成本(元)", "库存",
                   "描述", "标签", "额外打包费(元)")


@router.get("/me/dishes/import-template")
async def dish_import_template(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """导入模板(CSV)。带两行示例 —— 空模板商家不知道每列该填成什么样。"""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    await _my_shop_or_404(db, user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_IMPORT_COLUMNS)
    w.writerow(["招牌牛腩饭", "主食", "28", "12", "50",
                "十二小时慢炖,不加淀粉", "招牌|微辣", "1"])
    w.writerow(["酸梅汤", "饮品", "6", "1.5", "100", "", "", ""])
    # BOM:Excel 不给 BOM 会把中文认成乱码,商家打开是一屏问号
    return StreamingResponse(
        io.BytesIO(("\ufeff" + buf.getvalue()).encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="menu-template.csv"'})


@router.post("/me/dishes/import-preview")
async def dish_import_preview(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """解析表格并**预览**,不落库。

    ## 为什么一定要两步

    直接落库的话,一次错误的表格能把 80 道菜的价格全改掉,而商家发现时
    已经卖了半天 —— 一列串位就是一整店的价格错乱,退款和差评一起来。
    所以先返回逐行的「新增 / 更新 / 有问题」,商家看过再确认。

    有问题的行**不阻塞其余行**:80 行里错 2 行,不该逼商家把整张表重做。
    """
    from ..schemas import DISH_BADGES

    shop = await _my_shop_or_404(db, user)
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        raise HTTPException(422, "没有解析到任何数据行")
    if len(rows) > 500:
        raise HTTPException(422, "一次最多导入 500 行")

    existing = {d.name: d for d in (await db.scalars(
        select(Dish).where(Dish.merchant_id == shop.id)))}
    seen: set[str] = set()
    out = []
    for i, raw in enumerate(rows):
        r = {k: str(v or "").strip() for k, v in (raw or {}).items()}
        name = r.get("名称", "")[:60]
        problems = []
        if not name:
            problems.append("缺名称")
        elif name in seen:
            problems.append("表格里重复出现")
        seen.add(name)

        def _money(key, required=False):
            v = r.get(key, "")
            if not v:
                if required:
                    problems.append(f"缺{key}")
                return None
            try:
                cents = round(float(v) * 100)
            except ValueError:
                problems.append(f"{key}不是数字")
                return None
            if cents < 0:
                problems.append(f"{key}不能是负数")
                return None
            return cents

        price = _money("价格(元)", required=True)
        cost = _money("成本(元)")
        packing = _money("额外打包费(元)")
        stock = None
        if r.get("库存"):
            try:
                stock = max(0, int(float(r["库存"])))
            except ValueError:
                problems.append("库存不是数字")
        badges = [b for b in r.get("标签", "").replace("、", "|").split("|")
                  if b.strip()]
        bad_badges = [b for b in badges if b not in DISH_BADGES]
        if bad_badges:
            problems.append(f"标签不在白名单:{'、'.join(bad_badges)}")

        hit = existing.get(name)
        out.append({
            "row": i + 2,          # +2:第 1 行是表头,商家看到的行号要对得上
            "name": name,
            "action": "problem" if problems
            else ("update" if hit else "create"),
            "problems": problems,
            "price_cents": price,
            "cost_cents": cost,
            "packing_fee_cents": packing,
            "stock": stock,
            "category": r.get("分类", "")[:20],
            "description": r.get("描述", "")[:200],
            "badges": badges,
            "old_price_cents": hit.price_cents if hit else None,
        })
    return {
        "items": out,
        "create": sum(1 for i in out if i["action"] == "create"),
        "update": sum(1 for i in out if i["action"] == "update"),
        "problem": sum(1 for i in out if i["action"] == "problem"),
        "note": "确认后才会写入。有问题的行会被跳过,其余照常导入 —— "
                "80 行里错 2 行,不该逼你把整张表重做。",
    }


@router.post("/me/dishes/import")
async def dish_import_commit(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """确认导入。只写 action 为 create/update 的行。

    **新建的菜默认下架(is_on_sale=False)**:一次导入几十道菜直接上架,
    图片、描述、库存都还没核对过就出现在顾客面前。商家挨个看过再上,
    比事后一个个下架强。更新已有的菜不动上下架状态(那是门店当下的决定)。
    """
    from ..services.moderation import guard_text

    shop = await _my_shop_or_404(db, user)
    items = payload.get("items") or []
    if not items:
        raise HTTPException(422, "没有可导入的行")
    existing = {d.name: d for d in (await db.scalars(
        select(Dish).where(Dish.merchant_id == shop.id)))}

    created = updated = 0
    for it in items:
        if it.get("action") not in ("create", "update"):
            continue
        name = str(it.get("name", "")).strip()[:60]
        if not name or not it.get("price_cents"):
            continue
        await guard_text(db, name, "菜品名称")
        if it.get("description"):
            await guard_text(db, str(it["description"]), "菜品描述")
        d = existing.get(name)
        if d is None:
            d = Dish(merchant_id=shop.id, name=name, stock=0,
                     is_on_sale=False)   # 导入的新菜默认下架,商家核对后再上
            db.add(d)
            created += 1
        else:
            updated += 1
        d.price_cents = int(it["price_cents"])
        if it.get("cost_cents") is not None:
            d.cost_cents = int(it["cost_cents"])
        if it.get("packing_fee_cents") is not None:
            d.packing_fee_cents = int(it["packing_fee_cents"])
        if it.get("stock") is not None:
            d.stock = int(it["stock"])
        if it.get("category"):
            d.category = str(it["category"])[:20]
        if it.get("description"):
            d.description = str(it["description"])[:200]
        if it.get("badges"):
            d.badges = list(it["badges"])
    await db.commit()
    return {
        "created": created, "updated": updated,
        "note": "新导入的菜默认**下架**,核对图片和库存后再上架 —— "
                "几十道菜没核对就出现在顾客面前,事后一个个下架更麻烦。",
    }


# ---------- 商家系统回调(收银/ERP 主动收单) ----------

@router.get("/me/webhooks")
async def my_webhooks(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """回调配置 + 最近的投递情况。"""
    from ..models import MerchantWebhook, WebhookDelivery
    from ..services.webhooks import EVENTS

    shop = await _my_shop_or_404(db, user)
    hooks = (await db.scalars(
        select(MerchantWebhook)
        .where(MerchantWebhook.merchant_id == shop.id)
        .order_by(MerchantWebhook.id))).all()
    ids = [h.id for h in hooks]
    dead = []
    if ids:
        dead = [{
            "id": d.id, "event": d.event, "order_no": d.order_no,
            "attempts": d.attempts, "last_error": d.last_error,
            "created_at": d.created_at,
        } for d in (await db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id.in_(ids),
                   WebhookDelivery.status == "failed")
            .order_by(WebhookDelivery.id.desc()).limit(50)))]
    return {
        "events": [{"value": k, "label": v} for k, v in EVENTS.items()],
        "items": [{
            "id": h.id, "url": h.url, "events": h.events, "active": h.active,
            "fail_streak": h.fail_streak, "last_error": h.last_error,
            "last_ok_at": h.last_ok_at, "created_at": h.created_at,
        } for h in hooks],
        # 死信:推了五次都没成功的。**摊开给商家看,而不是默默丢掉** ——
        # 他以为收到了、实际没有,比明确失败糟得多
        "failed": dead,
        "note": "签名在 X-SuperZ-Signature 头:HMAC-SHA256(时间戳.请求体)。"
                "请拒绝时间戳偏差超过 5 分钟的请求,并按 X-SuperZ-Delivery "
                "去重 —— 我们会重试,同一件事可能到两次。",
    }


@router.post("/me/webhooks")
async def add_webhook(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """新增回调地址。**密钥明文只在这里给一次**。"""
    import secrets as _secrets

    from ..models import MerchantWebhook
    from ..redis_client import get_redis
    from ..services.webhooks import EVENTS, UnsafeUrl, validate_url
    from .open_api import hash_key

    shop = await _money_shop_or_403(db, user)   # 对外通道属于经营者本人
    url = str(payload.get("url", "")).strip()[:300]
    try:
        validate_url(url)
    except UnsafeUrl as exc:
        raise HTTPException(422, str(exc))
    events = [e for e in (payload.get("events") or []) if e in EVENTS]
    if not events:
        raise HTTPException(422, "至少订阅一个事件")
    n = await db.scalar(select(func.count(MerchantWebhook.id)).where(
        MerchantWebhook.merchant_id == shop.id))
    if n >= 3:
        raise HTTPException(422, "最多配置 3 个回调地址")

    secret = _secrets.token_urlsafe(32)
    hook = MerchantWebhook(merchant_id=shop.id, url=url,
                           secret_hash=hash_key(secret), events=events)
    db.add(hook)
    await db.commit()
    await db.refresh(hook)
    # 明文放 Redis 供签名用(库里只有哈希)。不设过期 ——
    # 回调是长期配置,过期了商家会莫名其妙收不到单
    await get_redis().set(f"webhook:secret:{hook.id}", secret)
    return {
        "id": hook.id, "url": hook.url, "events": hook.events,
        "secret": secret,
        "note": "这是唯一一次看到密钥明文的机会,请立刻保存。"
                "丢了只能重置(重置后旧签名立即失效)。",
    }


@router.delete("/me/webhooks/{hook_id}")
async def remove_webhook(
    hook_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import MerchantWebhook
    from ..redis_client import get_redis

    shop = await _money_shop_or_403(db, user)
    hook = await db.get(MerchantWebhook, hook_id)
    if hook is None or hook.merchant_id != shop.id:
        raise HTTPException(404, "回调不存在")
    await get_redis().delete(f"webhook:secret:{hook.id}")
    await db.delete(hook)
    await db.commit()
    return {"ok": True}


@router.post("/me/webhooks/{hook_id}/retry")
async def retry_failed_deliveries(
    hook_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """把死信重新排队(商家修好自己的服务之后手动补推)。"""
    from datetime import datetime as _dt

    from ..models import MerchantWebhook, WebhookDelivery

    shop = await _money_shop_or_403(db, user)
    hook = await db.get(MerchantWebhook, hook_id)
    if hook is None or hook.merchant_id != shop.id:
        raise HTTPException(404, "回调不存在")
    rows = list(await db.scalars(
        select(WebhookDelivery).where(
            WebhookDelivery.webhook_id == hook.id,
            WebhookDelivery.status == "failed").limit(200)))
    for d in rows:
        d.status = "pending"
        d.attempts = 0
        d.next_retry_at = _dt.now(timezone.utc)
    # 补推前先把闸门打开:停用状态下清扫任务会直接把它们再判死
    hook.active = True
    hook.fail_streak = 0
    await db.commit()
    return {"ok": True, "requeued": len(rows)}


# ---------- 多台云打印机(前厅 / 后厨 / 标签) ----------

_PURPOSES = {"front": "前厅小票", "kitchen": "后厨备餐单", "label": "标签"}
_MAX_PRINTERS = 8


def _printer_out(p) -> dict:
    return {"id": p.id, "sn": p.sn, "name": p.name, "purpose": p.purpose,
            "purpose_label": _PURPOSES.get(p.purpose, p.purpose),
            "auto": p.auto, "options": p.options or {},
            "created_at": p.created_at}


@router.get("/me/printers")
async def my_printers(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """本店绑定的打印机。前厅一台出顾客小票、后厨一台出备餐单是标配。"""
    from ..models import MerchantPrinter

    shop = await _my_shop_or_404(db, user)
    rows = (await db.scalars(
        select(MerchantPrinter)
        .where(MerchantPrinter.merchant_id == shop.id)
        .order_by(MerchantPrinter.id))).all()
    return {
        "enabled": settings.feie_configured,
        "purposes": [{"value": k, "label": v} for k, v in _PURPOSES.items()],
        "items": [_printer_out(p) for p in rows],
        "note": "后厨那张**不印顾客手机号和地址** —— 后厨用不到,"
                "而备餐单会被随手丢在操作台上。前厅那张要印(骑手来取要核对)。",
    }


@router.post("/me/printers")
async def add_printer(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """绑一台新打印机(机身贴纸上的 SN 与 KEY)。"""
    from ..models import MerchantPrinter
    from ..services.moderation import guard_text

    if not settings.feie_configured:
        raise HTTPException(503, _FEIE_DISABLED)
    shop = await _my_shop_or_404(db, user)
    sn = str(payload.get("sn", "")).strip()[:32]
    key = str(payload.get("key", "")).strip()[:32]
    if not sn or not key:
        raise HTTPException(422, "请填写机身贴纸上的 SN 与 KEY")
    purpose = str(payload.get("purpose") or "front")
    if purpose not in _PURPOSES:
        raise HTTPException(422, "用途只支持:前厅小票 / 后厨备餐单 / 标签")
    name = str(payload.get("name", "")).strip()[:30] or _PURPOSES[purpose]
    await guard_text(db, name, "打印机名称")

    n = await db.scalar(select(func.count(MerchantPrinter.id)).where(
        MerchantPrinter.merchant_id == shop.id))
    if n >= _MAX_PRINTERS:
        raise HTTPException(422, f"最多绑定 {_MAX_PRINTERS} 台")
    dup = await db.scalar(select(MerchantPrinter).where(
        MerchantPrinter.merchant_id == shop.id, MerchantPrinter.sn == sn))
    if dup is not None:
        raise HTTPException(409, "这台打印机已经绑过了")

    # 先在飞鹅那边绑,成功了再落库 —— 反过来的话库里有一条打不出东西的记录,
    # 商家看着"已绑定"却永远收不到单
    try:
        await cloud_print.bind_printer(sn, key, name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except httpx.HTTPError:
        raise HTTPException(502, "云打印服务暂时不可用,请稍后再试")

    p = MerchantPrinter(merchant_id=shop.id, sn=sn, name=name,
                        purpose=purpose, auto=True, options={})
    db.add(p)
    # 兼容老字段:第一台前厅机同时写回 Merchant.printer_sn,
    # 让还没升级的客户端/兜底逻辑照样能出票
    if purpose == "front" and not shop.printer_sn:
        shop.printer_sn = sn
        shop.printer_auto = True
    await db.commit()
    await db.refresh(p)
    return _printer_out(p)


@router.patch("/me/printers/{printer_id}")
async def update_printer(
    printer_id: int,
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """改用途 / 改名 / 开关自动出票 / 改小票开关。"""
    from ..models import MerchantPrinter
    from ..services.moderation import guard_text

    shop = await _my_shop_or_404(db, user)
    p = await db.get(MerchantPrinter, printer_id)
    if p is None or p.merchant_id != shop.id:
        raise HTTPException(404, "打印机不存在")
    if "purpose" in payload:
        if payload["purpose"] not in _PURPOSES:
            raise HTTPException(422, "未知用途")
        p.purpose = payload["purpose"]
    if payload.get("name"):
        name = str(payload["name"]).strip()[:30]
        await guard_text(db, name, "打印机名称")
        p.name = name
    if "auto" in payload:
        p.auto = bool(payload["auto"])
    if "options" in payload:
        opt = payload["options"] or {}
        # 白名单:只认这三个开关。不做自由排版编辑器 ——
        # 那个的维护成本远超收益,而且商家排错版就是一屏乱码
        p.options = {k: bool(opt.get(k)) for k in
                     ("show_price", "show_remark", "big_pickup_code")
                     if k in opt}
    await db.commit()
    await db.refresh(p)
    return _printer_out(p)


@router.delete("/me/printers/{printer_id}")
async def remove_printer(
    printer_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import MerchantPrinter

    shop = await _my_shop_or_404(db, user)
    p = await db.get(MerchantPrinter, printer_id)
    if p is None or p.merchant_id != shop.id:
        raise HTTPException(404, "打印机不存在")
    try:
        await cloud_print.unbind_printer(p.sn)
    except (ValueError, httpx.HTTPError):
        # 飞鹅那边解绑失败不该卡住本地删除:商家的诉求是"别再往这台打了",
        # 本地删掉就已经达成了
        logger.warning("飞鹅解绑失败,仍删除本地记录: %s", p.sn)
    if shop.printer_sn == p.sn:
        shop.printer_sn = ""
    await db.delete(p)
    await db.commit()
    return {"ok": True}


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
    printer_id: int | None = None,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """补打小票:自动出票失败、纸打完了、单据丢了,都从这里再打一张。

    [printer_id] 指定补打哪一台(后厨的单丢了就只补后厨那张);
    不传则**所有自动出票的机器各补一张**,与支付成功时那次一致。
    """
    from ..models import MerchantPrinter

    if not settings.feie_configured:
        raise HTTPException(503, _FEIE_DISABLED)
    shop = await _my_shop_or_404(db, user)
    order = await db.scalar(select(Order).where(
        Order.order_no == order_no, Order.merchant_id == shop.id))
    if order is None:
        raise HTTPException(404, "订单不存在")

    stmt = select(MerchantPrinter).where(
        MerchantPrinter.merchant_id == shop.id)
    if printer_id is not None:
        stmt = stmt.where(MerchantPrinter.id == printer_id)
    else:
        stmt = stmt.where(MerchantPrinter.auto.is_(True))
    targets = list(await db.scalars(stmt))
    if not targets and shop.printer_sn and printer_id is None:
        # 兜底:还没在新界面绑过、只有老字段的店
        targets = [MerchantPrinter(sn=shop.printer_sn, purpose="front",
                                   options={})]
    if not targets:
        raise HTTPException(422, "还没绑定云打印机")

    failed = []
    for p in targets:
        try:
            await cloud_print.print_content(
                p.sn, cloud_print.build_ticket(
                    order, shop.name, purpose=p.purpose,
                    options=p.options or {}))
        except ValueError as exc:
            failed.append(f"{p.name or p.sn}:{exc}")
        except httpx.HTTPError:
            failed.append(f"{p.name or p.sn}:云打印服务暂时不可用")
    # **部分成功不算失败**:两台机器补打,后厨那台缺纸不该让前厅那张
    # 也白打一次。全失败才报错,部分失败在返回体里说清是哪台
    if failed and len(failed) == len(targets):
        raise HTTPException(422, ";".join(failed))
    return {"ok": True, "printed": len(targets) - len(failed),
            "failed": failed}


@router.get("/me/finance/daily", response_model=list[DayStatOut])
async def finance_daily(
    days: int = 30,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """按日对账单:订单数、菜品流水、平台佣金、净收入。

    走 _money_shop_or_403 而不是 _my_shop_or_404:这是**钱的明细**,
    与 /me/wallet、/me/withdrawals、/me/finance/statement.csv 同一条边界 ——
    品牌区域经理能改价改设置(那是运营授权),但碰不到钱。
    """
    shop = await _money_shop_or_403(db, user)
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
    # 与 /me/finance/daily 同一条边界:逐单入账明细属于经营者本人
    shop = await _money_shop_or_403(db, user)
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

    # 每单分账明细,与 /me/wallet 同口径:只对经营者本人
    shop = await _money_shop_or_403(db, user)
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
    # 成本按**菜名**匹配销量快照(快照里存的是下单当时的菜名)。
    # 只取录过成本的:cost_cents = 0 是"没录过",不是"成本为零" ——
    # 猜一个成本算出来的毛利,比不显示更糟(商家会照着它定价)
    costs = {name: c for name, c in (await db.execute(
        select(Dish.name, Dish.cost_cents).where(
            Dish.merchant_id == shop.id, Dish.cost_cents > 0))).all()}
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
        # 毛利:只对录过成本的菜给。**不含平台佣金与配送** ——
        # 那是订单层面的,摊到单个菜上只能靠分摊,分摊出来的数不能用来定价。
        # 这里说的就是"卖价 - 进价",商家一眼能对上自己的账
        cost = costs.get(name)
        if cost:
            entry["cost_cents"] = cost
            gross = s["amount_cents"] - cost * s["qty"]
            entry["gross_profit_cents"] = gross
            entry["margin"] = (round(gross / s["amount_cents"], 3)
                               if s["amount_cents"] else 0.0)
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
        # 有几道菜还没录成本 —— 录了才有毛利可看,不催但要让人知道
        "dishes_without_cost": sum(
            1 for d in top_dishes if "margin" not in d),
        "margin_note": "毛利 = 卖价 − 进价,**不含平台佣金与配送费** ——"
                       "那是订单层面的,摊到单个菜上的数不能拿来定价。"
                       "没录成本的菜不算毛利(猜一个成本算出来的数更糟)。",
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
    shop = await owned_shop(db, user)
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
    老库存量商家可能没传图(入驻早于强制上传),只公示证号不报错。

    餐饮店公示两张:营业执照 + 食品经营许可证。此前只有后者 ——
    总局令第 123 号第十一条要求的是"营业执照和食品经营许可证"两样都在
    主页面显著位置持续展示,而酒店那条路径反倒是全的。同一件事,
    两个业态两个口径,漏的那个就是合规缺口。
    """
    shop = await db.get(Merchant, merchant_id)
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "店铺不存在")
    items = []
    # 酒店的 license_no 存的就是营业执照号(入驻表单如此收);
    # 餐饮的 license_no 是食品经营许可证号,营业执照另存 business_license_no
    labels = ({"license": "营业执照", "special": "特种行业许可证(旅馆业)",
               "hygiene": "卫生许可证"} if shop.biz_type == "hotel"
              else {"business_license": "营业执照",
                    "license": "食品经营许可证"})
    for kind, label in labels.items():
        no = ""
        if kind == "license":
            no = shop.license_no or ""
        elif kind == "business_license":
            no = shop.business_license_no or ""
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
            # 证照上的主体名称。光一串信用代码查不出是谁 ——
            # 公示的意义在于用户能对上"这家店背后是哪个法律主体"
            "subject": shop.license_subject or "",
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


#: 「今天发生了什么」里各口径的状态集合。挪到模块级是为了让 SQL 和
#: 说明用同一份定义,别在两处各写一遍
_ONGOING_STATES = (OrderStatus.PAID, OrderStatus.ACCEPTED,
                   OrderStatus.READY, OrderStatus.PICKED_UP)
_DONE_STATES = (OrderStatus.DELIVERED, OrderStatus.COMPLETED)
_EMPTY_DAY = {"orders": 0, "gmv_cents": 0, "ongoing": 0,
              "done": 0, "cancelled": 0, "pickup_orders": 0}


async def _today_and_yesterday(db: AsyncSession,
                               merchant_id: int) -> tuple[dict, dict]:
    """今天 + 昨天的下单口径汇总,**一条 SQL**。

    口径:这是「生意热度」,不是「实际入账」—— 对账页(finance/daily)按
    merchant_earnings 结算口径,未完成的单不在里面;这里按 created_at
    数今天发生了什么,两边数字对不上是正常的。

    原来是 `_day_summary` 跑两遍:两个往返,而且每遍都把那一天的**订单
    行全取回 Python** 再 for 循环数 —— 为了 6 个数字,一家一天 500 单的
    店要传 500 行回来,两天就是 1000 行。商家端前台每 30 秒刷一次。

    现在用条件聚合(`count(*) FILTER (WHERE ...)`)在库里数完,两天靠
    `created_at >= 今天零点` 分组,一次取回 2 行。昨天和今天的时间段本来
    就首尾相接,所以一个 BETWEEN 就够,不用查两次。
    """
    t_start, t_end = _bj_day_bounds(0)
    y_start, _ = _bj_day_bounds(-1)
    not_cancelled = Order.status != OrderStatus.CANCELLED
    is_today = (Order.created_at >= t_start).label("is_today")
    rows = (await db.execute(
        select(
            is_today,
            func.count().filter(not_cancelled).label("orders"),
            func.coalesce(
                func.sum(Order.total_cents - Order.refund_cents)
                .filter(not_cancelled), 0).label("gmv_cents"),
            func.count().filter(
                Order.status.in_(_ONGOING_STATES)).label("ongoing"),
            func.count().filter(
                Order.status.in_(_DONE_STATES)).label("done"),
            func.count().filter(
                Order.status == OrderStatus.CANCELLED).label("cancelled"),
            func.count().filter(
                and_(not_cancelled, Order.pickup)).label("pickup_orders"),
        )
        .where(Order.merchant_id == merchant_id,
               Order.created_at >= y_start, Order.created_at < t_end,
               Order.status != OrderStatus.PENDING_PAYMENT)
        .group_by(is_today))).all()
    by_day = {r.is_today: {"orders": r.orders, "gmv_cents": r.gmv_cents,
                           "ongoing": r.ongoing, "done": r.done,
                           "cancelled": r.cancelled,
                           "pickup_orders": r.pickup_orders}
              for r in rows}
    # 某一天一单都没有时这天没有行,给全零 —— 不能少一个键
    return (by_day.get(True, dict(_EMPTY_DAY)),
            by_day.get(False, dict(_EMPTY_DAY)))


@router.get("/me/today")
async def my_today(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """今日实时经营(下单口径,北京时区),附昨日全天做参照。"""
    shop = await _my_shop_or_404(db, user)
    today, yesterday = await _today_and_yesterday(db, shop.id)
    return {"today": today, "yesterday": yesterday}


@router.get("/me/todos")
async def my_todos(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """待办聚合:商家当下欠着的事,数字非零才值得展示。
    只聚合已有数据,不引入新状态 —— 每一项点进去都有现成的处理界面。"""
    from ..models import (Appeal, AfterSale, AfterSaleStatus, Review,
                          StaffHealthCert)
    from ..services.licenses import stage as _lic_stage
    shop = await _my_shop_or_404(db, user)
    now = datetime.now(timezone.utc)

    # 健康证:30 天内到期或已过期的在岗人数(归档的不算)
    cert_rows = (await db.scalars(
        select(StaffHealthCert.expires_at).where(
            StaffHealthCert.merchant_id == shop.id,
            StaffHealthCert.archived.is_(False)))).all()
    health_expiring = sum(
        1 for e in cert_rows
        if _lic_stage(e) in ("soon", "urgent", "last", "expired", "overdue"))

    # ## 八个计数一趟取回,不是一条一趟
    #
    # 这些计数彼此无关,谁也不等谁,可原来是八次 `await db.scalar(...)`
    # 排着队跑 —— 八个往返,每个 0.5~1ms,而整个接口只回 343 字节。
    # 商家端前台每 30 秒打一次,一家店一天就是两千多次。
    #
    # 现在拼成一条 `SELECT (子查询), (子查询), ...`:WHERE 条件一个字
    # 没改,只是让库一次算完。**别改成 join**——八个条件各管各的表和
    # 时间窗,join 起来要处理笛卡尔积,写对了也没人看得懂。
    #
    # 「店铺券快发完」原来是把本店所有在架批次整行捞回来在 Python 里数,
    # 顺手也并进去:开发库里有商家攒了 462 个批次,那是一次全表捞。
    # `total / 10` 在 Postgres 里整数相除就是截断,与 Python 的 `//`
    # 对非负数完全一致(total > 0 已经保证了非负)。
    from .appeals import appeal_cutoff
    cutoff = appeal_cutoff()
    appealed_sales_q = select(Appeal.target_id).where(
        Appeal.target_type == "after_sale")
    appealed_reviews_q = select(Appeal.target_id).where(
        Appeal.target_type == "review")

    def _count(model, *conds):
        return select(func.count(model.id)).where(*conds).scalar_subquery()

    counts = (await db.execute(select(
        _count(Order,
               Order.merchant_id == shop.id,
               Order.status == OrderStatus.PAID).label("pending_orders"),
        _count(AfterSale,
               AfterSale.merchant_id == shop.id,
               AfterSale.status == AfterSaleStatus.pending).label(
                   "after_sales"),
        # 差评待回复:近 7 天 ≤3 星还没回应的 —— 回应越快挽回余地越大
        _count(Review,
               Review.merchant_id == shop.id,
               Review.merchant_rating <= 3,
               Review.reply == "",
               Review.hidden.is_(False),
               Review.created_at > now - timedelta(days=7)).label(
                   "bad_unreplied"),
        # 超过 24 小时还没回的差评:行业里"差评 24 小时内必回"是常识,
        # 拖过一天再回,顾客早就走了。单列出来而不是混在待回复里
        _count(Review,
               Review.merchant_id == shop.id,
               Review.merchant_rating <= 3,
               Review.reply == "",
               Review.hidden.is_(False),
               Review.created_at < now - timedelta(hours=24),
               Review.created_at > now - timedelta(days=7)).label(
                   "bad_overdue"),
        # 临期营销:店铺券快发完(余量 ≤10%,含已发完但还挂着的)
        _count(CouponBatch,
               CouponBatch.merchant_id == shop.id,
               CouponBatch.active.is_(True),
               CouponBatch.total > 0,
               (CouponBatch.total - CouponBatch.issued)
               <= CouponBatch.total / 10).label("coupon_low"),
        # 限时折扣 24h 内到期(到期自动失效,提醒续期或收手)
        _count(Dish,
               Dish.merchant_id == shop.id,
               Dish.flash_price_cents.is_not(None),
               Dish.flash_until.is_not(None),
               Dish.flash_until > now,
               Dish.flash_until < now + timedelta(hours=24)).label(
                   "flash_expiring"),
        # 还来得及申诉的裁决数(售后判商家责 + 差评),已申诉过的不算。
        #
        # 口径是「**还来得及**」不是「历史上被判过几次」:后者点进去多半
        # 什么也做不了,给它挂红数字只会制造焦虑 —— 下一次商家就不信
        # 这个角标了(同 SzIconGridItem.badge 的规矩:只给"你还有事要做"的)。
        #
        # 窗口判据从 appeals.py 借,不在这儿抄一遍 —— 抄一遍的话哪天只改了
        # 一处,角标说有 2 单可申诉、点进去提交却被 422 挡回来
        _count(AfterSale,
               AfterSale.merchant_id == shop.id,
               AfterSale.status == AfterSaleStatus.accepted,
               AfterSale.fault != "rider",
               AfterSale.processed_at.is_not(None),
               AfterSale.processed_at > cutoff,
               AfterSale.id.not_in(appealed_sales_q)).label(
                   "appealable_sales"),
        _count(Review,
               Review.merchant_id == shop.id,
               Review.merchant_rating <= 3,
               Review.hidden.is_(False),
               Review.created_at > cutoff,
               Review.id.not_in(appealed_reviews_q)).label(
                   "appealable_reviews"),
    ))).one()

    # 未读消息(评价/系统触达;订单类与公告不计):与消息中心同一口径 ——
    # 走同一个函数,而不是"照着写一遍",两处数字对不上比不显示更糟
    from ..services import message_center
    messages_unread = await message_center.unread_count(db, "merchant",
                                                        user.id)

    return {
        "pending_orders": counts.pending_orders,
        "after_sales": counts.after_sales,
        "bad_reviews_unreplied": counts.bad_unreplied,
        "bad_reviews_overdue": counts.bad_overdue,  # 其中超 24 小时的
        "coupon_batches_low": counts.coupon_low,
        "flash_expiring": counts.flash_expiring,
        "messages_unread": messages_unread,
        "appealable": counts.appealable_sales + counts.appealable_reviews,
        # 证照/健康证到期:**不计入待办角标数**,单独一档。
        # 它们和"有几单待接"不是一回事 —— 混进同一个数字里,
        # 商家清完订单就以为清完了,而这两条是清不掉的(要去办证)
        "license_stage": _license_stage_of(shop),
        "health_certs_expiring": health_expiring,
    }


# ---------- 进货查验台账(食品溯源) ----------

def _keep_until(shelf_life_end: date | None, purchased_on: date) -> date:
    """这条记录**最短**要留到哪天(《食品安全法》第五十条第二款)。

    保质期满后六个月;没有明确保质期的,进货日起两年。
    算给商家看,不是拿来自动删的 —— 到期只代表"法律上可以删了",
    不代表该删。自动清掉商家的合规证据,风险全在他身上,
    而我们省下的只是几行存储。
    """
    if shelf_life_end is not None:
        # 六个月按 183 天算:法条说的是"六个月",不是"180 天",
        # 宁可多留几天也不要算短
        return shelf_life_end + timedelta(days=183)
    return purchased_on + timedelta(days=730)


def _purchase_out(r) -> dict:
    return {
        "id": r.id, "name": r.name, "spec": r.spec, "qty": r.qty,
        "produced_on": r.produced_on, "batch_no": r.batch_no,
        "shelf_life_end": r.shelf_life_end,
        "purchased_on": r.purchased_on,
        "supplier_name": r.supplier_name,
        "supplier_address": r.supplier_address,
        "supplier_phone": r.supplier_phone,
        "supplier_license_url": r.supplier_license_url,
        "receipt_url": r.receipt_url,
        "note": r.note,
        "keep_until": _keep_until(r.shelf_life_end, r.purchased_on),
        "created_at": r.created_at,
    }


@router.get("/me/purchases")
async def my_purchases(
    q: str | None = None,
    days: int = Query(default=90, ge=1, le=1095),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """进货台账。[q] 按食材名反查 —— 出食安问题时问的就是
    "这批肉是谁供的、什么时候进的",答不上来只能自己扛。

    **q 有值时不受 days 限制**:反查是往回追,而追的那批货往往就是
    久一点的那批;用默认窗口把它滤掉,这个功能就白做了。
    """
    from ..models import PurchaseRecord

    shop = await _my_shop_or_404(db, user)
    stmt = select(PurchaseRecord).where(
        PurchaseRecord.merchant_id == shop.id)
    if q:
        stmt = stmt.where(PurchaseRecord.name.ilike(f"%{q.strip()[:30]}%"))
    else:
        since = date.today() - timedelta(days=days)
        stmt = stmt.where(PurchaseRecord.purchased_on >= since)
    rows = (await db.scalars(
        stmt.order_by(PurchaseRecord.purchased_on.desc(),
                      PurchaseRecord.id.desc()).limit(limit))).all()
    return {
        "items": [_purchase_out(r) for r in rows],
        "note": "记录与凭证至少留到「最短留存」那天(保质期满后六个月;"
                "没有明确保质期的两年)。平台不会替你删 —— 到期只代表"
                "法律上可以删,不代表该删。",
    }


@router.get("/me/purchases/suppliers")
async def my_suppliers(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """用过的供货商(去重,最近在前)。

    同一个供货商反复进货,每次重填名称/地址/电话是这个台账最容易
    半途而废的地方 —— 录第三次就没人录了。
    """
    from ..models import PurchaseRecord

    shop = await _my_shop_or_404(db, user)
    rows = (await db.execute(
        select(PurchaseRecord.supplier_name,
               func.max(PurchaseRecord.supplier_address),
               func.max(PurchaseRecord.supplier_phone),
               func.max(PurchaseRecord.supplier_license_url),
               func.max(PurchaseRecord.purchased_on).label("last"))
        .where(PurchaseRecord.merchant_id == shop.id,
               PurchaseRecord.supplier_name != "")
        .group_by(PurchaseRecord.supplier_name)
        .order_by(func.max(PurchaseRecord.purchased_on).desc())
        .limit(50))).all()
    return [{"name": n, "address": a, "phone": p, "license_url": lic,
             "last_purchased_on": last} for n, a, p, lic, last in rows]


@router.post("/me/purchases")
async def add_purchase(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """录一条进货记录。

    法定必记项里我们只把**食材名**和**进货日期**做成必填,其余尽量宽松 ——
    这个台账最大的敌人不是填得不全,是**根本没人填**。先让人记下来,
    界面上再提示哪几项还缺,比一上来就八个必填要现实。
    """
    from ..models import PurchaseRecord
    from ..services.moderation import guard_text

    shop = await _my_shop_or_404(db, user)
    name = str(payload.get("name", "")).strip()[:60]
    if len(name) < 1:
        raise HTTPException(422, "请填写食材名称")
    await guard_text(db, name, "食材名称")
    supplier = str(payload.get("supplier_name", "")).strip()[:60]
    if supplier:
        await guard_text(db, supplier, "供货商名称")

    def _date(key, required=False):
        raw = payload.get(key)
        if not raw:
            if required:
                raise HTTPException(422, "请填写进货日期")
            return None
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            raise HTTPException(422, f"{key} 日期格式:YYYY-MM-DD")

    rec = PurchaseRecord(
        merchant_id=shop.id,
        name=name,
        spec=str(payload.get("spec", "")).strip()[:40],
        qty=str(payload.get("qty", "")).strip()[:30],
        produced_on=_date("produced_on"),
        batch_no=str(payload.get("batch_no", "")).strip()[:40],
        shelf_life_end=_date("shelf_life_end"),
        purchased_on=_date("purchased_on", required=True),
        supplier_name=supplier,
        supplier_address=str(
            payload.get("supplier_address", "")).strip()[:120],
        supplier_phone=str(payload.get("supplier_phone", "")).strip()[:20],
        supplier_license_url=str(
            payload.get("supplier_license_url", "")).strip()[:300],
        receipt_url=str(payload.get("receipt_url", "")).strip()[:300],
        note=str(payload.get("note", "")).strip()[:200],
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    out = _purchase_out(rec)
    # 缺哪几项法定必记项,当场说清楚 —— 但不拦,拦了就没人录了
    missing = [label for key, label in (
        ("spec", "规格"), ("qty", "数量"), ("supplier_name", "供货商名称"),
        ("supplier_address", "供货商地址"), ("supplier_phone", "联系方式"),
    ) if not getattr(rec, key)]
    if not rec.produced_on and not rec.batch_no:
        missing.append("生产日期或批号")
    if not rec.shelf_life_end:
        missing.append("保质期")
    if not rec.receipt_url:
        missing.append("进货凭证照片")
    out["missing"] = missing
    return out


@router.delete("/me/purchases/{record_id}")
async def delete_purchase(
    record_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """删一条录错的记录。

    **只给删录错的**,不是清理工具 —— 到了最短留存期也不会有任何
    自动清理任务来删它(见 _keep_until 的说明)。
    """
    from ..models import PurchaseRecord

    shop = await _my_shop_or_404(db, user)
    rec = await db.get(PurchaseRecord, record_id)
    if rec is None or rec.merchant_id != shop.id:
        raise HTTPException(404, "记录不存在")
    await db.delete(rec)
    await db.commit()
    return {"ok": True}


# ---------- 从业人员健康证台账 ----------

def _mask_cert_no(no: str) -> str:
    """证件号打码。台账是给商家自查"谁的证快到期了"用的,
    不是员工身份信息的查询库 —— 号码只在编辑那一条时回全。"""
    if len(no) <= 6:
        return "*" * len(no)
    return f"{no[:3]}{'*' * (len(no) - 6)}{no[-3:]}"


def _cert_out(c, *, full_no: bool = False) -> dict:
    from ..services.licenses import days_left, stage
    return {
        "id": c.id, "name": c.name, "role": c.role,
        "cert_no": c.cert_no if full_no else _mask_cert_no(c.cert_no),
        "photo_url": c.photo_url,
        "issued_at": c.issued_at, "expires_at": c.expires_at,
        "days_left": days_left(c.expires_at),
        # 与食品经营许可证同一套档位判定,商家不用学第二套说法
        "stage": stage(c.expires_at),
        "archived": c.archived,
    }


@router.get("/me/health-certs")
async def my_health_certs(
    include_archived: bool = False,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """本店从业人员健康证台账,快到期的排前面。

    《食品安全法》四十五条要求接触直接入口食品的从业人员持证上岗、
    一年一检。监管检查看的是**记录** —— 塞在抽屉里翻不出来就是没有。
    """
    from ..models import StaffHealthCert
    from ..services.licenses import stage

    shop = await _my_shop_or_404(db, user)
    stmt = select(StaffHealthCert).where(
        StaffHealthCert.merchant_id == shop.id)
    if not include_archived:
        stmt = stmt.where(StaffHealthCert.archived.is_(False))
    rows = (await db.scalars(stmt.order_by(StaffHealthCert.id))).all()
    items = [_cert_out(c) for c in rows]
    order = {"overdue": 0, "expired": 1, "last": 2, "urgent": 3,
             "soon": 4, "unknown": 5, "ok": 6}
    items.sort(key=lambda x: (order.get(x["stage"], 9),
                              x["days_left"] if x["days_left"] is not None
                              else 9999))
    expiring = sum(1 for i in items if i["stage"] in
                   ("soon", "urgent", "last", "expired", "overdue")
                   and not i["archived"])
    return {
        "items": items,
        "expiring": expiring,
        "note": "健康证一年一检。到期只提醒、不停业 —— 证是按人的,"
                "一个人的证过期停整家店不成比例。",
    }


@router.post("/me/health-certs")
async def add_health_cert(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """录一张健康证。同名同岗视为**换新证**,更新那一条而不是堆两条 ——
    堆着的话台账里一个人两条记录,到期提醒会重复,查的时候也分不清哪张有效。"""
    from ..models import StaffHealthCert
    from ..services.moderation import guard_text

    shop = await _my_shop_or_404(db, user)
    name = str(payload.get("name", "")).strip()[:30]
    if len(name) < 2:
        raise HTTPException(422, "请填写姓名")
    await guard_text(db, name, "姓名")
    role = str(payload.get("role", "")).strip()[:20]
    if role:
        await guard_text(db, role, "岗位")
    raw_exp = payload.get("expires_at")
    if not raw_exp:
        raise HTTPException(422, "请填写有效期至(到期提醒靠它)")
    try:
        exp = date.fromisoformat(str(raw_exp))
    except ValueError:
        raise HTTPException(422, "有效期格式:YYYY-MM-DD")
    issued = None
    if payload.get("issued_at"):
        try:
            issued = date.fromisoformat(str(payload["issued_at"]))
        except ValueError:
            raise HTTPException(422, "发证日期格式:YYYY-MM-DD")

    existing = await db.scalar(select(StaffHealthCert).where(
        StaffHealthCert.merchant_id == shop.id,
        StaffHealthCert.name == name,
        StaffHealthCert.role == role,
        StaffHealthCert.archived.is_(False)))
    cert = existing or StaffHealthCert(merchant_id=shop.id, name=name,
                                       role=role)
    cert.cert_no = str(payload.get("cert_no", "")).strip()[:40]
    cert.photo_url = str(payload.get("photo_url", "")).strip()[:300]
    cert.expires_at = exp
    cert.issued_at = issued
    if existing is None:
        db.add(cert)
    await db.commit()
    await db.refresh(cert)
    return _cert_out(cert, full_no=True)


@router.delete("/me/health-certs/{cert_id}")
async def archive_health_cert(
    cert_id: int,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """员工离职:**归档不删除**。

    监管查的是"当时在岗的人有没有证",记录删掉等于把当时的合规证据
    也一起删了 —— 到时候说不清。归档后不再提醒、不计入在岗人数。
    """
    from ..models import StaffHealthCert

    shop = await _my_shop_or_404(db, user)
    cert = await db.get(StaffHealthCert, cert_id)
    if cert is None or cert.merchant_id != shop.id:
        raise HTTPException(404, "记录不存在")
    cert.archived = True
    await db.commit()
    return {"ok": True, "note": "已归档;记录仍保留以备核查"}


# ---------- 续证复审(过审后资质变更的唯一通道) ----------

@router.get("/me/license-renewal")
async def my_license_renewal(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """我最近一次续证提交的进度(没提交过返回 null)。"""
    from ..models import LicenseRenewal
    shop = await _my_shop_or_404(db, user)
    row = await db.scalar(
        select(LicenseRenewal)
        .where(LicenseRenewal.merchant_id == shop.id)
        .order_by(LicenseRenewal.id.desc()).limit(1))
    if row is None:
        return {"renewal": None}
    return {"renewal": {
        "id": row.id, "status": row.status,
        "license_no": row.license_no,
        "license_expires_at": row.license_expires_at,
        "reject_reason": row.reject_reason,
        "created_at": row.created_at, "reviewed_at": row.reviewed_at,
    }}


@router.post("/me/license-renewal")
async def submit_license_renewal(
    payload: dict,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """提交续证材料,人工核验后自动替换生效。

    **提交期间照常营业** —— 续证的店绝大多数在正常经营,只是证到期要
    换新的。为了换证停业几天,惩罚的是守规矩的那批人。
    """
    from ..models import LicenseRenewal
    from ..services.moderation import guard_text

    shop = await _money_shop_or_403(db, user)   # 资质是经营者本人的事
    no = str(payload.get("license_no", "")).strip()[:50]
    img = str(payload.get("license_image_url", "")).strip()[:300]
    if not no or not img:
        raise HTTPException(422, "请填写新证的编号并上传照片")
    raw_exp = payload.get("license_expires_at")
    if not raw_exp:
        raise HTTPException(422, "请填写新证的有效期至(到期提醒靠它)")
    try:
        exp = date.fromisoformat(str(raw_exp))
    except ValueError:
        raise HTTPException(422, "有效期格式:YYYY-MM-DD")
    if exp <= date.today():
        # 交一张已经过期的证是没有意义的,当场拦掉比让人等三天核验强
        raise HTTPException(422, "新证的有效期不能是今天或更早")
    subject = str(payload.get("license_subject", "")).strip()[:100]
    if subject:
        await guard_text(db, subject, "证照主体名称")

    pending = await db.scalar(select(LicenseRenewal).where(
        LicenseRenewal.merchant_id == shop.id,
        LicenseRenewal.status == "pending"))
    if pending is not None:
        raise HTTPException(409, "已有一份续证材料在核验中,请等结果或联系客服")

    db.add(LicenseRenewal(
        merchant_id=shop.id, submitted_by=user.id,
        license_no=no, license_image_url=img, license_expires_at=exp,
        business_license_no=str(
            payload.get("business_license_no", "")).strip()[:50],
        license_subject=subject))
    await db.commit()
    return {"ok": True,
            "note": "已提交,核验通过后自动替换;核验期间照常营业。"}


def _license_stage_of(shop) -> str:
    """证照档位(unknown/ok/soon/urgent/last/expired/overdue)。"""
    from ..services.licenses import stage
    return stage(shop.license_expires_at)


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
    shop = await owned_shop(db, user)
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
    shop = await owned_shop(db, user)
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
    shop = await owned_shop(db, user)
    key = await db.get(MerchantApiKey, key_id)
    if shop is None or key is None or key.merchant_id != shop.id:
        raise HTTPException(404, "Key 不存在")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    return {"ok": True}


# ---------- 消息中心(公告 + 触达记录,订单类不进这里) ----------
#
# 实现搬到了 services/message_center.py —— 骑手端要的是同一件事,
# 复制一份的代价不是多几十行,是两份口径会分叉。这里只留路由。


@router.get("/me/messages")
async def my_messages(
    category: str | None = None,   # review / system;缺省全部
    before: int | None = None,     # push_logs 游标(上一页最后一条 id)
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """消息中心:置顶当前生效的平台公告 + 本人触达记录(评价/系统)。

    未读只算触达条数,**公告不计未读** —— 横幅本来就常驻在页面顶上,
    再给它记一个红点,红点就永远消不掉。
    """
    from ..services import message_center
    await _my_shop_or_404(db, user)
    return await message_center.fetch(db, "merchant", user.id,
                                      category=category, before=before)


@router.post("/me/messages/read")
async def mark_messages_read(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """记已读水位到当前时刻。"""
    from ..services import message_center
    await _my_shop_or_404(db, user)
    return await message_center.mark_read("merchant", user.id)


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

    # 证照有效期:合规档案的第一块 —— 它是唯一一条"到期就自动出事"的,
    # 其余几块都是已经发生的事的记录
    from ..services.licenses import GRACE_DAYS, days_left, stage
    lic_stage = stage(shop.license_expires_at)
    license_block = {
        "expires_at": shop.license_expires_at,
        "days_left": days_left(shop.license_expires_at),
        "stage": lic_stage,
        "grace_days": GRACE_DAYS,
        "license_no": shop.license_no,
        "license_subject": shop.license_subject,
        "business_license_no": shop.business_license_no,
        "hint": {
            "unknown": "还没登记有效期。登记后我们会在到期前 30/7/1 天提醒你 ——"
                       "证过期是静默失效,没人提醒就只能等监管上门。",
            "ok": "在有效期内。",
            "soon": "还有不到 30 天到期,续证要跑审批流程,建议现在就去办。",
            "urgent": "7 天内到期,请尽快办理。",
            "last": "明天到期。",
            "expired": f"已过期,目前仍可接单,{GRACE_DAYS} 天宽限期后将暂停营业。",
            "overdue": "已超过宽限期,店铺已暂停接单;上传新证后由平台人工核验恢复。",
        }.get(lic_stage, ""),
    }

    # 从业人员健康证:与证照同一套档位口径
    from ..models import StaffHealthCert
    cert_rows = (await db.scalars(
        select(StaffHealthCert).where(
            StaffHealthCert.merchant_id == shop.id,
            StaffHealthCert.archived.is_(False)))).all()
    health_block = {
        "total": len(cert_rows),
        "expiring": sum(1 for c in cert_rows if stage(c.expires_at) in
                        ("soon", "urgent", "last")),
        "expired": sum(1 for c in cert_rows if stage(c.expires_at) in
                       ("expired", "overdue")),
        "missing": sum(1 for c in cert_rows if c.expires_at is None),
        "hint": "《食品安全法》四十五条:接触直接入口食品的从业人员"
                "一年一检、持证上岗。到期只提醒不停业 —— 证是按人的。",
    }

    return {
        "shop_status": shop.status.value,
        "reject_reason": shop.reject_reason or "",
        "license": license_block,
        "health_certs": health_block,
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
    from ..services.flags import wait_comp_on
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
                    # 等餐补偿是运行时开关(flags.wait_comp_on,默认关 ——
                    # 平台现阶段没有这笔预算)。关着的时候这句话不能出现:
                    # 公示了却不给,比不公示更坏
                    *(["骑手到店等餐超时有补偿,同样平台出"]
                      if await wait_comp_on(db) else []),
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
    # 对账明细含每单分账与平台佣金 —— 与 /me/wallet 同口径,只对经营者本人
    shop = await _money_shop_or_403(db, user)
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
