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
    # 等餐补偿:骑手到店后餐没好的那段时间,他没有任何收入 ——
    # 而这不是他的问题。**平台承担**,不进 delivery_fee_cents
    # (那是顾客付的钱),而是单独加在骑手的入账里。
    #
    # 这个补偿的函数和配置项早就写好了,但**在 AL 落地之前没有数据可算**
    # (没有到店时刻就没有等餐时长),所以一直是死代码。现在接上。
    wait_cents = 0
    if order.arrived_shop_at and order.picked_up_at:
        from .pricing import wait_compensation_cents
        wait_minutes = max(
            0.0,
            (order.picked_up_at - order.arrived_shop_at).total_seconds() / 60)
        wait_cents = wait_compensation_cents(wait_minutes)

    # 帮买:商品款按**小票实付**结给骑手,平台一分不抽 ——
    # 那是他替用户垫付的钱(虽然钱从平台走),对它抽成没有任何道理。
    # 没填小票就按预付金额结,而不是按 0 —— 骑手确实买了东西,
    # 让他自己承担平台的流程缺失是最坏的一种处理
    from .errand import KIND_ERRAND_BUY
    goods = 0
    if order.order_kind == KIND_ERRAND_BUY:
        goods = (order.goods_actual_cents
                 if order.goods_actual_cents is not None
                 else order.goods_budget_cents)

    # 跑腿单:平台从跑腿费里收 2%,骑手拿 98%。
    # **和外卖不是同一个口径**,外卖配送费一分不抽(平台收入来自商家佣金),
    # 跑腿没有商家,这 2% 是这条业务上唯一的收入
    from .errand import is_errand, service_fee_cents
    fee_cut = (service_fee_cents(order.delivery_fee_cents)
               if is_errand(order) else 0)
    db.add(
        RiderEarning(
            rider_id=order.rider_id,
            order_id=order.id,
            order_no=order.order_no,
            # 配送费 + 小费,一分不少全归骑手;再加平台承担的等餐补偿;
            # 跑腿单扣掉平台服务费
            amount_cents=(order.delivery_fee_cents + order.tip_cents
                          + wait_cents - fee_cut + goods),
        )
    )
    if wait_cents:
        # 记进订单的费用拆分,骑手在收入明细里看得到这笔是怎么来的。
        # **不加进 delivery_fee_cents** —— 顾客不该为商家的慢买单
        parts = dict(order.fee_parts or {})
        parts["wait"] = wait_cents
        order.fee_parts = parts


async def credit_merchant_for_order(db: AsyncSession, order: Order) -> None:
    # 跑腿单不产生商家入账:那个服务主体没有经营者、没有收款账户,
    # 给它记一行 food=0/commission=2%/net=-2% 的账,只会让它的钱包变成负数,
    # 然后每日核账的「商家余额不得为负」当场报红。
    # 平台那 2% 记在 order.commission_cents 上,审计里单独有一条跑腿恒等式
    from .errand import is_errand
    if is_errand(order):
        return
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
    #
    # **钳 0**:应收是负数意味着"商家倒贴钱给平台",钱包会被这一行倒扣。
    # 缺货退款按占比分摊满减之后(routers/orders.refund_item)这个数不该
    # 再为负,这里是兜底 —— 真为负了,审计规则 1 会因为净额对不上
    # 当场报红(order_gross 那边不钳),不会被这层兜底掩盖过去
    gross = max(order.food_cents + order.packing_fee_cents
                - order.discount_cents, 0)
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
