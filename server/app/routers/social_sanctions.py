"""我的处罚与申诉 `/social/v1`(DEV-PROMPTS-40 #368,S6)。

- `GET /social/v1/me/sanctions`:对我这个人的处罚 + 对我当群主 / 频道主的会话的处罚,生效中的和历史分开;
- `POST /social/v1/sanctions/{id}/appeal`:一次处罚申诉一次,理由 5–500 字,由另一名审核员处理。

封号期间这两个接口照样能用(申诉在 services/sanctions.ACCOUNT_BAN_ALLOWED 里)。
处罚、申诉结果都会进「互动消息 → 系统通知」。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import SocialSanction, User
from ..services import sanctions
from .social import social_user

router = APIRouter(prefix="/social/v1", tags=["社交"])


@router.get("/me/sanctions")
async def my_sanctions(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    return await sanctions.mine(db, me.id)


class AppealIn(BaseModel):
    text: str = Field(max_length=sanctions.APPEAL_MAX)


@router.post("/sanctions/{sanction_id}/appeal")
async def appeal(sanction_id: int, body: AppealIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    s = await db.scalar(select(SocialSanction).where(SocialSanction.id == sanction_id)
                        .with_for_update().execution_options(populate_existing=True))
    if s is None:
        raise HTTPException(404, "没有这条处罚")
    await sanctions.appeal(db, me, s, body.text)
    await db.commit()
    return {"id": s.id, "appeal": sanctions.party_out(s)["appeal"]}
