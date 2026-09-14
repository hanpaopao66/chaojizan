"""注销账号时消息这一半的清理(DEV-PROMPTS-40 S5「注销账号级联删除消息正文、媒体」)。

视频那一半在 services/video.purge_user,两边都由 routers/auth.delete_account 调,调用方负责提交。

口径:
- **他发的消息**:正文、实体、媒体、附加信息清空,打删除标记 —— 和「为所有人删除」完全一样,
  seq 占位留着(S10:不能有空洞);每个会话登记一条 del 事件,在线的人当场看到消失。
  频道帖子(as_chat)不动:那是频道的内容,不是这个人的;服务消息、通话记录只有「谁、什么时候」,也不动;
- **他的媒体**(聊天、贴纸、头像):库里的行删掉、对象存储里的文件提交后删 —— 下载地址当场 404;
- 他建的贴纸包删掉;他的回应、投票、@ 记录、隐藏记录、草稿、分组、定时消息、入群申请删掉;
- 群主 / 频道主注销:交给资历最老的管理员,没有管理员给最早进来的成员,一个人都不剩就解散;
  其他群 / 频道里是正常的「退出」;
- 收藏夹整个删;私聊留着(对面那一方的会话还在,只是对面显示「已注销用户」、他说过的话没了);
- @超级赞号释放(顾客账号的号冷冻 180 天,和换号一样,见 services/social.release_user_username),
  签名、隐私、通知设置清空;联系人、拉黑两个方向都删。
"""
from collections import defaultdict

from sqlalchemy import case, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (ACTIVE_ROLES, Chat, ChatFolder, ChatMember, ChatMessage, InviteLink,
                      JoinRequest, MediaFile, MessageHide, MessageMention, MessageReaction,
                      Poll, PollVote, ScheduledMessage, SocialBlock, SocialContact,
                      SocialProfile, StickerSet, User, UserEvent, UserRole, UserStickerSet,
                      Username)
from .chat_view import now_utc
from .rt_events import append_chat_event, append_user_event
from .social import release_user_username
from .video import _media_objects, remove_objects_after_commit

#: 一条 del 事件里最多带多少个 seq(事件太大客户端解析、推送都吃力)
DEL_EVENT_CHUNK = 500
#: 不清的消息种类:只有「谁、什么时候」,没有这个人写的内容
KEEP_KINDS = ("service", "call")


async def purge_user(db: AsyncSession, user_id: int) -> dict:
    """返回清掉了多少,给日志用。"""
    now = now_utc()
    out = {"messages": 0, "media": 0, "chats_left": 0, "chats_handed_over": 0, "chats_deleted": 0}

    # ---- 他发的消息 ----
    rows = (await db.execute(select(ChatMessage.chat_id, ChatMessage.seq).where(
        ChatMessage.sender_id == user_id, ChatMessage.deleted_at.is_(None),
        ChatMessage.as_chat.is_(False), ChatMessage.kind.notin_(KEEP_KINDS)))).all()
    by_chat: dict[int, list[int]] = defaultdict(list)
    for chat_id, seq in rows:
        by_chat[chat_id].append(seq)
    if rows:
        await db.execute(update(ChatMessage).where(
            ChatMessage.sender_id == user_id, ChatMessage.deleted_at.is_(None),
            ChatMessage.as_chat.is_(False), ChatMessage.kind.notin_(KEEP_KINDS))
            .values(deleted_at=now, text="", entities=[], media=[], extra={}, markup=None,
                    forward=None, pinned_at=None, poll_id=None)
            .execution_options(synchronize_session=False))
        for chat_id, seqs in by_chat.items():
            seqs.sort()
            await db.execute(delete(MessageReaction).where(MessageReaction.chat_id == chat_id,
                                                           MessageReaction.seq.in_(seqs)))
            await db.execute(delete(MessageMention).where(MessageMention.chat_id == chat_id,
                                                          MessageMention.seq.in_(seqs)))
            for i in range(0, len(seqs), DEL_EVENT_CHUNK):
                await append_chat_event(db, chat_id, "del",
                                        {"seqs": seqs[i:i + DEL_EVENT_CHUNK], "by": user_id})
        out["messages"] = len(rows)

    # ---- 他在别人消息上留下的痕迹 ----
    await db.execute(delete(MessageReaction).where(MessageReaction.user_id == user_id))
    await db.execute(delete(MessageMention).where(MessageMention.user_id == user_id))
    await db.execute(delete(MessageHide).where(MessageHide.user_id == user_id))
    await db.execute(delete(PollVote).where(PollVote.user_id == user_id))
    await db.execute(delete(Poll).where(Poll.creator_id == user_id))

    # ---- 媒体(聊天、贴纸、头像)----
    media = list(await db.scalars(select(MediaFile).where(
        MediaFile.owner_id == user_id, MediaFile.purpose.in_(("chat", "sticker", "avatar", "export")))))
    if media:
        objs: list[tuple[str, bool]] = []
        for mf in media:
            objs += _media_objects(mf)
        await db.execute(delete(MediaFile).where(MediaFile.id.in_([m.id for m in media])))
        remove_objects_after_commit(db, objs)
        out["media"] = len(media)
    await db.execute(delete(StickerSet).where(StickerSet.owner_id == user_id,
                                              StickerSet.is_official.is_(False)))
    await db.execute(delete(UserStickerSet).where(UserStickerSet.user_id == user_id))

    # ---- 会话成员 ----
    members = list(await db.scalars(select(ChatMember).where(
        ChatMember.user_id == user_id, ChatMember.role.in_(ACTIVE_ROLES))
        .with_for_update().execution_options(populate_existing=True)))
    for m in members:
        chat = await db.get(Chat, m.chat_id, with_for_update=True)
        if chat is None or chat.deleted_at is not None:
            continue
        m.draft = None
        if chat.type == "saved":
            chat.deleted_at = now
            continue
        if chat.type == "private":
            continue  # 对面那一方的会话留着
        if m.role == "owner":
            if await _hand_over(db, chat, user_id):
                out["chats_handed_over"] += 1
            else:
                out["chats_deleted"] += 1
                continue
        m.role = "left"
        m.left_at = now
        m.rights = {}
        chat.member_count = max(0, (chat.member_count or 1) - 1)
        await append_chat_event(db, chat.id, "member", {"user_id": user_id, "role": "left"})
        out["chats_left"] += 1

    # ---- 其余个人设置 ----
    for model, col in ((ChatFolder, ChatFolder.user_id), (ScheduledMessage, ScheduledMessage.sender_id),
                       (JoinRequest, JoinRequest.user_id), (UserEvent, UserEvent.user_id)):
        await db.execute(delete(model).where(col == user_id))
    await db.execute(update(InviteLink).where(InviteLink.creator_id == user_id)
                     .values(revoked=True))
    await db.execute(delete(SocialContact).where(
        (SocialContact.owner_id == user_id) | (SocialContact.contact_id == user_id)))
    await db.execute(delete(SocialBlock).where(
        (SocialBlock.user_id == user_id) | (SocialBlock.blocked_id == user_id)))
    prof = await db.get(SocialProfile, user_id)
    owner = await db.get(User, user_id)
    if prof is not None and prof.username and owner is not None \
            and owner.role == UserRole.customer:
        # 超级赞号和换号、清空一样冷冻 180 天(迁移 0133):注销后马上被别人注册的话,拿着老链接、
        # 老二维码、记着这个号的人找到的是另一个人。机器人(删机器人也走这里)的号不冷冻
        await release_user_username(db, user_id, prof.username)
    await db.execute(delete(Username).where(Username.owner_type == "user",
                                            Username.owner_id == user_id))
    if prof is not None:
        prof.username = None
        prof.bio = ""
        prof.privacy = {}
        prof.notify = {}
        prof.last_seen_at = None
        # 标签是他自己写给别人看的字,和签名一起清;隐藏设置跟着回到缺省
        prof.tags = []
        prof.tags_hidden = False
        prof.badges_hidden = []
        prof.badges_shown = []
    return out


async def _hand_over(db: AsyncSession, chat: Chat, user_id: int) -> bool:
    """群主 / 频道主注销:交给资历最老的管理员,没有就给最早进来的成员。一个人都没有 → 解散,返回 False。"""
    heir = await db.scalar(select(ChatMember).where(
        ChatMember.chat_id == chat.id, ChatMember.user_id != user_id,
        ChatMember.role.in_(("admin", "member")))
        .order_by(case((ChatMember.role == "admin", 0), else_=1), ChatMember.joined_at,
                  ChatMember.user_id)
        .limit(1).with_for_update())
    if heir is None:
        chat.deleted_at = now_utc()
        if chat.username:
            await db.execute(delete(Username).where(Username.owner_type == "chat",
                                                    Username.owner_id == chat.id))
            chat.username = None
        await append_chat_event(db, chat.id, "chat", {"deleted": True, "id": chat.id})
        return False
    heir.role = "owner"
    heir.rights = {}
    heir.restrictions = {}
    chat.owner_id = heir.user_id
    await append_chat_event(db, chat.id, "member", {"user_id": heir.user_id, "role": "owner"})
    await append_user_event(db, heir.user_id, "chat_join", {"chat": {"id": chat.id, "type": chat.type}})
    return True
