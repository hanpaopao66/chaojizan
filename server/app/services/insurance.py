"""骑手意外险(桩):每日首次上线自动投当日单。

未配置 insurance_* = 登记模式:只落 rider_insurance_days 记录
(status=registered),保障金池兜底先行赔付——每单计提的骑手保障金
(见 services/ledger.py)就是这笔钱的来源。
配置后调保险服务商 API 投保(status=insured,落保单号与保费)。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import RiderInsuranceDay

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
        # 调 API 投保 → record.policy_no / premium_cents / status="insured"
        record.status = "registered"
        logger.warning("保险 API 已配置但接入待实现,先落登记记录")
    db.add(record)
