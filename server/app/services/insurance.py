"""骑手意外险(桩):每日首次上线自动投当日单。

未配置 insurance_* = 登记模式:只落 rider_insurance_days 记录
(status=registered),保障金池兜底先行赔付——每单计提的骑手保障金
(见 services/ledger.py)就是这笔钱的来源。
配置后调保险服务商 API 投保(status=insured,落保单号)。

## 保费骑手出,每天第一单扣一次(2026-10-08 运营方定)

每天第一单送到入账时(services/settlement.settle_order),从这一单的收入里扣
`rider_insurance_fee_cents`(默认 2.5 元)。同一个北京日只扣一次:扣过的那天,
当天记录的 premium_cents 写上扣了多少,之后的单看到它就不再扣。
一单都没送到的那天不扣 —— 没有收入可扣,也就不在这里收钱。

记账:rider_earnings 上追加一行 `insurance_fee`(负数),挂在当天第一单上。
**不是罚款**,账本里单独记成保险费:公开账本放在 rider_insurance_rows(不进
rider_rows,那一栏「只进不冲」),骑手的流水里写「今日保险费」。

钱去哪:接入保险服务商后交保费;接入之前(登记模式,status=registered)
这笔钱**进骑手保障金池**,出事故由池子先行赔付 —— 平台不留
(services/rider_fault.fund_balance 把它算进池子余额)。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import EarningKind, Order, RiderEarning, RiderInsuranceDay

logger = logging.getLogger("superz.insurance")


def _today_bj() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


async def ensure_today(db: AsyncSession, rider_id: int) -> None:
    """确保今天有投保/登记记录(幂等)。失败只记日志,绝不阻塞上线。"""
    day = _today_bj()
    existing = await db.scalar(
        select(RiderInsuranceDay.id).where(
            RiderInsuranceDay.rider_id == rider_id,
            RiderInsuranceDay.day == day))
    if existing:
        return
    record = RiderInsuranceDay(rider_id=rider_id, day=day)
    if settings.insurance_configured:
        # TODO 接入保险服务商(众安/泰康在线按天骑手意外险):
        # 调 API 投保 → record.policy_no / status="insured"。
        # 保费是骑手出的那笔(charge_daily_fee 扣、写进 premium_cents),这里不另记
        record.status = "registered"
        logger.warning("保险 API 已配置但接入待实现,先落登记记录")
    db.add(record)


def fee_cents() -> int:
    return max(0, settings.rider_insurance_fee_cents)


async def charge_daily_fee(db: AsyncSession, order: Order) -> int:
    """当天第一单送到:从这一单的收入里扣当日保险费。**只改库不提交**。

    同一个北京日只扣一次。并发两单同时完成也只扣一次:当天记录先
    INSERT … ON CONFLICT DO NOTHING 保证存在(上线时没落上的,比如跨零点一直在线的,
    这里补上),再 SELECT … FOR UPDATE 锁住它,看 premium_cents 决定扣不扣。
    返回扣了多少(分),没扣是 0。
    """
    fee = fee_cents()
    if fee <= 0 or order.rider_id is None:
        return 0
    day = _today_bj()
    await db.execute(
        pg_insert(RiderInsuranceDay)
        .values(rider_id=order.rider_id, day=day, status="registered",
                policy_no="", premium_cents=0)
        .on_conflict_do_nothing(index_elements=["rider_id", "day"]))
    record = await db.scalar(
        select(RiderInsuranceDay).where(
            RiderInsuranceDay.rider_id == order.rider_id,
            RiderInsuranceDay.day == day)
        .with_for_update().execution_options(populate_existing=True))
    if record is None or record.premium_cents > 0:
        return 0
    record.premium_cents = fee
    db.add(RiderEarning(
        rider_id=order.rider_id, order_id=order.id, order_no=order.order_no,
        amount_cents=-fee, kind=EarningKind.insurance_fee,
        note=f"今日保险费({day}):当天第一单扣,一天只扣一次"))
    return fee
