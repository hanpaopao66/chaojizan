"""结算:订单完成 → 骑手、商家分别入账;售后 → 冲账(追加负数行)。

人工确认收货和超时自动确认走的都是 settle_order,
两张流水表都靠 (order_id, kind) 唯一约束 + 先查后插保证幂等,绝不重复入账。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EarningKind, MerchantEarning, Order, RiderEarning


async def credit_rider_for_order(db: AsyncSession, order: Order) -> None:
    if order.rider_id is None:
        return  # 理论上完成单必有骑手,防御一下
    existing = await db.scalar(
        select(RiderEarning.id).where(
            RiderEarning.order_id == order.id,
            RiderEarning.kind == EarningKind.earning,
        )
    )
    if existing:
        return
    db.add(
        RiderEarning(
            rider_id=order.rider_id,
            order_id=order.id,
            order_no=order.order_no,
            # 配送费 + 小费,一分不少全归骑手
            amount_cents=order.delivery_fee_cents + order.tip_cents,
        )
    )


async def credit_merchant_for_order(db: AsyncSession, order: Order) -> None:
    existing = await db.scalar(
        select(MerchantEarning.id).where(
            MerchantEarning.order_id == order.id,
            MerchantEarning.kind == EarningKind.earning,
        )
    )
    if existing:
        return
    # 商家应收口径 = 菜品 + 打包费 - 商家满减(food_cents 列存的就是这个口径);
    # 自配送单配送费归商家(商家出运力),并入本行 food 口径——
    # 行内 net == food - commission 恒等式不破,佣金仍只按餐费计
    gross = order.food_cents + order.packing_fee_cents - order.discount_cents
    if order.self_delivery:
        gross += order.delivery_fee_cents
    db.add(
        MerchantEarning(
            merchant_id=order.merchant_id,
            order_id=order.id,
            order_no=order.order_no,
            food_cents=gross,
            commission_cents=order.commission_cents,
            net_cents=gross - order.commission_cents,
            # 分账口径的钱已直达商家微信商户号,平台侧不可提现(钱包过滤)
            settle_mode=order.settle_mode,
        )
    )


async def settle_order(db: AsyncSession, order: Order) -> None:
    """订单完成的唯一结算入口。"""
    await credit_rider_for_order(db, order)
    await credit_merchant_for_order(db, order)
    # 分账口径的单:落分账台账并尝试请求(幂等;失败留 pending 清扫兜底)
    from .profit_sharing import ensure_record
    await ensure_record(db, order)
    # 邀请有礼:被邀请人的首个完成单触发双方发券(风控命中的单不触发)
    try:
        from ..routers.referrals import reward_referral_if_first_order
        await reward_referral_if_first_order(db, order)
    except Exception:
        import logging
        logging.getLogger("superz.settlement").exception("邀请奖励失败")


async def reverse_merchant_earning(db: AsyncSession, order: Order, note: str) -> bool:
    """售后冲账:对已结算订单追加一条负数行,与入账行相加归零。

    骑手入账不冲(配送已完成,配送费归骑手是平台原则),
    (order_id, kind) 唯一约束保证一单最多冲一次。
    未结算(还没完成就退款)的订单没有入账行,无需冲账,返回 False。
    """
    earning = await db.scalar(
        select(MerchantEarning).where(
            MerchantEarning.order_id == order.id,
            MerchantEarning.kind == EarningKind.earning,
        )
    )
    if earning is None:
        return False
    already = await db.scalar(
        select(MerchantEarning.id).where(
            MerchantEarning.order_id == order.id,
            MerchantEarning.kind == EarningKind.reversal,
        )
    )
    if already:
        return False
    db.add(
        MerchantEarning(
            merchant_id=earning.merchant_id,
            order_id=order.id,
            order_no=order.order_no,
            food_cents=-earning.food_cents,
            commission_cents=-earning.commission_cents,
            net_cents=-earning.net_cents,
            settle_mode=earning.settle_mode,
            kind=EarningKind.reversal,
            note=note[:200],
        )
    )
    # 分账口径的单:售后成立同步发起渠道分账回退(桩)
    from .profit_sharing import request_return
    if earning.settle_mode == "profit_sharing":
        await request_return(db, order)
    return True
