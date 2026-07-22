"""高峰备货建议(纯建议,不自动改库存)。

口径:近 14 天同餐段(午市 10:00-14:00 / 晚市 16:00-21:00,北京时间)
各菜品「有销量的天」的日销量 P80 作为建议份数;有销量的天数不足 7 天
的菜不给建议(标「数据积累中」)。与当前库存对比,缺口最大的前 5 个
进「可能不够卖」清单。每天 10:00 与 16:00(饭点前)推送商家,
Redis 按 日+餐段 防重。
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Dish, Merchant, Order
from ..state_machine import OrderStatus

logger = logging.getLogger("superz.stocking")

MEALS = {"lunch": (10, 14), "dinner": (16, 21)}
MEAL_LABELS = {"lunch": "午市", "dinner": "晚市"}
WINDOW_DAYS = 14
MIN_DATA_DAYS = 7
SHORTLIST_SIZE = 5


def p80(values: list[int]) -> int:
    """80 分位(向上取):[3,5,8] → 8;[2,2,4,6,10] → 6。"""
    ordered = sorted(values)
    idx = math.ceil(0.8 * len(ordered)) - 1
    return ordered[max(0, idx)]


async def meal_suggestions(db: AsyncSession, merchant_id: int,
                           meal: str) -> list[dict]:
    """全部在售菜的备货建议(含数据积累中的);建议值=同餐段日销量 P80。"""
    start_h, end_h = MEALS[meal]
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    rows = (await db.execute(
        select(Order.items, Order.created_at).where(
            Order.merchant_id == merchant_id,
            Order.status == OrderStatus.COMPLETED,
            Order.created_at >= since))).all()

    # dish_id → {日期: 当日该餐段销量}(0 元赠品行不计)
    daily: dict[int, dict[str, int]] = {}
    for items, created in rows:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        bj = created + timedelta(hours=8)
        if not start_h <= bj.hour < end_h:
            continue
        day = bj.strftime("%m-%d")
        for item in items or []:
            if item.get("price_cents", 0) <= 0:
                continue
            per_day = daily.setdefault(item["dish_id"], {})
            per_day[day] = per_day.get(day, 0) + item.get("quantity", 0)

    dishes = (await db.scalars(
        select(Dish).where(Dish.merchant_id == merchant_id,
                           Dish.is_on_sale.is_(True)))).all()
    out = []
    for dish in dishes:
        values = [v for v in daily.get(dish.id, {}).values() if v > 0]
        if len(values) < MIN_DATA_DAYS:
            out.append({
                "dish_id": dish.id, "name": dish.name,
                "stock": dish.stock, "sold_out_today": dish.sold_out_today,
                "suggested": None, "data_days": len(values),
            })
            continue
        suggested = p80(values)
        out.append({
            "dish_id": dish.id, "name": dish.name,
            "stock": dish.stock, "sold_out_today": dish.sold_out_today,
            "suggested": suggested, "data_days": len(values),
            "deficit": max(0, suggested - dish.stock),
        })
    return out


def shortlist(suggestions: list[dict]) -> list[dict]:
    """「可能不够卖」TOP5:库存低于建议值的,按缺口从大到小。"""
    short = [s for s in suggestions if s.get("deficit", 0) > 0]
    short.sort(key=lambda s: -s["deficit"])
    return short[:SHORTLIST_SIZE]


def current_meal(now_beijing: datetime) -> str:
    """当前该看哪个餐段:14 点前看午市,之后看晚市。"""
    return "lunch" if now_beijing.hour < 14 else "dinner"


async def push_stocking_reminders(now_beijing: datetime) -> int:
    """10:00/16:00 给有缺口的商家推备货提示(Redis 按日+餐段防重)。

    返回本次推送的商家数(不在提醒窗口/已推过返回 0)。
    """
    from ..db import SessionLocal
    from ..redis_client import get_redis
    from .auto_flow import _in_window
    from .push import push_to_user

    if _in_window("10:00", now_beijing, window_seconds=300):
        meal = "lunch"
    elif _in_window("16:00", now_beijing, window_seconds=300):
        meal = "dinner"
    else:
        return 0
    redis = get_redis()
    if not await redis.set(f"stocking:{now_beijing.date()}:{meal}", 1,
                           ex=86400, nx=True):
        return 0

    pushed = 0
    async with SessionLocal() as db:
        shops = (await db.scalars(
            select(Merchant).where(Merchant.is_open.is_(True)))).all()
        for shop in shops:
            try:
                short = shortlist(
                    await meal_suggestions(db, shop.id, meal))
                if not short:
                    continue
                names = "、".join(
                    f"{s['name']}(建议{s['suggested']}份,现{s['stock']})"
                    for s in short[:3])
                await push_to_user(
                    shop.owner_id, f"{MEAL_LABELS[meal]}备货提示",
                    f"按近 14 天同餐段销量估算,这些菜可能不够卖:{names}。"
                    "店铺-库存页可一键按建议补库存(纯建议,不自动改)",
                    {"type": "stocking"}, record_skip=True)
                pushed += 1
            except Exception:
                logger.exception("备货提示失败 merchant=%s", shop.id)
    if pushed:
        logger.info("备货提示:%s 家商家(%s)", pushed, MEAL_LABELS[meal])
    return pushed
