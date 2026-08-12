"""预计送达时间(ETA)与超时安抚赔付(准时宝-lite)。

口径(平台立场):赔付成本平台承担,不扣骑手不扣商家。
- 支付时按朴素公式生成 eta_at:备餐 20 分钟 + 每公里 5 分钟,最少 30 分钟;
  预约单 = 预约时间。只对主配送单生成(自取/追加单没有独立送达承诺)。
- 实际送达超过 eta 15 分钟:自动发无门槛 3 元安抚券(7 天有效)+ 致歉推送,
  每单最多一次(coupons.source 唯一约束兜底幂等)。
- 超时归因只统计不追责(商家出餐超时/配送耗时长/接单等待久,后台可见)。
- 豁免:极端天气停运开关开启期间及其前后 1 小时;用户改过地址的单。
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Coupon, Merchant, Order, OrderEvent
from ..redis_client import get_redis
from .pricing import haversine_m

logger = logging.getLogger("superz.eta")

ETA_PREP_MINUTES = 20        # 备餐兜底时长(商家无实测样本时用)
# 骑行折算保留为兜底。**真实换算走 labor_guard.ride_minutes** ——
# 那里的速度是写死的常量,不由骑手实际表现训练(见 #144 的红线)
ETA_MINUTES_PER_KM = 5
ETA_MIN_MINUTES = 30         # 最短承诺(别把话说太满)
LATE_GRACE_MINUTES = 15      # 超过 ETA 这么久才算超时
COMP_AMOUNT_CENTS = 300      # 安抚券面额(无门槛)
COMP_VALID_DAYS = 7
WEATHER_EXEMPT_SECONDS = 3600  # 停运开关切换前后 1 小时豁免

# 极端天气停运开关最近一次切换时刻(admin set_flag 时写入)
WEATHER_TOGGLE_KEY = "weather_shutdown:last_toggle"


def compute_eta(
    order: Order,
    merchant: Merchant,
    *,
    prep_minutes: float | None = None,
    severe_weather: bool = False,
    route_minutes: float | None = None,
) -> datetime | None:
    """支付成功时调用;自取/追加单返回 None。

    ## 劳动者保护红线(#144)

    骑行时间走 `labor_guard.ride_minutes`,速度是**写死的常量**,
    不由骑手实际表现训练 —— 用实际速度反过来收紧时限,正是把骑手逼到
    逆行、闯灯的那套机制。

    结果再过一道 `clamp_eta_minutes`:**只许放宽,不许收紧**。
    所以传进来的 `prep_minutes`(商家实测出餐分位数)即便比兜底值小,
    也不会让 ETA 变短 —— 出餐快是商家的功劳,不该变成骑手的压力。

    `severe_weather=True` 时用更慢的速度:恶劣天气加价的同时**必须放宽时限**,
    只加价不放宽等于用钱买骑手冒险。
    """
    if order.pickup or order.parent_order_no:
        return None
    if order.scheduled_at is not None:
        return order.scheduled_at

    from . import labor_guard

    distance_m = haversine_m(merchant.lat, merchant.lng, order.lat, order.lng)
    # route_minutes 由 compute_eta_async 传进来(腾讯路网时长,含路口红灯);
    # 不传就是纯常量速度。ride_minutes 里取 max,只放宽不收紧
    ride = labor_guard.ride_minutes(distance_m, severe_weather=severe_weather,
                                    route_minutes=route_minutes)

    # 备餐:有实测分位数就用,没有就用兜底。**取更大的那个** ——
    # 实测比兜底短时不缩短 ETA(见上面的红线)
    prep = max(prep_minutes or 0.0, float(ETA_PREP_MINUTES))
    # 忙碌模式:商家自己声明"现在出餐慢",承诺随之放宽 ——
    # 先说清楚再让用户下单,而不是下了单再超时。
    # getattr 防御:单元测试用 SimpleNamespace 模拟商家,没有这两个字段
    if getattr(merchant, "busy_active", False):
        prep += getattr(merchant, "busy_extra_minutes", 10)

    # 爬楼:6 楼无电梯和 1 楼临街是两种活。**加进给顾客看的 ETA** ——
    # 一个诚实的 35 分钟好过一个乐观的 28 分钟再超时赔付。
    # 顾客没填楼层时是 0,不猜
    stairs = labor_guard.floor_minutes(
        getattr(order, "floor", None), getattr(order, "has_elevator", None))

    baseline = max(ETA_MIN_MINUTES, ETA_PREP_MINUTES
                   + math.ceil(distance_m / 1000 * ETA_MINUTES_PER_KM))
    proposed = max(ETA_MIN_MINUTES, prep + ride + stairs)
    minutes = labor_guard.clamp_eta_minutes(proposed, baseline)
    return datetime.now(timezone.utc) + timedelta(minutes=math.ceil(minutes))


async def compute_eta_async(
    order: Order,
    merchant: Merchant,
    *,
    prep_minutes: float | None = None,
    severe_weather: bool = False,
) -> datetime | None:
    """带**路线级余量**的 ETA(#268)。支付成功时用这个。

    和同步版 [compute_eta] 的唯一差别:多打一次腾讯骑行路径接口,
    拿路网时长(含路口、红灯)喂给 `labor_guard.ride_minutes`。

    ## 为什么要它

    常量速度 15km/h 已经是故意压低的(把红灯、找楼栋、等电梯都包了),
    但它是**一个平均值拍在所有路线上** —— 市区过 8 个红灯和郊区一条
    直路拿的是同一份余量。市区骑手那几分钟的差额,就是他要抢的那几个灯。

    ## 只放宽不收紧

    `ride_minutes` 里取 `max(常量, 路网)`,方向不能反 —— 路网算的是
    纯骑行,不含取餐爬楼。再加上 `clamp_eta_minutes` 那道闸,
    这条改动**不可能让任何一单的 ETA 变短**。

    ## 拿不到就退回常量

    没配 key、接口挂了、配额用尽 —— 一律 `route_minutes=None`,
    结果和改之前完全一样。**不编一个数出来**:估不出路口就说估不出。
    """
    if order.pickup or order.parent_order_no:
        return None
    if order.scheduled_at is not None:
        return order.scheduled_at

    route_minutes: float | None = None
    try:
        from .routing import bicycling_route
        _dist, route_minutes, _src = await bicycling_route(
            merchant.lat, merchant.lng, order.lat, order.lng)
    except Exception:
        # 路径服务挂了不该拦住下单 —— 退回常量口径,ETA 只是少了一点余量
        logger.warning("ETA 取路网时长失败,退回常量速度", exc_info=True)

    return compute_eta(order, merchant, prep_minutes=prep_minutes,
                       severe_weather=severe_weather,
                       route_minutes=route_minutes)


ETA_REFRESH_THRESHOLD_MIN = 5  # 偏差 >5 分钟才刷新+推送(克制,不频繁打扰)


def _travel_minutes(km: float) -> int:
    return max(1, math.ceil(km * ETA_MINUTES_PER_KM))


def _estimate_remaining_minutes(order, merchant, rider_pos, now) -> int:
    """按当前状态估算从 now 起还需多久送达(分钟)。"""
    from ..state_machine import OrderStatus
    drop = (order.lat, order.lng)
    shop_to_drop = haversine_m(
        merchant.lat, merchant.lng, drop[0], drop[1]) / 1000
    if rider_pos is not None and order.status == OrderStatus.PICKED_UP:
        # 已取餐:只剩骑手→收货点
        km = haversine_m(rider_pos[0], rider_pos[1], drop[0], drop[1]) / 1000
        return _travel_minutes(km)
    if rider_pos is not None and order.status in (
            OrderStatus.ACCEPTED, OrderStatus.READY):
        # 骑手已接单未取餐:骑手→商家 + 商家→收货点(未出餐再加备餐缓冲)
        to_shop = haversine_m(rider_pos[0], rider_pos[1],
                              merchant.lat, merchant.lng) / 1000
        prep = 0 if order.status == OrderStatus.READY else 8
        return prep + _travel_minutes(to_shop) + _travel_minutes(shop_to_drop)
    # 无骑手位置:备餐缓冲 + 商家→收货点直线折算
    prep = ETA_PREP_MINUTES if order.status == OrderStatus.ACCEPTED else 5
    return prep + _travel_minutes(shop_to_drop)


async def recompute_eta(db: AsyncSession, order: Order, merchant: Merchant,
                        rider_pos=None, delay: bool = False) -> bool:
    """动态重估 eta_at。仅在偏差 >5 分钟时写库并推送(克制)。

    自取/追加/预约单不刷新(它们没有动态承诺)。延后才主动推,提前送到是惊喜
    不特意打扰。刷新后的 eta_at 直接成为超时赔付的新基准(compensate 读 eta_at)。
    调用方负责 commit;本函数只改 order.eta_at + 内联推送(非资金关键)。
    """
    from ..state_machine import OrderStatus
    if (order.pickup or order.parent_order_no
            or order.scheduled_at is not None or order.eta_at is None):
        return False
    if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        return False
    now = datetime.now(timezone.utc)
    remaining = _estimate_remaining_minutes(order, merchant, rider_pos, now)
    new_eta = now + timedelta(minutes=remaining)
    old_eta = order.eta_at if order.eta_at.tzinfo else \
        order.eta_at.replace(tzinfo=timezone.utc)
    if abs((new_eta - old_eta).total_seconds()) < \
            ETA_REFRESH_THRESHOLD_MIN * 60:
        return False
    later = new_eta > old_eta
    order.eta_at = new_eta
    if later or delay:
        hhmm = (new_eta + timedelta(hours=8)).strftime("%H:%M")
        msg = (f"商家出餐较慢,预计送达延后到 {hhmm}" if delay
               else f"预计送达时间已更新为 {hhmm}")
        try:
            from .push import push_to_user
            await push_to_user(order.customer_id, "预计送达时间更新", msg,
                               {"type": "order", "order_no": order.order_no})
        except Exception:
            logger.exception("ETA 刷新推送失败")
    return True


async def _weather_exempt(db: AsyncSession, at: datetime) -> bool:
    from .flags import weather_shutdown_on
    if await weather_shutdown_on(db):
        return True
    raw = await get_redis().get(WEATHER_TOGGLE_KEY)
    if not raw:
        return False
    try:
        toggled = datetime.fromisoformat(
            raw.decode() if isinstance(raw, bytes) else raw)
    except ValueError:
        return False
    return abs((at - toggled).total_seconds()) <= WEATHER_EXEMPT_SECONDS


async def compensate_if_late(db: AsyncSession, order: Order) -> bool:
    """送达时判超时并发券。独立事务,失败绝不影响送达主流程。"""
    from ..config import settings
    if not settings.eta_compensation_enabled:
        return False  # 预算紧张时可关(.env ETA_COMPENSATION_ENABLED=false)
    now = datetime.now(timezone.utc)
    if (order.pickup or order.parent_order_no or order.eta_at is None
            or order.total_cents <= 0):
        return False
    eta = order.eta_at
    if eta.tzinfo is None:
        eta = eta.replace(tzinfo=timezone.utc)
    late_minutes = int((now - eta).total_seconds() // 60)
    if late_minutes < LATE_GRACE_MINUTES:
        return False
    # 每单最多一次(查一遍 + source 唯一约束双保险)
    source = f"eta:{order.order_no}"
    if await db.scalar(select(Coupon.id).where(Coupon.source == source)):
        return False
    # 豁免:改过地址 / 极端天气窗口
    addr_changed = await db.scalar(
        select(OrderEvent.id).where(
            OrderEvent.order_id == order.id,
            OrderEvent.to_status == "address_changed").limit(1))
    if addr_changed or await _weather_exempt(db, now):
        return False

    # 归因(只统计不追责):出餐超时定格 > 配送在途偏长 > 接单等待久/综合
    events = {}
    for e in (await db.scalars(
            select(OrderEvent).where(OrderEvent.order_id == order.id)
            .order_by(OrderEvent.created_at))):
        events.setdefault(e.to_status, e.created_at)
    picked_at = events.get("picked_up")
    if order.ready_late:
        cause = "商家出餐超时"
    elif picked_at is not None and (now - picked_at) > timedelta(
            minutes=LATE_GRACE_MINUTES + ETA_MINUTES_PER_KM * 4):
        cause = "配送在途偏长"
    else:
        cause = "接单等待久/综合"

    coupon = Coupon(
        user_id=order.customer_id,
        amount_cents=COMP_AMOUNT_CENTS,
        min_spend_cents=0,
        expires_at=now + timedelta(days=COMP_VALID_DAYS),
        source=source,
        note=f"订单尾号{order.order_no[-6:]}超时{late_minutes}分钟;归因:{cause}",
    )
    db.add(coupon)
    db.add(OrderEvent(
        order_id=order.id, from_status=order.status.value,
        to_status="eta_compensated", actor_role="system", actor_id=None,
        note=f"超时{late_minutes}分钟,自动发{COMP_AMOUNT_CENTS / 100:g}元安抚券"
             f"(平台承担);归因:{cause}",
    ))
    try:
        await db.commit()
    except Exception:  # 并发下 source 唯一约束兜底
        await db.rollback()
        return False
    try:
        from .push import push_to_user
        await push_to_user(
            order.customer_id, "这单送晚了,抱歉",
            f"比预计晚了 {late_minutes} 分钟,已放入 "
            f"{COMP_AMOUNT_CENTS / 100:g} 元无门槛安抚券(7 天内有效),"
            "成本由平台承担,不扣骑手不扣商家",
            {"type": "coupon"}, record_skip=True)
    except Exception:
        logger.exception("超时赔付推送失败")
    return True


async def release_coupon(db: AsyncSession, order_no: str) -> None:
    """订单全额退款/关单时把券放回券包(未过期可再用)。不单独 commit,
    随调用方事务一起提交。"""
    coupon = await db.scalar(
        select(Coupon).where(Coupon.used_order_no == order_no))
    if coupon is not None:
        coupon.used_order_no = ""
