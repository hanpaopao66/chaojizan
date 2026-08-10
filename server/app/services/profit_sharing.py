"""微信服务商分账(二清收口)——本地台账与桩。

口径(平台立场):货款不经平台账户。订单完成 → 佣金留平台、
净额(菜品口径 + 自配送费)分给商家的特约商户号;配送费+小费
走灵工平台代发(见 flexwork)。资质未到位时:
- settle_mode 一律 platform(现状,平台代收代付过渡口径);
- 商家 sub_mchid+ps_ready 就绪且 wxpay 配置后,新订单才进分账口径。

台账 profit_sharing_records 一单一条(unique 幂等),清扫任务重试,
超过 MAX_ATTEMPTS 置 failed 人工介入;全额退款走分账回退(returned)。

**渠道本身一行都还没写**(走普通服务商 /v3/profitsharing 还是电商收付通
/v3/ecommerce/profitsharing,取决于类目答案,两套 API 不通用)。
在那之前这里绝不产生 success —— 台账写着"已分账"而钱没动,
比没有台账更坏:它让对账在错误的地方停下来。挂起的量由每日账务自检
盯着(见 stuck_summary 与 services/audit.py)。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Merchant, Order, ProfitSharingRecord
from .wechat_pay import get_client

logger = logging.getLogger("superz.profit_sharing")

MAX_ATTEMPTS = 5

# 渠道调用的三态。**为什么不是布尔**:布尔只能表达"这一单成没成",
# 而"渠道整套还没接通"是全局状态。两者混在一个 False 里,未实现的渠道
# 会把每条台账都刷到重试上限烧成 failed(理由见 sweep_pending)。
CHANNEL_OK = "ok"                        # 渠道受理,资金已按台账流动
CHANNEL_UNIMPLEMENTED = "unimplemented"  # 渠道未配置/未实现:全局性,不计次
CHANNEL_ERROR = "error"                  # 单笔被拒/网络故障:计次,可烧 failed

# 分账挂起多久算"卡住了"。清扫任务分钟级跑一轮,6 小时还没走通
# 就不是抖动而是真出事了;调小会让刚落台账、还没轮到清扫的单误报。
STUCK_HOURS = 6


def settle_mode_for(merchant: Merchant) -> str:
    """支付时快照:三条件齐(支付配置/特约商户号/接收方就绪)才走分账。"""
    if (settings.wxpay_configured and merchant.sub_mchid
            and merchant.ps_ready):
        return "profit_sharing"
    return "platform"


async def _call_channel(record: ProfitSharingRecord, action: str) -> str:
    """调渠道:**现在恒返回 CHANNEL_UNIMPLEMENTED**,真实分账尚未接入。

    这里以前的行为是"商户参数配齐了就返回 True",于是台账会出现
    「分账成功」而实际一分钱没动 —— 哪天管理端把某商家 ps_ready 打开,
    系统就开始自信地记假账,而假账的害处不是少一条记录,是**对账会在
    错误的地方停下来**:所有下游(商家钱包、审计恒等、微信账单核对)
    都以为这笔已经了结。真钱的东西宁可显性挂着,也不要一个漂亮的假终态。

    TODO(联调,等类目答案):普通服务商 client.profitsharing_order /
    return_order,电商收付通 /v3/ecommerce/profitsharing/orders ——
    两套入参不同但都要 transaction_id(见 Order.wx_transaction_id)与
    receivers=[{type: MERCHANT_ID, account: sub_mchid, amount: net_cents}]。
    """
    client = get_client()
    if client is None:
        # 未配置是预期状态(开发期/资质到位前),info 就够,别刷屏
        logger.info("分账%s跳过,渠道未配置: %s", action, record.order_no)
        record.note = "渠道未配置,等服务商参数就位"[:200]
        return CHANNEL_UNIMPLEMENTED
    # 配置齐了却调不出去才是该吵的情况:说明有人已经以为分账能用了,
    # 商家那边也可能正等着货款到账。error 级别,让日志告警抓得到
    logger.error("分账%s未发起:渠道未接入(等服务商类目确认) %s 净额 %s 分 → %s",
                 action, record.order_no, record.net_cents, record.sub_mchid)
    record.note = "分账渠道未接入,本笔未发起,挂起等待"[:200]
    return CHANNEL_UNIMPLEMENTED


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
    # attempts 是"真打到渠道几次",不是"被扫过几次"(见 sweep_pending)
    result = await _call_channel(record, "请求")
    if result != CHANNEL_UNIMPLEMENTED:
        record.attempts = 1
    if result == CHANNEL_OK:
        record.status = "success"


async def request_return(db: AsyncSession, order: Order) -> None:
    """全额退款的分账单:分出去过的发起回退,没分出去的直接了结。

    分这两种情况,是因为它们的**资金事实**不同:
    - pending/failed:钱从没离开过,没有可回退的东西,写 returned 是如实记账;
    - success:钱已经在商家账户,回退调不通就**绝不能**改状态 ——
      改了等于账面上宣称钱回来了,而商家那边余额照样是多的。

    随调用方事务提交。
    """
    record = await db.scalar(select(ProfitSharingRecord).where(
        ProfitSharingRecord.order_id == order.id))
    if record is None or record.status == "returned":
        return
    if record.status != "success":
        record.status = "returned"
        record.note = (record.note + ";全额退款,该笔从未实际分账,无需回退")[:200]
        return
    if await _call_channel(record, "回退") == CHANNEL_OK:
        record.status = "returned"
        record.note = (record.note + ";全额退款,分账已回退")[:200]
        return
    # 保持 success:钱确实还在商家账户。这条落在挂起自检的视野之外
    # (它查的是 pending),所以必须在这里自己吵一声
    logger.error("分账回退未完成 %s:货款仍在商家 %s 账上,退款已出账,需人工冲平",
                 record.order_no, record.sub_mchid)
    record.note = (record.note + ";全额退款但分账回退未完成,需人工")[:200]


async def sweep_pending(db: AsyncSession) -> int:
    """清扫兜底:重试 pending 的分账,超上限置 failed 供人工介入。

    **attempts 只在渠道真的被调用过时才递增**,渠道未实现的一律不计次。
    两件事必须分开,理由是 failed 不可自愈:未实现的渠道若照常计次,
    5 轮清扫内就会把全部台账烧成 failed,而清扫只捞 pending ——
    等分账真接上那天,这批单子一条都不会被自动重试,只能人工逐条捞。
    挂着难看,但挂着能自愈;failed 是终态,烧掉就得手工。

    挂了多少、挂了多久由每日账务自检报出来(见 stuck_summary),
    所以"留在 pending"不等于"没人知道"。
    """
    rows = (await db.scalars(
        select(ProfitSharingRecord)
        .where(ProfitSharingRecord.status == "pending")
        .with_for_update(skip_locked=True).limit(50))).all()
    done = 0
    for record in rows:
        result = await _call_channel(record, "重试")
        if result == CHANNEL_UNIMPLEMENTED:
            continue  # 不计次、不改状态,原地等渠道接上
        record.attempts += 1
        if result == CHANNEL_OK:
            record.status = "success"
            done += 1
        elif record.attempts >= MAX_ATTEMPTS:
            record.status = "failed"
            record.note = (record.note + ";超过重试上限,请人工处理")[:200]
    return done


async def stuck_summary(db: AsyncSession) -> dict:
    """挂起分账概览,给每日账务自检用。

    分账是"货款直达商家、平台靠分账拿佣金"的那一步。它挂着的时候,
    台账上白纸黑字写着这笔钱该怎么分,而实际上一分都没动 ——
    以前这里完全看不见(桩直接置 success),这个函数就是把它照出来。

    pending 只统计超过 STUCK_HOURS 的:刚落台账、清扫还没轮到的不算卡住,
    否则每天核账都会抓到几笔"刚出生"的单,红灯久了就没人看了。
    failed 一笔都要报 —— 它是终态,不会自己好。
    """
    now = datetime.now(timezone.utc)
    oldest = await db.scalar(
        select(ProfitSharingRecord)
        .where(ProfitSharingRecord.status == "pending",
               ProfitSharingRecord.created_at
               < now - timedelta(hours=STUCK_HOURS))
        .order_by(ProfitSharingRecord.created_at).limit(1))
    stuck_n, stuck_cents = 0, 0
    oldest_hours, oldest_order_no = 0, ""
    if oldest is not None:
        stuck_n, stuck_cents = (await db.execute(
            select(sa_func.count(ProfitSharingRecord.id),
                   sa_func.coalesce(
                       sa_func.sum(ProfitSharingRecord.net_cents), 0))
            .where(ProfitSharingRecord.status == "pending",
                   ProfitSharingRecord.created_at
                   < now - timedelta(hours=STUCK_HOURS)))).one()
        oldest_order_no = oldest.order_no
        created = oldest.created_at
        if created.tzinfo is None:  # 与仓库其它处一致:naive 一律当 UTC
            created = created.replace(tzinfo=timezone.utc)
        oldest_hours = int((now - created).total_seconds() // 3600)
    failed_n, failed_cents = (await db.execute(
        select(sa_func.count(ProfitSharingRecord.id),
               sa_func.coalesce(
                   sa_func.sum(ProfitSharingRecord.net_cents), 0))
        .where(ProfitSharingRecord.status == "failed"))).one()
    return {
        "stuck": stuck_n, "stuck_cents": stuck_cents,
        "oldest_hours": oldest_hours, "oldest_order_no": oldest_order_no,
        "failed": failed_n, "failed_cents": failed_cents,
    }
