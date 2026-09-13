"""聊天接口 `/chat/v1`(DEV-PROMPTS-40 §8,#344–#352)。

路由只做三件事:取当前用户、调 services/chat_store 或 chat_view、提交。
权限、seq、事件全在 service 里 —— 路由里不写任何判定,判定写两份迟早不一样。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (ACTIVE_ROLES, Chat, ChatEvent, ChatFolder, ChatMember, ChatMessage,
                      ChatReport, InviteLink, JoinRequest, MessageHide, MessageReaction,
                      ScheduledMessage, SocialProfile, User, UserEvent, Username)
from ..ratelimit import check_rate_limit
from ..services import chat_store as store
from ..services.chat_perms import chat_settings
from ..services.chat_view import (can_read_chat, chat_card, dialogs, enrich_messages,
                                  is_active, member_of, messages_page, now_utc,
                                  public_chat_card, visible_floor)
from ..services.rt_events import append_user_event
from ..services.social import user_cards
from .social import social_user

async def chat_on(db: AsyncSession = Depends(get_db)) -> None:
    """「消息」急停闸(#375 chat_enabled):关掉时整个 /chat/v1 回 503。每次现查,拉闸立刻生效。"""
    from ..services.flags import social_flag_on
    if not await social_flag_on(db, "chat_enabled"):
        raise HTTPException(503, "消息功能暂停中,稍后再试")


router = APIRouter(prefix="/chat/v1", tags=["聊天"], dependencies=[Depends(chat_on)])

#: 举报原因代码(§5.11,和后台、文档一张表)
REPORT_REASONS = {"C101", "C102", "C103", "C104", "C105", "C106", "C107", "C108", "C109",
                  "X999"}
FOLDERS_MAX = 10
SCHEDULED_MAX = 100


async def _chat(db: AsyncSession, chat_id: int) -> Chat:
    chat = await db.get(Chat, chat_id)
    if chat is None or chat.deleted_at is not None:
        raise HTTPException(404, "会话不存在")
    return chat


async def _readable(db: AsyncSession, chat_id: int, me: User) -> tuple[Chat, ChatMember | None]:
    chat = await _chat(db, chat_id)
    ok, m = await can_read_chat(db, chat, me.id)
    if not ok:
        raise HTTPException(403, "你不在这个会话里")
    return chat, m


async def _one_message(db: AsyncSession, me: User, chat: Chat, seq: int) -> dict:
    m = await db.scalar(select(ChatMessage).where(ChatMessage.chat_id == chat.id,
                                                  ChatMessage.seq == seq))
    return (await enrich_messages(db, me.id, chat, [m]))[0] if m is not None else {}


# ---------------- 会话 ----------------

@router.get("/dialogs")
async def list_dialogs(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """会话列表(含归档的,客户端按 `my.archived` 分;带未读、未读 @、最后一条)。"""
    items = await dialogs(db, me.id)
    prof = await db.get(SocialProfile, me.id)
    return {"items": items, "user_pts": prof.user_pts if prof else 0}


class PrivateIn(BaseModel):
    user_id: int


@router.post("/chats/private")
async def open_private(body: PrivateIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    chat, _ = await store.private_chat(db, me, body.user_id)
    await db.commit()
    return await chat_card(db, me.id, chat)


@router.post("/chats/saved")
async def open_saved(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    chat = await store.saved_chat(db, me)
    await db.commit()
    return await chat_card(db, me.id, chat)


class CreateIn(BaseModel):
    type: str = Field(pattern="^(group|channel)$")
    title: str = Field(max_length=128)
    about: str = Field(default="", max_length=255)
    member_ids: list[int] = Field(default_factory=list, max_length=200)


@router.post("/chats")
async def create(body: CreateIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    chat, skipped = await store.create_chat(db, me, body.type, body.title, body.about,
                                            body.member_ids)
    await db.commit()
    card = await chat_card(db, me.id, chat)
    card["skipped_user_ids"] = skipped
    return card


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: int, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    chat, m = await _readable(db, chat_id, me)
    return await chat_card(db, me.id, chat, m)


class ChatPatch(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    about: str | None = Field(default=None, max_length=255)
    photo: str | None = Field(default=None, max_length=300)
    username: str | None = Field(default=None, max_length=32)
    settings: dict | None = None


@router.patch("/chats/{chat_id}")
async def patch_chat(chat_id: int, body: ChatPatch, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    chat = await store.lock_chat(db, chat_id)
    await store.update_chat_info(db, chat, me, body.model_dump(exclude_unset=True))
    await db.commit()
    return await chat_card(db, me.id, chat)


@router.delete("/chats/{chat_id}")
async def remove_chat(chat_id: int, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    chat = await store.lock_chat(db, chat_id)
    await store.delete_chat(db, chat, me)
    await db.commit()
    return {"ok": True}


@router.post("/chats/{chat_id}/leave")
async def leave(chat_id: int, me: User = Depends(social_user),
                db: AsyncSession = Depends(get_db)):
    chat = await store.lock_chat(db, chat_id)
    await store.leave_chat(db, chat, me)
    await db.commit()
    return {"ok": True}


@router.post("/chats/{chat_id}/join")
async def join_public(chat_id: int, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    res = await store.join_public(db, me, chat)
    await db.commit()
    return res


class DialogPatch(BaseModel):
    pinned: bool | None = None
    archived: bool | None = None
    muted_until: int | str | None = None
    marked_unread: bool | None = None
    draft: dict | None = None


@router.patch("/dialogs/{chat_id}")
async def patch_dialog(chat_id: int, body: DialogPatch, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    await store.update_dialog(db, chat, me, body.model_dump(exclude_unset=True))
    await db.commit()
    return await chat_card(db, me.id, chat)


class ClearIn(BaseModel):
    revoke: bool = False


@router.post("/dialogs/{chat_id}/clear")
async def clear(chat_id: int, body: ClearIn, me: User = Depends(social_user),
                db: AsyncSession = Depends(get_db)):
    chat = await store.lock_chat(db, chat_id)
    await store.clear_history(db, chat, me, body.revoke)
    await db.commit()
    return {"ok": True}


@router.delete("/dialogs/{chat_id}")
async def delete_dialog(chat_id: int, revoke: bool = False, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    """删除会话:私聊 = 清空(可选对双方)并从我的列表里拿掉;群 / 频道 = 退出。"""
    chat = await store.lock_chat(db, chat_id)
    if chat.type in ("group", "channel"):
        await store.leave_chat(db, chat, me)
    else:
        await store.clear_history(db, chat, me, revoke)
        m = await member_of(db, chat.id, me.id)
        if m is not None and chat.type == "private":
            m.visible = False
            m.pinned_rank = None
            await append_user_event(db, me.id, "chat_leave", {"chat_id": chat.id,
                                                              "role": "hidden"})
    await db.commit()
    return {"ok": True}


class ReadIn(BaseModel):
    seq: int


@router.post("/dialogs/{chat_id}/read")
async def mark_read(chat_id: int, body: ReadIn, me: User = Depends(social_user),
                    db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    m = await store.read(db, chat, me, body.seq)
    await db.commit()
    return {"last_read_seq": m.last_read_seq}


# ---------------- 消息 ----------------

@router.get("/chats/{chat_id}/messages")
async def list_messages(chat_id: int, before: int | None = None, after: int | None = None,
                        around: int | None = None, limit: int = Query(50, ge=1, le=100),
                        me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    chat, m = await _readable(db, chat_id, me)
    return await messages_page(db, me.id, chat, m, before=before, after=after, around=around,
                               limit=limit)


class SendIn(BaseModel):
    random_id: str | None = Field(default=None, max_length=20)
    kind: str = Field(default="text", max_length=12)
    text: str = Field(default="", max_length=4096)
    entities: list | None = None
    media_ids: list[int] | None = None
    reply_to_seq: int | None = None
    grouped_id: str | None = Field(default=None, max_length=20)
    silent: bool = False
    no_preview: bool = False
    as_chat: bool = False
    location: dict | None = None
    contact: dict | None = None
    poll: dict | None = None
    dice: dict | None = None
    sticker_id: int | None = None


@router.post("/chats/{chat_id}/messages")
async def send_message(chat_id: int, body: SendIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    msg, _ = await store.send(db, chat, me, body.model_dump())
    seq = msg.seq
    await db.commit()
    return await _one_message(db, me, chat, seq)


class EditIn(BaseModel):
    text: str = Field(max_length=4096)
    entities: list | None = None


@router.patch("/chats/{chat_id}/messages/{seq}")
async def edit_message(chat_id: int, seq: int, body: EditIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    await store.edit(db, chat, me, seq, body.text, body.entities)
    await db.commit()
    return await _one_message(db, me, chat, seq)


class DeleteIn(BaseModel):
    seqs: list[int] = Field(max_length=100)
    revoke: bool = False


@router.post("/chats/{chat_id}/messages/delete")
async def delete_messages(chat_id: int, body: DeleteIn, me: User = Depends(social_user),
                          db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    done = await store.delete_messages(db, chat, me, body.seqs, body.revoke)
    await db.commit()
    return {"seqs": done}


class ForwardIn(BaseModel):
    seqs: list[int] = Field(max_length=100)
    to_chat_ids: list[int] = Field(max_length=10)
    hide_sender: bool = False


@router.post("/chats/{chat_id}/messages/forward")
async def forward_messages(chat_id: int, body: ForwardIn, me: User = Depends(social_user),
                           db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    sent = await store.forward(db, me, chat, body.seqs, body.to_chat_ids, body.hide_sender)
    await db.commit()
    return {"sent": [{"chat_id": c, "seq": s} for c, s in sent]}


class ReactIn(BaseModel):
    emoji: str = Field(max_length=16)
    add: bool = True


@router.post("/chats/{chat_id}/messages/{seq}/reactions")
async def react(chat_id: int, seq: int, body: ReactIn, me: User = Depends(social_user),
                db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    await store.react(db, chat, me, seq, body.emoji, body.add)
    await db.commit()
    return await _one_message(db, me, chat, seq)


@router.get("/chats/{chat_id}/messages/{seq}/reactions")
async def who_reacted(chat_id: int, seq: int, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    """谁回应了什么(频道只给数,不给人 —— 和 TG 一样)。"""
    chat, m = await _readable(db, chat_id, me)
    if chat.type == "channel":
        raise HTTPException(422, "频道不公开回应的人")
    rows = (await db.execute(select(MessageReaction.user_id, MessageReaction.emoji).where(
        MessageReaction.chat_id == chat.id, MessageReaction.seq == seq)
        .order_by(MessageReaction.created_at.desc()).limit(200))).all()
    cards = await user_cards(db, me.id, [u for u, _ in rows])
    return {"items": [{"user": cards.get(u), "emoji": e} for u, e in rows if u in cards]}


@router.get("/chats/{chat_id}/messages/{seq}/readers")
async def readers(chat_id: int, seq: int, me: User = Depends(social_user),
                  db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    rows = await store.readers(db, chat, me, seq)
    cards = await user_cards(db, me.id, [r["user_id"] for r in rows])
    return {"items": [{"user": cards[r["user_id"]], "read_at": r["read_at"]}
                      for r in rows if r["user_id"] in cards]}


class PinIn(BaseModel):
    seq: int | None = None
    pinned: bool = True
    notify: bool = True


@router.post("/chats/{chat_id}/pins")
async def pin(chat_id: int, body: PinIn, me: User = Depends(social_user),
              db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    seqs = await store.pin(db, chat, me, body.seq, body.pinned, body.notify)
    await db.commit()
    return {"seqs": seqs, "pinned": body.pinned}


@router.get("/chats/{chat_id}/pins")
async def pins(chat_id: int, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    chat, m = await _readable(db, chat_id, me)
    floor = visible_floor(chat, m) if m else 0
    msgs = list(await db.scalars(select(ChatMessage).where(
        ChatMessage.chat_id == chat.id, ChatMessage.pinned_at.is_not(None),
        ChatMessage.deleted_at.is_(None), ChatMessage.seq > floor)
        .order_by(ChatMessage.seq.desc()).limit(100)))
    return {"items": await enrich_messages(db, me.id, chat, msgs)}


class VoteIn(BaseModel):
    options: list[int] = Field(default_factory=list, max_length=10)


@router.post("/chats/{chat_id}/polls/{seq}/vote")
async def vote(chat_id: int, seq: int, body: VoteIn, me: User = Depends(social_user),
               db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    await store.vote(db, chat, me, seq, body.options)
    await db.commit()
    return await _one_message(db, me, chat, seq)


@router.post("/chats/{chat_id}/polls/{seq}/close")
async def close_poll(chat_id: int, seq: int, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    await store.close_poll(db, chat, me, seq)
    await db.commit()
    return await _one_message(db, me, chat, seq)


@router.get("/chats/{chat_id}/polls/{seq}/voters")
async def poll_voters(chat_id: int, seq: int, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    """公开投票:每个选项谁投了。匿名投票不给。"""
    from ..models import Poll, PollVote
    chat, m = await _readable(db, chat_id, me)
    msg = await db.scalar(select(ChatMessage).where(ChatMessage.chat_id == chat.id,
                                                    ChatMessage.seq == seq))
    poll = await db.get(Poll, msg.poll_id) if msg is not None and msg.poll_id else None
    if poll is None:
        raise HTTPException(404, "没有这个投票")
    if poll.anonymous:
        raise HTTPException(403, "匿名投票不公开谁投了什么")
    rows = (await db.execute(select(PollVote.user_id, PollVote.options)
                             .where(PollVote.poll_id == poll.id))).all()
    cards = await user_cards(db, me.id, [u for u, _ in rows])
    by_opt: dict[int, list] = {i: [] for i in range(len(poll.options or []))}
    for uid, opts in rows:
        for o in opts or []:
            if o in by_opt and uid in cards:
                by_opt[o].append(cards[uid])
    return {"options": [{"index": i, "voters": v} for i, v in by_opt.items()]}


class ViewsIn(BaseModel):
    seqs: list[int] = Field(max_length=100)


@router.post("/chats/{chat_id}/views")
async def count_views(chat_id: int, body: ViewsIn, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    """频道帖子浏览量:每人每条只算一次(Redis 集合去重)。"""
    from ..redis_client import get_redis
    chat, _ = await _readable(db, chat_id, me)
    if chat.type != "channel":
        return {"views": {}}
    r = get_redis()
    counted = []
    for s in sorted(set(body.seqs))[:100]:
        try:
            added = await r.sadd(f"chat:views:{chat.id}:{s}", me.id)
            if added:
                await r.expire(f"chat:views:{chat.id}:{s}", 90 * 86400)
                counted.append(s)
        except Exception:
            break
    if counted:
        await db.execute(update(ChatMessage).where(ChatMessage.chat_id == chat.id,
                                                   ChatMessage.seq.in_(counted))
                         .values(views=ChatMessage.views + 1))
        await db.commit()
    rows = (await db.execute(select(ChatMessage.seq, ChatMessage.views).where(
        ChatMessage.chat_id == chat.id, ChatMessage.seq.in_(body.seqs)))).all()
    return {"views": {str(s): v for s, v in rows}}


# ---------------- 成员与邀请 ----------------

@router.get("/chats/{chat_id}/members")
async def members(chat_id: int, q: str = "", role: str = "", offset: int = 0,
                  limit: int = Query(50, ge=1, le=200), me: User = Depends(social_user),
                  db: AsyncSession = Depends(get_db)):
    chat, m = await _readable(db, chat_id, me)
    perms = store.perms_of(chat, m)
    if chat.type == "channel" and not perms.is_admin:
        raise HTTPException(403, "频道订阅者名单只有管理员能看")
    roles = ACTIVE_ROLES if role != "banned" else ("banned",)
    if role == "banned" and not perms.ban_users:
        raise HTTPException(403, "你没有管理成员的权限")
    if role == "admins":
        roles = ("owner", "admin")
    stmt = (select(ChatMember).join(User, User.id == ChatMember.user_id)
            .where(ChatMember.chat_id == chat.id, ChatMember.role.in_(roles)))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.outerjoin(SocialProfile, SocialProfile.user_id == ChatMember.user_id).where(
            or_(User.name.ilike(like), SocialProfile.username.ilike(like)))
    order = case({"owner": 0, "admin": 1, "member": 2, "restricted": 3, "banned": 4},
                 value=ChatMember.role, else_=5)
    rows = list(await db.scalars(stmt.order_by(order, ChatMember.joined_at)
                                 .offset(offset).limit(limit)))
    cards = await user_cards(db, me.id, [r.user_id for r in rows])
    return {"items": [{"user": cards.get(r.user_id), "role": r.role, "title": r.title,
                       "rights": r.rights if perms.is_admin or r.user_id == me.id else {},
                       "restrictions": r.restrictions if perms.ban_users else {},
                       "joined_at": r.joined_at.isoformat() if r.joined_at else None}
                      for r in rows if r.user_id in cards],
            "total": chat.member_count}


class AddMembersIn(BaseModel):
    user_ids: list[int] = Field(max_length=200)


@router.post("/chats/{chat_id}/members")
async def add_members(chat_id: int, body: AddMembersIn, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    chat = await store.lock_chat(db, chat_id)
    res = await store.add_members(db, chat, me, body.user_ids)
    await db.commit()
    return res


class MemberPatch(BaseModel):
    action: str = Field(pattern="^(promote|demote|restrict|unrestrict|ban|unban|kick)$")
    rights: dict | None = None
    title: str | None = Field(default=None, max_length=16)
    perms: dict | None = None
    until: datetime | None = None


@router.patch("/chats/{chat_id}/members/{user_id}")
async def patch_member(chat_id: int, user_id: int, body: MemberPatch,
                       me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    chat = await store.lock_chat(db, chat_id)
    until = body.until
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    tm = await store.set_member(db, chat, me, user_id, action=body.action, rights=body.rights,
                                title=body.title, perms=body.perms, until=until)
    await db.commit()
    return {"user_id": user_id, "role": tm.role, "rights": tm.rights,
            "restrictions": tm.restrictions, "title": tm.title}


class TransferIn(BaseModel):
    user_id: int


@router.post("/chats/{chat_id}/transfer")
async def transfer(chat_id: int, body: TransferIn, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    chat = await store.lock_chat(db, chat_id)
    await store.transfer_owner(db, chat, me, body.user_id)
    await db.commit()
    return {"ok": True}


def _invite_out(link: InviteLink) -> dict:
    return {"code": link.code, "url": f"https://chaojizan.cc/join/{link.code}",
            "title": link.title, "is_primary": link.is_primary, "revoked": link.revoked,
            "expire_at": link.expire_at.isoformat() if link.expire_at else None,
            "usage_limit": link.usage_limit, "usage_count": link.usage_count,
            "requires_approval": link.requires_approval,
            "created_at": link.created_at.isoformat() if link.created_at else None}


@router.get("/chats/{chat_id}/invites")
async def invites(chat_id: int, me: User = Depends(social_user),
                  db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    _, p = await store.require_member(db, chat, me.id)
    if not p.invite_users:
        raise HTTPException(403, "你没有邀请成员的权限")
    await store.ensure_primary_invite(db, chat, me.id)
    await db.commit()
    rows = list(await db.scalars(select(InviteLink).where(InviteLink.chat_id == chat.id)
                                 .order_by(InviteLink.is_primary.desc(),
                                           InviteLink.created_at.desc())))
    return {"items": [_invite_out(r) for r in rows]}


class InviteIn(BaseModel):
    title: str = Field(default="", max_length=32)
    expire_at: datetime | None = None
    usage_limit: int | None = None
    requires_approval: bool = False


@router.post("/chats/{chat_id}/invites")
async def create_invite(chat_id: int, body: InviteIn, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    exp = body.expire_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    link = await store.create_invite(db, chat, me, title=body.title, expire_at=exp,
                                     usage_limit=body.usage_limit,
                                     requires_approval=body.requires_approval)
    await db.commit()
    return _invite_out(link)


@router.delete("/chats/{chat_id}/invites/{code}")
async def revoke_invite(chat_id: int, code: str, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    link = await store.revoke_invite(db, chat, me, code)
    await db.commit()
    return _invite_out(link)


@router.get("/join/{code}")
async def invite_preview(code: str, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    """点邀请链接时先看一眼:群名、头像、人数、我是不是已经在里面。"""
    link, chat = await store.resolve_invite(db, code)
    m = await member_of(db, chat.id, me.id)
    return {"chat": {"id": chat.id, "type": chat.type, "title": chat.title,
                     "about": chat.about, "photo": chat.photo_url,
                     "member_count": chat.member_count, "username": chat.username},
            "is_member": is_active(m),
            "requires_approval": link.requires_approval or
            chat_settings(chat.settings)["join_by_request"]}


class JoinIn(BaseModel):
    about: str = Field(default="", max_length=140)


@router.post("/join/{code}")
async def join(code: str, body: JoinIn | None = None, me: User = Depends(social_user),
               db: AsyncSession = Depends(get_db)):
    res = await store.join_by_invite(db, me, code, (body.about if body else ""))
    await db.commit()
    return res


@router.get("/chats/{chat_id}/join-requests")
async def join_requests(chat_id: int, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    _, p = await store.require_member(db, chat, me.id)
    if not p.invite_users:
        raise HTTPException(403, "你没有处理入群申请的权限")
    rows = list(await db.scalars(select(JoinRequest).where(JoinRequest.chat_id == chat.id)
                                 .order_by(JoinRequest.created_at)))
    cards = await user_cards(db, me.id, [r.user_id for r in rows])
    return {"items": [{"user": cards.get(r.user_id), "about": r.about,
                       "created_at": r.created_at.isoformat() if r.created_at else None}
                      for r in rows if r.user_id in cards]}


class DecideIn(BaseModel):
    approve: bool


@router.post("/chats/{chat_id}/join-requests/{user_id}")
async def decide(chat_id: int, user_id: int, body: DecideIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    chat = await store.lock_chat(db, chat_id)
    await store.decide_join_request(db, chat, me, user_id, body.approve)
    await db.commit()
    return {"ok": True}


# ---------------- 断线补齐 ----------------

class SyncIn(BaseModel):
    user_pts: int = 0
    chats: dict[str, int] = Field(default_factory=dict)


#: 单个会话落后超过这么多条事件就不补了,让客户端重拉(§5.3)
SYNC_MAX_EVENTS = 500


@router.post("/sync")
async def sync(body: SyncIn, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    prof = await db.get(SocialProfile, me.id)
    user_pts = prof.user_pts if prof else 0
    uevs = list(await db.scalars(select(UserEvent).where(
        UserEvent.user_id == me.id, UserEvent.pts > body.user_pts)
        .order_by(UserEvent.pts).limit(SYNC_MAX_EVENTS + 1)))
    user_reset = len(uevs) > SYNC_MAX_EVENTS or (
        body.user_pts < user_pts and (not uevs or uevs[0].pts != body.user_pts + 1))
    out_chats: dict[str, dict] = {}
    for key, pts in list(body.chats.items())[:500]:
        try:
            cid = int(key)
        except ValueError:
            continue
        chat = await db.get(Chat, cid)
        if chat is None or chat.deleted_at is not None:
            out_chats[key] = {"gone": True}
            continue
        ok, m = await can_read_chat(db, chat, me.id)
        if not ok:
            out_chats[key] = {"gone": True}
            continue
        if pts >= chat.pts:
            out_chats[key] = {"events": [], "pts": chat.pts}
            continue
        evs = list(await db.scalars(select(ChatEvent).where(
            ChatEvent.chat_id == cid, ChatEvent.pts > pts)
            .order_by(ChatEvent.pts).limit(SYNC_MAX_EVENTS + 1)))
        if len(evs) > SYNC_MAX_EVENTS or not evs or evs[0].pts != pts + 1:
            out_chats[key] = {"reset": True, "pts": chat.pts}
            continue
        floor = visible_floor(chat, m) if m else 0
        items = []
        for e in evs:
            d = e.data or {}
            # 清空过记录 / 入群前的消息事件不补给他
            if e.type in ("msg", "edit") and int(d.get("seq") or 0) <= floor:
                continue
            items.append({"t": "ev", "chat_id": cid, "pts": e.pts, "type": e.type, "data": d})
        out_chats[key] = {"events": items, "pts": chat.pts}
    return {"user_pts": user_pts, "user_reset": user_reset,
            "user_events": [] if user_reset else [
                {"t": "uev", "pts": e.pts, "type": e.type, "data": e.data} for e in uevs],
            "chats": out_chats}


# ---------------- 搜索与共享媒体 ----------------

@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=64), me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    """全局搜索:我的会话名、联系人和公开的人 / 群 / 频道(用户名)、我能读的消息正文。"""
    await check_rate_limit("chat_search", str(me.id), 60)
    term = q.strip()
    like = f"%{term}%"
    my = (select(ChatMember.chat_id).where(ChatMember.user_id == me.id,
                                           ChatMember.role.in_(ACTIVE_ROLES)))
    chats = list(await db.scalars(select(Chat).where(
        Chat.id.in_(my), Chat.deleted_at.is_(None), Chat.type.in_(("group", "channel")),
        Chat.title.ilike(like)).limit(20)))
    chat_items = [await chat_card(db, me.id, c) for c in chats]
    # 私聊按对方名字搜
    peers = list(await db.scalars(select(User.id).join(
        ChatMember, and_(ChatMember.user_id == User.id)).where(
        ChatMember.chat_id.in_(select(ChatMember.chat_id).where(
            ChatMember.user_id == me.id, ChatMember.role.in_(ACTIVE_ROLES))),
        User.id != me.id, User.name.ilike(like)).limit(20)))
    # 公开的:用户名前缀匹配
    uname = term.lstrip("@").lower()
    public_users, public_chats = [], []
    if len(uname) >= 3:
        rows = (await db.execute(select(Username.owner_type, Username.owner_id).where(
            Username.username_lc.like(f"{uname}%")).limit(20))).all()
        public_users = [oid for t, oid in rows if t == "user" and oid != me.id]
        for t, oid in rows:
            if t == "chat":
                card = await public_chat_card(db, me, oid)
                if card:
                    public_chats.append(card)
    cards = await user_cards(db, me.id, list(dict.fromkeys(peers + public_users)))
    # 消息正文:只搜我能读的(清空过的不搜)
    mrows = (await db.execute(
        select(ChatMessage).join(ChatMember, and_(ChatMember.chat_id == ChatMessage.chat_id,
                                                  ChatMember.user_id == me.id))
        .where(ChatMember.role.in_(ACTIVE_ROLES), ChatMessage.deleted_at.is_(None),
               ChatMessage.seq > ChatMember.cleared_seq, ChatMessage.text.ilike(like),
               ~exists().where(and_(MessageHide.chat_id == ChatMessage.chat_id,
                                    MessageHide.seq == ChatMessage.seq,
                                    MessageHide.user_id == me.id)))
        .order_by(ChatMessage.created_at.desc()).limit(50))).scalars().all()
    by_chat: dict[int, list] = {}
    for m in mrows:
        by_chat.setdefault(m.chat_id, []).append(m)
    messages = []
    for cid, ms in by_chat.items():
        c = await db.get(Chat, cid)
        if c is None:
            continue
        card = await chat_card(db, me.id, c)
        for item in await enrich_messages(db, me.id, c, ms):
            messages.append({"chat": {"id": c.id, "type": c.type, "title": card["title"],
                                      "photo": card["photo"]}, "message": item})
    messages.sort(key=lambda x: x["message"]["created_at"], reverse=True)
    return {"chats": chat_items + public_chats,
            "users": [cards[i] for i in dict.fromkeys(peers + public_users) if i in cards],
            "messages": messages}


MEDIA_TABS = {
    "photo": ("photo", "video", "gif"),
    "file": ("file",),
    "voice": ("voice", "video_note"),
}


@router.get("/chats/{chat_id}/search")
async def search_in_chat(chat_id: int, q: str = "", kind: str = "", from_user: int | None = None,
                         before: int | None = None, limit: int = Query(50, ge=1, le=100),
                         me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """会话内搜索 / 共享媒体(kind=photo|file|voice|link)。按 seq 倒序,before 翻页。"""
    chat, m = await _readable(db, chat_id, me)
    floor = visible_floor(chat, m) if m else 0
    conds = [ChatMessage.chat_id == chat.id, ChatMessage.seq > floor,
             ChatMessage.deleted_at.is_(None), ChatMessage.kind != "service"]
    if m is not None:
        conds.append(~exists().where(and_(MessageHide.chat_id == ChatMessage.chat_id,
                                          MessageHide.seq == ChatMessage.seq,
                                          MessageHide.user_id == me.id)))
    if q.strip():
        conds.append(ChatMessage.text.ilike(f"%{q.strip()}%"))
    if kind in MEDIA_TABS:
        conds.append(ChatMessage.kind.in_(MEDIA_TABS[kind]))
    elif kind == "link":
        conds.append(or_(ChatMessage.entities.contains([{"type": "url"}]),
                         ChatMessage.entities.contains([{"type": "text_link"}])))
    if from_user:
        conds.append(ChatMessage.sender_id == from_user)
    if before:
        conds.append(ChatMessage.seq < before)
    msgs = list(await db.scalars(select(ChatMessage).where(*conds)
                                 .order_by(ChatMessage.seq.desc()).limit(limit)))
    return {"items": await enrich_messages(db, me.id, chat, msgs),
            "has_more": len(msgs) == limit}


@router.get("/link-preview")
async def link_preview(url: str = Query(max_length=2048), me: User = Depends(social_user)):
    """输入框里先看一眼预览(发出去之后服务端还会再取一次写进消息)。"""
    from ..services.link_preview import build_preview
    await check_rate_limit("chat_link_preview", str(me.id), 20)
    info = await build_preview(url)
    if info is None:
        raise HTTPException(404, "这个链接没有可以预览的内容")
    return info


# ---------------- 定时消息 ----------------

class ScheduleIn(SendIn):
    send_at: datetime


def _sched_out(s: ScheduledMessage) -> dict:
    return {"id": s.id, "chat_id": s.chat_id, "send_at": s.send_at.isoformat(),
            "payload": s.payload}


@router.get("/chats/{chat_id}/scheduled")
async def scheduled(chat_id: int, me: User = Depends(social_user),
                    db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    await store.require_member(db, chat, me.id)
    rows = list(await db.scalars(select(ScheduledMessage).where(
        ScheduledMessage.chat_id == chat.id, ScheduledMessage.sender_id == me.id)
        .order_by(ScheduledMessage.send_at)))
    return {"items": [_sched_out(r) for r in rows]}


@router.post("/chats/{chat_id}/scheduled")
async def schedule(chat_id: int, body: ScheduleIn, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    chat = await _chat(db, chat_id)
    _, p = await store.require_member(db, chat, me.id)
    if not p.send_messages:
        raise HTTPException(403, "你在这个会话里不能发言")
    at = body.send_at if body.send_at.tzinfo else body.send_at.replace(tzinfo=timezone.utc)
    if at <= now_utc():
        raise HTTPException(422, "定时要选将来的时间")
    if (at - now_utc()).days > 365:
        raise HTTPException(422, "最多定一年以内")
    n = await db.scalar(select(func.count()).select_from(ScheduledMessage).where(
        ScheduledMessage.chat_id == chat.id, ScheduledMessage.sender_id == me.id))
    if (n or 0) >= SCHEDULED_MAX:
        raise HTTPException(422, f"一个会话最多 {SCHEDULED_MAX} 条定时消息")
    payload = body.model_dump(exclude={"send_at", "random_id"})
    if payload.get("kind") not in ("text", "photo", "video", "file", "voice", "sticker",
                                   "location", "poll", "gif"):
        raise HTTPException(422, "这类消息不能定时发送")
    row = ScheduledMessage(chat_id=chat.id, sender_id=me.id, payload=payload, send_at=at)
    db.add(row)
    await db.commit()
    return _sched_out(row)


class ReschedIn(BaseModel):
    send_at: datetime


@router.patch("/chats/{chat_id}/scheduled/{sid}")
async def reschedule(chat_id: int, sid: int, body: ReschedIn, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    row = await db.get(ScheduledMessage, sid)
    if row is None or row.chat_id != chat_id or row.sender_id != me.id:
        raise HTTPException(404, "没有这条定时消息")
    at = body.send_at if body.send_at.tzinfo else body.send_at.replace(tzinfo=timezone.utc)
    if at <= now_utc():
        raise HTTPException(422, "定时要选将来的时间")
    row.send_at = at
    await db.commit()
    return _sched_out(row)


@router.delete("/chats/{chat_id}/scheduled/{sid}")
async def unschedule(chat_id: int, sid: int, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    row = await db.get(ScheduledMessage, sid)
    if row is None or row.chat_id != chat_id or row.sender_id != me.id:
        raise HTTPException(404, "没有这条定时消息")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/chats/{chat_id}/scheduled/{sid}/send-now")
async def send_now(chat_id: int, sid: int, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    row = await db.get(ScheduledMessage, sid)
    if row is None or row.chat_id != chat_id or row.sender_id != me.id:
        raise HTTPException(404, "没有这条定时消息")
    chat = await _chat(db, chat_id)
    payload = dict(row.payload or {})
    await db.delete(row)
    msg, _ = await store.send(db, chat, me, payload)
    seq = msg.seq
    await db.commit()
    return await _one_message(db, me, chat, seq)


async def send_due_scheduled(limit: int = 50) -> int:
    """清扫任务调:把到点的定时消息发出去。

    **每条一个事务**:一条发不出去(发的人被踢了、被拉黑了)只回滚它自己,
    不会把同一批里别人的消息连带回滚,也不会把失败那条的事件漏发出去。
    发不出去的丢掉,并给发的人一个用户事件说明原因。
    """
    from ..db import SessionLocal
    async with SessionLocal() as db:
        ids = list(await db.scalars(select(ScheduledMessage.id).where(
            ScheduledMessage.send_at <= now_utc()).order_by(ScheduledMessage.send_at)
            .limit(limit)))
    sent = 0
    for sid in ids:
        async with SessionLocal() as db:
            row = await db.scalar(select(ScheduledMessage).where(ScheduledMessage.id == sid)
                                  .with_for_update(skip_locked=True))
            if row is None:
                continue
            payload, chat_id, sender_id = dict(row.payload or {}), row.chat_id, row.sender_id
            chat = await db.get(Chat, chat_id)
            user = await db.get(User, sender_id)
            await db.delete(row)
            if chat is None or user is None or chat.deleted_at is not None:
                await db.commit()
                continue
            try:
                await store.send(db, chat, user, payload)
                await db.commit()
                sent += 1
            except HTTPException as e:
                await db.rollback()
                async with SessionLocal() as db2:
                    await db2.execute(ScheduledMessage.__table__.delete()
                                      .where(ScheduledMessage.id == sid))
                    await append_user_event(db2, sender_id, "scheduled_failed",
                                            {"chat_id": chat_id, "reason": str(e.detail)})
                    await db2.commit()
    return sent


# ---------------- 分组 ----------------

class FolderIn(BaseModel):
    id: int | None = None
    title: str = Field(max_length=12)
    rules: dict = Field(default_factory=dict)


class FoldersIn(BaseModel):
    items: list[FolderIn] = Field(max_length=FOLDERS_MAX)


def _folder_out(f: ChatFolder) -> dict:
    return {"id": f.id, "title": f.title, "rules": f.rules, "position": f.position}


@router.get("/folders")
async def folders(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    rows = list(await db.scalars(select(ChatFolder).where(ChatFolder.user_id == me.id)
                                 .order_by(ChatFolder.position)))
    return {"items": [_folder_out(f) for f in rows]}


_FOLDER_TYPES = {"private", "group", "channel", "bot", "contacts", "non_contacts"}


@router.put("/folders")
async def put_folders(body: FoldersIn, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    """整体替换(客户端改完排序、增删之后一次交上来)。"""
    existing = {f.id: f for f in await db.scalars(select(ChatFolder)
                                                  .where(ChatFolder.user_id == me.id))}
    keep = set()
    for pos, it in enumerate(body.items):
        title = it.title.strip()
        if not title:
            raise HTTPException(422, "分组名不能为空")
        rules = {
            "types": [t for t in (it.rules.get("types") or []) if t in _FOLDER_TYPES],
            "include": [int(i) for i in (it.rules.get("include") or [])][:200],
            "exclude": [int(i) for i in (it.rules.get("exclude") or [])][:200],
            "exclude_muted": bool(it.rules.get("exclude_muted")),
            "exclude_read": bool(it.rules.get("exclude_read")),
            "exclude_archived": bool(it.rules.get("exclude_archived", True)),
        }
        if not rules["types"] and not rules["include"]:
            raise HTTPException(422, f"分组「{title}」至少要包含一类会话或一个会话")
        f = existing.get(it.id) if it.id else None
        if f is None:
            f = ChatFolder(user_id=me.id, title=title, rules=rules, position=pos)
            db.add(f)
        else:
            f.title, f.rules, f.position = title, rules, pos
        await db.flush()
        keep.add(f.id)
    for fid, f in existing.items():
        if fid not in keep:
            await db.delete(f)
    await append_user_event(db, me.id, "folders", {})
    await db.commit()
    return await folders(me, db)


# ---------------- 举报 ----------------

class ReportIn(BaseModel):
    target_type: str = Field(pattern="^(chat|message|user)$")
    chat_id: int | None = None
    seqs: list[int] = Field(default_factory=list, max_length=20)
    user_id: int | None = None
    reason_code: str
    note: str = Field(default="", max_length=500)


# ---------------- 导出我的数据(S5) ----------------

@router.get("/export")
async def export_status(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """导出进度:none / running(带 progress)/ failed(带 error)/ ready(带下载地址);`last` 是上一份做好的。"""
    from ..services import chat_export
    return await chat_export.status(db, me.id)


@router.post("/export")
async def export_start(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """开始导出聊天记录(JSON + 媒体)和自己的投稿。后台打包,做好了发一条 `export` 用户事件。"""
    from ..services import chat_export
    return await chat_export.start(db, me)


@router.post("/reports")
async def report(body: ReportIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    """举报会话、消息、用户(#368 处理)。举报人对被举报的一方永远匿名。"""
    await check_rate_limit("chat_report", str(me.id), 10)
    if body.reason_code not in REPORT_REASONS:
        raise HTTPException(422, "请选择举报原因")
    if body.reason_code == "X999" and len(body.note.strip()) < 5:
        raise HTTPException(422, "选「其他」要写明原因(至少 5 个字)")
    if body.target_type in ("chat", "message"):
        if body.chat_id is None:
            raise HTTPException(422, "缺少会话")
        chat, _ = await _readable(db, body.chat_id, me)
        if body.target_type == "message" and not body.seqs:
            raise HTTPException(422, "要举报哪几条消息?")
    elif body.user_id is None:
        raise HTTPException(422, "缺少用户")
    row = ChatReport(reporter_id=me.id, target_type=body.target_type, chat_id=body.chat_id,
                     seqs=sorted(set(body.seqs)), user_id=body.user_id,
                     reason_code=body.reason_code, note=body.note.strip())
    db.add(row)
    await db.commit()
    return {"id": row.id, "status": row.status}
