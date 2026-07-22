"""用户主动售后:判责 + 各自承担 + 平台只垫付不兜底。

- 申请必须带举证照片;30 天 3 次成功售后后走客服;黑名单用户只能走工单
- 商家同意 = 商家责任:退餐费(配送费已履约不退),商家净额+平台佣金冲账
- 骑手责任(洒餐/丢餐)由客服在管理后台仲裁:平台先行赔付全额(含配送费),
  商家与骑手收入不动,资金来源是公开账本里逐日计提的骑手保障金(rider_fund)
退款写 refunds 流水(真实/模拟通道同一入口)+ 订单 refund_cents 汇总 +
已结算订单冲账(负数行,见 services/settlement.py)。
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import AfterSale, AfterSaleStatus, Merchant, Order, User
from ..schemas import AfterSaleIn, AfterSaleOut, AfterSaleReplyIn, MerchantAfterSaleOut
from ..security import require_role
from ..services.push import push_to_user
from ..services.settlement import reverse_merchant_earning
from ..services.wechat_pay import request_refund
from ..state_machine import OrderStatus

router = APIRouter(tags=["售后"])

APPLY_WINDOW_DAYS = 7


def _summary(order: Order) -> str:
    return "、".join(f"{i['name']}×{i['quantity']}" for i in order.items)


def _merchant_out(a: AfterSale, order: Order) -> MerchantAfterSaleOut:
    out = MerchantAfterSaleOut.model_validate(a)
    out.order_no = order.order_no
    out.order_summary = _summary(order)
    out.total_cents = order.total_cents
    return out


@router.post("/orders/{order_no}/after-sale", response_model=AfterSaleOut)
async def submit_after_sale(
    order_no: str,
    payload: AfterSaleIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    if user.after_sale_banned:
        raise HTTPException(403, "售后功能已受限,请通过平台客服工单处理")
    if not payload.images:
        raise HTTPException(422, "售后需上传照片举证(拍一下餐品即可);"
                                 "如无法上传请升级 App 到最新版")
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.status not in (OrderStatus.DELIVERED, OrderStatus.COMPLETED):
        raise HTTPException(409, "订单送达后才能申请售后")
    # 次数风控:30 天内成功售后 ≥3 次,再申请必须走客服人工核实(公平不纵容恶意售后)
    from sqlalchemy import func as sa_func
    accepted_recent = await db.scalar(
        select(sa_func.count(AfterSale.id)).where(
            AfterSale.customer_id == user.id,
            AfterSale.status == AfterSaleStatus.accepted,
            AfterSale.created_at
            >= datetime.now(timezone.utc) - timedelta(days=30),
        )
    )
    if accepted_recent >= 3:
        raise HTTPException(409, "30 天内已有 3 次成功售后,新申请请联系平台客服核实")
    if order.created_at < datetime.now(timezone.utc) - timedelta(days=APPLY_WINDOW_DAYS):
        raise HTTPException(409, f"超过售后期({APPLY_WINDOW_DAYS} 天),请联系平台客服")
    existing = await db.scalar(
        select(AfterSale).where(AfterSale.order_id == order.id)
    )
    if existing:
        raise HTTPException(409, "这一单已经申请过售后")

    after_sale = AfterSale(
        order_id=order.id,
        customer_id=user.id,
        merchant_id=order.merchant_id,
        reason=payload.reason.strip(),
        images=payload.images,
    )
    db.add(after_sale)
    await db.commit()
    await db.refresh(after_sale)

    # 提醒商家老板尽快处理
    merchant = await db.get(Merchant, order.merchant_id)
    if merchant:
        await push_to_user(
            merchant.owner_id, "有新的售后申请",
            f"{_summary(order)}:{payload.reason[:30]}",
            {"order_no": order.order_no, "type": "after_sale"},
        )
    return after_sale


@router.get("/orders/{order_no}/after-sale", response_model=AfterSaleOut)
async def get_after_sale(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    after_sale = await db.scalar(
        select(AfterSale).where(AfterSale.order_id == order.id)
    )
    if after_sale is None:
        raise HTTPException(404, "还没有售后申请")
    return after_sale


@router.get("/merchants/me/after-sales", response_model=list[MerchantAfterSaleOut])
async def my_shop_after_sales(
    status: AfterSaleStatus | None = None,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    query = (
        select(AfterSale, Order)
        .join(Order, Order.id == AfterSale.order_id)
        .where(AfterSale.merchant_id == shop.id)
        .order_by(AfterSale.created_at.desc())
        .limit(100)
    )
    if status is not None:
        query = query.where(AfterSale.status == status)
    rows = await db.execute(query)
    return [_merchant_out(a, order) for a, order in rows]


async def _get_pending(
    db: AsyncSession, after_sale_id: int, user: User
) -> tuple[AfterSale, Order]:
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    after_sale = await db.get(AfterSale, after_sale_id, with_for_update=True)
    if shop is None or after_sale is None or after_sale.merchant_id != shop.id:
        raise HTTPException(404, "售后申请不存在")
    if after_sale.status != AfterSaleStatus.pending:
        raise HTTPException(409, "该申请已处理过")
    order = await db.get(Order, after_sale.order_id)
    return after_sale, order


@router.post("/after-sales/{after_sale_id}/accept", response_model=AfterSaleOut)
async def accept_after_sale(
    after_sale_id: int,
    payload: AfterSaleReplyIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """同意售后 = 退还餐费部分(实付 - 配送费);已结算订单同步冲账。

    责任与钱的走向(行业通行判责规则的最简自动化形态):
    - 商家:冲回净额(菜价 - 佣金),损失由责任方商家承担 —— 同意售后即认责
    - 平台:佣金也冲回,不赚退款单的钱
    - 骑手:配送费分文不动 —— 配送已履约,菜品问题不该骑手买单
    - 用户:配送费不退(餐已送到家);配送本身出问题(洒餐/丢餐)属骑手/平台
      责任,量极小,走平台客服人工处理,平台先行赔付
    """
    after_sale, order = await _get_pending(db, after_sale_id, user)
    # 配送费不退:骑手入账保留,退款只覆盖餐费部分,平台不再为售后单倒贴配送费。
    # total_cents 在缺货部分退款时已同步扣减,此处即"用户当前净付金额"
    delivery_kept = order.delivery_fee_cents if order.rider_id is not None else 0
    refund_amount = max(order.total_cents - delivery_kept, 0)
    if refund_amount <= 0:
        raise HTTPException(409, "该订单已无可退金额")
    after_sale.status = AfterSaleStatus.accepted
    after_sale.fault = "merchant"  # 商家同意即认责,损失从商家结算款出
    after_sale.reply = payload.reply.strip()
    after_sale.processed_at = datetime.now(timezone.utc)
    order.refund_cents += refund_amount
    order.refund_note = (
        f"{order.refund_note};售后退餐费(配送费已履约不退)"
        if order.refund_note else "售后退餐费(配送费已履约不退)"
    )
    await reverse_merchant_earning(db, order, f"售后冲账:{after_sale.reason[:50]}")
    await request_refund(db, order, refund_amount, f"售后退款:{after_sale.reason[:30]}")
    await db.commit()
    await db.refresh(after_sale)
    await push_to_user(
        order.customer_id, "售后已通过",
        f"退款 ¥{refund_amount / 100:.2f} 将原路返回(配送费已履约不退):{after_sale.reply[:30]}",
        {"order_no": order.order_no},
    )
    return after_sale


@router.post("/after-sales/{after_sale_id}/reject", response_model=AfterSaleOut)
async def reject_after_sale(
    after_sale_id: int,
    payload: AfterSaleReplyIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    after_sale, order = await _get_pending(db, after_sale_id, user)
    after_sale.status = AfterSaleStatus.rejected
    after_sale.reply = payload.reply.strip()
    after_sale.processed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(after_sale)
    await push_to_user(
        order.customer_id, "售后处理结果",
        f"商家回复:{after_sale.reply[:40]}(如有异议可联系平台客服)",
        {"order_no": order.order_no},
    )
    return after_sale
