"""订单超时自动流转(后台清扫任务)。

四条规则:
  1. 待支付超过 pay_timeout_minutes      → 自动关单(回补库存)
  2. 已支付商家超时未接单                → 自动取消 = 全额退款(回补库存)
  3. 已送达超过 auto_confirm_hours 未确认 → 自动完成(结算触发点)
  4. 无人接单兜底(抢单模式的红线,见 _sweep_no_rider):
     提醒线 → 推送在线骑手催抢单 + 告知商家,每单一次;
     取消线 → 全额退款,商家已出餐的平台按应收赔付餐损(不让商家背锅)

判定用 updated_at(每次状态流转都会刷新),待支付用 created_at。
所有变更照常写 OrderEvent(actor=system),和人工操作走同一套审计。
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal
from ..models import (
    Dish,
    EarningKind,
    Merchant,
    MerchantEarning,
    MerchantStatus,
    Order,
    OrderEvent,
    User,
    UserRole,
)
from ..state_machine import OrderStatus
from ..ws import manager
from .privacy_phone import unbind_order
from .push import push_to_user
from .settlement import settle_order
from .wechat_pay import request_refund

BEIJING = ZoneInfo("Asia/Shanghai")

logger = logging.getLogger("superz.auto_flow")

# 这些状态取消时菜还没开始做,库存要还回去
RESTOCK_FROM_STATUSES = {OrderStatus.PENDING_PAYMENT, OrderStatus.PAID}


async def restore_stock(db: AsyncSession, order: Order) -> None:
    for item in order.items:
        await db.execute(
            update(Dish)
            .where(Dish.id == item["dish_id"])
            .values(stock=Dish.stock + item["quantity"])
        )


async def _transition_batch(
    db: AsyncSession,
    from_status: OrderStatus,
    to_status: OrderStatus,
    time_column,
    older_than: datetime,
    reason: str,
    extra_where=None,
) -> list[Order]:
    """把超时订单批量流转到目标状态。skip_locked 避免和在线请求互相卡锁。"""
    conditions = [Order.status == from_status, time_column < older_than]
    if extra_where is not None:
        conditions.append(extra_where)
    orders = (
        await db.scalars(
            select(Order)
            .where(*conditions)
            .with_for_update(skip_locked=True)
            .limit(200)
        )
    ).all()
    for order in orders:
        order.status = to_status
        if to_status == OrderStatus.CANCELLED:
            order.cancel_reason = reason
            if from_status in RESTOCK_FROM_STATUSES:
                await restore_stock(db, order)
            # 抵扣过券的,把券放回券包(未过期可再用)
            from .eta import release_coupon
            await release_coupon(db, order.order_no)
            # 已支付订单自动取消 = 全额退款(与人工取消/拒单同一口径)。
            # 先发起退款再累计 refund_cents:微信通道按 total+已退 反推原始支付总额
            if from_status != OrderStatus.PENDING_PAYMENT and order.total_cents > 0:
                refund_amount = order.total_cents
                note = f"取消退款:{reason}"
                await request_refund(db, order, refund_amount, note)
                order.refund_cents += refund_amount
                order.refund_note = (
                    f"{order.refund_note};{note}" if order.refund_note else note
                )
        db.add(
            OrderEvent(
                order_id=order.id,
                from_status=from_status.value,
                to_status=to_status.value,
                actor_role="system",
                actor_id=None,
            )
        )
        logger.info("auto_flow: %s %s -> %s (%s)", order.order_no, from_status.value, to_status.value, reason)
    return list(orders)


async def _sweep_voucher_purchases(db, now: datetime) -> int:
    """团购券待支付超时关闭 + 库存回补(与外卖支付超时同节奏)。"""
    from ..models import Voucher, VoucherPurchase, VoucherPurchaseStatus

    stale = (
        await db.scalars(
            select(VoucherPurchase)
            .where(
                VoucherPurchase.status == VoucherPurchaseStatus.pending_payment,
                VoucherPurchase.created_at
                < now - timedelta(minutes=settings.pay_timeout_minutes),
            )
            .with_for_update(skip_locked=True)
            .limit(200)
        )
    ).all()
    for p in stale:
        p.status = VoucherPurchaseStatus.cancelled
        p.refund_note = "支付超时自动关闭"
        await db.execute(
            update(Voucher).where(Voucher.id == p.voucher_id)
            .values(total_count=Voucher.total_count + 1,
                    sold_count=Voucher.sold_count - 1))
    return len(stale)


async def _sweep_orphan_appends(db: AsyncSession, now: datetime) -> list[Order]:
    """孤儿追加单:原单被取消(任何路径)后,追加单失去配送载体,级联取消退款。
    30 秒清扫周期的最终一致足够——期间商家看到的也是"原单已取消"。"""
    orphans = (
        await db.scalars(
            select(Order)
            .where(
                Order.parent_order_no != "",
                Order.status.in_([OrderStatus.PAID, OrderStatus.ACCEPTED,
                                  OrderStatus.READY]),
                Order.parent_order_no.in_(
                    select(Order.order_no).where(
                        Order.status == OrderStatus.CANCELLED)),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        )
    ).all()
    for order in orphans:
        from_status = order.status
        order.status = OrderStatus.CANCELLED
        order.cancel_reason = "原订单已取消,追加单一并取消并退款"
        if from_status in RESTOCK_FROM_STATUSES:
            await restore_stock(db, order)
        if order.total_cents > 0:
            note = "原单取消,追加单退款"
            await request_refund(db, order, order.total_cents, note)
            order.refund_cents += order.total_cents
            order.refund_note = (f"{order.refund_note};{note}"
                                 if order.refund_note else note)
        db.add(OrderEvent(order_id=order.id, from_status=from_status.value,
                          to_status=OrderStatus.CANCELLED.value,
                          actor_role="system", actor_id=None))
        logger.info("auto_flow: 追加单 %s 随原单 %s 级联取消",
                    order.order_no, order.parent_order_no)
    return list(orphans)


async def _sweep_ready_timeout(db: AsyncSession, now: datetime):
    """出餐超时两档催单(每档一次):
    一档:超过承诺出餐时长未出餐 → 催商家;
    二档:超过 1.5 倍 → 再催商家 + 安抚用户(「商家出餐慢了,已催促」)。
    预约单以预约时间为基准:预约前 promise 分钟该出餐,预约到点仍未出餐进二档。
    """
    orders = (
        await db.scalars(
            select(Order)
            .where(
                Order.status == OrderStatus.ACCEPTED,
                Order.ready_alert_stage < 2,
                Order.accepted_at.is_not(None),
            )
            .with_for_update(skip_locked=True)
            .limit(200)
        )
    ).all()
    if not orders:
        return [], []
    shops = {
        m.id: m
        for m in await db.scalars(
            select(Merchant).where(
                Merchant.id.in_({o.merchant_id for o in orders})))
    }
    stage1: list[Order] = []
    stage2: list[Order] = []
    for order in orders:
        shop = shops.get(order.merchant_id)
        if shop is None:
            continue
        promise = timedelta(minutes=shop.promise_ready_minutes)
        accepted_at = order.accepted_at
        if accepted_at.tzinfo is None:
            accepted_at = accepted_at.replace(tzinfo=timezone.utc)
        if order.scheduled_at is not None:
            scheduled_at = order.scheduled_at
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
            d1, d2 = scheduled_at - promise, scheduled_at
        else:
            d1, d2 = accepted_at + promise, accepted_at + promise * 1.5
        if order.ready_alert_stage == 0 and now > d1:
            order.ready_alert_stage = 1
            stage1.append(order)
            logger.info("auto_flow: %s 出餐超时一档提醒", order.order_no)
        elif order.ready_alert_stage == 1 and now > d2:
            order.ready_alert_stage = 2
            stage2.append(order)
            logger.info("auto_flow: %s 出餐超时二档提醒(安抚用户)", order.order_no)
            # 出餐严重超时:顺延 ETA 并告知用户"商家出餐较慢,预计延后到 X"
            try:
                from .eta import recompute_eta
                await recompute_eta(db, order, shop, delay=True)
            except Exception:
                logger.exception("出餐超时 ETA 顺延失败 %s", order.order_no)
    return stage1, stage2


async def _notify_ready_timeout(stage1, stage2) -> None:
    """出餐催单推送(commit 之后发)。"""
    if not stage1 and not stage2:
        return
    async with SessionLocal() as db:
        owners = {
            m.id: m.owner_id
            for m in await db.scalars(
                select(Merchant).where(Merchant.id.in_(
                    {o.merchant_id for o in [*stage1, *stage2]})))
        }
    for order in stage1:
        owner = owners.get(order.merchant_id)
        if owner:
            await push_to_user(owner, "出餐超时提醒",
                               f"订单#{order.order_no[-6:]} 已超过承诺出餐时长,请尽快出餐",
                               {"type": "order", "order_no": order.order_no})
    for order in stage2:
        owner = owners.get(order.merchant_id)
        if owner:
            await push_to_user(owner, "出餐严重超时",
                               f"订单#{order.order_no[-6:]} 严重超时,用户已收到致歉,请立即处理",
                               {"type": "order", "order_no": order.order_no})
        await push_to_user(order.customer_id, "抱歉让你久等了",
                           "商家出餐慢了,平台已催促;如不想等了可联系商家协商取消",
                           {"type": "order", "order_no": order.order_no})


async def _sweep_no_rider(db: AsyncSession, now: datetime):
    """无人接单兜底。即时单从下单时间起算;预约单以预约时间为基准
    (提前 30 分钟还没人接就提醒,到点仍没人接就取消)。

    取消的钱怎么算:用户全额退款;商家已出餐(READY)的,平台按商家应收口径
    (菜品+打包-满减)全额赔付、佣金一分不收——运力不足是平台的问题,
    不能让做了餐的商家背锅。赔付走 merchant_earnings 正常入账行,
    公开账本里 net == food - 0 恒等式照样成立,社区可验证。
    """
    from .wechat_pay import request_refund

    waiting = [
        Order.status.in_([OrderStatus.ACCEPTED, OrderStatus.READY]),
        Order.rider_id.is_(None),
        Order.pickup.is_(False),        # 自取单不需要骑手,不在兜底范围
        Order.self_delivery.is_(False),  # 商家自送,不在兜底范围
        Order.parent_order_no == "",    # 追加单随原单,原单被兜底时一并级联
    ]
    immediate = Order.scheduled_at.is_(None)
    scheduled = Order.scheduled_at.is_not(None)
    # 即时单计时基准:进入无骑手状态的时刻(支付/转单时写入)。
    # 转出的单从转单时刻重新起算,不会一回池就被兜底取消;老数据回退 created_at
    pool_since = func.coalesce(Order.rider_pool_since, Order.created_at)

    # 极端天气停运时取消线缩短:运力大概率断供,别让用户干等
    from .flags import weather_shutdown_on
    cancel_minutes = (15 if await weather_shutdown_on(db)
                      else settings.no_rider_cancel_minutes)

    cancel_orders = (
        await db.scalars(
            select(Order)
            .where(
                *waiting,
                (immediate & (pool_since
                              < now - timedelta(minutes=cancel_minutes)))
                | (scheduled & (Order.scheduled_at < now)),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        )
    ).all()
    compensated: dict[int, int] = {}  # order_id -> 赔付金额
    for order in cancel_orders:
        from_status = order.status
        refund_amount = order.total_cents
        order.status = OrderStatus.CANCELLED
        order.cancel_reason = "长时间无骑手接单,平台自动取消并全额退款"
        order.refund_cents += refund_amount
        note = "无骑手接单,全额退款"
        order.refund_note = (
            f"{order.refund_note};{note}" if order.refund_note else note)
        await request_refund(db, order, refund_amount, "无骑手接单自动取消")
        if from_status == OrderStatus.READY:
            comp = (order.food_cents + order.packing_fee_cents
                    - order.discount_cents)
            if comp > 0:
                db.add(MerchantEarning(
                    merchant_id=order.merchant_id,
                    order_id=order.id,
                    order_no=order.order_no,
                    food_cents=comp,
                    commission_cents=0,
                    net_cents=comp,
                    kind=EarningKind.earning,
                    note="无骑手接单取消,平台赔付餐损(佣金不收)",
                ))
                compensated[order.id] = comp
        db.add(OrderEvent(
            order_id=order.id,
            from_status=from_status.value,
            to_status=OrderStatus.CANCELLED.value,
            actor_role="system",
            actor_id=None,
        ))
        logger.info("auto_flow: %s 无骑手接单自动取消(已出餐赔付=%s 分)",
                    order.order_no, compensated.get(order.id, 0))

    alert_orders = (
        await db.scalars(
            select(Order)
            .where(
                *waiting,
                Order.no_rider_alerted_at.is_(None),
                (immediate & (pool_since
                              < now - timedelta(minutes=settings.no_rider_alert_minutes)))
                | (scheduled & (Order.scheduled_at < now + timedelta(minutes=30))),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        )
    ).all()
    for order in alert_orders:
        order.no_rider_alerted_at = now
        logger.info("auto_flow: %s 无骑手接单,提醒在线骑手与商家", order.order_no)
    return alert_orders, cancel_orders, compensated


async def _notify_no_rider(alert_orders, cancel_orders, compensated) -> None:
    """无人接单的推送(commit 之后发,推送失败不影响账)。"""
    if not alert_orders and not cancel_orders:
        return
    async with SessionLocal() as db:
        merchant_ids = {o.merchant_id for o in [*alert_orders, *cancel_orders]}
        owners = {
            m.id: m.owner_id
            for m in await db.scalars(
                select(Merchant).where(Merchant.id.in_(merchant_ids)))
        }
        online_riders = []
        if alert_orders:
            online_riders = (
                await db.scalars(
                    select(User.id).where(
                        User.role == UserRole.rider, User.is_online.is_(True))
                    .limit(100)
                )
            ).all()
    for order in cancel_orders:
        await push_to_user(order.customer_id, "订单已退款",
                           "长时间无骑手接单,订单已自动取消并全额退款,抱歉让你久等了",
                           {"type": "order", "order_no": order.order_no})
        owner = owners.get(order.merchant_id)
        if owner:
            comp = compensated.get(order.id, 0)
            body = (f"订单无骑手接单已自动取消,已出餐部分平台赔付 ¥{comp / 100:.2f}(佣金不收)"
                    if comp else "订单无骑手接单已自动取消,用户已全额退款")
            await push_to_user(owner, "订单已取消", body,
                               {"type": "order", "order_no": order.order_no})
    for order in alert_orders:
        owner = owners.get(order.merchant_id)
        if owner:
            await push_to_user(owner, "订单还没有骑手接单",
                               "已提醒附近在线骑手;若长时间无人接单,平台会自动取消并退款",
                               {"type": "order", "order_no": order.order_no})
    for rider_id in online_riders:
        await push_to_user(rider_id, "有订单等待接单",
                           f"{len(alert_orders)} 个订单还没有骑手接,顺路就去抢一单吧",
                           {"type": "grab"})


async def _sweep_rider_offline(db: AsyncSession, now: datetime) -> int:
    """位置心跳断档超 5 分钟的在线骑手视为掉线:置离线并补写下线时间。
    上线不足 5 分钟的不动(给冷启动上报留时间)。"""
    from sqlalchemy import and_

    from ..models import RiderSession
    from ..redis_client import RIDER_LOC_KEY, get_redis

    rows = (await db.execute(
        select(User, RiderSession)
        .join(RiderSession, and_(RiderSession.rider_id == User.id,
                                 RiderSession.offline_at.is_(None)))
        .where(User.role == UserRole.rider, User.is_online.is_(True),
               RiderSession.online_at < now - timedelta(minutes=5))
        .limit(200))).all()
    redis = get_redis()
    closed = 0
    for user, sess in rows:
        loc = await redis.hgetall(RIDER_LOC_KEY.format(rider_id=user.id))
        if not loc:  # 位置键 5 分钟过期,不存在即断档
            user.is_online = False
            sess.offline_at = now
            closed += 1
    if closed:
        logger.info("auto_flow: %s 名骑手心跳断档,已补写下线", closed)
    return closed


async def _sweep_privacy_unbind(db: AsyncSession, now: datetime) -> int:
    """隐私中间号解绑:订单终结(完成/取消)N 小时后释放 X 号。

    只有接入 AXB 后才会有绑定记录;解绑失败保留 privacy_phone,下轮重试。
    """
    result = await db.scalars(
        select(Order).where(
            Order.privacy_phone != "",
            Order.status.in_([OrderStatus.COMPLETED, OrderStatus.CANCELLED]),
            Order.updated_at
            < now - timedelta(hours=settings.privacy_phone_unbind_hours),
        ).limit(200)
    )
    count = 0
    for order in result:
        await unbind_order(order)
        if not order.privacy_phone:
            count += 1
    return count


async def sweep_once() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        expired_vouchers = await _sweep_voucher_purchases(db, now)
        if expired_vouchers:
            logger.info("auto_flow: 关闭 %s 张超时未支付的团购券", expired_vouchers)
        closed_unpaid = await _transition_batch(
            db,
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.CANCELLED,
            Order.created_at,
            now - timedelta(minutes=settings.pay_timeout_minutes),
            "支付超时",
        )
        cancelled_unaccepted = await _transition_batch(
            db,
            OrderStatus.PAID,
            OrderStatus.CANCELLED,
            Order.updated_at,
            now - timedelta(minutes=settings.accept_timeout_minutes),
            "商家超时未接单",
            # 预约单豁免:商家不必立即接单,预约时间前 1 小时还没接才算超时
            extra_where=(
                Order.scheduled_at.is_(None)
                | (Order.scheduled_at < now + timedelta(hours=1))
            ),
        )
        completed = await _transition_batch(
            db,
            OrderStatus.DELIVERED,
            OrderStatus.COMPLETED,
            Order.updated_at,
            now - timedelta(hours=settings.auto_confirm_hours),
            "超时自动确认收货",
        )
        # 自取单出餐后长时间没来取:超时自动完成(餐已做,商家收入保住)
        pickup_done = await _transition_batch(
            db,
            OrderStatus.READY,
            OrderStatus.COMPLETED,
            Order.updated_at,
            now - timedelta(hours=settings.auto_confirm_hours),
            "自取超时自动完成",
            extra_where=Order.pickup.is_(True),
        )
        # 自动确认同样触发结算(骑手 + 商家;自取单无骑手行)
        for order in [*completed, *pickup_done]:
            await settle_order(db, order)
        alerted, no_rider_cancelled, compensated = await _sweep_no_rider(db, now)
        ready_stage1, ready_stage2 = await _sweep_ready_timeout(db, now)
        orphan_appends = await _sweep_orphan_appends(db, now)
        unbound = await _sweep_privacy_unbind(db, now)
        await _sweep_rider_offline(db, now)
        # 分账重试兜底(桩模式下 pending 会累积 attempts,资质到位后自然走通)
        from .profit_sharing import sweep_pending as _ps_sweep
        await _ps_sweep(db)
        await db.commit()
        # 超时赔付兜底补发:送达时判赔失败/进程重启漏掉的,清扫补上
        # (compensate_if_late 自带幂等与豁免判断,独立事务)
        try:
            from .eta import LATE_GRACE_MINUTES, compensate_if_late
            late_delivered = (await db.scalars(
                select(Order).where(
                    Order.status == OrderStatus.DELIVERED,
                    Order.eta_at.isnot(None),
                    Order.eta_at
                    < now - timedelta(minutes=LATE_GRACE_MINUTES),
                ).limit(50))).all()
            for order in late_delivered:
                await compensate_if_late(db, order)
        except Exception:
            logger.exception("超时赔付兜底补发失败")

    try:
        await _notify_no_rider(alerted, no_rider_cancelled, compensated)
        await _notify_ready_timeout(ready_stage1, ready_stage2)
    except Exception:  # 推送永远不能拖垮清扫主流程
        logger.exception("无人接单/出餐超时推送失败")

    for order in [*closed_unpaid, *cancelled_unaccepted, *completed,
                  *pickup_done, *no_rider_cancelled, *orphan_appends]:
        await manager.broadcast(
            f"order:{order.order_no}",
            {"type": "order_status", "order_no": order.order_no, "status": order.status.value},
        )
    return {
        "closed_unpaid": len(closed_unpaid),
        "cancelled_unaccepted": len(cancelled_unaccepted),
        "auto_completed": len(completed),
        "pickup_auto_completed": len(pickup_done),
        "no_rider_alerted": len(alerted),
        "no_rider_cancelled": len(no_rider_cancelled),
        "ready_alert_1": len(ready_stage1),
        "ready_alert_2": len(ready_stage2),
        "orphan_appends_cancelled": len(orphan_appends),
        "privacy_unbound": unbound,
    }


def _in_window(target_hhmm: str, now: datetime, window_seconds: int = 150) -> bool:
    """now 是否落在 target 时刻后的窗口内(窗口略大于清扫间隔,保证不漏触发)。"""
    try:
        hour, minute = target_hhmm.split(":")
        target = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    except ValueError:
        return False
    delta = (now - target).total_seconds()
    return 0 <= delta < window_seconds


def _holiday_plan_for(plans: list, today: str) -> dict | None:
    """当天生效的节假日计划(from ≤ 今天 ≤ to),没有返回 None。"""
    for p in plans or []:
        start = p.get("from", "")
        end = p.get("to") or start
        if start and start <= today <= end:
            return p
    return None


def _in_business_range(open_t: str, close_t: str, now: datetime) -> bool:
    """now 是否在营业区间内(支持跨天,如 18:00-02:00)。没设时间视为随时可开。"""
    if not open_t or not close_t:
        return True
    hhmm = now.strftime("%H:%M")
    if open_t <= close_t:
        return open_t <= hhmm < close_t
    return hhmm >= open_t or hhmm < close_t


async def sync_business_hours(now: datetime | None = None) -> dict[str, int]:
    """营业时间自动开关店:到开店时刻自动营业,到打烊时刻自动歇业。

    只在时刻边界的窗口内动手,其余时间商家手动开关不受干扰
    (设了 21:00 打烊,老板 15:00 想临时歇业照样可以)。
    优先级:节假日计划 > 临时歇业 > 每日 open/close > 手动开关——
    歇业计划日强制关店;特殊时段日用计划时段替代每日时段;
    临时歇业(closed_until)未到点不自动开,到点若在营业区间内自动恢复。
    """
    now = now or datetime.now(BEIJING)
    today = now.strftime("%Y-%m-%d")
    opened = closed = 0
    async with SessionLocal() as db:
        shops = (
            await db.scalars(
                select(Merchant).where(
                    Merchant.status == MerchantStatus.approved,
                    ((Merchant.open_time != "") & (Merchant.close_time != ""))
                    | Merchant.closed_until.is_not(None)
                    | text("merchants.holiday_plans != '[]'::jsonb"),
                )
            )
        ).all()
        for shop in shops:
            plan = _holiday_plan_for(shop.holiday_plans, today)
            # 歇业计划日:强制关店(优先级最高,想营业请删计划)
            if plan is not None and plan.get("closed", True):
                if shop.is_open:
                    shop.is_open = False
                    closed += 1
                    logger.info("holiday close: %s (%s~%s)",
                                shop.name, plan.get("from"), plan.get("to"))
                continue
            # 特殊时段日:用计划时段替代每日时段
            open_t = plan["open"] if plan is not None else shop.open_time
            close_t = plan["close"] if plan is not None else shop.close_time
            # 临时歇业:未到点跳过自动开店;到点清标记,在营业区间内则恢复
            if shop.closed_until is not None:
                if shop.closed_until > now:
                    continue
                shop.closed_until = None
                if not shop.is_open and _in_business_range(open_t, close_t, now):
                    shop.is_open = True
                    opened += 1
                    logger.info("rest over, reopen: %s", shop.name)
                continue
            if not (open_t and close_t):
                continue
            if _in_window(open_t, now) and not shop.is_open:
                shop.is_open = True
                opened += 1
                logger.info("auto open: %s at %s", shop.name, open_t)
            elif _in_window(close_t, now) and shop.is_open:
                shop.is_open = False
                closed += 1
                logger.info("auto close: %s at %s", shop.name, close_t)
        await db.commit()
    return {"opened": opened, "closed": closed}


async def reset_daily_stock(db: AsyncSession) -> tuple[int, int]:
    """库存每日恢复(本身幂等,可安全重复执行):

    1. 设了 daily_stock 的菜:stock 回满到目标值,估清标记一并清除;
    2. 没设每日回满但估清过的菜:stock 恢复为估清前存档值。
    返回 (回满数, 估清恢复数)。
    """
    refilled = (await db.execute(
        update(Dish)
        .where(Dish.daily_stock.is_not(None))
        .values(stock=Dish.daily_stock, sold_out_today=False,
                stock_before_soldout=None)
    )).rowcount
    restored = (await db.execute(
        update(Dish)
        .where(Dish.daily_stock.is_(None), Dish.sold_out_today.is_(True))
        .values(
            stock=func.coalesce(Dish.stock_before_soldout, Dish.stock),
            sold_out_today=False,
            stock_before_soldout=None,
        )
    )).rowcount
    await db.commit()
    return refilled, restored


async def cleanup_expired_holiday_plans(db: AsyncSession,
                                        today: str) -> int:
    """清理已过期的节假日计划条目(to < 今天)。幂等。"""
    shops = (await db.scalars(
        select(Merchant).where(text("merchants.holiday_plans != '[]'::jsonb"))
    )).all()
    cleaned = 0
    for shop in shops:
        kept = [p for p in shop.holiday_plans
                if (p.get("to") or p.get("from", "")) >= today]
        if len(kept) != len(shop.holiday_plans):
            shop.holiday_plans = kept
            cleaned += 1
    await db.commit()
    return cleaned


async def maybe_reset_daily_stock(now: datetime | None = None) -> bool:
    """每天北京时间 04:00 窗口执行一次库存回满/估清恢复(Redis 防重)。

    过期节假日计划的清理也搭这班车(每天一次足够)。
    """
    from ..redis_client import get_redis

    now = now or datetime.now(BEIJING)
    if not _in_window("04:00", now, window_seconds=300):
        return False
    redis = get_redis()
    if not await redis.set(f"stock:reset:{now.date()}", 1, ex=86400, nx=True):
        return False
    async with SessionLocal() as db:
        refilled, restored = await reset_daily_stock(db)
        cleaned = await cleanup_expired_holiday_plans(
            db, now.strftime("%Y-%m-%d"))
    logger.info("每日任务:库存回满 %s 个,估清恢复 %s 个,过期节假日计划清理 %s 家",
                refilled, restored, cleaned)
    return True


def tier_rate_for(count: int):
    """按上月完成单量查阶梯费率;任何档不得高于 5% 承诺上限(强制钳制)。"""
    from decimal import Decimal
    cap = Decimal("0.050")
    rate = cap
    for threshold, r in settings.commission_tiers:
        if count >= int(threshold):
            rate = min(Decimal(str(r)), cap)
    return rate


def _beijing_month_bounds(now_beijing: datetime) -> tuple[datetime, datetime]:
    """上个自然月的 [起, 止) UTC 边界(按北京时间划月)。"""
    month_start = now_beijing.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_start = (month_start - timedelta(days=1)).replace(day=1)
    return (prev_start.astimezone(timezone.utc),
            month_start.astimezone(timezone.utc))


async def completed_counts(db: AsyncSession, start_utc: datetime,
                           end_utc: datetime) -> dict[int, int]:
    """各商家在时间窗内的完成单量(以 completed 事件时间为准)。"""
    rows = await db.execute(
        select(Order.merchant_id, func.count(func.distinct(Order.id)))
        .join(OrderEvent, OrderEvent.order_id == Order.id)
        .where(OrderEvent.to_status == OrderStatus.COMPLETED.value,
               OrderEvent.created_at >= start_utc,
               OrderEvent.created_at < end_utc)
        .group_by(Order.merchant_id))
    return dict(rows.all())


async def recalc_commission_tiers(
        db: AsyncSession, now_beijing: datetime) -> list[dict]:
    """月度重算全体商家费率:min(档位费率, 现费率),手工优惠不上调。

    历史订单佣金不动(下单时快照);公开账本无需改——payload 的
    commission_rate_max 仍是 5% 上限,witness 校验的是 ≤ 上限。
    返回变更清单 [{merchant_id, owner_id, name, old, new}] 供推送。
    """
    start_utc, end_utc = _beijing_month_bounds(now_beijing)
    counts = await completed_counts(db, start_utc, end_utc)
    merchants = (await db.scalars(select(Merchant))).all()
    changes: list[dict] = []
    for shop in merchants:
        target = min(tier_rate_for(counts.get(shop.id, 0)),
                     shop.commission_rate)
        if target != shop.commission_rate:
            changes.append({
                "merchant_id": shop.id, "owner_id": shop.owner_id,
                "name": shop.name,
                "old": shop.commission_rate, "new": target,
            })
            shop.commission_rate = target
    await db.commit()
    return changes


async def maybe_recalc_commission_tiers(now: datetime | None = None) -> bool:
    """每月 1 日北京时间 04:10 重算阶梯佣金(Redis 防重,重启安全)。"""
    from ..redis_client import get_redis

    now = now or datetime.now(BEIJING)
    if now.day != 1 or not _in_window("04:10", now, window_seconds=300):
        return False
    redis = get_redis()
    if not await redis.set(f"tier:recalc:{now.strftime('%Y-%m')}", 1,
                           ex=86400 * 40, nx=True):
        return False
    async with SessionLocal() as db:
        changes = await recalc_commission_tiers(db, now)
    logger.info("阶梯佣金月度重算完成:%s 家费率下调", len(changes))
    for c in changes:  # 费率变化推送商家(只降不升,是好消息)
        try:
            await push_to_user(
                c["owner_id"], "佣金费率下调",
                f"上月单量达标,「{c['name']}」佣金费率由 "
                f"{float(c['old']) * 100:.1f}% 降至 {float(c['new']) * 100:.1f}%,"
                f"本月起生效。单量越大费率越低,5% 永远是上限",
                {"type": "shop"}, record_skip=True)
        except Exception:
            logger.exception("费率下调推送失败")
    return True


async def maybe_run_daily_audit(now: datetime | None = None) -> bool:
    """每天北京时间 04:00 窗口执行一次账务自检(Redis 防重,重启安全)。"""
    from ..redis_client import get_redis
    from .audit import run_audit

    now = now or datetime.now(BEIJING)
    if not _in_window("04:00", now, window_seconds=300):
        return False
    redis = get_redis()
    if not await redis.set(f"audit:ran:{now.date()}", 1, ex=86400, nx=True):
        return False
    await run_audit()
    return True


async def maybe_record_health_probe() -> bool:
    """每 5 分钟自记一次系统健康(/status 可用率数据源,透明中心公示)。

    数据库挂了这一行写不进来——缺探针按不可用计,可用率只低不虚高。
    Redis 不可用时跳过防重直接记录(单实例部署,重复无害)。顺手清 90 天前的。
    """
    import time as _time

    from sqlalchemy import delete, text as sa_text

    from ..models import HealthProbe
    from ..redis_client import get_redis

    slot = int(_time.time() // 300)
    redis_ok = True
    try:
        if not await get_redis().set(f"health:probe:{slot}", 1, ex=360, nx=True):
            return False  # 本 5 分钟窗口已记录
    except Exception:
        redis_ok = False  # Redis 挂了也要留档,如实记 redis_ok=False
    try:
        async with SessionLocal() as db:
            await db.execute(sa_text("SELECT 1"))
            db.add(HealthProbe(db_ok=True, redis_ok=redis_ok))
            await db.execute(delete(HealthProbe).where(
                HealthProbe.created_at
                < datetime.now(timezone.utc) - timedelta(days=90)))
            await db.commit()
        return True
    except Exception:
        logger.warning("健康探针记录失败(数据库不可用,缺档即降可用率)")
        return False


async def auto_flow_loop() -> None:
    logger.info("auto_flow loop started, interval=%ss", settings.sweep_interval_seconds)
    while True:
        try:
            await sweep_once()
            await sync_business_hours()
            await maybe_reset_daily_stock()
            # 饭点前备货提示(10:00 午市 / 16:00 晚市,Redis 防重)
            from .stocking import push_stocking_reminders
            await push_stocking_reminders(datetime.now(BEIJING))
            # 营销触达(10:00 生日+复购 / 18:00 收藏上新,每周 2 条频控)
            from .marketing import maybe_run_marketing
            await maybe_run_marketing(datetime.now(BEIJING))
            await maybe_recalc_commission_tiers()
            await maybe_run_daily_audit()
            await maybe_record_health_probe()
            # 公开账本锚点补到昨天(幂等,通常零工作量;见 services/ledger.py)
            from .ledger import build_missing_anchors
            async with SessionLocal() as db:
                await build_missing_anchors(db)
        except Exception:  # 清扫失败不能拖垮主服务,下一轮重试
            logger.exception("auto_flow sweep failed")
        await asyncio.sleep(settings.sweep_interval_seconds)
