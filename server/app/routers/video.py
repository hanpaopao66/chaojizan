"""视频接口 `/video/v1`(DEV-PROMPTS-40 §8「视频」,#357–#367)。接口参考:docs/VIDEO-API.md。

路由只做三件事:取当前用户、调 services/video*.py、提交。判定都在 service 里。

- 整个模块挂在平台开关 `video_enabled` 上,投稿再挂 `video_upload_enabled`(#375):
  生产缺省关、开发 / CI 缺省开,关着回 503 和一句明确的话;
- 浏览类接口没登录也能用(公开稿件);互动、投稿、「我的」要登录,而且只对用户端账号开放(D1);
- 播放地址 `/video/v1/vod/…` 支持 Range;网页 `<video>` 带不了 Authorization 头,
  地址带绑定用户的签名(services/video.vod_query),播放时照样按那个人重新判权。
"""
import asyncio
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (Danmaku, FavFolder, User, UserRole, Video, VideoComment, VideoPart,
                      WatchHistory, WatchLater)
from ..ratelimit import (check_daily_limit, check_rate_limit, check_rate_limit_seconds,
                         client_ip)
from ..security import get_current_user_optional
from ..services import storage
from ..services import video as vsvc
from ..services import video_feed as feed
from ..services import video_interact as act
from ..services import video_rank as rank
from ..services import video_talk as talk
from ..services.flags import video_flag_on
from ..services.social import SOCIAL_ROLES
from .social import social_user

VIDEO_OFF = "视频功能暂未开放"
UPLOAD_OFF = "视频投稿暂未开放"


async def video_on(db: AsyncSession = Depends(get_db)) -> None:
    if not await video_flag_on(db, "video_enabled"):
        raise HTTPException(503, VIDEO_OFF)


async def upload_on(db: AsyncSession = Depends(get_db)) -> None:
    if not await video_flag_on(db, "video_upload_enabled"):
        raise HTTPException(503, UPLOAD_OFF)


async def viewer_optional(user: User | None = Depends(get_current_user_optional)) -> User | None:
    """没登录 = None。商家、骑手这些角色也当没登录处理(消息和视频只在用户端开放,D1)。"""
    if user is None or user.role not in SOCIAL_ROLES:
        return None
    return user


router = APIRouter(prefix="/video/v1", tags=["视频"], dependencies=[Depends(video_on)])


# 点赞 / 投币 / 收藏:每人每秒 5 次(§5.7)
async def _act_limit(user: User) -> None:
    await check_rate_limit_seconds("video_act", str(user.id), 5, 1, "点得太快了,歇一下")


def _page(page: int) -> int:
    return max(0, min(page, 200))


# =====================================================================
# 浏览
# =====================================================================

@router.get("/feed/recommend")
async def feed_recommend(page: int = 0, me: User | None = Depends(viewer_optional),
                         db: AsyncSession = Depends(get_db)):
    """推荐(§5.9 公开公式)。每一屏 20 条,同一个 UP 主一屏最多 2 个;每条带 rank 和 why。"""
    return await feed.rank_feed(db, me, mode="recommend", page=_page(page))


@router.get("/feed/hot")
async def feed_hot(page: int = 0, me: User | None = Depends(viewer_optional),
                   db: AsyncSession = Depends(get_db)):
    """热门:按热度排,所有人看到的一样(不个性化)。"""
    return await feed.rank_feed(db, me, mode="hot", page=_page(page))


@router.get("/feed/vertical")
async def feed_vertical(page: int = 0, me: User | None = Depends(viewer_optional),
                        db: AsyncSession = Depends(get_db)):
    """竖屏流:只取竖屏视频(宽 < 高),其余同推荐。"""
    return await feed.rank_feed(db, me, mode="vertical", page=_page(page))


@router.get("/feed/following")
async def feed_following(cursor: str | None = None, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    return await feed.following_feed(db, me, cursor)


@router.get("/zones")
async def list_zones(db: AsyncSession = Depends(get_db)):
    return {"items": await feed.zones(db)}


@router.get("/zones/{zone}")
async def zone_videos(zone: str, order: Literal["hot", "new"] = "hot", page: int = 0,
                      me: User | None = Depends(viewer_optional),
                      db: AsyncSession = Depends(get_db)):
    if zone not in vsvc.ZONES:
        raise HTTPException(404, "没有这个分区")
    return await feed.zone_page(db, me, zone, order, _page(page))


@router.get("/rank")
async def leaderboard(zone: str | None = None, days: int = 3,
                      me: User | None = Depends(viewer_optional),
                      db: AsyncSession = Depends(get_db)):
    """排行榜:某分区(或全站)按「互动分」在 1 / 3 / 7 天窗口里排,前 100。"""
    if days not in rank.RANK_WINDOWS_DAYS:
        raise HTTPException(422, "days 只能是 1 / 3 / 7")
    if zone and zone not in vsvc.ZONES:
        raise HTTPException(404, "没有这个分区")
    return await feed.leaderboard(db, me, zone or None, days)


@router.get("/rank/formula")
async def rank_formula():
    """排序公式原文和全部参数(透明中心、「为什么推荐」页直接展示)。"""
    return {"formula": rank.FORMULA, "weights": rank.WEIGHTS,
            "window_hours": rank.WINDOW_HOURS, "decay_offset_hours": rank.DECAY_OFFSET_HOURS,
            "decay_power": rank.DECAY_POWER, "follow_bonus": rank.FOLLOW_BONUS,
            "zone_bonus": rank.ZONE_BONUS, "top_zones": rank.TOP_ZONES,
            "zone_lookback_days": rank.ZONE_LOOKBACK_DAYS, "screen_size": rank.SCREEN_SIZE,
            "per_uploader_per_screen": rank.PER_UPLOADER_PER_SCREEN,
            "watched_ratio": rank.WATCHED_RATIO, "watched_skip_days": rank.WATCHED_SKIP_DAYS,
            "rank_windows_days": list(rank.RANK_WINDOWS_DAYS),
            "source": "server/app/services/video_rank.py"}


@router.get("/videos/{vid}")
async def get_video(vid: str, me: User | None = Depends(get_current_user_optional),
                    db: AsyncSession = Depends(get_db)):
    """视频详情。审核中的只有 UP 主和审核员能看(D10);别人一律 404。"""
    viewer = me if me is not None and (me.role in SOCIAL_ROLES or me.role == UserRole.admin) \
        else None
    v = await vsvc.viewable(db, vid, viewer)
    return await vsvc.detail(db, v, viewer)


@router.get("/videos/{vid}/related")
async def related(vid: str, me: User | None = Depends(viewer_optional),
                  db: AsyncSession = Depends(get_db)):
    v = await vsvc.viewable(db, vid, me)
    return await feed.related(db, me, v)


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=64),
                 order: Literal["default", "views", "new", "danmaku"] = "default",
                 duration: int = Query(0, ge=0, le=4), zone: str | None = None, page: int = 0,
                 request: Request = None, me: User | None = Depends(viewer_optional),
                 db: AsyncSession = Depends(get_db)):
    """视频搜索。order:default 综合 / views 最多播放 / new 最新 / danmaku 最多弹幕;
    duration:1 = 0–10 分钟、2 = 10–30、3 = 30–60、4 = 60+。"""
    await check_rate_limit("video_search", str(me.id) if me else client_ip(request), 60)
    if zone and zone not in vsvc.ZONES:
        raise HTTPException(404, "没有这个分区")
    out = await feed.search_videos(db, me, q, order=order, duration=duration, zone=zone,
                                   page=_page(page))
    if _page(page) == 0:
        await feed.record_term(db, me, q)
        await db.commit()
    return out


@router.get("/search/users")
async def search_users(q: str = Query(min_length=1, max_length=64), page: int = 0,
                       request: Request = None, me: User | None = Depends(viewer_optional),
                       db: AsyncSession = Depends(get_db)):
    await check_rate_limit("video_search", str(me.id) if me else client_ip(request), 60)
    return await feed.search_users(db, me, q, _page(page))


@router.get("/search/hot")
async def search_hot(db: AsyncSession = Depends(get_db)):
    """热搜:24 小时内至少 5 个不同的人搜过的词(防刷)。"""
    return {"items": await feed.hot_terms(db), "min_users": feed.HOT_TERM_MIN_USERS}


async def _social_target(db: AsyncSession, user_id: int) -> User:
    t = await db.get(User, user_id)
    if t is None or t.deleted_at is not None or t.role not in SOCIAL_ROLES:
        raise HTTPException(404, "没有这个用户")
    return t


@router.get("/users/{user_id}/space")
async def user_space(user_id: int, me: User | None = Depends(viewer_optional),
                     db: AsyncSession = Depends(get_db)):
    """UP 主空间:资料、关注 / 粉丝 / 获赞 / 投稿数、公开收藏夹、第一页投稿。"""
    t = await _social_target(db, user_id)
    out = await feed.space(db, me, t)
    await db.commit()
    return out


@router.get("/users/{user_id}/videos")
async def user_videos(user_id: int, order: Literal["new", "views"] = "new", page: int = 0,
                      me: User | None = Depends(viewer_optional),
                      db: AsyncSession = Depends(get_db)):
    await _social_target(db, user_id)
    return await feed.user_videos(db, me, user_id, order, _page(page))


@router.get("/users/{user_id}/fans")
async def user_fans(user_id: int, cursor: str | None = None,
                    me: User | None = Depends(viewer_optional),
                    db: AsyncSession = Depends(get_db)):
    await _social_target(db, user_id)
    return await act.follow_page(db, me, user_id, fans=True, cursor=cursor)


@router.get("/users/{user_id}/following")
async def user_following(user_id: int, cursor: str | None = None,
                         me: User | None = Depends(viewer_optional),
                         db: AsyncSession = Depends(get_db)):
    await _social_target(db, user_id)
    return await act.follow_page(db, me, user_id, fans=False, cursor=cursor)


@router.get("/favorites/{folder_id}")
async def folder_view(folder_id: int, cursor: str | None = None,
                      me: User | None = Depends(viewer_optional),
                      db: AsyncSession = Depends(get_db)):
    """看一个收藏夹里的视频:公开的谁都能看,私密的只有自己。"""
    f = await db.get(FavFolder, folder_id)
    if f is None or (not f.public and (me is None or me.id != f.user_id)):
        raise HTTPException(404, "没有这个收藏夹")
    return await act.folder_items(db, me, f, cursor)


# =====================================================================
# 互动
# =====================================================================

class LikeIn(BaseModel):
    like: bool = True


@router.post("/videos/{vid}/like")
async def like(vid: str, body: LikeIn | None = None, me: User = Depends(social_user),
               db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    v = await vsvc.viewable(db, vid, me)
    _published(v)
    out = await act.set_like(db, me, v, (body or LikeIn()).like)
    await db.commit()
    return out


def _published(v: Video) -> None:
    if v.status != "published":
        raise HTTPException(409, "视频还没公开,不能互动")


class CoinIn(BaseModel):
    amount: int = 1
    #: 投币时顺手点赞(B 站的「同时点赞」勾选)
    like: bool = False


@router.post("/videos/{vid}/coin")
async def coin(vid: str, body: CoinIn, me: User = Depends(social_user),
               db: AsyncSession = Depends(get_db)):
    """投币:自制最多 2 枚、转载 1 枚,投出的归 UP 主。硬币只是积分(D13、S4)。"""
    await _act_limit(me)
    v = await vsvc.viewable(db, vid, me, lock=True)
    _published(v)
    out = await vsvc.give_coins(db, me, v, body.amount)
    if body.like:
        out["liked"] = (await act.set_like(db, me, v, True))["liked"]
    await db.commit()
    coins = await db.scalar(select(Video.coins).where(Video.id == v.id))
    return {**out, "coins": int(coins or 0)}


class FavoriteIn(BaseModel):
    #: 这个视频要在的**全部**收藏夹;空列表 = 取消收藏;不传 = 收进默认收藏夹
    folder_ids: list[int] | None = Field(default=None, max_length=50)


@router.post("/videos/{vid}/favorite")
async def favorite(vid: str, body: FavoriteIn | None = None, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    v = await vsvc.viewable(db, vid, me)
    _published(v)
    out = await act.set_favorite(db, me, v, (body or FavoriteIn()).folder_ids)
    await db.commit()
    return out


class ShareIn(BaseModel):
    channel: str = Field(default="link", max_length=12)


@router.post("/videos/{vid}/share")
async def share(vid: str, body: ShareIn | None = None, me: User = Depends(social_user),
                db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    v = await vsvc.viewable(db, vid, me)
    _published(v)
    out = await act.share(db, me, v, (body or ShareIn()).channel)
    await db.commit()
    return out


@router.post("/videos/{vid}/triple")
async def triple(vid: str, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """三连:赞 + 投满 + 收进默认收藏夹(已经做过的跳过)。"""
    await _act_limit(me)
    v = await vsvc.viewable(db, vid, me, lock=True)
    _published(v)
    out = await act.triple(db, me, v)
    await db.commit()
    return out


class ViewIn(BaseModel):
    part_id: int | None = None
    #: 当前播放位置(续播用)
    position_ms: int = Field(default=0, ge=0)
    #: 这次打开以来实际播放了多久(计播放用:满 5 秒或 30% 才算)
    played_ms: int = Field(default=0, ge=0)
    #: 没登录时的设备号(只用来去重,服务端哈希后存)
    device_id: str = Field(default="", max_length=64)


@router.post("/videos/{vid}/view")
async def view(vid: str, body: ViewIn, request: Request,
               me: User | None = Depends(viewer_optional), db: AsyncSession = Depends(get_db)):
    """播放心跳(客户端每 15 秒一次)。同一个人(没登录按设备)同一个视频每天只算一次播放。"""
    key_src = str(me.id) if me else (body.device_id or client_ip(request))
    await check_rate_limit("video_view", key_src, 120)
    v = await vsvc.viewable(db, vid, me)
    if v.status != "published":
        return {"counted": False, "views": v.views}
    part = None
    if body.part_id:
        part = await db.get(VideoPart, body.part_id)
        if part is None or part.video_id != v.id or not part.live:
            raise HTTPException(404, "没有这个分 P")
    ua = request.headers.get("user-agent", "")
    key = act.viewer_key(me, body.device_id or request.headers.get("x-device-id", ""),
                         f"{client_ip(request)}|{ua}")
    out = await act.record_view(db, me, v, part=part, position_ms=body.position_ms,
                                played_ms=body.played_ms, key=key)
    await db.commit()
    return out


@router.post("/videos/{vid}/not-interested")
async def not_interested(vid: str, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    """不感兴趣:个性化推荐和竖屏流里不再出现(关掉个性化时不生效,S9)。"""
    v = await vsvc.viewable(db, vid, me)
    await act.not_interested(db, me, v)
    await db.commit()
    return {"ok": True}


class FollowIn(BaseModel):
    follow: bool = True


@router.post("/users/{user_id}/follow")
async def follow(user_id: int, body: FollowIn | None = None, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    out = await act.set_follow(db, me, user_id, (body or FollowIn()).follow)
    await db.commit()
    return out


@router.get("/me/following")
async def my_following(cursor: str | None = None, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    return await act.follow_page(db, me, me.id, fans=False, cursor=cursor)


# =====================================================================
# 弹幕
# =====================================================================

async def _part(db: AsyncSession, part_id: int, viewer: User | None) -> tuple[Video, VideoPart]:
    part = await db.get(VideoPart, part_id)
    if part is None:
        raise HTTPException(404, "没有这个分 P")
    v = await db.get(Video, part.video_id)
    if not vsvc.can_view(v, viewer):
        raise HTTPException(404, "没有这个分 P")
    if not part.live and not (viewer and (viewer.id == v.uploader_id or vsvc.is_admin(viewer))):
        raise HTTPException(404, "没有这个分 P")
    return v, part


@router.get("/parts/{part_id}/danmaku")
async def danmaku_list(part_id: int, segment: int = Query(0, ge=0, le=100),
                       me: User | None = Depends(viewer_optional),
                       db: AsyncSession = Depends(get_db)):
    """按 6 分钟一段拉(segment 从 0 起);客户端预取当前段和下一段。"""
    v, part = await _part(db, part_id, me)
    return await talk.list_danmaku(db, me, v, part, segment)


@router.get("/parts/{part_id}/danmaku/density")
async def danmaku_density(part_id: int, me: User | None = Depends(viewer_optional),
                          db: AsyncSession = Depends(get_db)):
    """高能进度条:整个分 P 按 5 秒一桶的弹幕数。"""
    _, part = await _part(db, part_id, me)
    return await talk.danmaku_density(db, me, part)


class DanmakuIn(BaseModel):
    time_ms: int = Field(ge=0)
    text: str = Field(max_length=500)
    mode: int = 1
    color: int = talk.WHITE
    size: int = 25


@router.post("/parts/{part_id}/danmaku")
async def danmaku_post(part_id: int, body: DanmakuIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """发弹幕:每人每 3 秒 1 条、每天 1,000 条;≤ 100 字、单行;过屏蔽词。"""
    v, part = await _part(db, part_id, me)
    talk.clean_danmaku(body.text, body.time_ms, body.mode, body.color, body.size,
                       part.duration_ms)
    await check_rate_limit_seconds("danmaku", str(me.id), 1, 3, "弹幕发得太快了,3 秒一条")
    await check_daily_limit("danmaku", str(me.id), 1000, "今天的弹幕发满 1000 条了,明天再来")
    d = await talk.post_danmaku(db, me, v, part, text=body.text, time_ms=body.time_ms,
                                mode=body.mode, color=body.color, size=body.size)
    await db.commit()
    return talk.danmaku_out(d, me.id)


@router.delete("/danmaku/{danmaku_id}")
async def danmaku_delete(danmaku_id: int, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    """发的人删自己的;UP 主删自己视频下任何人的。"""
    d = await db.get(Danmaku, danmaku_id)
    if d is None or d.deleted_at is not None:
        raise HTTPException(404, "弹幕不存在或已删除")
    v = await db.get(Video, d.video_id)
    await talk.delete_danmaku(db, me, d, v)
    await db.commit()
    return {"ok": True}


# =====================================================================
# 评论
# =====================================================================

@router.get("/videos/{vid}/comments")
async def comments(vid: str, sort: Literal["hot", "new"] = "hot", cursor: str | None = None,
                   me: User | None = Depends(viewer_optional),
                   db: AsyncSession = Depends(get_db)):
    v = await vsvc.viewable(db, vid, me)
    return await talk.list_comments(db, me, v, sort, cursor)


class CommentIn(BaseModel):
    text: str = Field(max_length=5000)
    #: 回复哪条评论(一级评论或回复都行);不传 = 发一级评论
    parent_id: int | None = None


@router.post("/videos/{vid}/comments")
async def comment_post(vid: str, body: CommentIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """发评论 / 回复:每人每 5 秒 1 条、每天 500 条;≤ 1,000 字;过屏蔽词;@用户名 会通知对方。"""
    v = await vsvc.viewable(db, vid, me, lock=True)
    talk.clean_comment(body.text)
    await check_rate_limit_seconds("video_comment", str(me.id), 1, 5, "评论太快了,5 秒一条")
    await check_daily_limit("video_comment", str(me.id), 500, "今天的评论发满 500 条了,明天再来")
    c = await talk.post_comment(db, me, v, body.text, body.parent_id)
    await db.commit()
    ppl = await vsvc.people(db, me.id, {c.user_id, c.reply_to_user_id or c.user_id})
    return talk.comment_out(c, v, ppl, {})


async def _comment_ctx(db: AsyncSession, comment_id: int, me: User | None,
                       *, lock: bool = False) -> tuple[Video, VideoComment]:
    c = await talk.get_comment(db, comment_id, lock=lock)
    v = await db.get(Video, c.video_id)
    if not vsvc.can_view(v, me):
        raise HTTPException(404, "评论不存在或已删除")
    if c.root_id is not None:
        root = await db.get(VideoComment, c.root_id)
        if root is None or root.deleted_at is not None:
            raise HTTPException(404, "评论不存在或已删除")
    return v, c


@router.get("/comments/{comment_id}/replies")
async def replies(comment_id: int, cursor: str | None = None,
                  me: User | None = Depends(viewer_optional),
                  db: AsyncSession = Depends(get_db)):
    v, c = await _comment_ctx(db, comment_id, me)
    if c.root_id is not None:
        raise HTTPException(422, "只有一级评论有回复列表")
    if me is not None and c.user_id in await talk.blocked_ids(db, me.id):
        raise HTTPException(404, "评论不存在或已删除")
    return await talk.list_replies(db, me, v, c, cursor)


class VoteIn(BaseModel):
    vote: int


@router.post("/comments/{comment_id}/vote")
async def comment_vote(comment_id: int, body: VoteIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """赞 1 / 踩 -1 / 取消 0。点踩数不对外。"""
    await _act_limit(me)
    v, c = await _comment_ctx(db, comment_id, me)
    out = await talk.vote(db, me, v, c, body.vote)
    await db.commit()
    return out


class PinIn(BaseModel):
    pinned: bool = True


@router.post("/comments/{comment_id}/pin")
async def comment_pin(comment_id: int, body: PinIn | None = None,
                      me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """UP 主置顶一条一级评论(新的顶掉旧的)。"""
    v, c = await _comment_ctx(db, comment_id, me, lock=True)
    out = await talk.pin(db, me, v, c, (body or PinIn()).pinned)
    await db.commit()
    return out


@router.delete("/comments/{comment_id}")
async def comment_delete(comment_id: int, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    """作者删自己的;UP 主删自己视频下的。删一级评论,楼里的回复一起不再显示。"""
    v, c = await _comment_ctx(db, comment_id, me, lock=True)
    await talk.delete_comment(db, me, v, c)
    await db.commit()
    return {"ok": True}


class ReportIn(BaseModel):
    target_type: Literal["video", "comment", "danmaku"]
    #: 举报视频时传 vid
    vid: str | None = None
    #: 举报评论 / 弹幕时传它的 id
    target_id: int | None = None
    reason_code: str
    note: str = Field(default="", max_length=500)


@router.post("/reports")
async def report(body: ReportIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    """举报视频、评论、弹幕(原因代码见 §5.11)。7 天内 3 个不同的人举报同一个对象自动进复审。"""
    await check_rate_limit("video_report", str(me.id), 10)
    if body.target_type == "video":
        v = await vsvc.viewable(db, body.vid or "", me)
        target_id, video_id = v.id, v.id
    elif body.target_type == "comment":
        v, c = await _comment_ctx(db, body.target_id or 0, me)
        target_id, video_id = c.id, v.id
    else:
        d = await db.get(Danmaku, body.target_id or 0)
        if d is None or d.deleted_at is not None:
            raise HTTPException(404, "弹幕不存在或已删除")
        v = await db.get(Video, d.video_id)
        if not vsvc.can_view(v, me):
            raise HTTPException(404, "弹幕不存在或已删除")
        target_id, video_id = d.id, v.id
    r = await vsvc.create_report(db, me, body.target_type, target_id, video_id, body.reason_code,
                                 body.note)
    await db.commit()
    return {"id": r.id, "status": r.status}


# =====================================================================
# 我的:历史、稍后再看、收藏夹、硬币、设置
# =====================================================================

@router.get("/me/history")
async def my_history(cursor: str | None = None, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    return await act.history_page(db, me, cursor)


@router.delete("/me/history")
async def clear_history(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(WatchHistory).where(WatchHistory.user_id == me.id))
    await db.commit()
    return {"ok": True}


@router.delete("/me/history/{vid}")
async def delete_history(vid: str, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    vid_id = await db.scalar(select(Video.id).where(Video.vid == vid))
    if vid_id is not None:
        await db.execute(delete(WatchHistory).where(WatchHistory.user_id == me.id,
                                                    WatchHistory.video_id == vid_id))
        await db.commit()
    return {"ok": True}


@router.get("/me/watch-later")
async def my_watch_later(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    return await act.watch_later_page(db, me)


class VidIn(BaseModel):
    vid: str


@router.post("/me/watch-later")
async def add_watch_later(body: VidIn, me: User = Depends(social_user),
                          db: AsyncSession = Depends(get_db)):
    v = await vsvc.viewable(db, body.vid, me)
    await act.add_watch_later(db, me, v)
    await db.commit()
    return await act.watch_later_page(db, me)


@router.delete("/me/watch-later/{vid}")
async def remove_watch_later(vid: str, me: User = Depends(social_user),
                             db: AsyncSession = Depends(get_db)):
    vid_id = await db.scalar(select(Video.id).where(Video.vid == vid))
    if vid_id is not None:
        await db.execute(delete(WatchLater).where(WatchLater.user_id == me.id,
                                                  WatchLater.video_id == vid_id))
        await db.commit()
    return {"ok": True}


@router.get("/me/favorites")
async def my_folders(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    out = await act.folders_of(db, me.id)
    await db.commit()
    return {"items": out, "max": act.FOLDERS_MAX}


class FolderIn(BaseModel):
    title: str = Field(max_length=100)
    public: bool = False


@router.post("/me/favorites")
async def create_folder(body: FolderIn, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    f = await act.create_folder(db, me, body.title, body.public)
    await db.commit()
    return act.folder_out(f)


@router.get("/me/favorites/{folder_id}")
async def my_folder(folder_id: int, cursor: str | None = None, me: User = Depends(social_user),
                    db: AsyncSession = Depends(get_db)):
    f = await act.own_folder(db, me.id, folder_id)
    return await act.folder_items(db, me, f, cursor)


class FolderPatch(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    public: bool | None = None


@router.patch("/me/favorites/{folder_id}")
async def patch_folder(folder_id: int, body: FolderPatch, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    f = await act.own_folder(db, me.id, folder_id, lock=True)
    if body.title is not None:
        t = " ".join(body.title.split())
        if not t or len(t) > act.FOLDER_TITLE_MAX:
            raise HTTPException(422, f"收藏夹名字 1–{act.FOLDER_TITLE_MAX} 个字")
        from ..services.moderation import guard_text
        await guard_text(db, t, "收藏夹名字")
        f.title = t
    if body.public is not None:
        f.public = body.public
    # 显式给值:不给的话 onupdate 由库里算,提交后这一列过期,下面读它会在异步会话里同步回库(500)
    f.updated_at = act.utcnow()
    await db.commit()
    return act.folder_out(f)


@router.delete("/me/favorites/{folder_id}")
async def delete_folder(folder_id: int, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    f = await act.own_folder(db, me.id, folder_id, lock=True)
    await act.delete_folder(db, me, f)
    await db.commit()
    return {"ok": True}


class MoveIn(BaseModel):
    vids: list[str] = Field(min_length=1, max_length=100)
    #: 挪到哪个收藏夹;不传 = 从这个收藏夹移除
    to: int | None = None


@router.post("/me/favorites/{folder_id}/move")
async def move_items(folder_id: int, body: MoveIn, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    f = await act.own_folder(db, me.id, folder_id, lock=True)
    out = await act.move_items(db, me, f, body.to, body.vids)
    await db.commit()
    return out


@router.get("/me/coins")
async def my_coins(cursor: int | None = None, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    """硬币余额和流水。硬币是纯积分:不能充值、提现、兑换(D13、S4)。"""
    out = await vsvc.coin_page(db, me.id, cursor)
    await db.commit()
    return out


@router.post("/me/coins/daily")
async def daily_coin(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """每天第一次打开视频 tab 领 1 枚(北京日期,一天一次,重复调用不会多给)。"""
    granted, bal = await vsvc.grant_daily(db, me.id)
    await db.commit()
    return {"granted": granted, "coins": bal}


@router.get("/me/settings")
async def my_settings(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    out = await act.get_settings(db, me)
    await db.commit()
    return out


class SettingsIn(BaseModel):
    #: 个性化推荐(S9):关掉之后推荐和没登录的人看到的完全一样
    personalize: bool | None = None
    #: 暂停记录观看历史
    history_paused: bool | None = None


@router.patch("/me/settings")
async def patch_settings(body: SettingsIn, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    out = await act.set_settings(db, me, personalize=body.personalize,
                                 history_paused_=body.history_paused)
    await db.commit()
    return out


# =====================================================================
# 投稿与创作中心
# =====================================================================

class VideoIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    zone: str | None = Field(default=None, max_length=16)
    tags: list[str] | None = Field(default=None, max_length=30)
    copyright: str | None = Field(default=None, max_length=8)
    source_url: str | None = Field(default=None, max_length=500)
    visibility: str | None = Field(default=None, max_length=8)
    allow_danmaku: bool | None = None
    allow_comments: bool | None = None
    shop_id: int | None = None
    shop_collab: bool | None = None
    scheduled_at: datetime | None = None
    cover_media_id: int | None = None


class PartOrder(BaseModel):
    id: int
    title: str | None = Field(default=None, max_length=200)


class VideoPatch(VideoIn):
    #: 下一版全部分 P 的顺序和标题
    parts: list[PartOrder] | None = Field(default=None, max_length=20)


@router.post("/uploads/videos", dependencies=[Depends(upload_on)])
async def create_video(body: VideoIn | None = None, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """建稿件(草稿)。要实名(D11);每人每天最多 10 个(D8)。
    原片用媒体接口传(purpose=video,kind=video_source),再 POST /videos/{vid}/parts 挂上。"""
    await check_rate_limit("video_create", str(me.id), 20)
    v = await vsvc.create_draft(db, me, (body or VideoIn()).model_dump(exclude_unset=True))
    await db.commit()
    return await vsvc.creator_detail(db, v, me)


@router.patch("/videos/{vid}")
async def patch_video(vid: str, body: VideoPatch, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    """改稿。没发布过的直接改;已发布的内容改动进待审,**线上仍是原来那一版**(§5.8)。"""
    v = await vsvc.own_video(db, vid, me)
    data = body.model_dump(exclude_unset=True)
    if "parts" in data and data["parts"] is not None:
        data["parts"] = [{"id": p["id"], "title": p.get("title")} for p in data["parts"]]
    await vsvc.edit(db, me, v, data)
    await vsvc.emit_video_event(db, v)
    await db.commit()
    return await vsvc.creator_detail(db, v, me)


class PartIn(BaseModel):
    media_id: int
    title: str = Field(default="", max_length=200)


@router.post("/videos/{vid}/parts", dependencies=[Depends(upload_on)])
async def add_part(vid: str, body: PartIn, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    """加一 P,马上开始转码。做完推用户事件 `video`。"""
    await vsvc.require_realname(db, me)
    v = await vsvc.own_video(db, vid, me)
    p = await vsvc.add_part(db, me, v, body.media_id, body.title)
    await vsvc.emit_video_event(db, v)
    await db.commit()
    out = await vsvc.creator_detail(db, v, me)
    out["added_part_id"] = p.id
    return out


@router.delete("/videos/{vid}/parts/{part_id}")
async def delete_part(vid: str, part_id: int, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    v = await vsvc.own_video(db, vid, me)
    part = await db.get(VideoPart, part_id)
    if part is None or part.video_id != v.id:
        raise HTTPException(404, "没有这个分 P")
    await vsvc.remove_part(db, v, part)
    await vsvc.emit_video_event(db, v)
    await db.commit()
    return await vsvc.creator_detail(db, v, me)


@router.post("/videos/{vid}/submit", dependencies=[Depends(upload_on)])
async def submit(vid: str, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """提交审核。转码没完的先进 processing,全部就绪自动进 reviewing。"""
    await vsvc.require_realname(db, me)
    v = await vsvc.own_video(db, vid, me)
    await vsvc.submit(db, me, v)
    await db.commit()
    return await vsvc.creator_detail(db, v, me)


@router.delete("/videos/{vid}/changes")
async def discard_changes(vid: str, me: User = Depends(social_user),
                          db: AsyncSession = Depends(get_db)):
    """放弃已发布稿件还没过审的改动(审核中的不能撤回)。"""
    v = await vsvc.own_video(db, vid, me)
    await vsvc.discard_changes(db, v)
    await vsvc.emit_video_event(db, v)
    await db.commit()
    return await vsvc.creator_detail(db, v, me)


class AppealIn(BaseModel):
    text: str = Field(max_length=500)


@router.post("/videos/{vid}/appeal")
async def appeal(vid: str, body: AppealIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    """对最近一次驳回 / 下架申诉:每个结论一次,由**另一名**审核员处理(S6)。"""
    v = await vsvc.own_video(db, vid, me)
    d = await vsvc.appeal(db, me, v, body.text)
    await db.commit()
    return {"id": d.id, "appeal_of": d.appeal_of, "state": "open"}


@router.delete("/videos/{vid}")
async def delete_video(vid: str, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """删除稿件:立即从所有地方消失、播放地址失效;媒体 30 天后清掉。"""
    v = await vsvc.own_video(db, vid, me)
    await vsvc.delete_video(db, v)
    await vsvc.emit_video_event(db, v)
    await db.commit()
    return {"ok": True}


CREATOR_FILTERS = {
    "all": None, "processing": ("draft", "processing", "failed"), "reviewing": ("reviewing",),
    "published": ("published", "scheduled"), "rejected": ("rejected",), "removed": ("removed",),
}


@router.get("/creator/videos")
async def creator_videos(status: Literal["all", "processing", "reviewing", "published",
                                         "rejected", "removed"] = "all",
                         cursor: int | None = None, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    """稿件管理:我的全部稿件(新建的在前)。status 按创作中心的页签筛。"""
    q = select(Video).where(Video.uploader_id == me.id, Video.deleted_at.is_(None))
    if CREATOR_FILTERS[status]:
        q = q.where(Video.status.in_(CREATOR_FILTERS[status]))
    if cursor:
        q = q.where(Video.id < cursor)
    rows = list(await db.scalars(q.order_by(Video.id.desc()).limit(21)))
    return {"items": [vsvc.creator_card(v) for v in rows[:20]],
            "next_cursor": str(rows[19].id) if len(rows) > 20 else None}


@router.get("/creator/videos/{vid}")
async def creator_video(vid: str, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    v = await vsvc.own_video(db, vid, me, lock=False)
    return await vsvc.creator_detail(db, v, me)


@router.get("/creator/videos/{vid}/stats")
async def creator_stats(vid: str, days: int = Query(30, ge=1, le=90),
                        me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """单稿数据:累计 + 近 N 天每天的增量(播放、点赞、硬币、收藏、评论、弹幕、分享)。"""
    v = await vsvc.own_video(db, vid, me, lock=False)
    return await vsvc.stats(db, v, days)


@router.get("/creator/overview")
async def creator_overview(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    out = await vsvc.overview(db, me)
    await db.commit()
    return out


# =====================================================================
# 播放地址(Range;判权)
# =====================================================================

async def _vod_target(db: AsyncSession, vid: str, part_id: int, me: User | None, u: int | None,
                      e: int | None, s: str) -> tuple[Video, VideoPart]:
    viewer = me
    if u and e and s and vsvc.check_vod_sig(vid, part_id, u, e, s):
        # 带签名的地址:签名绑定用户,下面照样按这个用户判权(删了、下架了、改私密了立刻失效)
        signed = await db.get(User, u)
        viewer = signed if signed is not None and signed.deleted_at is None else None
    try:
        v = await vsvc.get_video(db, vid)
    except HTTPException:
        raise HTTPException(404, "没有这个视频") from None
    part = await db.get(VideoPart, part_id)
    if part is None or part.video_id != v.id or part.status != "ready":
        raise HTTPException(404, "没有这个视频")
    if not vsvc.can_view(v, viewer):
        raise HTTPException(404, "没有这个视频")
    if not part.live and not (viewer and (viewer.id == v.uploader_id or vsvc.is_admin(viewer))):
        raise HTTPException(404, "没有这个视频")
    return v, part


@router.get("/vod/{vid}/{part_id}/{q}.mp4")
async def vod(vid: str, part_id: int, q: int, request: Request, u: int | None = None,
              e: int | None = None, s: str = "",
              me: User | None = Depends(get_current_user_optional),
              db: AsyncSession = Depends(get_db)):
    """播放。公开稿件不带签名也能看;其余的要登录或带签名。生产由 nginx 直出(X-Accel-Redirect)。"""
    from .media import file_response

    _, part = await _vod_target(db, vid, part_id, me, u, e, s)
    r = next((x for x in part.renditions or [] if int(x["q"]) == q), None)
    if r is None:
        raise HTTPException(404, "没有这个清晰度")
    size = await asyncio.to_thread(storage.stat_size, r["key"], True)
    if size is None:
        raise HTTPException(404, "文件不见了")
    return file_response(request, r["key"], True, size, "video/mp4")


@router.get("/vod/{vid}/{part_id}/sprite/{n}.jpg")
async def vod_sprite(vid: str, part_id: int, n: int, request: Request, u: int | None = None,
                     e: int | None = None, s: str = "",
                     me: User | None = Depends(get_current_user_optional),
                     db: AsyncSession = Depends(get_db)):
    """进度条缩略图(雪碧图第 n 张,10×10 格)。"""
    from .media import file_response

    _, part = await _vod_target(db, vid, part_id, me, u, e, s)
    keys = (part.sprite or {}).get("keys") or []
    if not 0 <= n < len(keys):
        raise HTTPException(404, "没有这张缩略图")
    size = await asyncio.to_thread(storage.stat_size, keys[n], True)
    if size is None:
        raise HTTPException(404, "文件不见了")
    return file_response(request, keys[n], True, size, "image/jpeg")
