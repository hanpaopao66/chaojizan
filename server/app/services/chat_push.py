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

from ..config import settings
from ..db import SessionLocal
from ..models import (ACTIVE_ROLES, Chat, ChatMember, ChatMessage, MessageMention,
                      SocialProfile, User, UserRole)
from .chat_view import KIND_LABELS
from .entities import mask_spoilers
from .social import display_name, notify_prefs

logger = logging.getLogger("superz.chat")


def _preview(m: ChatMessage) -> str:
    text = mask_spoilers(m.text or "", m.entities)
    if m.kind == "text":
        return text[:60]
    label = KIND_LABELS.get(m.kind, "消息")
    return f"[{label}]" + (f" {text[:40]}" if text else "")


#: 成员分批扫的批大小。
#:
#: 原来是「一条 SQL 把成员全查出来 + 再按这些 id 查一遍 SocialProfile」,
#: 群上限 1000 的时候没问题。2026-09-16 群放到 20 万(D7)之后这两句都不成立了:
#: 20 万行进内存,后一句还是 `IN (20 万个 id)` —— 一条消息就能把库打趴,
#: 而频道**本来就不限订阅人数**,也就是说这个坑在群提上限之前已经埋着了。
#:
#: 现在按 user_id 顺序分批扫,每批查、每批推。内存和单条 SQL 的大小都跟群的大小无关。
#: 批大小走配置(`CHAT_PUSH_CHUNK`):e2e 设成 2,让四个人的小群也走好几批。


async def notify_message(chat_id: int, seq: int) -> int:
    """给这条消息该收到推送的人推一遍。返回推给了几个人。

    **按成员分批**(`CHAT_PUSH_CHUNK`):20 万人的群不能一次性查出来。
    分批之后每一批各自 try —— 一批推失败不该让后面的人收不到。
    """
    from ..realtime.hub import hub
    from . import push

    sent = 0
    async with SessionLocal() as db:
        chat = await db.get(Chat, chat_id)
        msg = await db.scalar(select(ChatMessage).where(ChatMessage.chat_id == chat_id,
                                                        ChatMessage.seq == seq))
        if chat is None or msg is None or msg.deleted_at is not None:
            return 0
        if msg.kind == "service" or msg.silent or chat.type == "saved":
            return 0
        mentioned = set(await db.scalars(select(MessageMention.user_id).where(
            MessageMention.chat_id == chat_id, MessageMention.seq == seq)))
        sender = await db.get(User, msg.sender_id) if msg.sender_id else None
        sender_name = chat.title if msg.as_chat else (display_name(sender) if sender else "")
        now = datetime.now(timezone.utc)
        category = {"private": "private", "group": "group", "channel": "channel"}[chat.type]
        after = 0
        while True:
            # 机器人不推:它没有设备,消息经 Bot API 的更新送到(#355)。
            # 通知偏好(SocialProfile.notify)在同一条 SQL 里 outerjoin 出来 ——
            # 分成两条的话又回到「拿一批 id 再查一次」,批大小一大就是同一个问题
            rows = (await db.execute(
                select(ChatMember.user_id, ChatMember.muted_until, SocialProfile.notify)
                .join(User, User.id == ChatMember.user_id)
                .outerjoin(SocialProfile, SocialProfile.user_id == ChatMember.user_id)
                .where(ChatMember.chat_id == chat_id, ChatMember.role.in_(ACTIVE_ROLES),
                       ChatMember.user_id != (msg.sender_id or 0),
                       User.role != UserRole.bot, ChatMember.user_id > after)
                .order_by(ChatMember.user_id).limit(max(1, settings.chat_push_chunk)))).all()
            if not rows:
                break
            after = rows[-1][0]
            targets = []
            for uid, muted_until, notify in rows:
                if hub.is_foreground(uid):
                    continue
                if muted_until is not None and muted_until > now and uid not in mentioned:
                    continue
                prefs = notify_prefs(notify)
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
                continue
            try:
                sent += await push.fanout(targets, record_skip=True)
            except Exception:
                logger.warning("聊天推送失败(chat=%s seq=%s 这一批 %d 人)",
                               chat_id, seq, len(targets), exc_info=True)
    return sent
