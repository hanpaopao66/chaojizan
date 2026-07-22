"""微信支付:统一下单 + 回调。模拟支付仍在 orders.py(开发期用)。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Merchant, Order, Refund, RefundStatus, User
from ..security import require_role
from ..services.payment_core import mark_order_paid
from ..services.wechat_pay import create_app_prepay, parse_notify
from ..state_machine import OrderStatus

logger = logging.getLogger("superz.wxpay")

router = APIRouter(tags=["支付"])


@router.post("/orders/{order_no}/pay/wechat")
async def wechat_prepay(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """微信 App 支付统一下单,返回拉起支付的参数。未配置商户号时 503。"""
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise HTTPException(409, "订单不是待支付状态")
    return create_app_prepay(order)


@router.post("/payments/wechat/notify")
async def wechat_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """微信回调(支付 + 退款共用):验签 → 解密 → 按事件分发,全部幂等。"""
    body = await request.body()
    parsed = parse_notify(dict(request.headers), body)
    if parsed is None:
        # 未配置时不该被调到;验签失败一律拒绝,防伪造回调
        raise HTTPException(400, "验签失败")
    event_type, resource = parsed

    if event_type == "TRANSACTION.SUCCESS":
        if resource.get("trade_state") != "SUCCESS":
            return {"code": "SUCCESS", "message": "成功"}
        order = await db.scalar(
            select(Order)
            .where(Order.order_no == resource.get("out_trade_no"))
            .with_for_update()
        )
        if order is None:
            logger.error("微信回调找不到订单: %s", resource.get("out_trade_no"))
            raise HTTPException(404, "订单不存在")
        merchant = await db.get(Merchant, order.merchant_id)
        await mark_order_paid(db, order, merchant, actor_role="system")

    elif event_type.startswith("REFUND."):
        refund = await db.scalar(
            select(Refund)
            .where(Refund.out_refund_no == resource.get("out_refund_no"))
            .with_for_update()
        )
        if refund is None:
            logger.error("退款回调找不到流水: %s", resource.get("out_refund_no"))
            raise HTTPException(404, "退款流水不存在")
        if refund.status != RefundStatus.success:  # 幂等:成功是终态
            if event_type == "REFUND.SUCCESS":
                refund.status = RefundStatus.success
            else:  # ABNORMAL / CLOSED:渠道侧失败,审计会因金额不平而告警
                refund.status = RefundStatus.failed
                refund.error = f"渠道回调 {event_type}"
                logger.error("退款失败 %s: %s", refund.out_refund_no, event_type)
            await db.commit()

    return {"code": "SUCCESS", "message": "成功"}
