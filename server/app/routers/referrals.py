"""邀请有礼 —— **2026-09-14 停了**:奖励停发、三端入口下线。

拍板「平台没有钱,不做平台出钱的安抚和营销」时一起停的。原来的形态:邀请码 → 新用户
24 小时内填码 → 完成首单双方发券(券由首单那家店的「新客推荐券」批次出,#115)。

停了之后:

- **已经到账的不动** —— 发出去的券照旧能用,邀请关系、战绩都留着;
- **还没完成首单的邀请不再发奖励** —— 结算里那个钩子删了(services/settlement),
  pending 的邀请关系原样留着、不会变成 rewarded;
- 填邀请码的接口回 410,说清楚停了;「我的邀请」只剩战绩和一句照实的说明,
  客户端据此下线入口(老版本 App 点进来看到的也是这句话);
- 原来的两个配置(奖励开关、月上限)一起删了,不留一个能拨回来的开关。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Referral, User
from ..security import require_role

router = APIRouter(prefix="/referrals", tags=["邀请有礼"])

#: 停了之后给人看的那一句(我的邀请、填码被拒、规则页都用它)
STOPPED_NOTE = ("邀请有礼已经停了(2026-09-14):已经到账的券照旧能用;"
                "还没完成首单的邀请不再发奖励")


@router.get("/me")
async def my_referral(
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """我的邀请战绩。活动停了:不再给邀请码、不再能填码,只报历史和一句说明。"""
    invited = await db.scalar(select(func.count(Referral.id)).where(
        Referral.inviter_id == user.id))
    rewarded = await db.scalar(select(func.count(Referral.id)).where(
        Referral.inviter_id == user.id, Referral.status == "rewarded"))
    return {
        "enabled": False,
        "stopped": True,
        "note": STOPPED_NOTE,
        # 老版本 App 读 code 显示邀请码:给空串,它显示不出一个还能用的码
        "code": "",
        "invited": invited or 0,
        "rewarded": rewarded or 0,
        "can_claim": False,
    }


@router.post("/claim")
async def claim_referral(
    payload: dict,
    user: User = Depends(require_role("customer")),
):
    """填邀请码 —— 活动停了,一律 410,说清楚为什么。"""
    raise HTTPException(410, STOPPED_NOTE)
