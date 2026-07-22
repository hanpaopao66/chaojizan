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
    # 云打印小票(商家绑定了打印机才会真的打;后台任务,失败只记日志)
    try:
        print_order_async(order, merchant)
    except Exception:
        logger.exception("云打印任务创建失败")
    return order
