"""互动消息 `/social/v1/notifications`(DEV-PROMPTS-40 #367):回复我的 / @我的 / 收到的赞 / 系统通知。

「消息」列表第三行「互动消息」读这里;角标靠用户事件 `notify` 实时更新(见 services/social_notify.py),
不用轮询。这组接口不挂视频开关:视频关了,已经收到的审核结果、处罚通知也得能看。
"""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import User
from ..services import social_notify as sn
from .social import social_user

router = APIRouter(prefix="/social/v1/notifications", tags=["互动消息"])

Kind = Literal["reply", "at", "like", "system"]


@router.get("")
async def list_notifications(kind: Kind = "reply", cursor: str | None = None,
                             me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """某一类的互动消息,新的在前(赞按对象合并,新的赞会把那一行顶上来)。"""
    return await sn.list_items(db, me.id, kind, cursor)


@router.get("/unread")
async def unread(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    return await sn.unread_counts(db, me.id)


class ReadIn(BaseModel):
    #: 只标这一类;不传 = 全部
    kind: Kind | None = None
    #: 只标这几条
    ids: list[int] | None = Field(default=None, max_length=200)


@router.post("/read")
async def mark_read(body: ReadIn | None = None, me: User = Depends(social_user),
                    db: AsyncSession = Depends(get_db)):
    """标记已读。返回新的未读数;同时推一个 `notify` 用户事件,我的其他设备的角标跟着变。"""
    body = body or ReadIn()
    out = await sn.mark_read(db, me.id, kind=body.kind, ids=body.ids)
    await db.commit()
    return {"unread": out}
