"""通话接口 `/chat/v1/calls`(DEV-PROMPTS-40 §5.12,#354)。信令本身在 `/ws/v2`(services/calls.py)。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Call, User
from ..services import calls as call_service
from ..services.social import user_cards
from .chat import chat_on
from .social import social_user

router = APIRouter(prefix="/chat/v1/calls", tags=["聊天"], dependencies=[Depends(chat_on)])


@router.get("/ice-servers")
async def ice_servers(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """WebRTC 用的 STUN / TURN。TURN 的用户名密码是临时的(1 小时),每次打电话前取一次。"""
    from ..services.flags import social_flag_on
    if not await social_flag_on(db, "calls_enabled"):
        raise HTTPException(503, "通话功能暂未开放")
    return call_service.ice_servers(me.id)


@router.get("")
async def history(before_id: int | None = None, limit: int = Query(50, ge=1, le=100),
                  me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """通话记录(我打的、打给我的),新的在前。"""
    q = select(Call).where(or_(Call.caller_id == me.id, Call.callee_id == me.id))
    if before_id:
        q = q.where(Call.id < before_id)
    rows = list(await db.scalars(q.order_by(Call.id.desc()).limit(limit)))
    peers = {r.callee_id if r.caller_id == me.id else r.caller_id for r in rows}
    cards = await user_cards(db, me.id, peers)
    items = []
    for r in rows:
        outgoing = r.caller_id == me.id
        peer = r.callee_id if outgoing else r.caller_id
        dur = int((r.ended_at - r.answered_at).total_seconds()) \
            if r.answered_at and r.ended_at else 0
        items.append({"id": r.id, "call_id": r.call_id, "outgoing": outgoing, "video": r.video,
                      "state": r.state, "reason": r.reason, "duration": dur,
                      "chat_id": r.chat_id, "peer": cards.get(peer),
                      "started_at": r.started_at.isoformat() if r.started_at else None})
    return {"items": items, "has_more": len(rows) == limit}
