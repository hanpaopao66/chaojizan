"""视频:稿件、分 P、互动、弹幕、评论、收藏、历史、关注、审核、热搜、互动消息
(DEV-PROMPTS-40 §7「视频」,#357–#368)。

几条贯穿全模块的约定:

- 对外只用 `vid`(`sv` + 10 位 base58 随机,D19),不暴露自增 id —— 自增 id 等于公布投稿量;
- **线上版本和待审版本分开放**:videos 行上的标题、简介、封面……永远是审核过的那一版;
  已发布的稿件再改,改动先进 `pending_changes`,审核通过才搬到行上(§5.8「审核期间线上仍是上一版」)。
  分 P 同理:`video_parts.live` 为真的才是线上那几 P;
- 计数列(views / likes / …)是**展示用的累计数**;排序用的「近 72 小时增量、同一个人每种互动只算一次」
  不读计数列,直接从各张明细表按时间窗去重数(见 services/video_feed.window_counts)——
  计数列能被 bug 或手工改库带歪,明细表不会;
- 这里**不许出现** bid / boost / paid / promot / rank_score / weight_override 这类列(S3,
  tests/unit/test_video_rank.py 扫描):排序只吃公开计数、发布时间、关注关系和观看分区;
- 硬币只是积分(D13、S4):没有任何和钱有关的列。
"""
from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer,
                        SmallInteger, String, Text, func)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

#: 稿件状态(§5.8 状态机,见 services/video_state.py)
VIDEO_STATUSES = ("draft", "processing", "reviewing", "scheduled", "published", "rejected",
                  "failed", "removed", "deleted")
VISIBILITIES = ("public", "unlisted", "private")
#: 互动消息的四类(#367)
NOTIFY_KINDS = ("reply", "at", "like", "system")


def _now_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _count_col():
    return mapped_column(Integer, default=0, server_default="0")


class Video(Base):
    """一个稿件。行上的内容字段 = 线上版本(审核过的);改了待审的在 pending_changes。"""

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vid: Mapped[str] = mapped_column(String(12), unique=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                             index=True)
    title: Mapped[str] = mapped_column(String(80), default="", server_default="")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: 封面图的 media_files.id(上传的,或者转码出来的三帧候选之一)
    cover_media_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 过审后复制到公开桶的封面地址(/img/…)。没过审的稿件这里是空的 ——
    #: 审核中的封面只有 UP 主和审核员能看(D10),走带签名的 /media/v1/files
    cover_url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    zone: Mapped[str] = mapped_column(String(16), default="", server_default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list,
                                            server_default="{}")
    #: original 自制 / repost 转载(转载必填来源)
    copyright: Mapped[str] = mapped_column(String(8), default="original",
                                           server_default="original")
    source_url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    status: Mapped[str] = mapped_column(String(12), default="draft", server_default="draft")
    visibility: Mapped[str] = mapped_column(String(8), default="public", server_default="public")
    #: 竖屏 = 宽 < 高,以第一 P 为准(竖屏流只取它)
    is_vertical: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    allow_danmaku: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    allow_comments: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    #: 挂的店(D16,只许一家本平台商家);shop_collab = 与商家有无合作,挂了店就必须选
    shop_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shop_collab: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: 定时发布:审核通过后到点才公开(由清扫任务推进)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 最近一次提交审核的时间(审核队列按它排)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 驳回 / 下架的原因代码(§5.11)和给 UP 主看的说明
    reject_code: Mapped[str] = mapped_column(String(8), default="", server_default="")
    reject_note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    #: 转码失败的原因(failed 状态时给 UP 主看)
    fail_reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
    #: 已发布稿件改了、还没审的内容:{"state": editing|processing|reviewing|rejected|failed,
    #:  "fields": {...}, "parts": [{"id":…,"title":…}], "submitted_at": …, "reject_code": …}
    pending_changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    views: Mapped[int] = _count_col()
    likes: Mapped[int] = _count_col()
    coins: Mapped[int] = _count_col()
    favorites: Mapped[int] = _count_col()
    shares: Mapped[int] = _count_col()
    danmaku_count: Mapped[int] = _count_col()
    comment_count: Mapped[int] = _count_col()
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 删除 30 天后媒体清掉的时间(注销是立即清)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_videos_feed", "status", "visibility", "published_at"),
        Index("ix_videos_uploader_created", "uploader_id", "created_at"),
        Index("ix_videos_status_submitted", "status", "submitted_at"),
    )


class VideoPart(Base):
    """分 P。每 P 单独转码(§5.8),全部就绪稿件才进审核。"""

    __tablename__ = "video_parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    title: Mapped[str] = mapped_column(String(80), default="", server_default="")
    #: 原片(media_files,kind=video_source);转码成功后原片对象删掉,只留各档位
    source_media_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: processing / ready / failed
    status: Mapped[str] = mapped_column(String(12), default="processing",
                                        server_default="processing")
    error: Mapped[str] = mapped_column(String(300), default="", server_default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    w: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    h: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: [{"q": 720, "key": …, "w": …, "h": …, "bitrate": …, "size": …}],按档位从高到低
    renditions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    #: 雪碧图:{"interval_ms", "cols", "rows", "w", "h", "count", "keys": [...]}
    sprite: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: 自动封面候选(三帧)的 media_files.id
    cover_media_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    #: 属于线上版本。已发布稿件新加的 P 在过审之前是 False
    live: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = _now_col()


class VideoLike(Base):
    __tablename__ = "video_likes"

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"),
                                          primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True, index=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_video_likes_created", "created_at"),)


class VideoCoin(Base):
    """某人给某视频一共投了几枚(自制最多 2、转载最多 1,D13)。created_at 是第一次投的时间。"""

    __tablename__ = "video_coins"

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"),
                                          primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True, index=True)
    amount: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_video_coins_created", "created_at"),)


class CoinLedger(Base):
    """硬币流水,只追加。余额在 social_profiles.coins。

    reason 只有四种(S4,单测锁住):daily 每日首次 +1、video_approved 投稿过审 +2、
    coin_give 投出去 −n、coin_receive 别人投给我 +n。**没有充值、提现、兑换**。
    """

    __tablename__ = "coin_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(16))
    #: 关联对象,如 video:sv…
    ref: Mapped[str] = mapped_column(String(40), default="", server_default="")
    #: 记这一笔之后的余额(对账用)
    balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("ix_coin_ledger_user", "user_id", "id"),
        # 一个稿件只奖励一次过审硬币(改稿再审、申诉改判都不重复发)
        Index("uq_coin_ledger_approved", "user_id", "ref", unique=True,
              postgresql_where=sql_text("reason = 'video_approved'")),
    )


class VideoShare(Base):
    """分享。同一个人分享同一个视频只记一行(排序只算一次),times 是分享了几次。"""

    __tablename__ = "video_shares"

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"),
                                          primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True, index=True)
    channel: Mapped[str] = mapped_column(String(12), default="link", server_default="link")
    times: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_video_shares_created", "created_at"),)


class FavFolder(Base):
    """收藏夹。每人一个默认收藏夹(第一次收藏时建),自建的最多 50 个。"""

    __tablename__ = "fav_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(20))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: 公开的收藏夹出现在 UP 主空间里;缺省私密
    public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    item_count: Mapped[int] = _count_col()
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_fav_folders_default", "user_id", unique=True,
              postgresql_where=sql_text("is_default")),
    )


class FavItem(Base):
    __tablename__ = "fav_items"

    folder_id: Mapped[int] = mapped_column(ForeignKey("fav_folders.id", ondelete="CASCADE"),
                                           primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"),
                                          primary_key=True)
    #: 冗余一份收藏人:「我收藏了没有」和按人去重计数都靠它
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("ix_fav_items_user_video", "user_id", "video_id"),
        Index("ix_fav_items_video_created", "video_id", "created_at"),
        Index("ix_fav_items_created", "created_at"),
    )


class WatchLater(Base):
    __tablename__ = "watch_later"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"),
                                          primary_key=True)
    created_at: Mapped[datetime] = _now_col()


class WatchHistory(Base):
    """观看历史:每人每视频一行,记最后看到哪 P 的哪里。「看过 >50%」的 7 天内不再推荐。"""

    __tablename__ = "watch_history"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"),
                                          primary_key=True)
    part_idx: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    position_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    watched_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_watch_history_user_time", "user_id", "watched_at"),)


class VideoUserSetting(Base):
    """视频相关的个人开关。个性化推荐开关在 social_profiles.personalize_video(S9),这里放其余的。"""

    __tablename__ = "video_user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    #: 暂停记录观看历史
    history_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), onupdate=func.now())


class VideoNotInterested(Base):
    """「不感兴趣」:个性化推荐 / 竖屏流里不再出现(关掉个性化时不生效,见 S9)。"""

    __tablename__ = "video_not_interested"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"),
                                          primary_key=True)
    created_at: Mapped[datetime] = _now_col()


class Follow(Base):
    __tablename__ = "follows"

    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                             primary_key=True)
    followee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                             primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_follows_followee", "followee_id", "created_at"),
                      Index("ix_follows_follower", "follower_id", "created_at"))


class VideoComment(Base):
    """评论:两级。一级评论 root_id 为空;回复的 root_id 指向一级评论,parent_id 指向被回复的那条,
    回复的是「回复」时 reply_to_user_id 是那条回复的作者(显示「回复 @某人」)。"""

    __tablename__ = "video_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    root_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply_to_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: 文中 @ 到的人:[{"user_id": …, "username": …}]
    mentions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    likes: Mapped[int] = _count_col()
    #: 点踩数只用于内部(折叠、治理),**不对外**
    dislikes: Mapped[int] = _count_col()
    reply_count: Mapped[int] = _count_col()
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("ix_video_comments_video_root", "video_id", "root_id", "id"),
        Index("ix_video_comments_root", "root_id", "id"),
        Index("ix_video_comments_user", "user_id", "created_at"),
        Index("ix_video_comments_created", "created_at"),
    )


class CommentVote(Base):
    __tablename__ = "comment_votes"

    comment_id: Mapped[int] = mapped_column(ForeignKey("video_comments.id", ondelete="CASCADE"),
                                            primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True, index=True)
    #: 1 赞 / -1 踩
    vote: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = _now_col()


class Danmaku(Base):
    """弹幕(§5.10)。按分 P 存,拉取按 6 分钟一段。"""

    __tablename__ = "danmaku"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    part_id: Mapped[int] = mapped_column(ForeignKey("video_parts.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    time_ms: Mapped[int] = mapped_column(Integer)
    #: 1 滚动 / 4 底部 / 5 顶部
    mode: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    #: 24 位 RGB 整数,缺省白 16777215
    color: Mapped[int] = mapped_column(Integer, default=16777215, server_default="16777215")
    #: 18 小 / 25 标准
    size: Mapped[int] = mapped_column(SmallInteger, default=25, server_default="25")
    text: Mapped[str] = mapped_column(String(100))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("ix_danmaku_part_time", "part_id", "time_ms"),
        Index("ix_danmaku_video_created", "video_id", "created_at"),
        Index("ix_danmaku_user", "user_id", "created_at"),
        Index("ix_danmaku_created", "created_at"),
    )


class VideoViewDay(Base):
    """播放去重:同一个人(未登录按设备)同一个视频每天只算一次(§5.9)。"""

    __tablename__ = "video_view_days"

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"),
                                          primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    #: u<用户 id> / d<设备 id 的哈希>
    viewer_key: Mapped[str] = mapped_column(String(48), primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_video_view_days_created", "created_at"),)


class VideoStatDay(Base):
    """按天(北京日期)的增量:创作中心的近 30 天曲线。"""

    __tablename__ = "video_stat_days"

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"),
                                          primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    views: Mapped[int] = _count_col()
    likes: Mapped[int] = _count_col()
    coins: Mapped[int] = _count_col()
    favorites: Mapped[int] = _count_col()
    comments: Mapped[int] = _count_col()
    danmaku: Mapped[int] = _count_col()
    shares: Mapped[int] = _count_col()


class VideoReport(Base):
    """举报:视频、评论、弹幕。举报人对被举报的一方永远匿名。7 天内 3 个不同的人举报同一个对象 → 进复审。"""

    __tablename__ = "video_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                             index=True)
    #: video / comment / danmaku
    target_type: Mapped[str] = mapped_column(String(8))
    target_id: Mapped[int] = mapped_column(BigInteger)
    video_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reason_code: Mapped[str] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    #: open / escalated(7 天内 3 人举报,优先处理)/ actioned / dismissed
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    handled_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str] = mapped_column(String(300), default="", server_default="")
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_video_reports_target", "target_type", "target_id", "created_at"),
                      Index("ix_video_reports_status", "status", "id"))


class VideoDecision(Base):
    """审核、下架、申诉的全部记录(S6)。

    申诉也是一行:action=appeal,appeal_of 指向被申诉的结论;申诉结果再一行
    (appeal_upheld / appeal_overturned),appeal_of 指向申诉那一行。
    **处理申诉的人不能是原结论的作出者**(routers/video_admin.py 拒 403)。note_internal 不给 UP 主看。
    """

    __tablename__ = "video_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    #: approve / reject / approve_changes / reject_changes / remove / appeal /
    #: appeal_upheld / appeal_overturned
    action: Mapped[str] = mapped_column(String(24))
    reason_code: Mapped[str] = mapped_column(String(8), default="", server_default="")
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    note_internal: Mapped[str] = mapped_column(String(500), default="", server_default="")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                 nullable=True)
    appeal_of: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    #: 审核结论(通过 / 驳回)对应的那次提交是什么时候 —— 稿件行上的 submitted_at 会被下一次提交覆盖,
    #: 「审核时长中位数」(后台数据、透明中心)只能从这里算。这一列上线之前的结论为空,不参与计算
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), index=True)


class SearchTerm(Base):
    """热搜的按天汇总:某天有多少个不同的人搜过这个词。"""

    __tablename__ = "search_terms"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    term: Mapped[str] = mapped_column(String(32), primary_key=True)
    users: Mapped[int] = _count_col()


class SearchTermUser(Base):
    """谁搜过什么(去重用):热搜只数「24 小时内不同的人」,同一个人搜一百遍也只算一个(防刷)。"""

    __tablename__ = "search_term_users"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    term: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_search_term_users_created", "created_at"),)


class SocialNotification(Base):
    """互动消息(#367):回复我的 / @我的 / 收到的赞 / 系统通知。

    赞按对象合并:同一个人的同一个对象(我的某个视频、某条评论)只有一行,
    新的赞来了更新 actors / count / updated_at 并重新变未读(「小王等 12 人赞了你的视频」)。
    """

    __tablename__ = "social_notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    #: reply / at / like / system
    kind: Mapped[str] = mapped_column(String(8))
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 合并键:like:video:<id> / like:comment:<id>;不合并的为空
    group_key: Mapped[str] = mapped_column(String(40), default="", server_default="")
    count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    #: 最近的几个人(合并的赞用),新的在前
    actors: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("ix_social_notifications_user_kind", "user_id", "kind", "updated_at"),
        Index("uq_social_notifications_group", "user_id", "group_key", unique=True,
              postgresql_where=sql_text("group_key <> ''")),
    )


#: 视频模块的全部表(S3 列名守卫、S5 注销级联都按这张清单扫)
VIDEO_MODELS = (Video, VideoPart, VideoLike, VideoCoin, CoinLedger, VideoShare, FavFolder,
                FavItem, WatchLater, WatchHistory, VideoUserSetting, VideoNotInterested, Follow,
                VideoComment, CommentVote, Danmaku, VideoViewDay, VideoStatDay, VideoReport,
                VideoDecision, SearchTerm, SearchTermUser, SocialNotification)
