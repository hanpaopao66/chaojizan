"""音乐:音乐人、作品、歌曲、歌单、喜欢、收听、评论、举报、审核(DEV-PROMPTS-41 §7.1,#378)。

几条贯穿全模块的约定:

- 对外只用公开编号(`mt` 歌曲 / `mr` 作品 / `mp` 歌单 / `ma` 音乐人 + 10 位 base58,§5.1),
  不暴露自增 id —— 自增 id 等于公布上传量;
- **审核的单位是「作品」**(M3):单曲 / EP / 专辑连同里面的全部歌曲一起审,
  没过审的作品除了作者本人和管理员谁也拿不到详情、封面和播放地址(§3.3,一律 404);
- 计数列(plays / likes / comments / collects)是**展示用的累计数**;榜单的
  「近 7 天、按人去重」不读计数列,直接从 music_plays / music_track_likes /
  music_playlist_tracks 按时间窗 COUNT DISTINCT(见 services/music_rank.py)——
  计数列能被 bug 或手工改库带歪,明细表不会;
- 这里**不许出现**和钱有关的列(§3.1):没有付费单曲、数字专辑、打赏、会员、推广位。
  tests/unit/test_music_invariants.py 扫这张 MUSIC_MODELS 清单;
- **不要求实名**(§3.2):开通音乐人只要手机号账号,这里没有任何证件相关的列。
"""
from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer,
                        String, Text, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

#: 作品状态(§5.3 状态机,见 services/music_state.py)
RELEASE_STATUSES = ("draft", "reviewing", "published", "rejected", "withdrawn", "removed")
#: 作品类型(M3)
RELEASE_KINDS = ("single", "ep", "album")
#: 歌曲转码状态(§5.3 末尾)
TRANSCODE_STATUSES = ("pending", "processing", "ready", "failed")
#: 音乐人状态:active 正常 / suspended 后台停用 / closed 本人注销
ARTIST_STATUSES = ("active", "suspended", "closed")
#: 歌词种类(M8)
LYRICS_KINDS = ("none", "plain", "lrc")
#: 上传时必须勾的声明(M1):原创 / 已获授权。没有第三种
DECLARATIONS = ("original", "authorized")


def _now_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _count_col():
    return mapped_column(Integer, default=0, server_default="0")


class MusicArtist(Base):
    """音乐人。一个超级赞账号最多一个音乐人身份,艺名全站唯一(M2)。

    艺名唯一靠 name_lc(小写、去空白)上的唯一索引 —— 「周杰伦」和「周杰伦 」是同一个名字,
    靠应用层比对迟早会漏(两个请求同时提交时谁也查不到对方)。
    """

    __tablename__ = "music_artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aid: Mapped[str] = mapped_column(String(12), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(30))
    #: 唯一性判据:小写 + 去掉全部空白
    name_lc: Mapped[str] = mapped_column(String(30), unique=True)
    bio: Mapped[str] = mapped_column(String(500), default="", server_default="")
    #: 头像、横幅走公开图片用途 music_cover(音乐人主页本来就是公开的)
    avatar_url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    cover_url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    #: 擅长的曲风:["pop", "rock"](见 services/music.GENRES)
    genres: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active")
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), onupdate=func.now())


class MusicRelease(Base):
    """作品(单曲 / EP / 专辑)。**审核的单位**(M3):过审后歌曲不能改,要改就下架重交。"""

    __tablename__ = "music_releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rid: Mapped[str] = mapped_column(String(12), unique=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("music_artists.id", ondelete="CASCADE"),
                                           index=True)
    title: Mapped[str] = mapped_column(String(60), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(8), default="single", server_default="single")
    #: 审核前的封面:私密桶里的 media_files.id,只有作者和审核员看得到(§3.3)
    cover_media_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 过审后复制到公开桶的封面地址(/img/…)。没过审的作品这里是空的
    cover_url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    genre: Mapped[str] = mapped_column(String(16), default="", server_default="")
    language: Mapped[str] = mapped_column(String(16), default="", server_default="")
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="draft", server_default="draft")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 驳回 / 下架的原因代码(§5.11)和给音乐人看的说明
    reject_code: Mapped[str] = mapped_column(String(8), default="", server_default="")
    reject_note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    collects: Mapped[int] = _count_col()
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_music_releases_artist_created", "artist_id", "created_at"),
        # 审核队列:按提交时间先后
        Index("ix_music_releases_status_submitted", "status", "submitted_at"),
        Index("ix_music_releases_published", "status", "published_at"),
    )


class MusicTrack(Base):
    """一首歌。转码产物在 renditions(私密桶),播放要签名(§5.5)。"""

    __tablename__ = "music_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tid: Mapped[str] = mapped_column(String(12), unique=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("music_releases.id", ondelete="CASCADE"),
                                            index=True)
    #: 冗余一份音乐人:榜单「同一位音乐人最多 N 首」、音乐人主页都按它过滤,省一次 join
    artist_id: Mapped[int] = mapped_column(ForeignKey("music_artists.id", ondelete="CASCADE"),
                                           index=True)
    title: Mapped[str] = mapped_column(String(60), default="", server_default="")
    track_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: 原始音频的 media_files.id(用途 music、类型 audio_source);转码成功后原文件删掉
    source_media_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: [{"q": "std"|"hq", "key": …, "bitrate": …, "size": …}]
    renditions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    transcode_status: Mapped[str] = mapped_column(String(12), default="pending",
                                                  server_default="pending")
    fail_reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
    lyrics: Mapped[str] = mapped_column(Text, default="", server_default="")
    lyrics_kind: Mapped[str] = mapped_column(String(8), default="none", server_default="none")
    #: {"lyricist": [...], "composer": [...], "arranger": [...], "producer": [...]}
    credits: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    explicit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    declaration: Mapped[str] = mapped_column(String(12), default="original",
                                             server_default="original")
    plays: Mapped[int] = _count_col()
    likes: Mapped[int] = _count_col()
    comments: Mapped[int] = _count_col()
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_music_tracks_release_no", "release_id", "track_no", "id"),
        Index("ix_music_tracks_artist_plays", "artist_id", "plays"),
    )


class MusicPlaylist(Base):
    """歌单。自建的公开歌单才进「推荐歌单」(§5.4 至少 5 首)。"""

    __tablename__ = "music_playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pid: Mapped[str] = mapped_column(String(12), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(40), default="", server_default="")
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    cover_url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    track_count: Mapped[int] = _count_col()
    collects: Mapped[int] = _count_col()
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_music_playlists_owner_updated", "owner_id", "updated_at"),)


class MusicPlaylistTrack(Base):
    """歌单里的一首歌。position 是排序位(PUT …/order 全量重排)。

    added_by 冗余一份加歌的人:热歌榜的「近 7 天加入歌单人数」按人去重数它。
    """

    __tablename__ = "music_playlist_tracks"

    playlist_id: Mapped[int] = mapped_column(ForeignKey("music_playlists.id", ondelete="CASCADE"),
                                             primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("music_tracks.id", ondelete="CASCADE"),
                                          primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    added_at: Mapped[datetime] = _now_col()
    added_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_music_playlist_tracks_order", "playlist_id", "position", "track_id"),
        Index("ix_music_playlist_tracks_track_added", "track_id", "added_at"),
    )


class MusicTrackLike(Base):
    __tablename__ = "music_track_likes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("music_tracks.id", ondelete="CASCADE"),
                                          primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_music_track_likes_track_created", "track_id", "created_at"),)


class MusicPlaylistCollect(Base):
    __tablename__ = "music_playlist_collects"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("music_playlists.id", ondelete="CASCADE"),
                                             primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_music_playlist_collects_pl_created", "playlist_id", "created_at"),)


class MusicReleaseCollect(Base):
    __tablename__ = "music_release_collects"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("music_releases.id", ondelete="CASCADE"),
                                            primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_music_release_collects_rel_created", "release_id", "created_at"),)


class MusicPlay(Base):
    """一次有效收听(§5.4 的门槛 + 30 分钟去重)。榜单按 listener_key 去重数人。留 60 天。"""

    __tablename__ = "music_plays"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("music_tracks.id", ondelete="CASCADE"))
    #: u<用户 id> / d<设备号的哈希>(和视频的播放去重同一个写法)
    listener_key: Mapped[str] = mapped_column(String(48))
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ms_listened: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _now_col()
    #: 北京日(按天出数据用)
    day: Mapped[date] = mapped_column(Date)

    __table_args__ = (
        Index("ix_music_plays_track_created", "track_id", "created_at"),
        Index("ix_music_plays_created", "created_at"),
        Index("ix_music_plays_user", "user_id", "created_at"),
        Index("ix_music_plays_day", "day"),
    )


class MusicHistory(Base):
    """最近播放。每人留最近 300 首(清扫截掉多的)。"""

    __tablename__ = "music_history"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("music_tracks.id", ondelete="CASCADE"),
                                          primary_key=True)
    played_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_music_history_user_time", "user_id", "played_at"),)


class MusicComment(Base):
    """歌曲评论:两级(热评、楼中楼)。口径和视频评论一样,先发后审。"""

    __tablename__ = "music_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("music_tracks.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    root_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply_to_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: 文中 @ 到的人:[{"user_id": …, "username": …}]
    mentions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    likes: Mapped[int] = _count_col()
    reply_count: Mapped[int] = _count_col()
    #: visible / deleted / removed(举报处置)
    status: Mapped[str] = mapped_column(String(10), default="visible", server_default="visible")
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (
        Index("ix_music_comments_track_root", "track_id", "root_id", "id"),
        Index("ix_music_comments_root", "root_id", "id"),
        Index("ix_music_comments_user", "user_id", "created_at"),
    )


class MusicCommentLike(Base):
    __tablename__ = "music_comment_likes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("music_comments.id", ondelete="CASCADE"),
                                            primary_key=True)
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_music_comment_likes_comment", "comment_id"),)


class MusicReport(Base):
    """举报:歌曲、作品、评论、歌单、音乐人。版权投诉(M301)必须留联系方式 —— 侵权要联系得上投诉人。"""

    __tablename__ = "music_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                             index=True)
    #: track / release / comment / playlist / artist
    target_type: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[int] = mapped_column(BigInteger)
    reason_code: Mapped[str] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    #: 版权投诉的联系方式(只给审核员看,不给被举报的人)
    contact: Mapped[str] = mapped_column(String(120), default="", server_default="")
    #: open / escalated / actioned / dismissed
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    handled_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str] = mapped_column(String(300), default="", server_default="")
    created_at: Mapped[datetime] = _now_col()

    __table_args__ = (Index("ix_music_reports_target", "target_type", "target_id", "created_at"),
                      Index("ix_music_reports_status", "status", "id"))


class MusicDecision(Base):
    """审核、驳回、下架、恢复的全部记录,申诉写在同一行上(§5.3)。

    和视频的 video_decisions 不一样:那边申诉是另起一行、`appeal_of` 指回去;这里一个决定
    一行,申诉的正文和结论就落在这一行的 appeal_* 上 —— **每个决定只能申诉一次**
    因此是「appeal_at 非空就不许再申诉」,不用去查有没有另一行,少一次并发窗口。
    `appeal_by` 是复核的管理员,服务端拒绝它等于 admin_id(原审核人不能复核自己,§5.3)。
    """

    __tablename__ = "music_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("music_releases.id", ondelete="CASCADE"),
                                            index=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                 nullable=True)
    #: approve / reject / remove / restore
    action: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str] = mapped_column(String(8), default="", server_default="")
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    appeal_text: Mapped[str] = mapped_column(String(500), default="", server_default="")
    appeal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: "" 没结论 / upheld 维持 / overturned 改判
    appeal_result: Mapped[str] = mapped_column(String(12), default="", server_default="")
    appeal_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    appeal_note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), index=True)

    __table_args__ = (Index("ix_music_decisions_appeals", "appeal_at", "appeal_result"),)


class MusicUserSetting(Base):
    """音乐的个人开关。现在只有一个:个性化推荐(关掉后每日推荐只按热歌榜分数,§5.4)。"""

    __tablename__ = "music_user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    personalize: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), onupdate=func.now())


#: 音乐模块的全部表(不变量扫描、注销级联都按这张清单走)。
#: 新加的音乐表必须写进来,否则 test_music_invariants 里的列名扫描和 purge_user 会漏掉它
MUSIC_MODELS = (MusicArtist, MusicRelease, MusicTrack, MusicPlaylist, MusicPlaylistTrack,
                MusicTrackLike, MusicPlaylistCollect, MusicReleaseCollect, MusicPlay,
                MusicHistory, MusicComment, MusicCommentLike, MusicReport, MusicDecision,
                MusicUserSetting)
