"""开发者注册闸门(#329,D5)。

开关走 PlatformFlag `developer_signup`:invite(默认,邀请制)/ open / closed。
邀请名单存手机号的假名,不存明文。/auth/register 和 /auth/sms-login 在**新建** developer
账号时都过这里;已有账号登录不受影响(关掉注册不等于把已有开发者踢出去)。
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Developer, DeveloperInvite, PlatformFlag, User
from .crypto import pseudonym
from .miniapp_platform import now

FLAG = "developer_signup"
MODES = {"invite": "邀请制", "open": "开放注册", "closed": "暂停注册"}


def invite_key(phone: str) -> str:
    return pseudonym(phone, "developer-invite")


async def signup_mode(db: AsyncSession) -> str:
    flag = await db.get(PlatformFlag, FLAG)
    return flag.value if flag is not None and flag.value in MODES else "invite"


async def gate(db: AsyncSession, phone: str) -> DeveloperInvite | None:
    mode = await signup_mode(db)
    if mode == "closed":
        raise HTTPException(403, "开发者注册暂时关闭")
    if mode == "invite":
        inv = await db.scalar(select(DeveloperInvite).where(
            DeveloperInvite.phone_pseudonym == invite_key(phone)))
        if inv is None:
            raise HTTPException(403, "开发者注册目前是邀请制,这个手机号还没有收到邀请")
        return inv
    return None


def on_created(db: AsyncSession, user: User, invite: DeveloperInvite | None) -> None:
    """和 users 行同一个事务里建 developers 行(调用方 commit)。"""
    db.add(Developer(user_id=user.id, kind="individual",
                     display_name=f"开发者{user.phone[-4:]}", status="unverified"))
    if invite is not None and invite.used_at is None:
        invite.used_at = now()
