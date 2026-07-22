"""收款账户:骑手/商家提现的打款目标。

账号密文落库(services/crypto.py),普通接口永远只回尾 4 位;
完整账号只在管理端打款界面解密展示。
提现申请时快照冻结——改账户不影响在途申请;
账户刚变更(24 小时内)发起的提现,管理后台标黄提示人工电话核实(只提示不拦截)。
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import PayoutAccount, User
from ..schemas import PayoutAccountIn, PayoutAccountOut
from ..security import require_role
from ..services.crypto import encrypt

router = APIRouter(prefix="/payout-account", tags=["收款账户"])

RECENT_WINDOW = timedelta(hours=24)


def account_out(account: PayoutAccount | None) -> PayoutAccountOut:
    if account is None:
        return PayoutAccountOut(configured=False)
    return PayoutAccountOut(
        configured=True,
        kind=account.kind,
        holder_name=account.holder_name,
        bank_name=account.bank_name,
        account_tail=account.account_tail,
        updated_at=account.updated_at,
        recently_changed=account_recently_changed(account),
    )


def account_recently_changed(account: PayoutAccount) -> bool:
    updated = account.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated < RECENT_WINDOW


@router.get("", response_model=PayoutAccountOut)
async def my_payout_account(
    user: User = Depends(require_role("rider", "merchant")),
    db: AsyncSession = Depends(get_db),
):
    account = await db.scalar(
        select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    return account_out(account)


@router.put("", response_model=PayoutAccountOut)
async def save_payout_account(
    payload: PayoutAccountIn,
    user: User = Depends(require_role("rider", "merchant")),
    db: AsyncSession = Depends(get_db),
):
    """登记/更换收款账户(一人一户,更换即覆盖)。

    换账户后 24 小时内的提现会被人工加核——防止账号被盗后改卡跑款。
    """
    account = await db.scalar(
        select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    account_no = payload.account_no.strip()
    if account is None:
        account = PayoutAccount(user_id=user.id, role=user.role.value)
        db.add(account)
    account.kind = payload.kind
    account.holder_name = payload.holder_name.strip()
    account.account_no_encrypted = encrypt(account_no)
    account.account_tail = account_no[-4:]
    account.bank_name = payload.bank_name.strip()
    account.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(account)
    return account_out(account)
