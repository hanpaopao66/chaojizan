"""支付成功的统一入账逻辑。

模拟支付和微信支付回调都走 mark_order_paid,幂等语义只此一份:
重复回调直接返回当前订单,绝不重复计佣金、重复推送。
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Merchant, Order, OrderEvent
from ..state_machine import OrderStatus
from ..ws import manager
from .cloud_print import print_order_async
from .privacy_phone import bind_order
from .push import notify_new_order

logger = logging.getLogger("superz.payment")


async def mark_order_paid(
    db: AsyncSession,
    order: Order,
    merchant: Merchant,
    actor_role: str = "system",
    actor_id: int | None = None,
) -> Order:
    if order.status != OrderStatus.PENDING_PAYMENT:
        return order  # 幂等:已支付/已取消的重复回调不做任何事

    order.status = OrderStatus.PAID
    # 配送单绑定隐私中间号(未配置 AXB 时是空操作,失败也不阻塞支付)
    if not order.pickup:
        await bind_order(order)
        # 进入无骑手状态的时刻:无人接单兜底从这里起算(骑手转单时会刷新)
        order.rider_pool_since = datetime.now(timezone.utc)
    # 预计送达时间(超时 15 分钟自动赔安抚券,平台承担;见 services/eta.py)
    from .eta import compute_eta
    order.eta_at = compute_eta(order, merchant)
    # 结算口径快照:商家分账就绪(特约商户号+接收方)才走 profit_sharing
    from .profit_sharing import settle_mode_for
    order.settle_mode = settle_mode_for(merchant)
    # 佣金基数 = 商家实收口径(菜品 + 打包费 - 商家满减):
    # 商家让利的部分平台不抽成,平台补贴的部分照常计佣(商家全额收到)
    gross = order.food_cents + order.packing_fee_cents - order.discount_cents
    order.commission_cents = int(Decimal(max(gross, 0)) * merchant.commission_rate)
    db.add(
        OrderEvent(
            order_id=order.id,
            from_status=OrderStatus.PENDING_PAYMENT.value,
            to_status=OrderStatus.PAID.value,
            actor_role=actor_role,
            actor_id=actor_id,
        )
    )
    await db.commit()
    await db.refresh(order)

    summary = "、".join(f"{i['name']}×{i['quantity']}" for i in order.items)
    await manager.broadcast(
        f"order:{order.order_no}",
        {"type": "order_status", "order_no": order.order_no, "status": order.status.value},
    )
    # 商家听单:WebSocket(前台)+ 离线推送(退后台)双通道
    await manager.broadcast(
        f"merchant:{order.merchant_id}",
        {
            "type": "new_order",
            "order_no": order.order_no,
            "summary": summary,
            "total_cents": order.total_cents,
        },
    )
    try:
        await notify_new_order(merchant.owner_id, order.order_no, summary)
    except Exception:  # 推送永远不能拖垮支付主流程
        logger.exception("新订单推送失败")
    # 商家系统回调入队(只入队不投递:投递走清扫任务,
    # 对方慢 8 秒不该把支付回调也卡 8 秒)
    try:
        from .webhooks import enqueue as _wh_enqueue
        await _wh_enqueue(db, merchant.id, "order.paid", order)
    except Exception:
        logger.exception("回调入队失败")

    # 云打印小票(商家绑定了打印机才会真的打;后台任务,失败只记日志)。
    # 多台时按用途各出各的:前厅全量、后厨不带顾客手机号和地址
    try:
        from sqlalchemy import select as _select

        from ..models import MerchantPrinter
        printers = list(await db.scalars(
            _select(MerchantPrinter).where(
                MerchantPrinter.merchant_id == merchant.id)))
        print_order_async(order, merchant, printers)
    except Exception:
        logger.exception("云打印任务创建失败")

    # 自动接单(商家开了开关且在营业):支付即进入制作,高峰期不用守着屏幕点。
    # 预约单照常自动接 —— 备餐提醒按预约时间走,不受接单时刻影响。
    # 失败只记日志,单子留在 PAID 等商家手动接,绝不因此丢单
    if merchant.auto_accept and merchant.is_open:
        try:
            await _auto_accept(db, order)
        except Exception:
            logger.exception("自动接单失败 %s(留在待接单)", order.order_no)
    return order


async def _auto_accept(db: AsyncSession, order: Order) -> None:
    """system 身份执行 PAID→ACCEPTED,副作用与商家手动接单对齐:
    记 accepted_at(备餐计时起点)、事件流水、推骑手抢单、告知用户。"""
    from sqlalchemy import select

    # **重新上锁并确认仍是 PAID**。PAID commit 释放行锁之后到这里,
    # 隔着广播/推送/打印几次慢 IO(JPush 超时可达数秒),期间订单可能
    # 已被顾客取消退款,也可能商家已经手动接单 —— 盲写 stale 对象会把
    # 已退款的单复活成 ACCEPTED 继续履约,那是资损级的竞态
    locked = await db.scalar(
        select(Order).where(Order.id == order.id).with_for_update())
    if locked is None or locked.status != OrderStatus.PAID:
        await db.rollback()  # 释放锁,别拖住别人的事务
        return
    now = datetime.now(timezone.utc)
    locked.status = OrderStatus.ACCEPTED
    locked.accepted_at = now
    db.add(OrderEvent(
        order_id=locked.id,
        from_status=OrderStatus.PAID.value,
        to_status=OrderStatus.ACCEPTED.value,
        actor_role="system",
        actor_id=None,
        note="自动接单",
    ))
    await db.commit()
    await db.refresh(locked)
    # 提交之后接单已生效:通知失败只记日志,**不能**让调用方的
    # 「留在待接单」日志把排查带偏
    try:
        await manager.broadcast(
            f"order:{locked.order_no}",
            {"type": "order_status", "order_no": locked.order_no,
             "status": locked.status.value},
        )
        # 与手动接单同口径:自取/自送/追加单不进抢单池
        if (locked.rider_id is None and not locked.pickup
                and not locked.self_delivery and not locked.parent_order_no):
            from ..models import Merchant as _M
            from .push import notify_riders_new_grab
            shop = await db.get(_M, locked.merchant_id)
            await notify_riders_new_grab(
                db, locked, shop.name if shop else "商家")
        from .push import notify_order_status
        await notify_order_status(
            locked.customer_id, locked.order_no, "制作中")
    except Exception:
        logger.exception("自动接单通知失败 %s(接单已生效)", locked.order_no)
