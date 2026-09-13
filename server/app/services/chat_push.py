"""聊天消息的离线推送(DEV-PROMPTS-40 #353)。

规则(和 Telegram 一样的直觉):

- 此刻 App 在前台(实时网关有前台连接)的人不推 —— 他已经在 App 里收到了;
- 免打扰中的会话不推,**除非 @ 了他或者回复了他**;
- 用户在「通知」里关掉了私聊 / 群 / 频道某一类,那一类不推;
- 推送预览(D20)关掉时,标题和正文里都不出现消息内容和发送人,只说「你有一条新消息」;
- 静音发送的消息不推;服务消息(谁进群了、改群名了)不推。

推送日志表(push_logs)照常记每一条,e2e 靠它断言「该推的推了、不该推的没推」。
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import SessionLocal
from ..models import (ACTIVE_ROLES, Chat, ChatMember, ChatMessage, MessageMention,
                      SocialProfile, User, UserRole)
from .chat_view import KIND_LABELS
from .entities import mask_spoilers
from .social import display_name, notify_of

logger = logging.getLogger("superz.chat")


def _preview(m: ChatMessage) -> str:
    text = mask_spoilers(m.text or "", m.entities)
    if m.kind == "text":
        return text[:60]
    label = KIND_LABELS.get(m.kind, "消息")
    return f"[{label}]" + (f" {text[:40]}" if text else "")


async def notify_message(chat_id: int, seq: int) -> int:
    """给这条消息该收到推送的人推一遍。返回推给了几个人。"""
    from ..realtime.hub import hub
    from . import push

    async with SessionLocal() as db:
        chat = await db.get(Chat, chat_id)
        msg = await db.scalar(select(ChatMessage).where(ChatMessage.chat_id == chat_id,
                                                        ChatMessage.seq == seq))
        if chat is None or msg is None or msg.deleted_at is not None:
            return 0
        if msg.kind == "service" or msg.silent or chat.type == "saved":
            return 0
        # 机器人不推:它没有设备,消息经 Bot API 的更新送到(#355)
        members = (await db.execute(select(ChatMember.user_id, ChatMember.muted_until)
                                    .join(User, User.id == ChatMember.user_id).where(
            ChatMember.chat_id == chat_id, ChatMember.role.in_(ACTIVE_ROLES),
            ChatMember.user_id != (msg.sender_id or 0), User.role != UserRole.bot))).all()
        if not members:
            return 0
        mentioned = set(await db.scalars(select(MessageMention.user_id).where(
            MessageMention.chat_id == chat_id, MessageMention.seq == seq)))
        ids = [uid for uid, _ in members]
        profiles = {p.user_id: p for p in await db.scalars(
            select(SocialProfile).where(SocialProfile.user_id.in_(ids)))}
        sender = await db.get(User, msg.sender_id) if msg.sender_id else None
        sender_name = chat.title if msg.as_chat else (display_name(sender) if sender else "")
        now = datetime.now(timezone.utc)
        category = {"private": "private", "group": "group", "channel": "channel"}[chat.type]
        targets = []
        for uid, muted_until in members:
            if hub.is_foreground(uid):
                continue
            if muted_until is not None and muted_until > now and uid not in mentioned:
                continue
            prefs = notify_of(profiles.get(uid))
            if not prefs[category] and uid not in mentioned:
                continue
            if prefs["preview"]:
                if chat.type == "private":
                    title, content = sender_name, _preview(msg)
                elif chat.type == "group":
                    title, content = chat.title, f"{sender_name}:{_preview(msg)}"
                else:
                    title, content = chat.title, _preview(msg)
                if uid in mentioned and chat.type == "group":
                    title = f"{chat.title}(有人@你)"
            else:
                title, content = "超级赞", "你有一条新消息"
            targets.append((uid, title, content, {"type": "chat", "chat_id": str(chat_id),
                                                  "seq": str(seq)}))
    if not targets:
        return 0
    try:
        return await push.fanout(targets, record_skip=True)
    except Exception:
        logger.warning("聊天推送失败", exc_info=True)
        return 0
