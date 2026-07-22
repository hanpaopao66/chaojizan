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

ETA_PREP_MINUTES = 20        # 备餐兜底时长
ETA_MINUTES_PER_KM = 5       # 骑行折算
ETA_MIN_MINUTES = 30         # 最短承诺(别把话说太满)
LATE_GRACE_MINUTES = 15      # 超过 ETA 这么久才算超时
COMP_AMOUNT_CENTS = 300      # 安抚券面额(无门槛)
COMP_VALID_DAYS = 7
WEATHER_EXEMPT_SECONDS = 3600  # 停运开关切换前后 1 小时豁免

# 极端天气停运开关最近一次切换时刻(admin set_flag 时写入)
WEATHER_TOGGLE_KEY = "weather_shutdown:last_toggle"


def compute_eta(order: Order, merchant: Merchant) -> datetime | None:
    """支付成功时调用;自取/追加单返回 None。"""
    if order.pickup or order.parent_order_no:
        return None
    if order.scheduled_at is not None:
        return order.scheduled_at
    km = haversine_m(merchant.lat, merchant.lng, order.lat, order.lng) / 1000
    minutes = max(ETA_MIN_MINUTES,
                  ETA_PREP_MINUTES + math.ceil(km * ETA_MINUTES_PER_KM))
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


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
