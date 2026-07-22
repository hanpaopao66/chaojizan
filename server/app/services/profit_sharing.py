"""微信服务商分账(二清收口)——本地台账与桩。

口径(平台立场):货款不经平台账户。订单完成 → 佣金留平台、
净额(菜品口径 + 自配送费)分给商家的特约商户号;配送费+小费
走灵工平台代发(见 flexwork)。资质未到位时:
- settle_mode 一律 platform(现状,平台代收代付过渡口径);
- 商家 sub_mchid+ps_ready 就绪且 wxpay 配置后,新订单才进分账口径。

台账 profit_sharing_records 一单一条(unique 幂等),清扫任务重试,
超过 MAX_ATTEMPTS 置 failed 人工介入;全额退款走分账回退(returned)。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Merchant, Order, ProfitSharingRecord
from .wechat_pay import get_client

logger = logging.getLogger("superz.profit_sharing")

MAX_ATTEMPTS = 5


def settle_mode_for(merchant: Merchant) -> str:
    """支付时快照:三条件齐(支付配置/特约商户号/接收方就绪)才走分账。"""
    if (settings.wxpay_configured and merchant.sub_mchid
            and merchant.ps_ready):
        return "profit_sharing"
    return "platform"


async def _call_channel(record: ProfitSharingRecord, action: str) -> bool:
    """调渠道(桩):未配置返回 False(记录停在 pending,资质到位后重试)。

    TODO(联调):client.profitsharing_order / return_order,
    传 transaction_id 与 receivers=[{type: MERCHANT_ID, account: sub_mchid,
    amount: net_cents, description: 货款分账}]。
    """
    client = get_client()
    if client is None:
        record.note = "渠道未配置,桩模式待重试"
        return False
    logger.info("分账%s待实现(需服务商资质): %s %s 分",
                action, record.order_no, record.net_cents)
    record.note = "渠道已受理(联调桩)"
    return True


async def ensure_record(db: AsyncSession, order: Order) -> None:
    """订单完成时调用:settle_mode=profit_sharing 的单落台账并尝试分账。

    幂等(order_id 唯一);失败/未配置留 pending 给清扫任务。
    不单独 commit,随调用方事务提交;渠道调用失败绝不影响订单完成。
    """
    if order.settle_mode != "profit_sharing":
        return
    existing = await db.scalar(select(ProfitSharingRecord.id).where(
        ProfitSharingRecord.order_id == order.id))
    if existing:
        return
    merchant = await db.get(Merchant, order.merchant_id)
    if merchant is None or not merchant.sub_mchid:
        return
    gross = order.food_cents + order.packing_fee_cents - order.discount_cents
    if order.self_delivery:
        gross += order.delivery_fee_cents  # 自配送费归商家,一并分账
    record = ProfitSharingRecord(
        order_id=order.id, order_no=order.order_no,
        merchant_id=merchant.id, sub_mchid=merchant.sub_mchid,
        net_cents=max(gross - order.commission_cents, 0),
        commission_cents=order.commission_cents,
    )
    db.add(record)
    record.attempts = 1
    if await _call_channel(record, "请求"):
        record.status = "success"


async def request_return(db: AsyncSession, order: Order) -> None:
    """全额退款的已分账单:发起分账回退(桩)。随调用方事务提交。"""
    record = await db.scalar(select(ProfitSharingRecord).where(
        ProfitSharingRecord.order_id == order.id))
    if record is None or record.status == "returned":
        return
    await _call_channel(record, "回退")
    record.status = "returned"
    record.note = (record.note + ";全额退款,分账回退")[:200]


async def sweep_pending(db: AsyncSession) -> int:
    """清扫兜底:重试 pending 的分账,超上限置 failed 供人工介入。"""
    rows = (await db.scalars(
        select(ProfitSharingRecord)
        .where(ProfitSharingRecord.status == "pending")
        .with_for_update(skip_locked=True).limit(50))).all()
    done = 0
    for record in rows:
        record.attempts += 1
        if await _call_channel(record, "重试"):
            record.status = "success"
            done += 1
        elif record.attempts >= MAX_ATTEMPTS:
            record.status = "failed"
            record.note = (record.note + ";超过重试上限,请人工处理")[:200]
    return done
