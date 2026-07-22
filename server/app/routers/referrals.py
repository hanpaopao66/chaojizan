"""邀请有礼:邀请码 → 新用户 24 小时内填码 → 完成首单双方发券。

奖励挂"完成单"不挂注册,刷号无利可图;防刷三道:同设备不建立关系、
邀请人每自然月上限、风控命中的完成单不触发(留待下一笔干净的单)。
券为平台承担(subsidy 口径,#49 通道),source 唯一防重发。
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import Referral, User
from ..security import require_role

router = APIRouter(prefix="/referrals", tags=["邀请有礼"])

CLAIM_WINDOW_HOURS = 24


async def ensure_ref_code(db: AsyncSession, user: User) -> str:
    """懒生成 6 位邀请码(唯一,重试防碰撞)。"""
    if user.ref_code:
        return user.ref_code
    for _ in range(10):
        code = f"{secrets.randbelow(10**6):06d}"
        exists = await db.scalar(select(User.id).where(User.ref_code == code))
        if not exists:
            user.ref_code = code
            await db.commit()
            return code
    raise HTTPException(500, "邀请码生成失败,请重试")


@router.get("/me")
async def my_referral(
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """我的邀请码与战绩;新用户(24 小时内)另返回可填码标记。"""
    code = await ensure_ref_code(db, user)
    invited = await db.scalar(select(func.count(Referral.id)).where(
        Referral.inviter_id == user.id))
    rewarded = await db.scalar(select(func.count(Referral.id)).where(
        Referral.inviter_id == user.id, Referral.status == "rewarded"))
    claimed = await db.scalar(select(Referral.id).where(
        Referral.invitee_id == user.id))
    created = user.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    in_window = (datetime.now(timezone.utc) - created
                 <= timedelta(hours=CLAIM_WINDOW_HOURS))
    from ..services.flags import marketing_on
    return {
        "enabled": await marketing_on(db),
        "code": code,
        "reward_cents": settings.referral_reward_cents,
        "invited": invited,
        "rewarded": rewarded,
        "can_claim": bool(in_window and not claimed),
    }


@router.post("/claim")
async def claim_referral(
    payload: dict,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """新用户填邀请码(注册后 24 小时内,过期不候)。"""
    from ..services.flags import marketing_on
    if settings.referral_reward_cents <= 0 or not await marketing_on(db):
        raise HTTPException(409, "邀请活动暂未开启")
    code = str(payload.get("code", "")).strip()
    inviter = await db.scalar(select(User).where(User.ref_code == code))
    if inviter is None or len(code) != 6:
        raise HTTPException(404, "邀请码不存在")
    if inviter.id == user.id:
        raise HTTPException(422, "不能填自己的邀请码")
    created = user.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created > timedelta(
            hours=CLAIM_WINDOW_HOURS):
        raise HTTPException(409, "注册超过 24 小时,填码通道已关闭")
    existing = await db.scalar(select(Referral.id).where(
        Referral.invitee_id == user.id))
    if existing:
        raise HTTPException(409, "你已经填过邀请码了")
    # 防刷一:同设备不建立关系
    if user.device_id and inviter.device_id == user.device_id:
        raise HTTPException(422, "同一台设备上的账号不能互相邀请")
    # 防刷二:邀请人月上限(按填码时间算)
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    month_count = await db.scalar(select(func.count(Referral.id)).where(
        Referral.inviter_id == inviter.id,
        Referral.created_at >= month_start))
    if month_count >= settings.referral_monthly_cap:
        raise HTTPException(
            409, f"这位邀请人本月邀请已达 {settings.referral_monthly_cap} 人上限")
    db.add(Referral(inviter_id=inviter.id, invitee_id=user.id))
    await db.commit()
    return {"ok": True,
            "hint": f"完成首单后你和好友各得 "
                    f"{settings.referral_reward_cents / 100:g} 元券"}


async def reward_referral_if_first_order(db: AsyncSession, order) -> None:
    """完成单钩子(settle_order 内调用):被邀请人的首个完成单触发双发券。

    风控命中(multi_account_device 等)的单不触发,关系保留待下一笔干净单。
    不单独 commit,随调用方事务提交;失败不影响结算。
    """
    from ..services.flags import marketing_on
    if settings.referral_reward_cents <= 0 or not await marketing_on(db):
        return
    referral = await db.scalar(
        select(Referral).where(Referral.invitee_id == order.customer_id,
                               Referral.status == "pending")
        .with_for_update(skip_locked=True))
    if referral is None:
        return
    if order.risk_flags and order.risk_flags.get("hits"):
        return  # 防刷三:风控命中的单不算数
    from datetime import datetime as _dt

    from ..models import Coupon
    from ..services.push import push_to_user
    amount = settings.referral_reward_cents
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    for uid, tag in ((referral.invitee_id, "invitee"),
                     (referral.inviter_id, "inviter")):
        exists = await db.scalar(select(Coupon.id).where(
            Coupon.source == f"referral:{referral.id}:{tag}"))
        if not exists:
            db.add(Coupon(user_id=uid, amount_cents=amount,
                          min_spend_cents=0, expires_at=expires,
                          source=f"referral:{referral.id}:{tag}",
                          note="邀请有礼"))
    referral.status = "rewarded"
    referral.rewarded_at = _dt.now(timezone.utc)
    try:
        await push_to_user(referral.inviter_id, "邀请有礼到账",
                           f"你邀请的好友完成了首单,{amount / 100:g} 元券"
                           "已放进你的券包(7 天内有效)",
                           {"type": "coupon"}, record_skip=True)
    except Exception:
        pass
