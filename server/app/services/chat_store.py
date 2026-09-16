"""聊天的所有写操作(DEV-PROMPTS-40 #344 #345 #349 #350 #351)。

**写消息只能走 [insert_message]**:锁会话行 → 分配 seq → 写消息 → 同事务写事件。
其他代码直接 insert chat_messages 就会出现 seq 空洞或重号(S10)。

所有函数只改库、登记事件和提交后的任务,**不提交**;提交由调用方(路由)做 ——
这样一个请求里的多步操作要么全成、要么全不成,事件也跟着同进同退。
"""
import hashlib
import random
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (ACTIVE_ROLES, Chat, ChatMember, ChatMessage, InviteLink,
                      JoinRequest, MediaFile, MessageHide, MessageMention, MessageReaction,
                      Poll, PollVote, SocialProfile, Sticker, User, UserIdentity, UserRole,
                      Username)
from ..ratelimit import check_daily_limit, check_rate_limit, check_rate_limit_seconds
from .chat_perms import (DEFAULT_ADMIN_RIGHTS, GROUP_MAX_MEMBERS, SLOW_MODES, ADMIN_RIGHTS,
                         MEMBER_PERMS, Perms, can_delete_for_all, can_edit_message,
                         chat_settings, perms_for, reaction_allowed)
from .chat_view import (GROUP_READ_RECEIPTS_MAX, is_active, member_of, message_payload,
                        now_utc, poll_results_public, private_peer_id, visible_floor)
from .entities import (EntityError, auto_entities, mask_spoilers, mentioned_user_ids,
                       mentioned_usernames, urls, validate_entities)
from . import sanctions
from .moderation import guard_text
from .rt_events import after_commit, append_chat_event, append_user_event
from .social import (SOCIAL_ROLES, allowed, blocked_between, claim_username, display_name,
                     ensure_profile, new_public_id, validate_username)

TEXT_MAX = 4096
CAPTION_MAX = 1024
ALBUM_MAX = 10
#: 新账号(注册 < 24 小时)每天最多主动开 20 个新私聊(§5.7,防骚扰)
NEW_ACCOUNT_NEW_CHATS_PER_DAY = 20
CHATS_CREATED_PER_DAY = 10
PINNED_DIALOGS_MAX = 5
FORWARD_MAX = 100
FORWARD_TARGETS_MAX = 10
DICE = {"🎲": 6, "🎯": 6, "🏀": 5, "⚽": 5, "🎳": 6, "🎰": 64}
#: 媒体类消息要什么样的媒体
MEDIA_KIND_FOR = {
    "photo": ("photo",), "video": ("video",), "voice": ("voice",),
    "video_note": ("video_note", "video"), "gif": ("gif",),
    "file": ("file", "photo", "video", "voice", "gif"),
}
MEDIA_MSG_KINDS = set(MEDIA_KIND_FOR) | {"sticker"}


def _err(code: int, msg: str) -> HTTPException:
    return HTTPException(code, msg)


# ---------------- 基础 ----------------

async def lock_chat(db: AsyncSession, chat_id: int) -> Chat:
    """锁住会话行并拿到**锁之后的**最新值。

    `populate_existing` 不能省:同一个请求里先前 `db.get` 过这个会话的话,SQLAlchemy 会把
    会话里那个旧对象原样还回来,字段不刷新 —— 两个人同时发消息,都拿着锁之前读到的
    last_seq 算下一个 seq,撞同一个号(S10 的并发 e2e 就是这么抓到的)。
    """
    chat = await db.scalar(select(Chat).where(Chat.id == chat_id, Chat.deleted_at.is_(None))
                           .with_for_update().execution_options(populate_existing=True))
    if chat is None:
        raise _err(404, "会话不存在")
    return chat


def perms_of(chat: Chat, member: ChatMember | None) -> Perms:
    return perms_for(chat.type, chat.settings, member.role if member else None,
                     member.rights if member else None,
                     member.restrictions if member else None)


async def require_member(db: AsyncSession, chat: Chat, user_id: int) -> tuple[ChatMember, Perms]:
    m = await member_of(db, chat.id, user_id)
    if not is_active(m):
        raise _err(403, "你不在这个会话里")
    return m, perms_of(chat, m)


def _pair_key(a: int, b: int) -> str:
    x, y = sorted((a, b))
    return f"{x}:{y}"


async def _new_chat(db: AsyncSession, **kw) -> Chat:
    chat = Chat(public_id=new_public_id(), last_seq=0, pts=0, member_count=0,
                settings=kw.pop("settings", {}), **kw)
    db.add(chat)
    await db.flush()
    return chat


# ---------------- 建会话 ----------------

async def private_chat(db: AsyncSession, me: User, other_id: int) -> tuple[Chat, bool]:
    """和某人的私聊:有就返回,没有就建(对方在他那边先不显示,等第一条消息)。"""
    if other_id == me.id:
        return await saved_chat(db, me), False
    other = await db.get(User, other_id)
    if other is None or other.role not in SOCIAL_ROLES or other.deleted_at is not None:
        raise _err(404, "没有这个用户")
    key = _pair_key(me.id, other_id)
    chat = await db.scalar(select(Chat).where(Chat.pair_key == key))
    if chat is not None:
        return chat, False
    # 封号期间不能发起新的会话(已有的私聊照样能打开看)
    await sanctions.check_user(db, me.id, "create_chat")
    if await blocked_between(db, me.id, other_id):
        raise _err(403, "你们之间有一方把对方拉黑了,不能发起私聊")
    created = me.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if created is not None and now_utc() - created < timedelta(hours=24):
        await check_daily_limit("chat_new_private", str(me.id), NEW_ACCOUNT_NEW_CHATS_PER_DAY,
                                "新注册的账号每天最多主动发起 20 个私聊,明天再来")
    chat = await _new_chat(db, type="private", pair_key=key, created_by=me.id)
    await ensure_profile(db, me.id)
    await ensure_profile(db, other_id)
    db.add(ChatMember(chat_id=chat.id, user_id=me.id, role="member", visible=True))
    db.add(ChatMember(chat_id=chat.id, user_id=other_id, role="member", visible=False))
    chat.member_count = 2
    await db.flush()
    await append_user_event(db, me.id, "chat_join", {"chat": {"id": chat.id, "type": "private"}})
    await append_user_event(db, other_id, "chat_join",
                            {"chat": {"id": chat.id, "type": "private"}, "hidden": True})
    return chat, True


async def saved_chat(db: AsyncSession, me: User) -> Chat:
    key = f"s:{me.id}"
    chat = await db.scalar(select(Chat).where(Chat.pair_key == key))
    if chat is not None:
        return chat
    chat = await _new_chat(db, type="saved", pair_key=key, title="收藏夹", created_by=me.id)
    db.add(ChatMember(chat_id=chat.id, user_id=me.id, role="owner", visible=True))
    chat.member_count = 1
    await db.flush()
    await append_user_event(db, me.id, "chat_join", {"chat": {"id": chat.id, "type": "saved"}})
    return chat


async def has_identity(db: AsyncSession, user_id: int) -> bool:
    return await db.scalar(select(UserIdentity.id).where(UserIdentity.user_id == user_id)) \
        is not None


async def create_chat(db: AsyncSession, me: User, type_: str, title: str, about: str,
                      member_ids: list[int]) -> tuple[Chat, list[int]]:
    """建群 / 频道。返回 (会话, 因为隐私没能直接拉进来的人)。"""
    if type_ not in ("group", "channel"):
        raise _err(422, "只能建群组或频道")
    await sanctions.check_user(db, me.id, "create_chat")
    title = title.strip()
    if not 1 <= len(title) <= 128:
        raise _err(422, "名称 1–128 个字")
    await guard_text(db, f"{title}\n{about}", "名称或简介")
    await check_daily_limit("chat_create", str(me.id), CHATS_CREATED_PER_DAY,
                            "每天最多建 10 个群或频道")
    if type_ == "group" and not [i for i in member_ids if i != me.id]:
        raise _err(422, "建群至少要选一个人")
    chat = await _new_chat(db, type=type_, title=title, about=about.strip()[:255],
                           owner_id=me.id, created_by=me.id,
                           settings={"signatures": False} if type_ == "channel" else {})
    await ensure_profile(db, me.id)
    db.add(ChatMember(chat_id=chat.id, user_id=me.id, role="owner", visible=True, join_seq=0))
    chat.member_count = 1
    await db.flush()
    await append_user_event(db, me.id, "chat_join", {"chat": {"id": chat.id, "type": type_}})
    await send_service(db, chat, me.id, "chat_create", title=title)
    await ensure_primary_invite(db, chat, me.id)
    skipped: list[int] = []
    if member_ids:
        res = await add_members(db, chat, me, member_ids, announce=True)
        skipped = res["skipped"]
    return chat, skipped


# ---------------- 成员 ----------------

async def _upsert_member(db: AsyncSession, chat: Chat, user_id: int, *, role: str = "member",
                         invited_by: int | None = None) -> ChatMember:
    m = await member_of(db, chat.id, user_id)
    if m is None:
        m = ChatMember(chat_id=chat.id, user_id=user_id, role=role, invited_by=invited_by,
                       join_seq=chat.last_seq, visible=True, joined_at=now_utc())
        db.add(m)
    else:
        m.role = role
        m.invited_by = invited_by
        m.left_at = None
        m.join_seq = chat.last_seq
        m.restrictions = {}
        m.rights = {}
        m.visible = True
        m.joined_at = now_utc()
    chat.member_count = (chat.member_count or 0) + 1
    await ensure_profile(db, user_id)
    await db.flush()
    return m


async def _member_changed(db: AsyncSession, chat: Chat, user_id: int, role: str,
                          extra: dict | None = None, *, old_role: str | None = None,
                          actor_id: int | None = None) -> None:
    await append_chat_event(db, chat.id, "member",
                            {"user_id": user_id, "role": role, **(extra or {})})
    if role in ACTIVE_ROLES:
        await append_user_event(db, user_id, "chat_join",
                                {"chat": {"id": chat.id, "type": chat.type}})
    else:
        await append_user_event(db, user_id, "chat_leave", {"chat_id": chat.id, "role": role})
    # 变的是机器人自己的身份:给它一条 my_chat_member(#355;不是机器人的话一次主键查询就走)
    from .bots import on_member_changed
    await on_member_changed(db, chat, user_id,
                            old_role if old_role is not None else
                            ("left" if role in ACTIVE_ROLES else "member"),
                            role, actor_id, (extra or {}).get("rights"))


async def add_members(db: AsyncSession, chat: Chat, actor: User, user_ids: list[int],
                      *, announce: bool = True) -> dict:
    """拉人进群 / 频道。对方隐私「谁能拉我进群」不允许的,跳过并返回,由客户端改发邀请链接。"""
    if chat.type not in ("group", "channel"):
        raise _err(422, "只有群组和频道能拉人")
    me_m, p = await require_member(db, chat, actor.id)
    if not p.invite_users:
        raise _err(403, "你没有邀请成员的权限")
    # 被平台封禁的群 / 频道不能再进人(拉人、邀请链接、公开加入、审批入群申请都挡)
    await sanctions.check_chat(db, chat, actor.id, "join")
    added, skipped = [], []
    for uid in dict.fromkeys(user_ids):
        if uid == actor.id:
            continue
        u = await db.get(User, uid)
        if u is None or u.role not in SOCIAL_ROLES or u.deleted_at is not None:
            skipped.append(uid)
            continue
        m = await member_of(db, chat.id, uid)
        if is_active(m):
            continue
        if m is not None and m.role == "banned" and not p.ban_users:
            skipped.append(uid)
            continue
        prof = await db.get(SocialProfile, uid)
        if not await allowed(db, prof, uid, actor.id, "group_invite"):
            skipped.append(uid)
            continue
        if chat.type == "group" and (chat.member_count or 0) >= GROUP_MAX_MEMBERS:
            raise _err(422, f"群最多 {GROUP_MAX_MEMBERS} 人")
        old_role = m.role if m is not None else None
        await _upsert_member(db, chat, uid, invited_by=actor.id)
        await _member_changed(db, chat, uid, "member", {"invited_by": actor.id},
                              old_role=old_role, actor_id=actor.id)
        added.append(uid)
    if added and announce and chat.type == "group":
        await send_service(db, chat, actor.id, "members_add", user_ids=added,
                           names=[display_name(await db.get(User, i)) for i in added])
    return {"added": added, "skipped": skipped}


async def leave_chat(db: AsyncSession, chat: Chat, me: User) -> None:
    m, _ = await require_member(db, chat, me.id)
    if chat.type in ("private", "saved"):
        raise _err(422, "私聊不能退出,可以删除会话")
    if m.role == "owner":
        others = await db.scalar(select(func.count()).select_from(ChatMember).where(
            ChatMember.chat_id == chat.id, ChatMember.user_id != me.id,
            ChatMember.role.in_(ACTIVE_ROLES)))
        if others:
            raise _err(422, "你是群主,先把群主转让给别人再退出,或者解散")
        await delete_chat(db, chat, me)
        return
    m.role = "left"
    m.left_at = now_utc()
    m.rights = {}
    chat.member_count = max(0, (chat.member_count or 1) - 1)
    if chat.type == "group":
        await send_service(db, chat, me.id, "member_leave", name=display_name(me))
    await _member_changed(db, chat, me.id, "left")


async def set_member(db: AsyncSession, chat: Chat, actor: User, target_id: int, *,
                     action: str, rights: dict | None = None, title: str | None = None,
                     perms: dict | None = None, until: datetime | None = None) -> ChatMember:
    """任免管理员、限制、封禁、移出、解封。action:promote / demote / restrict / unrestrict /
    ban / unban / kick。"""
    if chat.type not in ("group", "channel"):
        raise _err(422, "只有群组和频道有成员管理")
    if target_id == actor.id and action not in ("demote",):
        raise _err(422, "不能对自己这么做")
    am, ap = await require_member(db, chat, actor.id)
    tm = await member_of(db, chat.id, target_id)
    if tm is None:
        raise _err(404, "这个人不在会话里")
    if tm.role == "owner":
        raise _err(403, "不能对群主这么做")
    old = {"old_role": tm.role, "actor_id": actor.id}
    if action in ("promote", "demote"):
        if not ap.add_admins:
            raise _err(403, "你没有任免管理员的权限")
        if not is_active(tm):
            raise _err(422, "这个人不在会话里")
        if tm.role == "admin" and am.role != "owner" and tm.invited_by != actor.id:
            raise _err(403, "只能修改自己任命的管理员")
        if action == "promote":
            want = {**DEFAULT_ADMIN_RIGHTS, **{k: bool(v) for k, v in (rights or {}).items()
                                               if k in ADMIN_RIGHTS}}
            if am.role != "owner":
                # 只能给自己有的权限
                mine = perms_of(chat, am)
                cap = {"change_info": mine.change_info, "delete_messages": mine.delete_others,
                       "ban_users": mine.ban_users, "invite_users": mine.invite_users,
                       "pin_messages": mine.pin_messages, "add_admins": mine.add_admins,
                       "post_messages": mine.send_messages, "edit_messages": mine.edit_others,
                       "anonymous": mine.anonymous}
                want = {k: v and cap.get(k, False) for k, v in want.items()}
            tm.role = "admin"
            tm.rights = want
            tm.title = (title or "").strip()[:16]
            tm.invited_by = actor.id
            tm.restrictions = {}
        else:
            tm.role = "member"
            tm.rights = {}
            tm.title = ""
        await _member_changed(db, chat, target_id, tm.role,
                              {"rights": tm.rights, "title": tm.title}, **old)
        return tm
    if not ap.ban_users:
        raise _err(403, "你没有管理成员的权限")
    if tm.role == "admin" and am.role != "owner":
        raise _err(403, "只有群主能处理管理员")
    if action == "restrict":
        if chat.type != "group":
            raise _err(422, "频道没有发言权限可限制")
        want = {k: bool((perms or {}).get(k, False)) for k in MEMBER_PERMS}
        tm.role = "restricted"
        tm.rights = {}
        tm.restrictions = {"perms": want, "until": until.isoformat() if until else None}
        await _member_changed(db, chat, target_id, "restricted",
                              {"restrictions": tm.restrictions}, **old)
    elif action == "unrestrict":
        tm.role = "member" if is_active(tm) else tm.role
        tm.restrictions = {}
        await _member_changed(db, chat, target_id, tm.role, **old)
    elif action in ("ban", "kick"):
        was_active = is_active(tm)
        tm.role = "banned" if action == "ban" else "left"
        tm.rights = {}
        tm.left_at = now_utc()
        tm.restrictions = {"until": until.isoformat() if until else None} if action == "ban" else {}
        if was_active:
            chat.member_count = max(0, (chat.member_count or 1) - 1)
        if chat.type == "group" and was_active:
            u = await db.get(User, target_id)
            await send_service(db, chat, actor.id, "member_kick",
                               user_id=target_id, name=display_name(u) if u else "")
        await _member_changed(db, chat, target_id, tm.role, **old)
    elif action == "unban":
        if tm.role == "banned":
            tm.role = "left"
            tm.restrictions = {}
            await _member_changed(db, chat, target_id, "left", **old)
    else:
        raise _err(422, "不认识的操作")
    return tm


async def transfer_owner(db: AsyncSession, chat: Chat, actor: User, target_id: int) -> None:
    am, _ = await require_member(db, chat, actor.id)
    if am.role != "owner":
        raise _err(403, "只有群主能转让")
    tm = await member_of(db, chat.id, target_id)
    if not is_active(tm) or tm is None:
        raise _err(422, "只能转让给会话里的人")
    target = await db.get(User, target_id)
    if target is not None and target.role == UserRole.bot:
        # 群主要为群负责(群主责任,#374),机器人背不了;和 Telegram 一样不许
        raise _err(422, "不能把群主转让给机器人")
    target_old = tm.role
    tm.role = "owner"
    tm.rights = {}
    tm.restrictions = {}
    am.role = "admin"
    am.rights = {k: True for k in ADMIN_RIGHTS}
    chat.owner_id = target_id
    await _member_changed(db, chat, target_id, "owner", old_role=target_old, actor_id=actor.id)
    await _member_changed(db, chat, actor.id, "admin", {"rights": am.rights},
                          old_role="owner", actor_id=actor.id)


async def delete_chat(db: AsyncSession, chat: Chat, actor: User) -> None:
    """解散群 / 删除频道(只有群主)。成员都会收到「会话没了」。"""
    if chat.type in ("group", "channel"):
        am = await member_of(db, chat.id, actor.id)
        if am is None or am.role != "owner":
            raise _err(403, "只有群主能解散")
    chat.deleted_at = now_utc()
    if chat.username:
        await db.execute(delete(Username).where(Username.owner_type == "chat",
                                                Username.owner_id == chat.id))
        chat.username = None
    members = list(await db.scalars(select(ChatMember.user_id).where(
        ChatMember.chat_id == chat.id, ChatMember.role.in_(ACTIVE_ROLES))))
    await append_chat_event(db, chat.id, "chat", {"deleted": True, "id": chat.id})
    for uid in members:
        await append_user_event(db, uid, "chat_leave", {"chat_id": chat.id, "role": "deleted"})
    # 群里的机器人:告诉它自己不在这个群了(#355)。只查机器人成员,不按人头逐个查
    from .bots import bots_in, on_member_changed
    for bot_id, _, _ in await bots_in(db, chat):
        bm = await member_of(db, chat.id, bot_id)
        await on_member_changed(db, chat, bot_id, bm.role if bm else "member", "left", actor.id)


# ---------------- 会话资料 ----------------

async def update_chat_info(db: AsyncSession, chat: Chat, actor: User, patch: dict) -> Chat:
    if chat.type not in ("group", "channel"):
        raise _err(422, "私聊没有可改的资料")
    am, p = await require_member(db, chat, actor.id)
    if not p.change_info:
        raise _err(403, "你没有修改资料的权限")
    # 被封的群改名、改简介、挂公开链接都是在群里「说话」(还会发服务消息、重新进搜索),一起挡
    await sanctions.check_chat(db, chat, actor.id, "speak")
    changed = {}
    if "title" in patch and patch["title"] is not None:
        t = str(patch["title"]).strip()
        if not 1 <= len(t) <= 128:
            raise _err(422, "名称 1–128 个字")
        await guard_text(db, t, "名称")
        if t != chat.title:
            chat.title = t
            changed["title"] = t
            await send_service(db, chat, actor.id, "title_change", title=t)
    if "about" in patch and patch["about"] is not None:
        await guard_text(db, str(patch["about"]), "简介")
        chat.about = str(patch["about"]).strip()[:255]
        changed["about"] = chat.about
    if "photo" in patch and patch["photo"] is not None:
        chat.photo_url = str(patch["photo"])[:300]
        changed["photo"] = chat.photo_url
        await send_service(db, chat, actor.id, "photo_change")
    if "username" in patch and patch["username"] is not None:
        await _set_chat_username(db, chat, actor, str(patch["username"]).strip().lstrip("@"))
        changed["username"] = chat.username
    if "settings" in patch and patch["settings"] is not None:
        s = dict(chat.settings or {})
        for k, v in patch["settings"].items():
            if k == "slow_mode":
                if chat.type != "group" or int(v) not in SLOW_MODES:
                    raise _err(422, "慢速模式只能是 0 / 10 / 30 / 60 / 300 / 900 / 3600 秒")
                s[k] = int(v)
            elif k == "default_perms" and isinstance(v, dict):
                s[k] = {pk: bool(pv) for pk, pv in v.items() if pk in MEMBER_PERMS}
            elif k == "reactions":
                if v not in ("all", "none") and not (isinstance(v, list) and len(v) <= 30):
                    raise _err(422, "表情回应设置不对")
                s[k] = v
            elif k in ("join_by_request", "signatures", "history_visible", "protected"):
                s[k] = bool(v)
            else:
                raise _err(422, f"没有这个设置:{k}")
        chat.settings = s
        changed["settings"] = chat_settings(s)
    if changed:
        await append_chat_event(db, chat.id, "chat", changed)
    return chat


async def _set_chat_username(db: AsyncSession, chat: Chat, actor: User, name: str) -> None:
    """设公开链接 = 变成公开群 / 频道(D11:要实名)。传空串 = 改回私有。"""
    await db.execute(delete(Username).where(Username.owner_type == "chat",
                                            Username.owner_id == chat.id))
    if not name:
        chat.username = None
        return
    if not await has_identity(db, actor.id):
        raise _err(403, "设公开链接(公开群 / 频道)要先完成实名认证")
    problem = validate_username(name, noun="链接名")
    if problem:
        raise _err(422, problem)
    await guard_text(db, name, "链接名")
    # 和超级赞号共用一个命名空间:被占了、是别人刚换下来还在冷冻的超级赞号,都拿不到(迁移 0133)
    problem = await claim_username(db, name, "chat", chat.id, noun="链接名")
    if problem:
        raise _err(409, problem)
    chat.username = name


# ---------------- 邀请链接 ----------------

def _invite_code() -> str:
    return new_public_id(16)


async def ensure_primary_invite(db: AsyncSession, chat: Chat, creator_id: int) -> InviteLink:
    link = await db.scalar(select(InviteLink).where(InviteLink.chat_id == chat.id,
                                                    InviteLink.is_primary.is_(True),
                                                    InviteLink.revoked.is_(False)))
    if link is None:
        link = InviteLink(chat_id=chat.id, code=_invite_code(), creator_id=creator_id,
                          is_primary=True)
        db.add(link)
        await db.flush()
    return link


async def create_invite(db: AsyncSession, chat: Chat, actor: User, *, title: str = "",
                        expire_at: datetime | None = None, usage_limit: int | None = None,
                        requires_approval: bool = False) -> InviteLink:
    _, p = await require_member(db, chat, actor.id)
    if not p.invite_users:
        raise _err(403, "你没有邀请成员的权限")
    if usage_limit is not None and not 1 <= usage_limit <= 99999:
        raise _err(422, "使用次数 1–99999")
    link = InviteLink(chat_id=chat.id, code=_invite_code(), creator_id=actor.id,
                      title=title.strip()[:32], expire_at=expire_at, usage_limit=usage_limit,
                      requires_approval=requires_approval)
    db.add(link)
    await db.flush()
    return link


async def revoke_invite(db: AsyncSession, chat: Chat, actor: User, code: str) -> InviteLink:
    _, p = await require_member(db, chat, actor.id)
    if not p.invite_users:
        raise _err(403, "你没有邀请成员的权限")
    link = await db.scalar(select(InviteLink).where(InviteLink.chat_id == chat.id,
                                                    InviteLink.code == code))
    if link is None:
        raise _err(404, "没有这个链接")
    link.revoked = True
    if link.is_primary:
        link.is_primary = False
        await db.flush()
        await ensure_primary_invite(db, chat, actor.id)
    return link


async def resolve_invite(db: AsyncSession, code: str) -> tuple[InviteLink, Chat]:
    link = await db.scalar(select(InviteLink).where(InviteLink.code == code))
    if link is None or link.revoked:
        raise _err(404, "邀请链接无效或已被撤销")
    chat = await db.get(Chat, link.chat_id)
    if chat is None or chat.deleted_at is not None:
        raise _err(404, "这个群已经解散了")
    if link.expire_at is not None and link.expire_at <= now_utc():
        raise _err(410, "邀请链接已过期")
    if link.usage_limit is not None and link.usage_count >= link.usage_limit:
        raise _err(410, "邀请链接的使用次数用完了")
    return link, chat


async def join_by_invite(db: AsyncSession, me: User, code: str, about: str = "") -> dict:
    link, chat = await resolve_invite(db, code)
    chat = await lock_chat(db, chat.id)
    m = await member_of(db, chat.id, me.id)
    if is_active(m):
        return {"status": "member", "chat_id": chat.id}
    if m is not None and m.role == "banned":
        raise _err(403, "你已被这个会话封禁")
    await sanctions.check_user(db, me.id, "join")
    await sanctions.check_chat(db, chat, me.id, "join")
    if link.requires_approval or chat_settings(chat.settings)["join_by_request"]:
        await db.execute(insert(JoinRequest).values(
            chat_id=chat.id, user_id=me.id, invite_code=code, about=about[:140]
        ).on_conflict_do_update(index_elements=["chat_id", "user_id"],
                                set_={"invite_code": code, "about": about[:140]}))
        admins = list(await db.scalars(select(ChatMember.user_id).where(
            ChatMember.chat_id == chat.id, ChatMember.role.in_(("owner", "admin")))))
        for uid in admins:
            await append_user_event(db, uid, "join_request", {"chat_id": chat.id,
                                                              "user_id": me.id})
        return {"status": "requested", "chat_id": chat.id}
    if chat.type == "group" and (chat.member_count or 0) >= GROUP_MAX_MEMBERS:
        raise _err(422, f"群已满({GROUP_MAX_MEMBERS} 人)")
    await _upsert_member(db, chat, me.id, invited_by=link.creator_id)
    link.usage_count += 1
    await _member_changed(db, chat, me.id, "member", {"via_invite": True})
    if chat.type == "group":
        await send_service(db, chat, me.id, "member_join", name=display_name(me))
    return {"status": "joined", "chat_id": chat.id}


async def join_public(db: AsyncSession, me: User, chat: Chat) -> dict:
    """公开群 / 频道直接加入(订阅)。"""
    if not chat.username or chat.type not in ("group", "channel"):
        raise _err(403, "这个会话不公开,要邀请链接才能加入")
    chat = await lock_chat(db, chat.id)
    m = await member_of(db, chat.id, me.id)
    if is_active(m):
        return {"status": "member", "chat_id": chat.id}
    if m is not None and m.role == "banned":
        raise _err(403, "你已被这个会话封禁")
    await sanctions.check_user(db, me.id, "join")
    await sanctions.check_chat(db, chat, me.id, "join")
    if chat_settings(chat.settings)["join_by_request"] and chat.type == "group":
        await db.execute(insert(JoinRequest).values(chat_id=chat.id, user_id=me.id)
                         .on_conflict_do_nothing(index_elements=["chat_id", "user_id"]))
        return {"status": "requested", "chat_id": chat.id}
    if chat.type == "group" and (chat.member_count or 0) >= GROUP_MAX_MEMBERS:
        raise _err(422, f"群已满({GROUP_MAX_MEMBERS} 人)")
    await _upsert_member(db, chat, me.id)
    await _member_changed(db, chat, me.id, "member", {"via_public": True})
    if chat.type == "group":
        await send_service(db, chat, me.id, "member_join", name=display_name(me))
    return {"status": "joined", "chat_id": chat.id}


async def decide_join_request(db: AsyncSession, chat: Chat, actor: User, user_id: int,
                              approve: bool) -> None:
    _, p = await require_member(db, chat, actor.id)
    if not p.invite_users:
        raise _err(403, "你没有处理入群申请的权限")
    req = await db.get(JoinRequest, (chat.id, user_id))
    if req is None:
        raise _err(404, "没有这个申请")
    if approve:
        await sanctions.check_chat(db, chat, actor.id, "join")
    await db.delete(req)
    if approve:
        m = await member_of(db, chat.id, user_id)
        if not is_active(m):
            await _upsert_member(db, chat, user_id, invited_by=actor.id)
            await _member_changed(db, chat, user_id, "member", {"approved_by": actor.id})
            if chat.type == "group":
                u = await db.get(User, user_id)
                await send_service(db, chat, user_id, "member_join",
                                   name=display_name(u) if u else "")
    await append_user_event(db, user_id, "join_decided",
                            {"chat_id": chat.id, "approved": approve})


# ---------------- 消息 ----------------

async def insert_message(db: AsyncSession, chat: Chat, *, sender_id: int | None, kind: str,
                         text: str = "", entities: list | None = None, media: list | None = None,
                         reply_to_seq: int | None = None, forward: dict | None = None,
                         grouped_id: int | None = None, poll_id: int | None = None,
                         extra: dict | None = None, markup: dict | None = None,
                         via_bot_id: int | None = None, silent: bool = False,
                         as_chat: bool = False, random_id: int | None = None) -> ChatMessage:
    """**写消息的唯一入口。** 调用方必须已经用 [lock_chat] 锁住会话行。"""
    seq = (chat.last_seq or 0) + 1
    chat.last_seq = seq
    chat.last_message_at = now_utc()
    msg = ChatMessage(chat_id=chat.id, seq=seq, sender_id=sender_id, kind=kind, text=text,
                      entities=entities or [], media=media or [], reply_to_seq=reply_to_seq,
                      forward=forward, grouped_id=grouped_id, poll_id=poll_id,
                      extra=extra or {}, markup=markup, via_bot_id=via_bot_id, silent=silent,
                      as_chat=as_chat, random_id=random_id, views=0, created_at=now_utc())
    db.add(msg)
    await db.flush()
    # 私聊:第一条消息让会话出现在对方的列表里
    if chat.type == "private":
        await db.execute(update(ChatMember).where(ChatMember.chat_id == chat.id,
                                                  ChatMember.visible.is_(False))
                         .values(visible=True))
    # 自己发的消息自己当然读过了
    if sender_id is not None:
        await db.execute(update(ChatMember).where(
            ChatMember.chat_id == chat.id, ChatMember.user_id == sender_id,
            ChatMember.last_read_seq < seq).values(last_read_seq=seq, last_read_at=now_utc(),
                                                   marked_unread=False))
    await append_chat_event(db, chat.id, "msg", await message_payload(db, chat, msg))
    # 会话里有机器人:按隐私模式的规则给它们各一条 message 更新,和消息同一个事务(#355)
    from .bots import on_message
    await on_message(db, chat, msg)
    return msg


async def send_service(db: AsyncSession, chat: Chat, actor_id: int | None, action: str,
                       **data) -> ChatMessage:
    return await insert_message(db, chat, sender_id=actor_id, kind="service",
                                extra={"service": {"action": action, **data}}, silent=True)


def _parse_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise _err(422, "编号格式不对")


async def _load_media(db: AsyncSession, me: User, ids: list[int], allowed_kinds: tuple) -> list[dict]:
    out = []
    for mid in ids:
        mf = await db.get(MediaFile, mid)
        if mf is None or mf.owner_id != me.id:
            raise _err(404, "附件不存在,或者不是你上传的")
        if mf.status != "ready":
            raise _err(409, "附件还在处理中,稍等一下再发")
        if mf.kind not in allowed_kinds:
            raise _err(422, "附件类型和消息类型对不上")
        out.append(media_json(mf))
    return out


def media_json(mf: MediaFile) -> dict:
    d = {"id": mf.id, "kind": mf.kind, "w": mf.w, "h": mf.h, "size": mf.size, "mime": mf.mime,
         "name": mf.name, "duration_ms": mf.duration_ms, "has_thumb": bool(mf.thumb_key)}
    if not mf.private and mf.key:
        # 贴纸这类公开图:直接给公开地址,客户端不用再去换签名(也能吃到 CDN 长缓存)
        from . import storage
        d["public_url"] = storage.url_for(mf.key, False)
    if mf.waveform:
        d["waveform"] = mf.waveform
    if mf.kind == "gif":
        d["loop"] = True
    return d


#: 同样的文字 24 小时内发给多少个不同的私聊就算群发垃圾(#369)
SPAM_SAME_TEXT_CHATS = 20
SPAM_PAUSE_SECONDS = 3600


async def _spam_guard(user_id: int, chat_id: int, text: str, kind: str) -> None:
    """同一段话 24 小时内发给 20 个以上私聊 → 暂停发私聊 1 小时。

    只看文字消息、只数不同的会话(和同一个人来回聊天不算);短于 8 个字的不管 ——
    「在吗」「好的」谁都会发给很多人。Redis 不可用时放行(和限流一样)。
    """
    from ..redis_client import get_redis
    try:
        r = get_redis()
        if await r.exists(f"chat:spam_pause:{user_id}"):
            ttl = await r.ttl(f"chat:spam_pause:{user_id}")
            raise _err(429, f"同样的内容发给了太多人,{max(1, (ttl + 59) // 60)} 分钟后才能继续发私聊")
        norm = re.sub(r"\s+", " ", text.strip().lower())
        if kind != "text" or len(norm) < 8:
            return
        digest = hashlib.sha1(norm.encode()).hexdigest()[:16]
        key = f"chat:spam:{user_id}:{digest}"
        await r.sadd(key, chat_id)
        await r.expire(key, 86400)
        if await r.scard(key) > SPAM_SAME_TEXT_CHATS:
            await r.set(f"chat:spam_pause:{user_id}", "1", ex=SPAM_PAUSE_SECONDS)
            raise _err(429, "同样的内容发给了太多人,1 小时后才能继续发私聊")
    except HTTPException:
        raise
    except Exception:
        return


async def send(db: AsyncSession, chat: Chat, me: User, body: dict) -> tuple[ChatMessage, bool]:
    """发一条消息。返回 (消息, 是否新建);同一个 random_id 重发返回原来那条(§5.4)。"""
    random_id = _parse_int(body.get("random_id"))
    if random_id is not None:
        dup = await db.scalar(select(ChatMessage).where(
            ChatMessage.chat_id == chat.id, ChatMessage.sender_id == me.id,
            ChatMessage.random_id == random_id))
        if dup is not None:
            return dup, False
    # 平台处罚先于限流判:被禁言的人不该再占着限流的额度,提示也要说清楚是处罚不是太快
    await sanctions.check_user(db, me.id, "message")
    await check_rate_limit_seconds("chat_send", str(me.id), 5)
    await check_rate_limit("chat_send_min", str(me.id), 60)
    chat = await lock_chat(db, chat.id)
    member, p = await require_member(db, chat, me.id)
    # 会话被封:成员不能发言(在判完「你在不在这个会话里」之后,免得外人借此知道这个群被封了)
    await sanctions.check_chat(db, chat, me.id, "speak")
    kind = body.get("kind") or "text"
    to_bot = False
    if chat.type == "private":
        peer = await private_peer_id(db, chat, me.id)
        if peer is not None and await blocked_between(db, me.id, peer):
            raise _err(403, "你们之间有一方把对方拉黑了,消息发不出去")
        peer_user = await db.get(User, peer) if peer is not None else None
        to_bot = peer_user is not None and peer_user.role == UserRole.bot
    as_chat = False
    if chat.type == "channel":
        if not p.send_messages:
            raise _err(403, "只有频道管理员能发帖")
        as_chat = True
    elif body.get("as_chat"):
        if not p.anonymous:
            raise _err(403, "你不能匿名发言")
        as_chat = True
    # 发言权限
    need = {"text": "send_messages", "poll": "send_polls", "sticker": "send_stickers",
            "gif": "send_stickers", "dice": "send_stickers"}.get(kind, "send_media")
    if kind in ("location", "contact", "card"):
        need = "send_messages"
    if not p.send_messages or not getattr(p, need):
        raise _err(403, "你在这个会话里没有发这类消息的权限")
    grouped = _parse_int(body.get("grouped_id"))
    # 同样的话群发给一堆私聊 = 垃圾消息(#369):24 小时内发给 20 个以上私聊就停 1 小时。
    # 发给机器人的不算(#355):给一串机器人发同一句「/start 帮我查一下」骚扰不到任何人
    if chat.type == "private" and not to_bot:
        await _spam_guard(me.id, chat.id, str(body.get("text") or ""), kind)
    # 慢速模式(先于「每秒 1 条」判:它的提示说得清还要等几秒)。
    # 一个相册算一条:同一个 grouped_id 的后几张不再挡
    slow = chat_settings(chat.settings)["slow_mode"] if chat.type == "group" else 0
    if slow and not p.slow_mode_exempt:
        from ..redis_client import get_redis
        key = f"chat:slow:{chat.id}:{me.id}"
        try:
            r = get_redis()
            ttl = await r.ttl(key)
            if ttl and ttl > 0:
                held = await r.get(key)
                held = held.decode() if isinstance(held, bytes) else held
                if grouped is None or held != str(grouped):
                    raise _err(429, f"慢速模式:{ttl} 秒后才能再发")
            else:
                await r.set(key, str(grouped or 0), ex=slow)
        except HTTPException:
            raise
        except Exception:
            pass
    # 同一群每人每秒 1 条(§5.7);相册的几张是一次发出的,不按条算
    if chat.type == "group" and grouped is None:
        await check_rate_limit_seconds(f"chat_send_g{chat.id}", str(me.id), 1)
    text = str(body.get("text") or "")
    media: list[dict] = []
    extra: dict = {}
    poll_id = None
    if kind in MEDIA_KIND_FOR:
        ids = [int(i) for i in body.get("media_ids") or []]
        if len(ids) != 1:
            raise _err(422, "每条媒体消息带且只带一个附件(相册是同一个 grouped_id 的多条)")
        media = await _load_media(db, me, ids, MEDIA_KIND_FOR[kind])
        if len(text) > CAPTION_MAX:
            raise _err(422, f"说明最多 {CAPTION_MAX} 字")
    elif kind == "sticker":
        sid = _parse_int(body.get("sticker_id"))
        st = await db.get(Sticker, sid) if sid else None
        if st is None:
            raise _err(404, "没有这个贴纸")
        mf = await db.get(MediaFile, st.media_id)
        if mf is None:
            raise _err(404, "贴纸图片不见了")
        media = [media_json(mf)]
        extra["sticker"] = {"id": st.id, "set_id": st.set_id, "emoji": st.emoji}
        text = ""
    elif kind == "text":
        if not text.strip():
            raise _err(422, "不能发空消息")
        if len(text) > TEXT_MAX:
            raise _err(422, f"一条消息最多 {TEXT_MAX} 字")
    elif kind == "location":
        loc = body.get("location") or {}
        try:
            lat, lng = float(loc["lat"]), float(loc["lng"])
        except (KeyError, TypeError, ValueError):
            raise _err(422, "位置缺少经纬度")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise _err(422, "经纬度超出范围")
        extra["location"] = {"lat": lat, "lng": lng,
                             "title": str(loc.get("title") or "")[:64],
                             "address": str(loc.get("address") or "")[:128]}
        text = ""
    elif kind == "contact":
        cid = _parse_int((body.get("contact") or {}).get("user_id"))
        cu = await db.get(User, cid) if cid else None
        if cu is None or cu.role not in SOCIAL_ROLES:
            raise _err(404, "没有这个用户")
        cp = await db.get(SocialProfile, cu.id)
        extra["contact"] = {"user_id": cu.id, "name": display_name(cu),
                            "username": cp.username if cp else None}
        text = ""
    elif kind == "dice":
        d = body.get("dice") if isinstance(body.get("dice"), dict) else {}
        emoji = str(d.get("emoji") or "🎲")
        if emoji not in DICE:
            raise _err(422, "不支持这个骰子")
        extra["dice"] = {"emoji": emoji, "value": secrets.randbelow(DICE[emoji]) + 1}
        text = ""
    elif kind == "card":
        # 分享卡片(DEV-PROMPTS-41 §5.9):客户端只给 {type, id},**标题、副标题、封面由服务端查出来存快照**。
        # 不信客户端的两个理由:一是谁都能发一张「超级赞官方」的假卡片;二是对方以后改了标题,
        # 这条消息还应该是当时那句话。看不到的东西(没过审的作品、私密歌单、删了的帖子)直接拒。
        from . import cards
        c = body.get("card") if isinstance(body.get("card"), dict) else {}
        ctype, cid = str(c.get("type") or ""), str(c.get("id") or "")
        if ctype not in cards.known_types():
            raise _err(422, "不支持分享这种内容")
        snap = await cards.resolve(db, ctype, cid, me.id)
        if snap is None:
            raise _err(422, "这个内容现在分享不了(可能已经删了、还没过审或者不公开)")
        extra["card"] = {"type": ctype, "id": cid, **snap}
        text = ""
    elif kind == "poll":
        poll_id = await _create_poll(db, chat, me, body.get("poll") or {})
        text = ""
    else:
        raise _err(422, f"不支持的消息类型:{kind}")
    # 屏蔽词(#369):文字和说明都过一遍;命中就不发,告诉他为什么
    if text:
        await guard_text(db, text, "消息")
    # 实体
    try:
        ents = validate_entities(text, body.get("entities"))
    except EntityError as e:
        raise _err(422, str(e))
    ents = ents + auto_entities(text, ents)
    ents.sort(key=lambda e: (e["offset"], -e["length"]))
    if chat.type == "channel" and chat_settings(chat.settings)["signatures"]:
        extra["signature"] = display_name(me)
    reply_to = _parse_int(body.get("reply_to_seq"))
    if reply_to is not None:
        floor = visible_floor(chat, member)
        target = await db.scalar(select(ChatMessage.seq).where(
            ChatMessage.chat_id == chat.id, ChatMessage.seq == reply_to,
            ChatMessage.seq > floor, ChatMessage.deleted_at.is_(None)))
        if target is None:
            reply_to = None     # 被回复的那条已经删了:照发,只是不带引用(和 TG 一样)
    msg = await insert_message(
        db, chat, sender_id=me.id, kind=kind, text=text, entities=ents, media=media,
        reply_to_seq=reply_to, grouped_id=grouped, poll_id=poll_id, extra=extra,
        silent=bool(body.get("silent")), as_chat=as_chat, random_id=random_id)
    if poll_id:
        await db.execute(update(Poll).where(Poll.id == poll_id).values(chat_id=chat.id))
    await _record_mentions(db, chat, msg, ents, text)
    await _after_send(db, chat, msg, no_preview=bool(body.get("no_preview")) or not p.embed_links)
    return msg, True


async def _record_mentions(db: AsyncSession, chat: Chat, msg: ChatMessage, ents: list,
                           text: str) -> set[int]:
    """群里被 @ 的人记一行(未读 @ 计数、免打扰也照样推)。

    @超级赞号 在这里**不看**「按超级赞号找到我」开关,和视频评论(video_talk._resolve_mentions)不一样:
    这里只在这个群现在的成员里找,@ 一个群外的号什么都不发生,和没有这个号一样;群成员在成员列表里
    本来就看得到彼此的号,算不上「按号找到他」。而且客户端从成员列表里点人时,对方有号就插入 `@号`
    (没有号才用带 user_id 的 text_mention),这里跟着开关走的话,点选一个关了开关的成员他就收不到 @ 了。
    消息里的 @号 点开走 /social/v1/resolve,那边照开关回 404。私聊、频道不记。
    """
    ids = set(mentioned_user_ids(ents))
    names = mentioned_usernames(text, ents)
    if names:
        rows = await db.scalars(select(Username.owner_id).where(
            Username.owner_type == "user", Username.username_lc.in_(names)))
        ids |= set(rows)
    if msg.reply_to_seq:
        replied = await db.scalar(select(ChatMessage.sender_id).where(
            ChatMessage.chat_id == chat.id, ChatMessage.seq == msg.reply_to_seq))
        if replied:
            ids.add(replied)
    ids.discard(msg.sender_id or 0)
    if not ids or chat.type in ("private", "saved", "channel"):
        return set()
    members = set(await db.scalars(select(ChatMember.user_id).where(
        ChatMember.chat_id == chat.id, ChatMember.user_id.in_(ids),
        ChatMember.role.in_(ACTIVE_ROLES))))
    for uid in members:
        db.add(MessageMention(chat_id=chat.id, seq=msg.seq, user_id=uid))
    await db.flush()
    return members


async def _after_send(db: AsyncSession, chat: Chat, msg: ChatMessage, *, no_preview: bool) -> None:
    """提交之后:推送、链接预览。都不能拖慢发送本身。"""
    chat_id, seq = chat.id, msg.seq
    after_commit(db, lambda: _push_later(chat_id, seq))
    if msg.kind == "text" and not no_preview and urls(msg.text, msg.entities or []):
        after_commit(db, lambda: _preview_later(chat_id, seq))


async def _push_later(chat_id: int, seq: int) -> None:
    from .chat_push import notify_message
    await notify_message(chat_id, seq)


async def _preview_later(chat_id: int, seq: int) -> None:
    from .link_preview import attach_preview
    await attach_preview(chat_id, seq)


async def _create_poll(db: AsyncSession, chat: Chat, me: User, body: dict) -> int:
    q = str(body.get("question") or "").strip()
    opts = [str(o).strip() for o in body.get("options") or [] if str(o).strip()]
    if not 1 <= len(q) <= 255:
        raise _err(422, "问题 1–255 个字")
    if not 2 <= len(opts) <= 10 or any(len(o) > 100 for o in opts):
        raise _err(422, "选项 2–10 个,每个最多 100 字")
    if len(set(opts)) != len(opts):
        raise _err(422, "选项不能重复")
    await guard_text(db, "\n".join([q, *opts, str(body.get("explanation") or "")]), "投票")
    quiz = bool(body.get("quiz"))
    correct = body.get("correct")
    if quiz and (not isinstance(correct, int) or not 0 <= correct < len(opts)):
        raise _err(422, "测验要指定正确答案")
    multiple = bool(body.get("multiple")) and not quiz
    close_at = None
    if body.get("close_period"):
        secs = int(body["close_period"])
        if not 5 <= secs <= 600 * 60 * 24:
            raise _err(422, "截止时间 5 秒到 10 天之间")
        close_at = now_utc() + timedelta(seconds=secs)
    poll = Poll(chat_id=chat.id, creator_id=me.id, question=q, options=[{"text": o} for o in opts],
                multiple=multiple, quiz=quiz, correct=correct if quiz else None,
                explanation=str(body.get("explanation") or "")[:200] if quiz else "",
                anonymous=body.get("anonymous", True) is not False, closed=False,
                close_at=close_at)
    db.add(poll)
    await db.flush()
    return poll.id


async def _message(db: AsyncSession, chat: Chat, seq: int, member: ChatMember | None,
                   *, lock: bool = False) -> ChatMessage:
    q = select(ChatMessage).where(ChatMessage.chat_id == chat.id, ChatMessage.seq == seq,
                                  ChatMessage.deleted_at.is_(None))
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    m = await db.scalar(q)
    if m is None or (member is not None and seq <= visible_floor(chat, member)):
        raise _err(404, "消息不存在或已删除")
    return m


async def edit(db: AsyncSession, chat: Chat, me: User, seq: int, text: str,
               entities: list | None) -> ChatMessage:
    member, p = await require_member(db, chat, me.id)
    # 改消息等于重新说一遍:禁言、封号、会话被封时一样挡
    await sanctions.check_user(db, me.id, "message")
    await sanctions.check_chat(db, chat, me.id, "speak")
    msg = await _message(db, chat, seq, member, lock=True)
    mine = msg.sender_id == me.id
    age = (now_utc() - msg.created_at).total_seconds() / 3600 if msg.created_at else 0
    if not can_edit_message(chat.type, p, mine=mine, age_hours=age, kind=msg.kind):
        raise _err(403, "这条消息不能改了(只能改自己 48 小时内发的文字和说明)")
    if msg.kind == "text" and not text.strip():
        raise _err(422, "不能改成空消息;要删除请用删除")
    limit = TEXT_MAX if msg.kind == "text" else CAPTION_MAX
    if len(text) > limit:
        raise _err(422, f"最多 {limit} 字")
    if text:
        await guard_text(db, text, "消息")
    try:
        ents = validate_entities(text, entities)
    except EntityError as e:
        raise _err(422, str(e))
    ents = ents + auto_entities(text, ents)
    ents.sort(key=lambda e: (e["offset"], -e["length"]))
    if text == msg.text and ents == (msg.entities or []):
        return msg
    msg.text = text
    msg.entities = ents
    msg.edited_at = now_utc()
    extra = dict(msg.extra or {})
    extra.pop("preview", None)
    msg.extra = extra
    await db.flush()
    await append_chat_event(db, chat.id, "edit", await message_payload(db, chat, msg))
    from .bots import on_edit
    await on_edit(db, chat, msg)
    return msg


def _wipe(msg: ChatMessage) -> None:
    msg.deleted_at = now_utc()
    msg.text = ""
    msg.entities = []
    msg.media = []
    msg.extra = {}
    msg.markup = None
    msg.forward = None
    msg.pinned_at = None


async def delete_messages(db: AsyncSession, chat: Chat, me: User, seqs: list[int],
                          revoke: bool) -> list[int]:
    """revoke=True 为双方 / 所有人删除(正文和媒体清空、seq 占位);False 只为自己删除。"""
    member, p = await require_member(db, chat, me.id)
    seqs = sorted({int(s) for s in seqs})[:FORWARD_MAX]
    if not seqs:
        return []
    if chat.type == "saved":
        revoke = True
    if not revoke:
        for s in seqs:
            await db.execute(insert(MessageHide).values(chat_id=chat.id, seq=s, user_id=me.id)
                             .on_conflict_do_nothing())
        await append_user_event(db, me.id, "hide", {"chat_id": chat.id, "seqs": seqs})
        return seqs
    msgs = list(await db.scalars(select(ChatMessage).where(
        ChatMessage.chat_id == chat.id, ChatMessage.seq.in_(seqs),
        ChatMessage.deleted_at.is_(None)).with_for_update()
        .execution_options(populate_existing=True)))
    done = []
    for m in msgs:
        if m.kind == "service" and not p.delete_others and chat.type != "private":
            continue
        if not can_delete_for_all(chat.type, p, mine=m.sender_id == me.id):
            raise _err(403, "你只能为所有人删除自己发的消息")
        _wipe(m)
        done.append(m.seq)
    if done:
        await db.execute(delete(MessageReaction).where(MessageReaction.chat_id == chat.id,
                                                       MessageReaction.seq.in_(done)))
        await db.execute(delete(MessageMention).where(MessageMention.chat_id == chat.id,
                                                      MessageMention.seq.in_(done)))
        await append_chat_event(db, chat.id, "del", {"seqs": done, "by": me.id})
    return done


async def wipe_as_platform(db: AsyncSession, chat: Chat, seqs: list[int]) -> list[tuple[int, int | None, bool]]:
    """平台处置举报时删消息(#368):和「为所有人删除」同一个效果(正文、媒体清空,seq 占位,
    发 del 事件),但不看会话里的权限。调用方必须已经锁住会话行。

    返回真删掉的 [(seq, 发送人, 是不是以会话名义发的)] —— 处罚记在发送人头上。
    删除事件里不带是谁删的(`by` 为空):群里的人只需要知道「这条没了」。
    """
    seqs = sorted({int(s) for s in seqs})[:FORWARD_MAX]
    if not seqs:
        return []
    msgs = list(await db.scalars(select(ChatMessage).where(
        ChatMessage.chat_id == chat.id, ChatMessage.seq.in_(seqs),
        ChatMessage.deleted_at.is_(None), ChatMessage.kind != "service")
        .with_for_update().execution_options(populate_existing=True)))
    done = [(m.seq, m.sender_id, bool(m.as_chat)) for m in msgs]
    for m in msgs:
        _wipe(m)
    if done:
        gone = [s for s, _, _ in done]
        await db.execute(delete(MessageReaction).where(MessageReaction.chat_id == chat.id,
                                                       MessageReaction.seq.in_(gone)))
        await db.execute(delete(MessageMention).where(MessageMention.chat_id == chat.id,
                                                      MessageMention.seq.in_(gone)))
        await append_chat_event(db, chat.id, "del", {"seqs": gone, "by": None,
                                                     "by_platform": True})
    return done


async def clear_history(db: AsyncSession, chat: Chat, me: User, revoke: bool) -> None:
    member, p = await require_member(db, chat, me.id)
    if revoke and chat.type == "private":
        await db.execute(update(ChatMessage).where(
            ChatMessage.chat_id == chat.id, ChatMessage.deleted_at.is_(None))
            .values(deleted_at=now_utc(), text="", entities=[], media=[], extra={},
                    markup=None, forward=None, pinned_at=None))
        await db.execute(delete(MessageReaction).where(MessageReaction.chat_id == chat.id))
        await append_chat_event(db, chat.id, "clear", {"upto": chat.last_seq, "by": me.id})
        return
    member.cleared_seq = chat.last_seq
    member.last_read_seq = max(member.last_read_seq, chat.last_seq)
    await append_user_event(db, me.id, "dialog", {"chat_id": chat.id,
                                                  "cleared_seq": member.cleared_seq,
                                                  "last_read_seq": member.last_read_seq})


async def react(db: AsyncSession, chat: Chat, me: User, seq: int, emoji: str, add: bool) -> list:
    member, p = await require_member(db, chat, me.id)
    await check_rate_limit_seconds("chat_react", str(me.id), 5)
    msg = await _message(db, chat, seq, member)
    if msg.kind == "service":
        raise _err(422, "服务消息不能回应")
    if add:
        if not reaction_allowed(chat.settings, emoji):
            raise _err(422, "这个会话不能用这个表情回应")
        mine = list(await db.scalars(select(MessageReaction.emoji).where(
            MessageReaction.chat_id == chat.id, MessageReaction.seq == seq,
            MessageReaction.user_id == me.id)))
        if emoji not in mine and len(mine) >= 3:
            raise _err(422, "每条消息最多回应 3 个表情")
        await db.execute(insert(MessageReaction).values(
            chat_id=chat.id, seq=seq, user_id=me.id, emoji=emoji).on_conflict_do_nothing())
    else:
        await db.execute(delete(MessageReaction).where(
            MessageReaction.chat_id == chat.id, MessageReaction.seq == seq,
            MessageReaction.user_id == me.id, MessageReaction.emoji == emoji))
    rows = (await db.execute(select(MessageReaction.emoji, func.count()).where(
        MessageReaction.chat_id == chat.id, MessageReaction.seq == seq)
        .group_by(MessageReaction.emoji).order_by(func.count().desc()))).all()
    reactions = [{"emoji": e, "count": n} for e, n in rows]
    await append_chat_event(db, chat.id, "react", {"seq": seq, "reactions": reactions,
                                                   "actor": me.id, "emoji": emoji,
                                                   "added": add})
    return reactions


async def read(db: AsyncSession, chat: Chat, me: User, seq: int) -> ChatMember:
    member, _ = await require_member(db, chat, me.id)
    seq = min(int(seq), chat.last_seq)
    changed = False
    if seq > member.last_read_seq:
        member.last_read_seq = seq
        member.last_read_at = now_utc()
        changed = True
    if member.marked_unread:
        member.marked_unread = False
        changed = True
    if not changed:
        return member
    # 私聊和 ≤100 人的群广播「谁读到哪」(双勾、已读名单);大群和频道不广播
    if chat.type == "private" or (chat.type == "group"
                                  and (chat.member_count or 0) <= GROUP_READ_RECEIPTS_MAX):
        await append_chat_event(db, chat.id, "read", {"user_id": me.id,
                                                      "seq": member.last_read_seq})
    await append_user_event(db, me.id, "dialog", {"chat_id": chat.id,
                                                  "last_read_seq": member.last_read_seq,
                                                  "marked_unread": False})
    return member


async def readers(db: AsyncSession, chat: Chat, me: User, seq: int) -> list[dict]:
    """≤100 人的群里,自己这条消息 7 天内谁读了(按读的时间倒序)。"""
    member, _ = await require_member(db, chat, me.id)
    if chat.type != "group" or (chat.member_count or 0) > 100:
        raise _err(422, "只有 100 人以内的群能看已读名单")
    msg = await _message(db, chat, seq, member)
    if msg.sender_id != me.id:
        raise _err(403, "只能看自己发的消息谁读了")
    if msg.created_at and now_utc() - msg.created_at > timedelta(days=7):
        return []
    rows = (await db.execute(select(ChatMember.user_id, ChatMember.last_read_at).where(
        ChatMember.chat_id == chat.id, ChatMember.user_id != me.id,
        ChatMember.role.in_(ACTIVE_ROLES), ChatMember.last_read_seq >= seq)
        .order_by(ChatMember.last_read_at.desc()))).all()
    return [{"user_id": u, "read_at": t.isoformat() if t else None} for u, t in rows]


async def pin(db: AsyncSession, chat: Chat, me: User, seq: int | None, pinned: bool,
              notify: bool = True) -> list[int]:
    """置顶 / 取消置顶。seq 为空且 pinned=False = 全部取消。"""
    member, p = await require_member(db, chat, me.id)
    if not p.pin_messages:
        raise _err(403, "你没有置顶消息的权限")
    chat = await lock_chat(db, chat.id)
    if seq is None:
        if pinned:
            raise _err(422, "要置顶哪一条?")
        seqs = list(await db.scalars(select(ChatMessage.seq).where(
            ChatMessage.chat_id == chat.id, ChatMessage.pinned_at.is_not(None))))
        await db.execute(update(ChatMessage).where(ChatMessage.chat_id == chat.id)
                         .values(pinned_at=None))
    else:
        msg = await _message(db, chat, seq, member)
        if msg.kind == "service":
            raise _err(422, "服务消息不能置顶")
        msg.pinned_at = now_utc() if pinned else None
        seqs = [seq]
        if pinned and notify:
            await send_service(db, chat, me.id, "pin", seq=seq,
                               preview=mask_spoilers(msg.text or "", msg.entities)[:40])
    await append_chat_event(db, chat.id, "pin", {"seqs": seqs, "pinned": pinned})
    return seqs


async def forward(db: AsyncSession, me: User, from_chat: Chat, seqs: list[int],
                  to_chat_ids: list[int], hide_sender: bool = False) -> list[tuple[int, int]]:
    """转发:在目标会话里各发一份,带「转发自」;媒体引用同一个文件,不复制。"""
    from .chat_view import can_read_chat

    ok, src_member = await can_read_chat(db, from_chat, me.id)
    if not ok:
        raise _err(403, "你看不到这些消息")
    # 转发 = 在目标会话里发消息(目标会话被封的,在 _forward_one 里挡)
    await sanctions.check_user(db, me.id, "message")
    if chat_settings(from_chat.settings)["protected"]:
        raise _err(403, "这个会话禁止转发")
    seqs = sorted({int(s) for s in seqs})
    if not seqs or len(seqs) > FORWARD_MAX:
        raise _err(422, f"一次最多转发 {FORWARD_MAX} 条")
    targets = list(dict.fromkeys(int(t) for t in to_chat_ids))
    if not targets or len(targets) > FORWARD_TARGETS_MAX:
        raise _err(422, f"一次最多转到 {FORWARD_TARGETS_MAX} 个会话")
    floor = visible_floor(from_chat, src_member) if src_member else 0
    srcs = list(await db.scalars(select(ChatMessage).where(
        ChatMessage.chat_id == from_chat.id, ChatMessage.seq.in_(seqs),
        ChatMessage.seq > floor, ChatMessage.deleted_at.is_(None),
        ChatMessage.kind != "service").order_by(ChatMessage.seq)))
    if not srcs:
        raise _err(404, "要转发的消息不存在")
    sent: list[tuple[int, int]] = []
    group_map: dict[int, int] = {}
    for tid in targets:
        target = await db.get(Chat, tid)
        if target is None or target.deleted_at is not None:
            raise _err(404, "目标会话不存在")
        group_map.clear()  # 同一个相册在每个目标会话里各是一个新相册
        for src in srcs:
            fwd = await _forward_info(db, me, from_chat, src, hide_sender)
            gid = None
            if src.grouped_id:
                gid = group_map.setdefault(src.grouped_id, random.getrandbits(62))
            msg = await _forward_one(db, target, me, src, fwd, gid)
            sent.append((tid, msg.seq))
    return sent


async def _forward_info(db: AsyncSession, me: User, chat: Chat, src: ChatMessage,
                        hide_sender: bool) -> dict:
    if src.forward:        # 转发的转发:保留最初的来源
        return dict(src.forward)
    date = src.created_at.isoformat() if src.created_at else now_utc().isoformat()
    if src.as_chat or chat.type == "channel":
        return {"from_chat": {"id": chat.id, "title": chat.title, "username": chat.username},
                "orig_seq": src.seq if chat.username else None, "date": date}
    u = await db.get(User, src.sender_id) if src.sender_id else None
    if u is None:
        return {"hidden_name": "已注销的用户", "date": date}
    prof = await db.get(SocialProfile, u.id)
    # 原发送人的隐私「转发时附带我的链接」不允许时,只留名字不留链接(和 TG 一样)
    link_ok = await allowed(db, prof, u.id, me.id, "forwards") and not hide_sender
    if hide_sender:
        return {"hidden_name": "", "date": date, "hidden": True}
    if not link_ok:
        return {"hidden_name": display_name(u), "date": date}
    return {"from_user": {"id": u.id, "name": display_name(u)}, "date": date}


async def _forward_one(db: AsyncSession, target: Chat, me: User, src: ChatMessage,
                       fwd: dict, grouped_id: int | None) -> ChatMessage:
    target = await lock_chat(db, target.id)
    member, p = await require_member(db, target, me.id)
    await sanctions.check_chat(db, target, me.id, "speak")
    if target.type == "private":
        peer = await private_peer_id(db, target, me.id)
        if peer is not None and await blocked_between(db, me.id, peer):
            raise _err(403, "你们之间有一方把对方拉黑了,消息发不出去")
    as_chat = False
    if target.type == "channel":
        if not p.send_messages:
            raise _err(403, "只有频道管理员能发帖")
        as_chat = True
    elif not p.send_messages:
        raise _err(403, "你在这个会话里不能发言")
    extra = {k: v for k, v in (src.extra or {}).items()
             if k in ("location", "contact", "dice", "sticker", "preview", "card")}
    poll_id = None
    if src.poll_id:
        # 转发投票:目标会话里是一份新的投票,题目和选项照抄
        old = await db.get(Poll, src.poll_id)
        if old is not None:
            np = Poll(chat_id=target.id, creator_id=me.id, question=old.question,
                      options=old.options, multiple=old.multiple, quiz=old.quiz,
                      correct=old.correct, explanation=old.explanation,
                      anonymous=old.anonymous, closed=False)
            db.add(np)
            await db.flush()
            poll_id = np.id
    return await insert_message(db, target, sender_id=me.id, kind=src.kind, text=src.text,
                                entities=src.entities, media=src.media, forward=fwd,
                                grouped_id=grouped_id, poll_id=poll_id, extra=extra,
                                as_chat=as_chat)


async def vote(db: AsyncSession, chat: Chat, me: User, seq: int, options: list[int]) -> dict:
    member, _ = await require_member(db, chat, me.id)
    msg = await _message(db, chat, seq, member)
    if not msg.poll_id:
        raise _err(422, "这条不是投票")
    poll = await db.scalar(select(Poll).where(Poll.id == msg.poll_id).with_for_update()
                           .execution_options(populate_existing=True))
    if poll is None:
        raise _err(404, "投票不存在")
    if poll.closed or (poll.close_at is not None and poll.close_at <= now_utc()):
        raise _err(409, "投票已经结束了")
    opts = sorted({int(o) for o in options})
    existing = await db.get(PollVote, (poll.id, me.id))
    if not opts:
        if poll.quiz:
            raise _err(422, "测验投了就不能撤回")
        if existing is not None:
            await db.delete(existing)
    else:
        if any(not 0 <= o < len(poll.options) for o in opts):
            raise _err(422, "没有这个选项")
        if len(opts) > 1 and not poll.multiple:
            raise _err(422, "这个投票只能选一项")
        if existing is not None and poll.quiz:
            raise _err(409, "测验只能答一次")
        if existing is None:
            db.add(PollVote(poll_id=poll.id, user_id=me.id, options=opts))
        else:
            existing.options = opts
    await db.flush()
    results = await poll_results_public(db, poll)
    await append_chat_event(db, chat.id, "poll", {"seq": seq, "poll": results})
    return results


async def close_poll(db: AsyncSession, chat: Chat, me: User, seq: int) -> dict:
    member, p = await require_member(db, chat, me.id)
    msg = await _message(db, chat, seq, member)
    poll = await db.get(Poll, msg.poll_id) if msg.poll_id else None
    if poll is None:
        raise _err(422, "这条不是投票")
    if poll.creator_id != me.id and not p.delete_others:
        raise _err(403, "只有发起人或管理员能结束投票")
    poll.closed = True
    await db.flush()
    results = await poll_results_public(db, poll)
    await append_chat_event(db, chat.id, "poll", {"seq": seq, "poll": results})
    return results


# ---------------- 我这边的会话状态 ----------------

async def update_dialog(db: AsyncSession, chat: Chat, me: User, patch: dict) -> ChatMember:
    member, _ = await require_member(db, chat, me.id)
    out: dict = {"chat_id": chat.id}
    if "pinned" in patch and patch["pinned"] is not None:
        if patch["pinned"]:
            if member.pinned_rank is None:
                n = await db.scalar(select(func.count()).select_from(ChatMember).where(
                    ChatMember.user_id == me.id, ChatMember.pinned_rank.is_not(None),
                    ChatMember.archived.is_(False)))
                if (n or 0) >= PINNED_DIALOGS_MAX and not member.archived:
                    raise _err(422, f"最多置顶 {PINNED_DIALOGS_MAX} 个会话,先取消一个")
                top = await db.scalar(select(func.min(ChatMember.pinned_rank)).where(
                    ChatMember.user_id == me.id))
                member.pinned_rank = (top or 1) - 1
        else:
            member.pinned_rank = None
        out["pinned"] = member.pinned_rank is not None
        out["pinned_rank"] = member.pinned_rank
    if "archived" in patch and patch["archived"] is not None:
        member.archived = bool(patch["archived"])
        if member.archived:
            member.pinned_rank = None
            out["pinned"] = False
        out["archived"] = member.archived
    if "muted_until" in patch:
        v = patch["muted_until"]
        if v in (None, "", 0):
            member.muted_until = None
        elif v == "forever":
            member.muted_until = datetime(2100, 1, 1, tzinfo=timezone.utc)
        else:
            try:
                secs = int(v)
            except (TypeError, ValueError):
                raise _err(422, "免打扰时长不对")
            member.muted_until = now_utc() + timedelta(seconds=secs)
        out["muted_until"] = member.muted_until.isoformat() if member.muted_until else None
    if "marked_unread" in patch and patch["marked_unread"] is not None:
        member.marked_unread = bool(patch["marked_unread"])
        out["marked_unread"] = member.marked_unread
    if "draft" in patch:
        d = patch["draft"]
        if d and (d.get("text") or "").strip():
            member.draft = {"text": str(d.get("text"))[:TEXT_MAX],
                            "entities": d.get("entities") or [],
                            "reply_to_seq": d.get("reply_to_seq"),
                            "updated_at": now_utc().isoformat()}
        else:
            member.draft = None
        out["draft"] = member.draft
    await db.flush()
    await append_user_event(db, me.id, "dialog", out)
    return member


# ---------------- 机器人(#355)----------------
#
# 机器人经 Bot API 发、改、删消息走下面三个函数。「能不能往这个会话发」(和它说过话没有、被拉黑没有、
# 是不是群成员)调用方已经用 services/bots.resolve_target 判过;这里是写消息这一层的兜底和规则。
#
# 和 [send] 分开写:真人那套「每人每秒 5 条」「新号限制」「同样的话群发判垃圾」「慢速模式」不适用于
# 机器人(它有自己的限流,见 services/bots.check_send_rate),成员资格、群权限、屏蔽词、实体校验一样不少。
# 只有 Bot API 调它们,所以错误文案照 Telegram 的写法(「Bad Request: …」「Forbidden: …」)。

async def send_as_bot(db: AsyncSession, chat: Chat, bot: User, *, kind: str, text: str = "",
                      entities: list | None = None, media: list | None = None,
                      reply_to_seq: int | None = None, markup: dict | None = None,
                      silent: bool = False) -> ChatMessage:
    chat = await lock_chat(db, chat.id)
    member, p = await require_member(db, chat, bot.id)
    as_chat = False
    if chat.type == "channel":
        if not p.send_messages:
            raise _err(403, "Forbidden: need administrator rights in the channel chat")
        as_chat = True
    elif chat.type == "private":
        peer = await private_peer_id(db, chat, bot.id)
        if peer is not None and await blocked_between(db, bot.id, peer):
            raise _err(403, "Forbidden: bot was blocked by the user")
    need = "send_messages" if kind == "text" else "send_media"
    if not p.send_messages or not getattr(p, need):
        what = "text messages" if kind == "text" else "media messages"
        raise _err(403, f"Forbidden: not enough rights to send {what} to the chat")
    if kind == "text" and not text.strip():
        raise _err(400, "Bad Request: message text is empty")
    if kind == "text" and len(text) > TEXT_MAX:
        raise _err(400, "Bad Request: message is too long")
    if kind != "text" and len(text) > CAPTION_MAX:
        raise _err(400, "Bad Request: message caption is too long")
    if text:
        await guard_text(db, text, "消息")
    try:
        ents = validate_entities(text, entities)
    except EntityError as e:
        raise _err(400, f"Bad Request: can't parse entities: {e}")
    ents = ents + auto_entities(text, ents)
    ents.sort(key=lambda e: (e["offset"], -e["length"]))
    extra: dict = {}
    if chat.type == "channel" and chat_settings(chat.settings)["signatures"]:
        extra["signature"] = display_name(bot)
    if reply_to_seq is not None:
        floor = visible_floor(chat, member)
        target = await db.scalar(select(ChatMessage.seq).where(
            ChatMessage.chat_id == chat.id, ChatMessage.seq == reply_to_seq,
            ChatMessage.seq > floor, ChatMessage.deleted_at.is_(None)))
        if target is None:
            reply_to_seq = None     # 和真人一样:被回复的那条没了就不带引用,照发
    msg = await insert_message(db, chat, sender_id=bot.id, kind=kind, text=text, entities=ents,
                               media=media or [], reply_to_seq=reply_to_seq, extra=extra,
                               markup=markup, silent=silent, as_chat=as_chat)
    await _record_mentions(db, chat, msg, ents, text)
    await _after_send(db, chat, msg, no_preview=not p.embed_links)
    return msg


_NOT_MODIFIED = ("Bad Request: message is not modified: specified new message content and "
                 "reply markup are exactly the same as a current content and reply markup of "
                 "the message")


async def edit_as_bot(db: AsyncSession, chat: Chat, bot: User, seq: int, *, text: str | None,
                      entities: list | None, markup: dict | None) -> ChatMessage:
    """改机器人自己发的消息:text 为 None 时只换键盘(editMessageReplyMarkup)。

    markup 就是改完之后的键盘,None = 去掉键盘(Telegram 的 editMessageText 不带 reply_markup 也会去掉)。
    机器人改自己的消息不受 48 小时限制(和 Telegram 一样:按钮点下去之后改那条消息是机器人最常见的用法)。
    只换键盘不算「已编辑」(不设 edited_at),但照样发 edit 事件让客户端换键盘。
    """
    await require_member(db, chat, bot.id)
    msg = await db.scalar(select(ChatMessage).where(
        ChatMessage.chat_id == chat.id, ChatMessage.seq == seq,
        ChatMessage.deleted_at.is_(None)).with_for_update()
        .execution_options(populate_existing=True))
    if msg is None:
        raise _err(400, "Bad Request: message to edit not found")
    if msg.sender_id != bot.id:
        raise _err(400, "Bad Request: message can't be edited")
    changed = False
    if text is not None:
        if msg.kind != "text":
            raise _err(400, "Bad Request: there is no text in the message to edit")
        if not text.strip():
            raise _err(400, "Bad Request: message text is empty")
        if len(text) > TEXT_MAX:
            raise _err(400, "Bad Request: message is too long")
        await guard_text(db, text, "消息")
        try:
            ents = validate_entities(text, entities)
        except EntityError as e:
            raise _err(400, f"Bad Request: can't parse entities: {e}")
        ents = ents + auto_entities(text, ents)
        ents.sort(key=lambda e: (e["offset"], -e["length"]))
        if text != msg.text or ents != (msg.entities or []):
            msg.text = text
            msg.entities = ents
            msg.edited_at = now_utc()
            extra = dict(msg.extra or {})
            extra.pop("preview", None)
            msg.extra = extra
            changed = True
    if (markup or None) != (msg.markup or None):
        msg.markup = markup
        changed = True
    if not changed:
        raise _err(400, _NOT_MODIFIED)
    await db.flush()
    await append_chat_event(db, chat.id, "edit", await message_payload(db, chat, msg))
    return msg


async def delete_as_bot(db: AsyncSession, chat: Chat, bot: User, seq: int) -> None:
    """机器人删自己发的消息(为所有人删除:正文和媒体清空、seq 占位)。别人的一律不许删。"""
    await require_member(db, chat, bot.id)
    msg = await db.scalar(select(ChatMessage).where(
        ChatMessage.chat_id == chat.id, ChatMessage.seq == seq,
        ChatMessage.deleted_at.is_(None)).with_for_update()
        .execution_options(populate_existing=True))
    if msg is None:
        raise _err(400, "Bad Request: message to delete not found")
    if msg.sender_id != bot.id:
        raise _err(400, "Bad Request: message can't be deleted")
    _wipe(msg)
    await db.execute(delete(MessageReaction).where(MessageReaction.chat_id == chat.id,
                                                   MessageReaction.seq == seq))
    await db.execute(delete(MessageMention).where(MessageMention.chat_id == chat.id,
                                                  MessageMention.seq == seq))
    await append_chat_event(db, chat.id, "del", {"seqs": [seq], "by": bot.id})
