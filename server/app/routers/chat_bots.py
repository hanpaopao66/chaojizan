"""客户端用的两个机器人接口(DEV-PROMPTS-40 #355,docs/BOT-API.md「给客户端的接口」)。

前缀和聊天一样是 `/chat/v1`,单独一个文件是为了让机器人这块自成一处:
- `POST /chat/v1/chats/{chat_id}/messages/{seq}/callback`:点内联键盘的回调按钮,最多等机器人 10 秒回话;
- `GET /chat/v1/chats/{chat_id}/bot-info`:会话里的机器人(命令、菜单按钮、简介)。

开关 bots_enabled 关着时两个都回 503「机器人功能暂未开放」;和 /chat/v1 其余路由一样也挂着「消息」急停闸
chat_enabled(关着时 503「消息功能暂停中」)。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Chat, User
from ..ratelimit import check_rate_limit_seconds
from ..services import bots
from ..services.chat_view import is_active, member_of
from ..services.flags import bots_on
from .chat import chat_on
from .social import social_user

router = APIRouter(prefix="/chat/v1", tags=["聊天 · 机器人"], dependencies=[Depends(chat_on)])

#: 点回调按钮:每人每秒最多 3 次(§5.7)
CALLBACKS_PER_SECOND = 3


async def _member_chat(db: AsyncSession, chat_id: int, me: User):
    if not await bots_on(db):
        raise HTTPException(503, bots.BOTS_OFF)
    chat = await db.get(Chat, chat_id)
    if chat is None or chat.deleted_at is not None:
        raise HTTPException(404, "会话不存在")
    m = await member_of(db, chat.id, me.id)
    if not is_active(m):
        raise HTTPException(403, "你不在这个会话里")
    return chat, m


class CallbackIn(BaseModel):
    data: str = Field(min_length=1, max_length=64)


@router.post("/chats/{chat_id}/messages/{seq}/callback")
async def press_callback(chat_id: int, seq: int, body: CallbackIn,
                         me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """点机器人消息上的回调按钮:给机器人一条 callback_query,**最多等 10 秒**它的 answerCallbackQuery。

    响应 `{"answered":true,"text":"…","show_alert":false,"url":null}`;10 秒没等到 `{"answered":false}`。
    等的时候不占数据库连接(Redis BLPOP)。
    """
    chat, m = await _member_chat(db, chat_id, me)
    await check_rate_limit_seconds("bot_callback", str(me.id), CALLBACKS_PER_SECOND,
                                   message="点得太快了,歇一下再点")
    qid, bot_id = await bots.create_callback_query(db, chat, me, m, seq, body.data)
    # 先记下「这个查询是谁的」再提交:机器人一拿到更新就回话,也对得上
    await bots.remember_query(qid, bot_id, me.id)
    await db.commit()
    await db.close()
    ans = await bots.wait_answer(qid, bots.CALLBACK_WAIT_SECONDS)
    if ans is None:
        return {"answered": False}
    return {"answered": True, "text": ans.get("text") or "", "show_alert": bool(ans.get("show_alert")),
            "url": ans.get("url") or None}


@router.get("/chats/{chat_id}/bot-info")
async def bot_info(chat_id: int, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    """会话里的机器人:私聊里是对面那一个,群 / 频道里是所有机器人成员,没有就是空列表。"""
    chat, _ = await _member_chat(db, chat_id, me)
    return {"bots": await bots.bot_infos(db, chat)}
