"""论坛:帖子、回复串、转发、引用、点赞、书签、浏览、话题、提及、投票、置顶、屏蔽词、
举报、下架与申诉(DEV-PROMPTS-41 §7.2,#380)。

几条贯穿全模块的约定:

- 对外只用 `pid`(`fp` + 10 位 base58 随机,§5.1),不暴露自增 id —— 自增 id 等于公布发帖量;
- **实体只由服务端解析**(§5.6):话题、提及、链接存在 `forum_posts.entities` 里,客户端报什么都不算数。
  同一份实体还拆进 `forum_post_tags` / `forum_mentions` 两张表 —— 热门话题、话题页要按人去重数,
  JSONB 里数不出来;
- 计数列(replies / likes / …)是**展示用的累计数**;排序用的「发帖后 72 小时内、同一个人只算一次」
  不读计数列,直接从各张明细表按时间窗去重数(services/forum_rank + forum_feed.window_counts)——
  计数列能被 bug 或手工改库带歪,明细表不会;
- 这里**不许出现** sponsored / boost / promot / paid / price 这类列(§3.1,
  tests/unit/test_forum_invariants.py 扫描):排序只吃公开计数、发帖时间、关注关系和话题;
- 平台不收钱(§3.1):没有付费、打赏、会员、推广位的任何列。
"""
from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer,
                        SmallInteger, String, Text, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

#: 帖子状态:visible 正常 / deleted 作者删了 / removed 平台下架(§5.6)
POST_STATUSES = ("visible", "deleted", "removed")
#: 谁能回复(§5.6 F4):所有人 / 我关注的人 / 我提到的人
REPLY_POLICIES = ("all", "following", "mentioned")


def _now_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _count_col():
    return mapped_column(Integer, default=0, server_default="0")


class ForumPost(Base):
    """一条帖子。原帖、回复、引用都是这张表的一行 —— 和 X 一样,回复本身也是一条帖子,
    能被赞、被转发、被引用、被回复。

    - `reply_to_id` 指向被回复的那一条,`root_id` 记整串的第一条(串按 root 拉,不用递归);
    - `quote_of_id` 是引用:被引用的帖子删了或下架了,引用照样在(§5.6),只显示占位;
    - 作者删自己的帖子是软删(`status='deleted'`),下面的回复保留 —— 别人的话不该跟着消失。
    """

    __tablename__ = "forum_posts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pid: Mapped[str] = mapped_column(String(12), unique=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: 服务端解析出来的实体:{"tags": [{"tag","display"}], "mentions": [{"id","username"}],
    #: "links": ["https://…"]}。客户端不许自己报(§5.6)
    entities: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    #: 图片:[{"url": "/img/forum/u42-….jpg", "w": 1080, "h": 1440}],最多 4 张
    media: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    #: 站内卡片 {"type": "track|release|playlist|artist|post|video", "id": "<公开编号>"}。
    #: **只存 type 和 id**,标题封面每次现查(services/cards.py):对象改名、下架了不会留着旧快照
    card: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reply_to_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    reply_to_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    root_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    quote_of_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    reply_policy: Mapped[str] = mapped_column(String(10), default="all", server_default="all")
    status: Mapped[str] = mapped_column(String(8), default="visible", server_default="visible")
    #: 平台下架的原因代码(§5.11);作者自己删的这里是空
    removed_code: Mapped[str] = mapped_column(String(8), default="", server_default="")
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edit_count: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    replies: Mapped[int] = _count_col()
    reposts: Mapped[int] = _count_col()
    quotes: Mapped[int] = _count_col()
    likes: Mapped[int] = _count_col()
    bookmarks: Mapped[int] = _count_col()
    views: Mapped[int] = _count_col()
    created_at: Mapped[datetime] = _now_col()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # 推荐候选:72 小时内的原帖(reply_to_id IS NULL 在 SQL 里判,这里只给时间和状态)
        Index("ix_forum_posts_created", "status", "created_at"),
        Index("ix_forum_posts_author_created", "author_id", "created_at"),
        Index("ix_forum_posts_root", "root_id", "created_at"),
    )


class ForumPostEdit(Base):
    """编辑历史(§5.6 F3):每编辑一次把**旧的**正文存一行,发出 30 分钟内最多 5 次。

    留历史是为了「已编辑」这个标记有意义 —— 看得到改了什么,才不会有人发完就偷偷换内容。
    """

    __tablename__ = "forum_post_edits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                         index=True)
    text: Mapped[str] = mapped_column(Text, default="", server_default="")
    entities: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = _now_col()


class ForumRepost(Base):
    """转发(不带字;带字的是引用,引用是一条新帖子)。一个人对同一条帖子只能转发一次。"""

    __tablename__ = "forum_reposts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("uq_forum_reposts", "user_id", "post_id", unique=True),
        # 关注时间线按事件时间倒序拉转发;推荐按 72 小时窗口数转发人数
        Index("ix_forum_reposts_user_created", "user_id", "created_at"),
        Index("ix_forum_reposts_post_created", "post_id", "created_at"),
        Index("ix_forum_reposts_created", "created_at"),
    )


class ForumLike(Base):
    __tablename__ = "forum_likes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                         primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_forum_likes_post_created", "post_id", "created_at"),
                      Index("ix_forum_likes_created", "created_at"),
                      Index("ix_forum_likes_user_created", "user_id", "created_at"))


class ForumBookmark(Base):
    """书签。**只有自己看得见**(§4 F2):帖子上不下发别人的书签数,只有作者和本人看得到自己的。"""

    __tablename__ = "forum_bookmarks"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                         primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_forum_bookmarks_user_created", "user_id", "created_at"),)


class ForumTag(Base):
    """话题。`tag` 是小写规范化后的,`display` 是第一次用它的人写的原样(展示用)。

    `hidden` 是运营隐藏:热门榜上不出现,但话题页照样能打开、帖子照样在 —— **不偷偷压话题**
    (§2.2),隐藏要写原因、留痕(forum_decisions)。
    """

    __tablename__ = "forum_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag: Mapped[str] = mapped_column(String(30), unique=True)
    display: Mapped[str] = mapped_column(String(30), default="", server_default="")
    posts: Mapped[int] = _count_col()
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    hidden_code: Mapped[str] = mapped_column(String(8), default="", server_default="")
    last_used_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_forum_tags_last_used", "last_used_at"),)


class ForumPostTag(Base):
    """帖子用了哪个话题。`author_id` 冗余一份:热门话题数的是「用过这个话题的**人**」,
    按人去重要 join 回帖子才拿得到作者,窗口里的行数又不少 —— 冗余一列省掉这个 join。"""

    __tablename__ = "forum_post_tags"

    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                         primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("forum_tags.id", ondelete="CASCADE"),
                                        primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_forum_post_tags_tag_created", "tag_id", "created_at"),
                      Index("ix_forum_post_tags_author", "author_id", "created_at"))


class ForumMention(Base):
    """帖子里 @ 到的人。展示时还要按对方现在的「按超级赞号找到我」开关再滤一遍
    (和视频评论一个口径,见 services/video_talk.mentions_off)。"""

    __tablename__ = "forum_mentions"

    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                         primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True, index=True)


class ForumPoll(Base):
    """投票(§5.6):2–4 项、每项 1–25 字、5 分钟–7 天;每人一票、不能改。

    `closed_notified` 是清扫任务的幂等标记 —— 结束后给作者和投过票的人各发一条 `system`,
    只发一次(auto_flow 每 30 秒一轮,不防重会一直发)。
    """

    __tablename__ = "forum_polls"

    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                         primary_key=True)
    #: [{"text": "选项", "votes": 3}],下标就是选项号
    options: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total: Mapped[int] = _count_col()
    closed_notified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (Index("ix_forum_polls_ends", "ends_at"),)


class ForumPollVote(Base):
    __tablename__ = "forum_poll_votes"

    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                         primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True, index=True)
    option: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = _now_col()


class ForumPin(Base):
    """置顶到自己主页的那一条(每人最多一条,和 X 一样)。"""

    __tablename__ = "forum_pins"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _now_col()


class ForumMuteWord(Base):
    """屏蔽词:含这个词的帖子不进我的时间线、话题页、搜索结果。每人最多 100 个。

    **只对我生效**,不影响别人看得到什么 —— 这是过滤器,不是举报。
    """

    __tablename__ = "forum_mute_words"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    word: Mapped[str] = mapped_column(String(30), primary_key=True)
    created_at: Mapped[datetime] = _now_col()


class ForumViewDay(Base):
    """浏览去重:同一个人(没登录按设备)同一条帖子每天只算一次(§4 F5)。留 8 天。"""

    __tablename__ = "forum_view_days"

    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                         primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    #: u<用户 id> / d<设备 id 的哈希>
    viewer_key: Mapped[str] = mapped_column(String(48), primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_forum_view_days_created", "created_at"),)


class ForumReport(Base):
    """举报帖子。举报人对被举报的一方永远匿名(和视频举报同一个口径)。"""

    __tablename__ = "forum_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                             index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                         index=True)
    reason_code: Mapped[str] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    #: open / actioned / dismissed
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    handled_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str] = mapped_column(String(300), default="", server_default="")
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_forum_reports_status", "status", "id"),)


class ForumDecision(Base):
    """下架、恢复、话题隐藏、申诉的全部记录(§3.6 和视频同一套)。

    申诉不另起一张表:被申诉的那一行上直接写 `appeal_text` / `appeal_at` / `appeal_result` /
    `appeal_by` —— **每个决定只能申诉一次**(§5.6),一对一的东西不值得再开一张表。
    `appeal_by` 不能等于 `admin_id`(原审核人不能复核自己的决定,routers/forum_admin.py 拒 403)。

    话题隐藏没有 post_id(`post_id` 可空),`tag_id` 记是哪个话题。
    """

    __tablename__ = "forum_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("forum_posts.id", ondelete="CASCADE"),
                                                nullable=True, index=True)
    tag_id: Mapped[int | None] = mapped_column(ForeignKey("forum_tags.id", ondelete="CASCADE"),
                                               nullable=True, index=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                 nullable=True)
    #: remove / restore / tag_hide / tag_unhide
    action: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str] = mapped_column(String(8), default="", server_default="")
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    note_internal: Mapped[str] = mapped_column(String(500), default="", server_default="")
    appeal_text: Mapped[str] = mapped_column(String(500), default="", server_default="")
    appeal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: "" 没申诉 / open 待复核 / upheld 维持 / overturned 改判
    appeal_result: Mapped[str] = mapped_column(String(12), default="", server_default="")
    appeal_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    appeal_note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), index=True)

    __table_args__ = (Index("ix_forum_decisions_appeal", "appeal_result", "id"),)


class ForumUserSetting(Base):
    """论坛的个人开关。现在只有一个:个性化推荐(§5.7「关掉个性化后两个方括号都按 0 算」)。"""

    __tablename__ = "forum_user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    personalize: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), onupdate=func.now())


#: 论坛模块的全部表(§3.1 列名守卫、§3.7 注销级联都按这张清单扫)
FORUM_MODELS = (ForumPost, ForumPostEdit, ForumRepost, ForumLike, ForumBookmark, ForumTag,
                ForumPostTag, ForumMention, ForumPoll, ForumPollVote, ForumPin, ForumMuteWord,
                ForumViewDay, ForumReport, ForumDecision, ForumUserSetting)
