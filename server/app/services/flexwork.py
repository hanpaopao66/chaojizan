"""灵活用工代发桩:骑手劳务报酬通过灵工平台代发并完税。

现状:未接入服务商,T+1 批量打款仍走人工线下,骑手端展示
「收入需依法申报个税」提示;拿到灵工平台资质后:
  1. .env 配 FLEXWORK_APP_ID / FLEXWORK_SECRET
  2. 在 submit_payout_batch 里接服务商 API(批量代发,回调驱动
     withdrawals.channel='flexwork' + channel_ref=批次号 + 状态)
  3. 完税凭证在服务商后台,taxes 导出报表(routers/tax.py)与之对账
"""
import logging

from ..config import settings

logger = logging.getLogger("superz.flexwork")


async def submit_payout_batch(items: list[dict]) -> str | None:
    """提交代发批次。items: [{user_id, name, phone, amount_cents}, ...]

    返回批次号;未配置返回 None(调用方继续人工流程)。
    """
    if not settings.flexwork_configured:
        return None
    # TODO(接入): 调服务商批量代发 API,返回批次号并把
    # withdrawals.channel/channel_ref 落库;失败走 failed 状态闭环(#22)
    logger.warning("灵工平台已配置但接口未接入,本批次仍走人工打款")
    return None
