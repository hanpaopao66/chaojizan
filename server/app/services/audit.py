"""每日账务自检——账本的守夜人。

核对的恒等式(近 30 天):
  1. 每笔完成订单必须有商家入账,且 net == food - commission
  2. 每笔有骑手的完成订单必须有骑手入账,且金额 == 配送费
  3. 非取消订单:total == food + delivery
  4. 任何骑手的可提现余额不得为负
  5. 每笔订单的 refund_cents 必须等于 refunds 流水之和(失败流水不算 → 自动暴露)
  6. 售后退款(完成单退餐费,配送费已履约不退)的已结算订单必须有商家冲账负数行
  7. 全局恒等,分两侧:菜品侧 Σ应收 == Σ商家净额+Σ佣金(售后冲账单剔除);
     配送侧 Σ配送费 == Σ骑手入账(售后单保留 —— 配送费 100% 归骑手的账面铁证)

不平 → 写 audit_alerts + logger.error,管理后台首页红条展示。
backfill_missing_earnings() 可对缺账的历史订单补记账(自愈,幂等)。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sa_func
from sqlalchemy import select

from ..db import SessionLocal
from ..models import (
    AuditAlert,
    EarningKind,
    MerchantEarning,
    Order,
    Refund,
    RefundStatus,
    RiderEarning,
    User,
    UserRole,
    Withdrawal,
    WithdrawalStatus,
)
from ..state_machine import OrderStatus
from .settlement import settle_order

logger = logging.getLogger("superz.audit")

WINDOW_DAYS = 30


async def run_audit() -> list[dict]:
    """执行全部核对,返回问题列表并写入告警表。"""
    problems: list[dict] = []
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    async with SessionLocal() as db:
        # 1+2) 完成订单 vs 账本
        completed = (
            await db.scalars(
                select(Order).where(
                    Order.status == OrderStatus.COMPLETED,
                    Order.created_at >= since,
                )
            )
        ).all()
        order_ids = [o.id for o in completed] or [0]
        m_earnings = {
            e.order_id: e
            for e in await db.scalars(
                select(MerchantEarning).where(
                    MerchantEarning.order_id.in_(order_ids),
                    MerchantEarning.kind == EarningKind.earning,
                )
            )
        }
        m_reversals = {
            e.order_id
            for e in await db.scalars(
                select(MerchantEarning).where(
                    MerchantEarning.order_id.in_(order_ids),
                    MerchantEarning.kind == EarningKind.reversal,
                )
            )
        }
        r_earnings = {
            e.order_id: e
            for e in await db.scalars(
                select(RiderEarning).where(
                    RiderEarning.order_id.in_(order_ids),
                    RiderEarning.kind == EarningKind.earning,
                )
            )
        }
        def order_gross(o: Order) -> int:
            """商家应收口径 = 菜品 + 打包费 - 商家满减;
            自配送单配送费归商家,一并计入(与结算同口径)。"""
            gross = o.food_cents + o.packing_fee_cents - o.discount_cents
            if o.self_delivery:
                gross += o.delivery_fee_cents
            return gross

        for order in completed:
            me = m_earnings.get(order.id)
            if me is None:
                problems.append({
                    "check": "merchant_earning_missing",
                    "detail": f"完成订单 {order.order_no} 缺商家入账",
                })
            elif me.net_cents != order_gross(order) - order.commission_cents:
                problems.append({
                    "check": "merchant_earning_mismatch",
                    "detail": f"订单 {order.order_no} 商家净额 {me.net_cents} "
                              f"≠ 应收 {order_gross(order)}-佣金 {order.commission_cents}",
                })
            if order.rider_id is not None:
                re = r_earnings.get(order.id)
                if re is None:
                    problems.append({
                        "check": "rider_earning_missing",
                        "detail": f"完成订单 {order.order_no} 缺骑手入账",
                    })
                elif re.amount_cents != (order.delivery_fee_cents
                                         + order.tip_cents):
                    problems.append({
                        "check": "rider_earning_mismatch",
                        "detail": f"订单 {order.order_no} 骑手入账 {re.amount_cents} "
                                  f"≠ 配送费 {order.delivery_fee_cents}"
                                  f"+小费 {order.tip_cents}",
                    })

        # 3) 订单金额自洽:实付 = 菜品 + 打包 - 满减 + 配送 - 平台补贴
        bad_totals = (
            await db.scalars(
                select(Order).where(
                    Order.status != OrderStatus.CANCELLED,
                    Order.created_at >= since,
                    Order.total_cents
                    != Order.food_cents + Order.packing_fee_cents
                    - Order.discount_cents + Order.delivery_fee_cents
                    + Order.tip_cents - Order.subsidy_cents,
                )
            )
        ).all()
        for order in bad_totals:
            problems.append({
                "check": "order_total_mismatch",
                "detail": f"订单 {order.order_no} 实付 {order.total_cents} ≠ "
                          f"菜品 {order.food_cents}+打包 {order.packing_fee_cents}"
                          f"-满减 {order.discount_cents}+配送 {order.delivery_fee_cents}"
                          f"-补贴 {order.subsidy_cents}",
            })

        # 4) 骑手余额不得为负
        riders = (
            await db.scalars(select(User).where(User.role == UserRole.rider))
        ).all()
        for rider in riders:
            earned = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(RiderEarning.amount_cents), 0))
                .where(RiderEarning.rider_id == rider.id)
            )
            out = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(Withdrawal.amount_cents), 0))
                .where(
                    Withdrawal.user_id == rider.id,
                    Withdrawal.role == "rider",
                    Withdrawal.status.notin_(
                        [WithdrawalStatus.rejected, WithdrawalStatus.failed]),
                )
            )
            if earned - out < 0:
                problems.append({
                    "check": "rider_balance_negative",
                    "detail": f"骑手 {rider.phone} 余额为负:{earned - out} 分",
                })

        # 4b) 商家余额不得为负(口径同商家钱包:外卖净额+团购核销净额-提现)
        from ..models import Merchant, VoucherPurchase, VoucherPurchaseStatus
        merchants = (await db.scalars(select(Merchant))).all()
        for shop in merchants:
            food_net = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(MerchantEarning.net_cents), 0))
                .where(MerchantEarning.merchant_id == shop.id,
                       # 分账口径不进平台侧余额(钱包同口径,见 merchants.py)
                       MerchantEarning.settle_mode == "platform")
            )
            voucher_net = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(VoucherPurchase.net_cents), 0))
                .where(VoucherPurchase.merchant_id == shop.id,
                       VoucherPurchase.status == VoucherPurchaseStatus.redeemed)
            )
            out = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(Withdrawal.amount_cents), 0))
                .where(
                    Withdrawal.user_id == shop.owner_id,
                    Withdrawal.role == "merchant",
                    Withdrawal.status.notin_(
                        [WithdrawalStatus.rejected, WithdrawalStatus.failed]),
                )
            )
            if food_net + voucher_net - out < 0:
                problems.append({
                    "check": "merchant_balance_negative",
                    "detail": f"商家 {shop.name} 余额为负:"
                              f"{food_net + voucher_net - out} 分",
                })

        # 5) 退款一致性:订单汇总 == 逐笔流水之和(failed 不计入 → 自动暴露渠道失败)
        refunded_orders = (
            await db.scalars(
                select(Order).where(
                    Order.refund_cents > 0, Order.created_at >= since
                )
            )
        ).all()
        for order in refunded_orders:
            refunded = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(Refund.amount_cents), 0)).where(
                    Refund.order_id == order.id,
                    Refund.status != RefundStatus.failed,
                )
            )
            if refunded != order.refund_cents:
                problems.append({
                    "check": "refund_mismatch",
                    "detail": f"订单 {order.order_no} 退款汇总 {order.refund_cents} "
                              f"≠ 流水之和 {refunded}(可能有渠道退款失败,需人工介入)",
                })

        # 6) 售后退款的已结算订单必须已冲账(商家净额不能白拿)。
        #    新规则下完成单售后只退餐费(配送费保留),判定口径:
        #    退款 >= 餐费部分(total - 配送费)即视为售后单;兼容旧数据的全额退款。
        #    例外:判骑手责任的单(平台先行赔付),商家无责保留净额,不冲账
        from ..models import AfterSale
        rider_fault_ids = {
            a.order_id
            for a in await db.scalars(
                select(AfterSale).where(
                    AfterSale.fault.in_(["rider", "platform"]),
                    AfterSale.order_id.in_(order_ids),
                )
            )
        }
        for order in completed:
            food_part = order.total_cents - (
                order.delivery_fee_cents + order.tip_cents
                if order.rider_id is not None else 0)
            if (order.refund_cents >= food_part > 0
                    and order.id in m_earnings
                    and order.id not in m_reversals
                    and order.id not in rider_fault_ids):
                problems.append({
                    "check": "reversal_missing",
                    "detail": f"订单 {order.order_no} 售后已退餐费但商家入账未冲账",
                })

        # 7) 全局恒等(完成且未全退的订单,分两条核):
        #    菜品侧:Σ菜品金额 == Σ商家净额 + Σ平台佣金(售后冲账单两侧同时剔除:
        #           钱已退用户,商家/平台谁都不该再挂账)
        #    配送侧:Σ配送费(有骑手的单) == Σ骑手入账 —— 配送费 100% 归骑手的账面铁证
        #           (售后单保留在此侧:配送已履约,骑手入账与配送费依然一一对应)
        active = [o for o in completed if o.refund_cents < o.total_cents]
        active_food = [o for o in active if o.id not in m_reversals]
        food_lhs = sum(order_gross(o) for o in active_food)
        food_rhs = sum(
            m_earnings[o.id].net_cents + m_earnings[o.id].commission_cents
            for o in active_food if o.id in m_earnings
        )
        if food_lhs != food_rhs:
            problems.append({
                "check": "global_identity_mismatch",
                "detail": f"商家侧恒等不平:Σ应收(菜品+打包-满减) {food_lhs} "
                          f"≠ Σ净额+佣金 {food_rhs}"
                          f"(差 {food_lhs - food_rhs} 分,近 {WINDOW_DAYS} 天)",
            })
        fee_lhs = sum(o.delivery_fee_cents + o.tip_cents
                      for o in active if o.rider_id is not None)
        fee_rhs = sum(
            r_earnings[o.id].amount_cents
            for o in active if o.rider_id is not None and o.id in r_earnings
        )
        if fee_lhs != fee_rhs:
            problems.append({
                "check": "global_identity_mismatch",
                "detail": f"配送侧恒等不平:Σ(配送费+小费) {fee_lhs} ≠ Σ骑手入账 {fee_rhs}"
                          f"(差 {fee_lhs - fee_rhs} 分,近 {WINDOW_DAYS} 天)",
            })

        # 8) 团购券:每张已核销券 净额+服务费 == 售价(逐张),全局 Σ 同样恒等
        from ..models import VoucherPurchase, VoucherPurchaseStatus

        redeemed = (
            await db.scalars(
                select(VoucherPurchase).where(
                    VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
                    VoucherPurchase.created_at >= since,
                )
            )
        ).all()
        for p in redeemed:
            if p.net_cents + p.commission_cents != p.sell_price_cents:
                problems.append({
                    "check": "voucher_split_mismatch",
                    "detail": f"团购券 {p.purchase_no} 分账不平:"
                              f"净额 {p.net_cents}+服务费 {p.commission_cents}"
                              f" ≠ 售价 {p.sell_price_cents}",
                })

        for p in problems:
            db.add(AuditAlert(check_name=p["check"], detail=p["detail"][:500]))
            logger.error("账务告警 [%s] %s", p["check"], p["detail"])

        # 运行记录(透明中心公示口径):同一天重跑覆盖,取最新结果
        from zoneinfo import ZoneInfo

        from ..models import AuditRun

        day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        run = await db.scalar(select(AuditRun).where(AuditRun.day == day))
        if run is None:
            run = AuditRun(day=day)
            db.add(run)
        run.checked_orders = len(completed)
        run.problem_count = len(problems)
        await db.commit()

    if not problems:
        logger.info("账务自检通过:近 %s 天账目全部恒等", WINDOW_DAYS)
    return problems


async def backfill_legacy_refund_records() -> int:
    """退款流水/冲账功能上线前的历史退款订单,补录流水和冲账行(幂等)。

    - refund_cents 与流水之和的差额 → 补一条 mock 流水(note 标注历史补录)
    - 全额退款且已结算但没冲账 → 补冲账负数行
    上线切换时执行一次,此后审计的 5/6 号恒等式即可长期保持全绿。
    """
    import uuid as _uuid

    from ..models import Refund, RefundStatus
    from .settlement import reverse_merchant_earning

    fixed = 0
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    async with SessionLocal() as db:
        refunded = (
            await db.scalars(
                select(Order).where(
                    Order.refund_cents > 0, Order.created_at >= since
                )
            )
        ).all()
        for order in refunded:
            flows = await db.scalar(
                select(sa_func.coalesce(sa_func.sum(Refund.amount_cents), 0)).where(
                    Refund.order_id == order.id,
                    Refund.status != RefundStatus.failed,
                )
            )
            gap = order.refund_cents - flows
            if gap > 0:
                db.add(Refund(
                    order_id=order.id,
                    order_no=order.order_no,
                    out_refund_no=f"{order.order_no}-legacy-{_uuid.uuid4().hex[:6]}",
                    amount_cents=gap,
                    reason="历史退款补录(refunds 流水表上线前)",
                    channel="mock",
                    status=RefundStatus.success,
                ))
                fixed += 1
            # 冲账口径与规则 6 完全一致:退款覆盖餐费部分(配送费已履约不退)
            # 即需冲账;判骑手责的先行赔付单除外(商家无责保留净额)。
            # 口径不一致的教训:补录了入账却按旧口径不补冲账,规则 6 永久红灯
            from ..models import AfterSale
            food_part = order.total_cents - (
                order.delivery_fee_cents + order.tip_cents
                if order.rider_id is not None else 0)
            rider_fault = await db.scalar(
                select(AfterSale.id).where(
                    AfterSale.order_id == order.id,
                    AfterSale.fault.in_(["rider", "platform"])))
            if (food_part > 0 and order.refund_cents >= food_part
                    and rider_fault is None
                    and await reverse_merchant_earning(db, order, "历史售后冲账补录")):
                fixed += 1
        await db.commit()
    if fixed:
        logger.info("历史退款补录完成:%s 处", fixed)
    return fixed


async def backfill_missing_earnings() -> int:
    """对缺账的历史完成订单补记账(结算功能上线前的老订单),幂等。"""
    fixed = 0
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    async with SessionLocal() as db:
        completed = (
            await db.scalars(
                select(Order).where(
                    Order.status == OrderStatus.COMPLETED,
                    Order.created_at >= since,
                )
            )
        ).all()
        for order in completed:
            has_m = await db.scalar(
                select(MerchantEarning.id).where(
                    MerchantEarning.order_id == order.id,
                    MerchantEarning.kind == EarningKind.earning,
                )
            )
            has_r = order.rider_id is None or await db.scalar(
                select(RiderEarning.id).where(
                    RiderEarning.order_id == order.id,
                    RiderEarning.kind == EarningKind.earning,
                )
            )
            if not has_m or not has_r:
                await settle_order(db, order)  # 内部幂等,只补缺的
                fixed += 1
        await db.commit()
    if fixed:
        logger.info("补账完成:%s 笔历史订单", fixed)
    return fixed
