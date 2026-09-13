"""会话、消息、事件(DEV-PROMPTS-40 §7「会话与消息」,#343 #344)。

几条贯穿全模块的约定:

- 消息(`ChatMessage`,表 `chat_messages`;`messages` 表是订单内聊天,别混)对外用 `(chat_id, seq)` 标识,`seq` 在会话内从 1 起严格递增、不复用(S10)。
  **写消息只能走 services/chat_store.py**:它锁会话行分配 seq、同事务写事件,
  别处直接 insert chat_messages 就会出现空洞或重号;
- 「为双方删除」保留消息行占住 seq,正文和媒体清空(`deleted_at` 非空),不下发;
- 每个会话一条事件流(`chat_events`,按会话的 `pts` 连续),每个用户一条(`user_events`,
  `social_profiles.user_pts`)。**事件按会话记,不按人扇出** —— 频道十万订阅者发一条帖子
  也只写一行事件(D7);
- 事件保留 7 天,更旧的断线补齐直接让客户端重拉(§5.3 reset)。
"""
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint, func)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

CHAT_TYPES = ("private", "group", "channel", "saved")
MEMBER_ROLES = ("owner", "admin", "member", "restricted", "left", "banned")
#: 算「在会话里」的角色(能收事件、能读新消息)
ACTIVE_ROLES = ("owner", "admin", "member", "restricted")


def _now_col(nullable: bool = False):
    return mapped_column(DateTime(timezone=True), server_default=func.now(),
                         nullable=nullable)


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(8))
    #: 链接里用的随机编号(私有群的邀请预览、消息链接),不暴露自增 id
    public_id: Mapped[str] = mapped_column(String(16), unique=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    about: Mapped[str] = mapped_column(String(255), default="")
    photo_url: Mapped[str] = mapped_column(String(300), default="")
    #: 公开群 / 频道的 @用户名(命名空间在 usernames 表)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                 nullable=True)
    #: 私聊 `小id:大id`、收藏夹 `s:<uid>`,唯一 —— 同一对人只会有一个私聊
    pair_key: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    pts: Mapped[int] = mapped_column(BigInteger, default=0)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    #: slow_mode / join_by_request / default_perms / reactions / signatures /
    #: history_visible / protected(见 services/chat_perms.py 的缺省值)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                             nullable=True)
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(),
                                                 onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                        nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ChatMember(Base):
    """一个人在一个会话里的全部状态:角色权限 + 他自己这边的会话设置(置顶、免打扰……)。"""

    __tablename__ = "chat_members"

    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"),
                                         primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    role: Mapped[str] = mapped_column(String(12), default="member")
    rights: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: {"until": ISO 时间 | null, "perms": {...}};被限制 / 封禁时用
    restrictions: Mapped[dict] = mapped_column(JSONB, default=dict)
    title: Mapped[str] = mapped_column(String(16), default="")
    joined_at: Mapped[datetime] = _now_col()
    invited_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 入群时会话的 last_seq。`history_visible=false` 的群里看不到这之前的消息
    join_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    last_read_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)
    #: 「清空聊天记录」只对自己生效时,清到哪一条
    cleared_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                         nullable=True)
    #: 会话列表置顶:数字越小越靠前;null = 没置顶
    pinned_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    marked_unread: Mapped[bool] = mapped_column(Boolean, default=False)
    draft: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: 私聊 / 收藏夹里对方还没发过消息时,会话不出现在他的列表里(见 chat_view.dialogs)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (Index("ix_chat_members_user_role", "user_id", "role"),)


class ChatMessage(Base):
    """聊天消息。**表名不是 messages** —— 那张是订单内聊天(models.Message),两者无关。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                  nullable=True)
    #: 频道帖子、群里匿名管理员:显示成会话本身发的
    as_chat: Mapped[bool] = mapped_column(Boolean, default=False)
    #: 客户端生成的去重键(§5.4)
    random_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str] = mapped_column(String(12))
    text: Mapped[str] = mapped_column(Text, default="")
    entities: Mapped[list] = mapped_column(JSONB, default=list)
    media: Mapped[list] = mapped_column(JSONB, default=list)
    reply_to_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    forward: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    grouped_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    poll_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 位置 / 名片 / 骰子 / 服务动作 / 通话记录 / 链接预览
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    markup: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    via_bot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    silent: Mapped[bool] = mapped_column(Boolean, default=False)
    views: Mapped[int] = mapped_column(Integer, default=0)
    #: 置顶时间;非空 = 置顶中(会话可以同时置顶多条)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        UniqueConstraint("chat_id", "seq", name="uq_chat_messages_seq"),
        Index("ix_chat_messages_pinned", "chat_id", postgresql_where=sql_text("pinned_at IS NOT NULL")),
        Index("uq_chat_messages_random", "chat_id", "sender_id", "random_id", unique=True,
              postgresql_where=sql_text("random_id IS NOT NULL")),
        Index("ix_chat_messages_sender_time", "sender_id", "created_at"),
        # 媒体判权(「这个媒体在我能读的某条消息里吗」)靠它
        Index("ix_chat_messages_media", "media", postgresql_using="gin",
              postgresql_ops={"media": "jsonb_path_ops"}),
    )


class MessageHide(Base):
    """只为自己删除。"""

    __tablename__ = "message_hides"

    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"),
                                         primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)


class MessageReaction(Base):
    __tablename__ = "message_reactions"

    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"),
                                         primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    emoji: Mapped[str] = mapped_column(String(16), primary_key=True)
    created_at: Mapped[datetime] = _now_col()


class MessageMention(Base):
    """@ 了谁(未读 @ 计数、「@我的」跳转)。"""

    __tablename__ = "message_mentions"

    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"),
                                         primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)

    __table_args__ = (Index("ix_message_mentions_user", "user_id", "chat_id", "seq"),)


class ChatEvent(Base):
    __tablename__ = "chat_events"

    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"),
                                         primary_key=True)
    pts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_chat_events_created", "created_at"),)


class UserEvent(Base):
    __tablename__ = "user_events"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    pts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_user_events_created", "created_at"),)


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    creator_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question: Mapped[str] = mapped_column(String(255))
    #: [{"text": "…"}, …],2–10 个
    options: Mapped[list] = mapped_column(JSONB, default=list)
    multiple: Mapped[bool] = mapped_column(Boolean, default=False)
    quiz: Mapped[bool] = mapped_column(Boolean, default=False)
    correct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explanation: Mapped[str] = mapped_column(String(200), default="")
    anonymous: Mapped[bool] = mapped_column(Boolean, default=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now_col()


class PollVote(Base):
    __tablename__ = "poll_votes"

    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"),
                                         primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    options: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = _now_col()


class InviteLink(Base):
    __tablename__ = "invite_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(24), unique=True)
    creator_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(32), default="")
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now_col()


class JoinRequest(Base):
    __tablename__ = "join_requests"

    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"),
                                         primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    invite_code: Mapped[str] = mapped_column(String(24), default="")
    about: Mapped[str] = mapped_column(String(140), default="")
    created_at: Mapped[datetime] = _now_col()


class ScheduledMessage(Base):
    __tablename__ = "scheduled_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    #: 和发送接口同一个请求体(不含 random_id,到点时生成)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = _now_col()


class ChatFolder(Base):
    __tablename__ = "chat_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(12))
    #: {"types": [...], "include": [chat_id...], "exclude": [...],
    #:  "exclude_muted": bool, "exclude_read": bool, "exclude_archived": bool}
    rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _now_col()


class StickerSet(Base):
    __tablename__ = "sticker_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                 nullable=True)
    short_name: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(64))
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now_col()


class Sticker(Base):
    __tablename__ = "stickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("sticker_sets.id", ondelete="CASCADE"),
                                        index=True)
    media_id: Mapped[int] = mapped_column(Integer)
    emoji: Mapped[str] = mapped_column(String(16), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)


class UserStickerSet(Base):
    __tablename__ = "user_sticker_sets"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("sticker_sets.id", ondelete="CASCADE"),
                                        primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    installed_at: Mapped[datetime] = _now_col()


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[str] = mapped_column(String(24), unique=True)
    caller_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                           index=True)
    callee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                           index=True)
    chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video: Mapped[bool] = mapped_column(Boolean, default=False)
    #: ringing / active / ended / missed / declined / busy / failed
    state: Mapped[str] = mapped_column(String(10), default="ringing")
    started_at: Mapped[datetime] = _now_col()
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(24), default="")


class Bot(Base):
    """机器人:users 表里一行 role=bot 的账号 + 这张表的配置。token 只存哈希(#355,见 services/bots.py)。"""

    __tablename__ = "bots"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                          index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    #: token 的前 6 位,日志和后台里只显示这个
    token_prefix: Mapped[str] = mapped_column(String(12), default="")
    about: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(String(512), default="")
    commands: Mapped[list] = mapped_column(JSONB, default=list)
    webhook_url: Mapped[str] = mapped_column(String(300), default="")
    #: webhook 的 secret_token,**密文**(services/crypto.encrypt);空串 = 没设
    webhook_secret: Mapped[str] = mapped_column(Text, default="")
    #: 最近一次投递失败的时间和原因(getWebhookInfo 的 last_error_*)
    webhook_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                              nullable=True)
    webhook_error: Mapped[str] = mapped_column(String(300), default="")
    #: 菜单按钮:"" 没有 / commands 命令列表 / web_app 打开 menu_app_id 那个小程序
    menu_type: Mapped[str] = mapped_column(String(10), default="")
    menu_text: Mapped[str] = mapped_column(String(64), default="")
    menu_app_id: Mapped[str] = mapped_column(String(24), default="")
    privacy_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    #: 下一个 update_id。分配时锁这一行,保证「提交顺序 = 编号顺序」(见 services/bots.py)
    next_update_id: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = _now_col()


class BotUpdate(Base):
    """给机器人的一条更新(Update 对象原样存在 payload 里),getUpdates 取、webhook 推。"""

    __tablename__ = "bot_updates"

    bot_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                        primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_try_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("ix_bot_updates_due", "next_try_at", postgresql_where=sql_text("delivered_at IS NULL")),
        Index("ix_bot_updates_created", "created_at"),
    )


class ChatReport(Base):
    """举报:会话、消息、用户。处置走 #368(services/chat_moderation.py)。

    `seqs` 是举报人**当时看得到的**那几条(提交时校验过),管理员按 S8 只能看这几条和前后各 5 条;
    `context_floor` 是举报人当时的可见下限(清空记录、入群前的历史),上下文不会越过它 ——
    举报人自己都看不到的消息,不能借举报单被管理员看到。

    `subject_*` 是「被举报的是谁」:消息的发送人、被举报的用户,或者会话本身(举报整个会话、
    频道帖子)。「7 天内 3 个不同的人举报同一个对象」按它数 —— 一个人给十个陌生人发骚扰私信,
    十个私聊各是一张举报单,对象都是他。
    """

    __tablename__ = "chat_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                             index=True)
    #: chat / message / user
    target_type: Mapped[str] = mapped_column(String(8))
    chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    seqs: Mapped[list] = mapped_column(JSONB, default=list)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reason_code: Mapped[str] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(String(500), default="")
    #: open / escalated(7 天内 3 个不同的人举报同一个对象,优先处理)/ actioned / dismissed
    status: Mapped[str] = mapped_column(String(10), default="open")
    decision: Mapped[dict] = mapped_column(JSONB, default=dict)
    handled_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: user / chat —— 被举报的对象(见类注释)
    subject_type: Mapped[str] = mapped_column(String(8), default="", server_default="")
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 举报人提交时的可见下限:S8 的上下文不越过它
    context_floor: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_chat_reports_subject", "subject_type", "subject_id",
                            "created_at"),
                      Index("ix_chat_reports_status", "status", "id"))


class AdminChatView(Base):
    """管理员查看被举报的会话消息:每次一行审计(S8),次数在透明中心公示。

    `report_id` 在举报单被删时置空而不是跟着删 —— 留痕和公示的次数不能因为别的表的级联变少。
    """

    __tablename__ = "admin_chat_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer, index=True)
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_reports.id", ondelete="SET NULL"), nullable=True)
    chat_id: Mapped[int] = mapped_column(Integer)
    seqs: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = _now_col()
