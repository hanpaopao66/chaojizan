"""会话、消息对外的形状与读取(DEV-PROMPTS-40 §5.2,#344 #345 #348)。

「谁能看到哪些消息」只在这里算一次(`visible_floor`),分页、搜索、共享媒体、
媒体判权全部用它 —— 这是 S1 的核心,写两份就会有一份漏掉「清空记录」或「入群前的历史」。
"""
from datetime import datetime, timezone

from sqlalchemy import and_, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (ACTIVE_ROLES, Chat, ChatMember, ChatMessage, MessageHide,
                      MessageReaction, Poll, PollVote, SocialProfile, User)
from . import sanctions
from .chat_perms import chat_settings, perms_for
from .entities import mask_spoilers
from .social import display_name, privacy_of, user_cards

_UNSET = object()

#: 这个人数以内的群才有已读回执(广播「谁读到哪」、双勾、已读名单);和 chat_store.read 一致
GROUP_READ_RECEIPTS_MAX = 100

KIND_LABELS = {
    "photo": "图片", "video": "视频", "file": "文件", "voice": "语音", "video_note": "视频消息",
    "sticker": "贴纸", "gif": "GIF", "location": "位置", "contact": "名片", "poll": "投票",
    "dice": "骰子", "call": "通话", "card": "分享",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- 可见范围 ----------------

def visible_floor(chat: Chat, member: ChatMember | None) -> int:
    """这个人能看到的消息从哪个 seq 之后开始(不含)。

    - 自己「清空记录」清到的位置;
    - 不允许看历史的群:入群那一刻的 last_seq。
    """
    if member is None:
        return chat.last_seq  # 不在会话里:什么都看不到(公开频道预览另算)
    floor = member.cleared_seq or 0
    if chat.type == "group" and not chat_settings(chat.settings)["history_visible"]:
        floor = max(floor, member.join_seq or 0)
    return floor


async def member_of(db: AsyncSession, chat_id: int, user_id: int) -> ChatMember | None:
    return await db.get(ChatMember, (chat_id, user_id))


def is_active(member: ChatMember | None) -> bool:
    return member is not None and member.role in ACTIVE_ROLES


async def can_read_chat(db: AsyncSession, chat: Chat, user_id: int) -> tuple[bool, ChatMember | None]:
    """能不能读这个会话:在会话里,或者它是公开频道 / 公开群(不加入也能预览,和 TG 一样)。"""
    m = await member_of(db, chat.id, user_id)
    if is_active(m):
        return True, m
    if m is not None and m.role == "banned":
        return False, m
    if chat.type in ("channel", "group") and chat.username and chat.deleted_at is None:
        # 被平台封禁的公开群 / 频道,外人的预览也关掉(「公开发现里消失」);成员照样能看历史
        if await sanctions.chat_ban(db, chat.id) is None:
            return True, None
    return False, m


# ---------------- 输出 ----------------

def media_out(items: list | None, viewer_id: int | None = None) -> list[dict]:
    """消息里的媒体。给了 viewer_id(接口响应,按人)就签好下载地址;
    事件是发给会话里所有人的,不签,客户端拿 `/media/v1/sign` 换(见 services/media.signed_url)。"""
    from .media import signed_url
    out = []
    for it in items or []:
        mid = it.get("id")
        d = {k: it.get(k) for k in ("id", "kind", "w", "h", "size", "mime", "name",
                                    "duration_ms", "waveform", "loop") if k in it}
        if it.get("public_url"):
            d["url"] = it["public_url"]
            d["thumb"] = None
        elif viewer_id:
            d["url"] = signed_url(mid, viewer_id)
            d["thumb"] = signed_url(mid, viewer_id, True) if it.get("has_thumb") else None
        else:
            d["url"] = f"/media/v1/files/{mid}"
            d["thumb"] = f"/media/v1/files/{mid}?thumb=1" if it.get("has_thumb") else None
        out.append(d)
    return out


def sender_out(user: User | None, profile: SocialProfile | None) -> dict | None:
    """事件里的发送人。**头像只在他的头像隐私是「所有人」时带上** —— 同一条事件发给群里
    所有人,没法按人过滤;设了「联系人可见」的人,客户端再按名片接口单独取。"""
    if user is None:
        return None
    return {
        "id": user.id,
        "name": display_name(user),
        "username": profile.username if profile else None,
        "avatar": (user.avatar_url or "") if privacy_of(profile)["avatar"] == "everyone" else "",
        "is_bot": user.role.value == "bot",
    }


def message_out(m: ChatMessage, *, sender: dict | None, chat: Chat | None = None,
                reactions: list | None = None, reply: dict | None = None,
                poll: dict | None = None, viewer_id: int | None = None) -> dict:
    extra = m.extra or {}
    out = {
        "chat_id": m.chat_id,
        "seq": m.seq,
        "sender": None if m.as_chat else sender,
        "as_chat": m.as_chat,
        "kind": m.kind,
        "text": m.text or "",
        "entities": m.entities or [],
        "media": media_out(m.media, viewer_id),
        "reply_to": reply if m.reply_to_seq else None,
        "reply_to_seq": m.reply_to_seq,
        "forward": m.forward,
        "grouped_id": str(m.grouped_id) if m.grouped_id else None,
        "poll": poll,
        "location": extra.get("location"),
        "contact": extra.get("contact"),
        "dice": extra.get("dice"),
        "service": extra.get("service"),
        "call": extra.get("call"),
        "preview": extra.get("preview"),
        "sticker": extra.get("sticker"),
        # 分享卡片(§5.9):存的是发出去那一刻的快照,客户端照它画
        "card": extra.get("card"),
        "signature": extra.get("signature"),
        "reactions": reactions or [],
        "views": m.views if chat is not None and chat.type == "channel" else None,
        "silent": m.silent,
        "pinned": m.pinned_at is not None,
        "edited_at": m.edited_at.isoformat() if m.edited_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else now_utc().isoformat(),
        "markup": m.markup,
        "via_bot": m.via_bot_id,
        "random_id": str(m.random_id) if m.random_id is not None else None,
    }
    if m.as_chat and chat is not None:
        out["sender_chat"] = {"id": chat.id, "title": chat.title, "photo": chat.photo_url}
    return out


def preview_text(m: ChatMessage) -> str:
    text = mask_spoilers(m.text or "", m.entities)
    if m.kind == "text":
        return text[:80]
    if m.kind == "card":
        # 分享卡片(§5.9):写清分享的是什么 —— 「[歌曲] 晚风」比「[分享]」有用
        from .cards import preview as card_preview
        return card_preview((m.extra or {}).get("card"))[:80]
    label = KIND_LABELS.get(m.kind, "")
    if text:
        return f"[{label}] {text[:60]}" if label else text[:80]
    return f"[{label}]" if label else ""


async def poll_out(db: AsyncSession, poll: Poll, viewer_id: int) -> dict:
    rows = (await db.execute(select(PollVote.options).where(PollVote.poll_id == poll.id))).all()
    counts = [0] * len(poll.options or [])
    for (opts,) in rows:
        for i in opts or []:
            if 0 <= i < len(counts):
                counts[i] += 1
    mine = await db.scalar(select(PollVote.options).where(PollVote.poll_id == poll.id,
                                                           PollVote.user_id == viewer_id))
    voted = mine is not None
    closed = poll.closed or (poll.close_at is not None and poll.close_at <= now_utc())
    show = voted or closed
    return {
        "id": poll.id,
        "question": poll.question,
        "options": [{"text": o.get("text", ""), "votes": counts[i] if show else None}
                    for i, o in enumerate(poll.options or [])],
        "total_voters": len(rows),
        "multiple": poll.multiple,
        "quiz": poll.quiz,
        # 测验的正确答案:投过票或者截止了才给,否则就是把答案发给了所有人
        "correct": poll.correct if poll.quiz and show else None,
        "explanation": poll.explanation if poll.quiz and show else "",
        "anonymous": poll.anonymous,
        "closed": closed,
        "close_at": poll.close_at.isoformat() if poll.close_at else None,
        "my_votes": list(mine or []),
    }


async def poll_results_public(db: AsyncSession, poll: Poll) -> dict:
    """事件里广播的投票结果(不含「我投了什么」,客户端自己记)。"""
    rows = (await db.execute(select(PollVote.options).where(PollVote.poll_id == poll.id))).all()
    counts = [0] * len(poll.options or [])
    for (opts,) in rows:
        for i in opts or []:
            if 0 <= i < len(counts):
                counts[i] += 1
    closed = poll.closed or (poll.close_at is not None and poll.close_at <= now_utc())
    return {"id": poll.id, "counts": counts, "total_voters": len(rows), "closed": closed,
            "correct": poll.correct if poll.quiz and closed else None}


async def enrich_messages(db: AsyncSession, viewer_id: int, chat: Chat,
                          msgs: list[ChatMessage]) -> list[dict]:
    """一页消息的完整输出:发送人、回应(带「我点了没有」)、被回复的那条的摘要、投票。"""
    if not msgs:
        return []
    sender_ids = {m.sender_id for m in msgs if m.sender_id}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(sender_ids)))} \
        if sender_ids else {}
    profiles = {p.user_id: p for p in await db.scalars(
        select(SocialProfile).where(SocialProfile.user_id.in_(sender_ids)))} if sender_ids else {}
    seqs = [m.seq for m in msgs]
    react_rows = (await db.execute(
        select(MessageReaction.seq, MessageReaction.emoji, func.count(),
               func.bool_or(MessageReaction.user_id == viewer_id))
        .where(MessageReaction.chat_id == chat.id, MessageReaction.seq.in_(seqs))
        .group_by(MessageReaction.seq, MessageReaction.emoji))).all()
    reactions: dict[int, list] = {}
    for seq, emoji, n, me in react_rows:
        reactions.setdefault(seq, []).append({"emoji": emoji, "count": n, "me": bool(me)})
    for lst in reactions.values():
        lst.sort(key=lambda r: -r["count"])
    reply_seqs = {m.reply_to_seq for m in msgs if m.reply_to_seq}
    replies: dict[int, dict] = {}
    if reply_seqs:
        for r in await db.scalars(select(ChatMessage).where(
                ChatMessage.chat_id == chat.id, ChatMessage.seq.in_(reply_seqs))):
            ru = users.get(r.sender_id) if r.sender_id else None
            if ru is None and r.sender_id:
                ru = await db.get(User, r.sender_id)
            replies[r.seq] = {
                "seq": r.seq,
                "sender_name": chat.title if r.as_chat else (display_name(ru) if ru else ""),
                "preview": "消息已删除" if r.deleted_at else preview_text(r),
                "kind": r.kind,
                "deleted": r.deleted_at is not None,
            }
    polls: dict[int, dict] = {}
    for m in msgs:
        if m.poll_id:
            p = await db.get(Poll, m.poll_id)
            if p is not None:
                polls[m.seq] = await poll_out(db, p, viewer_id)
    out = []
    for m in msgs:
        u = users.get(m.sender_id) if m.sender_id else None
        out.append(message_out(
            m, sender=sender_out(u, profiles.get(m.sender_id)) if u else None, chat=chat,
            reactions=reactions.get(m.seq), reply=replies.get(m.reply_to_seq) if m.reply_to_seq
            else None, poll=polls.get(m.seq), viewer_id=viewer_id))
    return out


async def message_payload(db: AsyncSession, chat: Chat, m: ChatMessage) -> dict:
    """事件里的消息(发给会话里所有人,所以不带「我」相关的东西)。"""
    user = await db.get(User, m.sender_id) if m.sender_id else None
    profile = await db.get(SocialProfile, m.sender_id) if m.sender_id else None
    reply = None
    if m.reply_to_seq:
        r = await db.scalar(select(ChatMessage).where(ChatMessage.chat_id == chat.id,
                                                      ChatMessage.seq == m.reply_to_seq))
        if r is not None:
            ru = await db.get(User, r.sender_id) if r.sender_id else None
            reply = {"seq": r.seq,
                     "sender_name": chat.title if r.as_chat else (display_name(ru) if ru else ""),
                     "preview": "消息已删除" if r.deleted_at else preview_text(r),
                     "kind": r.kind, "deleted": r.deleted_at is not None}
    poll = None
    if m.poll_id:
        p = await db.get(Poll, m.poll_id)
        if p is not None:
            poll = await poll_out(db, p, 0)
            poll["my_votes"] = []
    reacts = (await db.execute(
        select(MessageReaction.emoji, func.count()).where(
            MessageReaction.chat_id == chat.id, MessageReaction.seq == m.seq)
        .group_by(MessageReaction.emoji))).all()
    return message_out(m, sender=sender_out(user, profile), chat=chat,
                       reactions=[{"emoji": e, "count": n, "me": False} for e, n in reacts],
                       reply=reply, poll=poll)


# ---------------- 会话 ----------------

async def private_peer_id(db: AsyncSession, chat: Chat, viewer_id: int) -> int | None:
    if chat.type != "private" or not chat.pair_key:
        return None
    a, b = (int(x) for x in chat.pair_key.split(":"))
    return b if a == viewer_id else a


def my_state(member: ChatMember | None) -> dict:
    if member is None:
        return {"role": None, "muted_until": None, "pinned": False, "archived": False,
                "marked_unread": False, "draft": None, "last_read_seq": 0, "cleared_seq": 0,
                "title": ""}
    return {
        "role": member.role,
        "rights": member.rights or {},
        "title": member.title or "",
        "muted_until": member.muted_until.isoformat() if member.muted_until else None,
        "pinned": member.pinned_rank is not None,
        "pinned_rank": member.pinned_rank,
        "archived": member.archived,
        "marked_unread": member.marked_unread,
        "draft": member.draft,
        "last_read_seq": member.last_read_seq,
        "cleared_seq": member.cleared_seq,
        "joined_at": member.joined_at.isoformat() if member.joined_at else None,
    }


def chat_base(chat: Chat) -> dict:
    s = chat_settings(chat.settings)
    return {
        "id": chat.id,
        "type": chat.type,
        "public_id": chat.public_id,
        "title": chat.title,
        "about": chat.about,
        "photo": chat.photo_url,
        "username": chat.username,
        "member_count": chat.member_count,
        "last_seq": chat.last_seq,
        "pts": chat.pts,
        "settings": {k: s[k] for k in ("slow_mode", "join_by_request", "default_perms",
                                       "reactions", "signatures", "history_visible",
                                       "protected")},
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
    }


async def chat_card(db: AsyncSession, viewer_id: int, chat: Chat,
                    member: ChatMember | None = None, *, peer_card: dict | None = None,
                    ban=_UNSET) -> dict:
    """某人看到的一个会话(会话资料 + 他自己的设置 + 他此刻的权限)。

    `platform_ban`:这个群 / 频道此刻被平台封禁时的提示(客户端在输入栏位置显示);
    会话列表一次查完所有会话的封禁再传进来(`ban`),不在这里一个个查。
    """
    if member is None:
        member = await member_of(db, chat.id, viewer_id)
    out = chat_base(chat)
    if chat.type in ("group", "channel"):
        if ban is _UNSET:
            ban = await sanctions.chat_ban(db, chat.id)
        out["platform_ban"] = sanctions.ban_brief(ban, chat.type)
    else:
        out["platform_ban"] = None
    out["my"] = my_state(member)
    out["perms"] = perms_for(chat.type, chat.settings, member.role if member else None,
                             member.rights if member else None,
                             member.restrictions if member else None).as_dict()
    out["read_floor"] = visible_floor(chat, member)
    if chat.type == "private":
        peer = await private_peer_id(db, chat, viewer_id)
        if peer_card is None and peer is not None:
            peer_card = (await user_cards(db, viewer_id, [peer])).get(peer)
        out["peer"] = peer_card
        if peer_card:
            out["title"] = peer_card.get("contact_alias") or peer_card["name"]
            out["photo"] = peer_card.get("avatar") or ""
        # 对方读到哪(双勾)
        if peer is not None:
            pm = await member_of(db, chat.id, peer)
            out["peer_read_seq"] = pm.last_read_seq if pm else 0
    elif chat.type == "saved":
        out["title"] = "收藏夹"
    elif chat.type == "group" and (chat.member_count or 0) <= GROUP_READ_RECEIPTS_MAX:
        # 群里「有人读了」就是双勾(和 Telegram 一样):别人读到的最远那条。
        # 只靠实时事件的话,事件发生时我不在线,打开时就一直是单勾
        out["peer_read_seq"] = int(await db.scalar(
            select(func.coalesce(func.max(ChatMember.last_read_seq), 0)).where(
                ChatMember.chat_id == chat.id, ChatMember.user_id != viewer_id,
                ChatMember.role.in_(ACTIVE_ROLES))) or 0)
    return out


async def public_chat_card(db: AsyncSession, viewer, chat_id: int) -> dict | None:
    """公开群 / 频道的名片(用 @用户名或链接找到时)。"""
    chat = await db.get(Chat, chat_id)
    if chat is None or chat.deleted_at is not None or not chat.username:
        return None
    # 被平台封禁的:搜索、@链接都找不到(「公开发现里消失」)
    if await sanctions.chat_ban(db, chat.id) is not None:
        return None
    m = await member_of(db, chat.id, viewer.id)
    out = chat_base(chat)
    out["is_member"] = is_active(m)
    out["banned"] = m is not None and m.role == "banned"
    return out


_DIALOGS_SQL = text("""
SELECT cm.chat_id,
       lm.id AS last_id,
       (SELECT count(*) FROM (
            SELECT 1 FROM chat_messages m
             WHERE m.chat_id = cm.chat_id
               AND m.seq > GREATEST(cm.last_read_seq, cm.cleared_seq)
               AND m.deleted_at IS NULL
               AND (m.sender_id IS DISTINCT FROM cm.user_id OR m.as_chat)
             LIMIT 1000) x) AS unread,
       (SELECT count(*) FROM message_mentions mm
         WHERE mm.chat_id = cm.chat_id AND mm.user_id = cm.user_id
           AND mm.seq > cm.last_read_seq) AS mentions
  FROM chat_members cm
  JOIN chats c ON c.id = cm.chat_id
  LEFT JOIN LATERAL (
        SELECT m.id FROM chat_messages m
         WHERE m.chat_id = cm.chat_id
           AND m.seq > cm.cleared_seq
           AND m.deleted_at IS NULL
           AND NOT EXISTS (SELECT 1 FROM message_hides h
                            WHERE h.chat_id = m.chat_id AND h.seq = m.seq
                              AND h.user_id = cm.user_id)
         ORDER BY m.seq DESC LIMIT 1) lm ON TRUE
 WHERE cm.user_id = :uid
   AND cm.role IN ('owner', 'admin', 'member', 'restricted')
   AND cm.visible
   AND c.deleted_at IS NULL
 ORDER BY (cm.pinned_rank IS NULL), cm.pinned_rank,
          COALESCE(c.last_message_at, c.created_at) DESC, c.id DESC
 LIMIT :lim
""")


async def dialogs(db: AsyncSession, viewer_id: int, limit: int = 1000) -> list[dict]:
    """会话列表:一条 SQL 取出每个会话的最后一条可见消息、未读数、未读 @ 数,不 N+1。"""
    rows = (await db.execute(_DIALOGS_SQL, {"uid": viewer_id, "lim": limit})).all()
    if not rows:
        return []
    chat_ids = [r.chat_id for r in rows]
    chats = {c.id: c for c in await db.scalars(select(Chat).where(Chat.id.in_(chat_ids)))}
    members = {m.chat_id: m for m in await db.scalars(select(ChatMember).where(
        ChatMember.user_id == viewer_id, ChatMember.chat_id.in_(chat_ids)))}
    last_ids = [r.last_id for r in rows if r.last_id]
    lasts = {m.id: m for m in await db.scalars(
        select(ChatMessage).where(ChatMessage.id.in_(last_ids)))} if last_ids else {}
    # 私聊对方的名片一次取完
    peer_of: dict[int, int] = {}
    for c in chats.values():
        if c.type == "private" and c.pair_key:
            a, b = (int(x) for x in c.pair_key.split(":"))
            peer_of[c.id] = b if a == viewer_id else a
    cards = await user_cards(db, viewer_id, peer_of.values())
    peer_reads = {}
    if peer_of:
        for pm in await db.scalars(select(ChatMember).where(
                ChatMember.chat_id.in_(list(peer_of)), ChatMember.user_id != viewer_id)):
            peer_reads[pm.chat_id] = pm.last_read_seq
    small_groups = [c.id for c in chats.values()
                    if c.type == "group" and (c.member_count or 0) <= GROUP_READ_RECEIPTS_MAX]
    if small_groups:
        for cid, mx in (await db.execute(
                select(ChatMember.chat_id, func.max(ChatMember.last_read_seq)).where(
                    ChatMember.chat_id.in_(small_groups), ChatMember.user_id != viewer_id,
                    ChatMember.role.in_(ACTIVE_ROLES)).group_by(ChatMember.chat_id))).all():
            peer_reads[cid] = int(mx or 0)
    bans = await sanctions.banned_chat_ids(
        db, [c.id for c in chats.values() if c.type in ("group", "channel")])
    out = []
    for r in rows:
        chat = chats.get(r.chat_id)
        if chat is None:
            continue
        card = await chat_card(db, viewer_id, chat, members.get(chat.id),
                               peer_card=cards.get(peer_of.get(chat.id)),
                               ban=bans.get(chat.id))
        if chat.id in peer_reads:
            card["peer_read_seq"] = peer_reads[chat.id]
        last = lasts.get(r.last_id) if r.last_id else None
        card["last_message"] = (await enrich_messages(db, viewer_id, chat, [last]))[0] \
            if last else None
        card["unread"] = int(r.unread or 0)
        card["unread_mentions"] = int(r.mentions or 0)
        out.append(card)
    return out


async def messages_page(db: AsyncSession, viewer_id: int, chat: Chat,
                        member: ChatMember | None, *, before: int | None = None,
                        after: int | None = None, around: int | None = None,
                        limit: int = 50) -> dict:
    """一页消息(按 seq 升序返回)。before / after / around 三选一,都不给就是最新一页。"""
    limit = max(1, min(limit, 100))
    floor = visible_floor(chat, member) if member is not None else 0
    base = [ChatMessage.chat_id == chat.id, ChatMessage.seq > floor,
            ChatMessage.deleted_at.is_(None)]
    if member is not None:
        base.append(~exists().where(and_(MessageHide.chat_id == ChatMessage.chat_id,
                                         MessageHide.seq == ChatMessage.seq,
                                         MessageHide.user_id == viewer_id)))
    if around is not None:
        half = limit // 2
        older = list(await db.scalars(select(ChatMessage).where(*base, ChatMessage.seq <= around)
                                      .order_by(ChatMessage.seq.desc()).limit(half + 1)))
        newer = list(await db.scalars(select(ChatMessage).where(*base, ChatMessage.seq > around)
                                      .order_by(ChatMessage.seq).limit(half)))
        msgs = list(reversed(older)) + newer
        has_older = len(older) > half
        if has_older:
            msgs = msgs[1:]
        has_newer = len(newer) == half
    elif after is not None:
        msgs = list(await db.scalars(select(ChatMessage).where(*base, ChatMessage.seq > after)
                                     .order_by(ChatMessage.seq).limit(limit + 1)))
        has_newer = len(msgs) > limit
        msgs = msgs[:limit]
        has_older = True
    else:
        q = select(ChatMessage).where(*base)
        if before is not None:
            q = q.where(ChatMessage.seq < before)
        msgs = list(await db.scalars(q.order_by(ChatMessage.seq.desc()).limit(limit + 1)))
        has_older = len(msgs) > limit
        msgs = list(reversed(msgs[:limit]))
        has_newer = before is not None
    return {"messages": await enrich_messages(db, viewer_id, chat, msgs),
            "has_older": has_older, "has_newer": has_newer}
