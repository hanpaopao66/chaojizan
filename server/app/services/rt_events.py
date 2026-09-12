"""事件:落库分配 pts,**提交之后**再分发(DEV-PROMPTS-40 §5.3,#343)。

写法:

    ev = await append_chat_event(db, chat_id, "msg", data)
    await db.commit()          # ← 提交成功后,本事务里攒下的事件自动交给实时网关

事务回滚时攒下的事件一起丢掉 —— 客户端永远不会收到一条库里没有的消息。
分发挂在 SQLAlchemy 的 after_commit 上,调用方不用记得「提交完再发」,
也就不会出现「先发了、提交却失败了」这种最难查的不一致。

pts 的分配靠 `UPDATE … SET pts = pts + 1 RETURNING pts`:行锁保证同一会话并发写
也是连续的(S10)。
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, event, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..models import Chat, ChatEvent, SocialProfile, UserEvent

logger = logging.getLogger("superz.realtime")

#: 事件表保留多久(更旧的断线补齐直接让客户端重拉)
RETENTION = timedelta(days=7)
_PENDING = "rt_pending"


def _queue(db: AsyncSession, frame: dict) -> None:
    db.info.setdefault(_PENDING, []).append(frame)


async def append_chat_event(db: AsyncSession, chat_id: int, type_: str, data: dict) -> dict:
    """会话事件:分配会话内 pts、写 chat_events、登记提交后分发。返回下发的帧。"""
    pts = await db.scalar(update(Chat).where(Chat.id == chat_id)
                          .values(pts=Chat.pts + 1).returning(Chat.pts))
    if pts is None:
        raise ValueError(f"会话 {chat_id} 不存在")
    db.add(ChatEvent(chat_id=chat_id, pts=pts, type=type_, data=data))
    frame = {"t": "ev", "chat_id": chat_id, "pts": pts, "type": type_, "data": data}
    _queue(db, frame)
    return frame


async def append_user_event(db: AsyncSession, user_id: int, type_: str, data: dict) -> dict:
    """用户事件:只和「我」有关的变化(进出会话、置顶、草稿、拉黑……),发给我的所有设备。"""
    from .social import ensure_profile

    await ensure_profile(db, user_id)
    pts = await db.scalar(update(SocialProfile).where(SocialProfile.user_id == user_id)
                          .values(user_pts=SocialProfile.user_pts + 1)
                          .returning(SocialProfile.user_pts))
    db.add(UserEvent(user_id=user_id, pts=pts, type=type_, data=data))
    frame = {"t": "uev", "user_id": user_id, "pts": pts, "type": type_, "data": data}
    _queue(db, frame)
    return frame


async def emit_user_event_now(user_id: int, type_: str, data: dict) -> None:
    """在自己的事务里写一条用户事件并提交(调用方手上没有会话时用)。"""
    from ..db import SessionLocal

    async with SessionLocal() as db:
        await append_user_event(db, user_id, type_, data)
        await db.commit()


_AFTER = "rt_after"


def after_commit(db: AsyncSession, coro_factory) -> None:
    """登记一件「提交成功之后才做」的事(推送、链接预览……)。回滚就不做。

    传的是**返回协程的函数**,不是协程本身 —— 事务回滚时协程根本不会被创建,
    不会留下「coroutine was never awaited」。
    """
    db.info.setdefault(_AFTER, []).append(coro_factory)


def _spawn(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 没有事件循环(同步脚本里提交):没有在线连接要通知
        coro.close()
        return
    task = loop.create_task(coro)
    task.add_done_callback(_log_failure)


def _log_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("提交后的任务失败", exc_info=task.exception())


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    frames = session.info.pop(_PENDING, None)
    if frames:
        from ..realtime.hub import hub

        _spawn(hub.dispatch(frames))
    for factory in session.info.pop(_AFTER, None) or ():
        _spawn(factory())


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_PENDING, None)
    session.info.pop(_AFTER, None)


async def purge_old_events(db: AsyncSession, now: datetime | None = None) -> int:
    """清扫任务调:删 7 天前的事件。返回删了多少行。"""
    cutoff = (now or datetime.now(timezone.utc)) - RETENTION
    a = await db.execute(delete(ChatEvent).where(ChatEvent.created_at < cutoff))
    b = await db.execute(delete(UserEvent).where(UserEvent.created_at < cutoff))
    await db.commit()
    return (a.rowcount or 0) + (b.rowcount or 0)
