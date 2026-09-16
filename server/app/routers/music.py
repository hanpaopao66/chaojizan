"""音乐接口 `/music/v1`(DEV-PROMPTS-41 §8.2,#378)。接口参考:docs/MUSIC-API.md。

路由只做三件事:取当前用户、调 services/music*.py、提交。判定都在 service 里。

- 整个模块挂在平台开关 `music_enabled` 上,上传 / 建作品 / 加歌 / 提交再挂 `music_upload_enabled`
  (§3.8):生产缺省关、开发 / CI 缺省开,关着回 503 和一句明确的话;
- 浏览类接口没登录也能用(已发布的作品);**不登录也能听**(M5),喜欢、评论、歌单、推荐要登录;
- 写接口一律走 routers/social.social_user —— 封号在那里统一挡(#368);
- 播放地址 `/music/v1/stream/…` 支持 Range;网页 `<audio>` 带不了 Authorization 头,
  地址带绑定用户的签名(services/music.stream_urls),播放时照样按那个人重新判权。
"""
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import Follow, MusicArtist, MusicRelease, MusicTrack, User, UserRole
from ..ratelimit import (check_daily_limit, check_rate_limit, check_rate_limit_seconds,
                         client_ip)
from ..security import get_current_user_optional
from ..services import music as msvc
from ..services import music_interact as act
from ..services import music_rank as rank
from ..services import music_state as mstate
from ..services import music_talk as talk
from ..services import storage
from ..services.flags import music_flag_on
from ..services.social import SOCIAL_ROLES
from .social import social_user

MUSIC_OFF = "音乐暂未开放"
UPLOAD_OFF = "音乐投稿暂未开放"


async def music_on(db: AsyncSession = Depends(get_db)) -> None:
    if not await music_flag_on(db, "music_enabled"):
        raise HTTPException(503, MUSIC_OFF)


async def music_upload_on(db: AsyncSession = Depends(get_db)) -> None:
    if not await music_flag_on(db, "music_upload_enabled"):
        raise HTTPException(503, UPLOAD_OFF)


async def viewer_optional(user: User | None = Depends(get_current_user_optional)) -> User | None:
    """没登录 = None。商家、骑手这些角色也当没登录处理(音乐只在用户端开放,D1)。"""
    if user is None or user.role not in SOCIAL_ROLES:
        return None
    return user


async def viewer_or_admin(user: User | None = Depends(get_current_user_optional)) -> User | None:
    """看详情时管理员也算「看得见的人」(§3.3 审核员能看没过审的)。"""
    if user is None or not (user.role in SOCIAL_ROLES or user.role == UserRole.admin):
        return None
    return user


router = APIRouter(prefix="/music/v1", tags=["音乐"], dependencies=[Depends(music_on)])


# 喜欢、收藏、加歌单、关注:每人每秒 5 次(§5.10)
async def _act_limit(user: User) -> None:
    await check_rate_limit_seconds("music_act", str(user.id), 5, 1, "点得太快了,歇一下")


def _page(page: int) -> int:
    return max(0, min(page, 200))


# =====================================================================
# 发现
# =====================================================================

# ---- 榜单的进程内小缓存 ----
#
# 三个榜要把全部已发布的歌和三张明细表按时间窗 COUNT(DISTINCT) 一遍,是这个模块最重的查询,
# 而且**所有人看到的是同一份**(榜不个性化)。缓存的上限统一压在 settings.public_cache_max_seconds
# 上(和 /screen、透明中心同一只闸):e2e 把它设成 0 就等于不缓存 ——
# 「听完一首歌立刻去看榜」在测试里必须当场生效。
#
# 每日推荐、发现页的 daily 不进这里:那是按人算的。
CHART_TTL_SECONDS = 60
_chart_cache: dict[str, tuple[float, list]] = {}


async def _cached_chart(db: AsyncSession, key: str) -> list[tuple[int, dict]]:
    import time

    ttl = min(CHART_TTL_SECONDS, settings.public_cache_max_seconds)
    hit = _chart_cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    ranked = await rank.chart(db, key)
    if ttl > 0:
        _chart_cache[key] = (time.monotonic() + ttl, ranked)
    return ranked


async def _tracks_by_ids(db: AsyncSession, viewer_id: int | None,
                         ranked: list[tuple[int, dict]]) -> list[dict]:
    """把 [(track_id, rank)] 变成带 rank 的歌曲卡片,保持名次顺序。"""
    if not ranked:
        return []
    ids = [t for t, _ in ranked]
    rows = {t.id: t for t in await db.scalars(select(MusicTrack).where(MusicTrack.id.in_(ids)))}
    ordered = [rows[t] for t, _ in ranked if t in rows]
    cards = await msvc.track_cards(db, viewer_id, ordered)
    by_id = dict(ranked)
    return [{**c, "rank": by_id[t.id]} for c, t in zip(cards, ordered)]


@router.get("/home")
async def home(me: User | None = Depends(viewer_optional), db: AsyncSession = Depends(get_db)):
    """发现页(§8.2):每日推荐、推荐歌单、新歌、三个榜的前三、曲风表。"""
    personalize = await msvc.personalize_on(db, me.id if me else None)
    daily = await rank.daily(db, me.id if me else None, personalize)
    new_rows, new_scored = await rank.new_scores(db)
    new_ranked = sorted(new_scored, key=lambda t: rank.order_key(
        new_scored[t]["score"], new_rows[t]["published_at"], t))[:6]
    charts = []
    for key, name in rank.CHARTS.items():
        top = (await _cached_chart(db, key))[:3]
        charts.append({"key": key, "name": name,
                       "top": await _tracks_by_ids(db, me.id if me else None, top)})
    pl_ids, pl_scored, _ = await rank.recommended_playlists(db, 0, 6)
    pls = await _playlists_by_ids(db, me.id if me else None, pl_ids, pl_scored)
    return {
        "daily": await _tracks_by_ids(db, me.id if me else None, daily[:6]),
        "daily_personalized": bool(me and personalize),
        "playlists": pls,
        "new_tracks": await _tracks_by_ids(db, me.id if me else None,
                                           [(t, new_scored[t]) for t in new_ranked]),
        "charts": charts,
        "genres": [{"key": k, "name": v} for k, v in msvc.GENRES.items()],
    }


async def _playlists_by_ids(db: AsyncSession, viewer_id: int | None, ids: list[int],
                            scored: dict) -> list[dict]:
    from ..models import MusicPlaylist

    if not ids:
        return []
    rows = {p.id: p for p in await db.scalars(
        select(MusicPlaylist).where(MusicPlaylist.id.in_(ids)))}
    ordered = [rows[i] for i in ids if i in rows]
    cards = await msvc.playlist_cards(db, viewer_id, ordered)
    return [{**c, "rank": scored[p.id]} for c, p in zip(cards, ordered)]


@router.get("/genres")
async def genres():
    return [{"key": k, "name": v} for k, v in msvc.GENRES.items()]


@router.get("/genres/{key}/tracks")
async def genre_tracks(key: str, page: int = 0, me: User | None = Depends(viewer_optional),
                       db: AsyncSession = Depends(get_db)):
    """这个曲风下的歌,按热歌榜分数排(§8.2)。"""
    if key not in msvc.GENRES:
        raise HTTPException(404, "没有这个曲风")
    ids, scored, more = await rank.genre_page(db, key, _page(page))
    return {"items": await _tracks_by_ids(db, me.id if me else None,
                                          [(t, scored[t]) for t in ids]),
            "has_more": more}


@router.get("/charts")
async def charts(me: User | None = Depends(viewer_optional), db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    out = []
    for key, name in rank.CHARTS.items():
        top = (await _cached_chart(db, key))[:3]
        out.append({"key": key, "name": name, "updated_at": now,
                    "top": await _tracks_by_ids(db, me.id if me else None, top)})
    return out


@router.get("/charts/{key}")
async def chart_detail(key: str, me: User | None = Depends(viewer_optional),
                       db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone

    if key not in rank.CHARTS:
        raise HTTPException(404, "没有这个榜单")
    ranked = await _cached_chart(db, key)
    items = await _tracks_by_ids(db, me.id if me else None, ranked)
    return {"key": key, "name": rank.CHARTS[key],
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": [{"rank_no": i + 1, "track": {k: v for k, v in x.items() if k != "rank"},
                       "rank": x["rank"]} for i, x in enumerate(items)]}


@router.get("/daily")
async def daily(me: User | None = Depends(viewer_optional), db: AsyncSession = Depends(get_db)):
    """每日推荐(§5.4)。关掉个性化 / 没登录时只按热歌榜分数。"""
    from ..services.video import bj_day

    personalize = await msvc.personalize_on(db, me.id if me else None)
    ranked = await rank.daily(db, me.id if me else None, personalize)
    return {"date": bj_day().isoformat(), "personalized": bool(me and personalize),
            "items": await _tracks_by_ids(db, me.id if me else None, ranked)}


@router.get("/rank/formula")
async def rank_formula():
    """榜单和推荐的公式原文与全部参数(§3.5 公开公式,透明中心直接展示)。"""
    return {"formula": rank.FORMULA, "params": rank.PARAMS,
            "charts": [{"key": k, "name": v} for k, v in rank.CHARTS.items()],
            "source": "server/app/services/music_rank.py"}


@router.get("/playlists/recommended")
async def recommended_playlists(page: int = 0, me: User | None = Depends(viewer_optional),
                                db: AsyncSession = Depends(get_db)):
    ids, scored, more = await rank.recommended_playlists(db, _page(page))
    return {"items": await _playlists_by_ids(db, me.id if me else None, ids, scored),
            "has_more": more}


# =====================================================================
# 歌曲、作品、音乐人
# =====================================================================

@router.get("/tracks/{tid}")
async def track_detail(tid: str, me: User | None = Depends(viewer_or_admin),
                       db: AsyncSession = Depends(get_db)):
    """歌曲详情。没过审的只有作者和审核员看得到(§3.3);别人一律 404。"""
    t, r, a = await msvc.viewable_track(db, tid, me)
    cards = await msvc.track_cards(db, me.id if me else None, [t])
    return {**cards[0], "lyrics_kind": t.lyrics_kind, "credits": t.credits or {},
            "declaration": t.declaration, "track_no": t.track_no,
            "stream": msvc.stream_urls(t, me.id if me else None)}


@router.get("/tracks/{tid}/lyrics")
async def lyrics(tid: str, me: User | None = Depends(viewer_or_admin),
                 db: AsyncSession = Depends(get_db)):
    t, _, _ = await msvc.viewable_track(db, tid, me)
    return {"kind": t.lyrics_kind, "text": t.lyrics or ""}


@router.get("/tracks/{tid}/stream")
async def resign_stream(tid: str, me: User | None = Depends(viewer_or_admin),
                        db: AsyncSession = Depends(get_db)):
    """重新签播放地址(旧的 6 小时到期了就来换一份)。"""
    t, _, _ = await msvc.viewable_track(db, tid, me)
    return msvc.stream_urls(t, me.id if me else None)


@router.get("/releases/{rid}")
async def release_detail(rid: str, me: User | None = Depends(viewer_or_admin),
                         db: AsyncSession = Depends(get_db)):
    r, a = await msvc.viewable_release(db, rid, me)
    tracks = await msvc.tracks_of(db, r.id)
    collected = False
    if me is not None:
        from ..models import MusicReleaseCollect
        collected = await db.scalar(select(MusicReleaseCollect.release_id).where(
            MusicReleaseCollect.user_id == me.id,
            MusicReleaseCollect.release_id == r.id)) is not None
    return {**msvc.release_card(r, a, len(tracks)), "description": r.description or "",
            "genre": r.genre, "genre_name": msvc.GENRES.get(r.genre, ""),
            "language": r.language, "language_name": msvc.LANGUAGES.get(r.language, ""),
            "collected": collected,
            "tracks": await msvc.track_cards(db, me.id if me else None, tracks)}


async def _artist(db: AsyncSession, aid: str) -> MusicArtist:
    if not msvc.valid_id("artist", aid):
        raise HTTPException(404, "没有这个音乐人")
    a = await db.scalar(select(MusicArtist).where(MusicArtist.aid == aid))
    if a is None or a.status == "closed":
        raise HTTPException(404, "没有这个音乐人")
    return a


@router.get("/users/{user_id}/artist")
async def user_artist(user_id: int, db: AsyncSession = Depends(get_db)):
    """这个人是不是音乐人(资料页的「TA 的音乐」入口按它决定露不露)。

    不是、或者被停用了都回 404 —— 和别处一样,「有但你看不了」不单独说。
    """
    a = await msvc.artist_of_user(db, user_id)
    if a is None or a.status != "active":
        raise HTTPException(404, "这个人还不是音乐人")
    return {"aid": a.aid, "name": a.name, "avatar": a.avatar_url or "",
            "tracks": len(await msvc.published_track_ids(db, a.id))}


@router.get("/artists/{aid}")
async def artist_home(aid: str, me: User | None = Depends(viewer_optional),
                      db: AsyncSession = Depends(get_db)):
    """音乐人主页。fans / followed 读 follows 表(#377 关注全站一张表,关注的是他的 users.id)。"""
    a = await _artist(db, aid)
    if a.status == "suspended" and not (me is not None and me.id == a.user_id):
        raise HTTPException(404, "没有这个音乐人")
    ids = await msvc.published_track_ids(db, a.id)
    followed = False
    if me is not None:
        followed = await db.scalar(select(Follow.followee_id).where(
            Follow.follower_id == me.id, Follow.followee_id == a.user_id)) is not None
    hot = list(await db.scalars(select(MusicTrack).where(MusicTrack.id.in_(ids or [0]))
                                .order_by(MusicTrack.plays.desc(), MusicTrack.id).limit(10)))
    rels = list(await db.scalars(select(MusicRelease).where(
        MusicRelease.artist_id == a.id, MusicRelease.status == "published",
        MusicRelease.deleted_at.is_(None))
        .order_by(MusicRelease.published_at.desc().nulls_last(), MusicRelease.id.desc())))
    return {**msvc.artist_card(a, fans=await msvc.fans_of(db, a.user_id), followed=followed,
                               track_count=len(ids)),
            "hot_tracks": await msvc.track_cards(db, me.id if me else None, hot),
            "releases": await msvc.release_cards(db, rels)}


@router.get("/artists/{aid}/tracks")
async def artist_tracks(aid: str, page: int = 0, me: User | None = Depends(viewer_optional),
                        db: AsyncSession = Depends(get_db)):
    a = await _artist(db, aid)
    ids = await msvc.published_track_ids(db, a.id)
    if not ids:
        return {"items": [], "has_more": False}
    per, p = 20, _page(page)
    rows = list(await db.scalars(select(MusicTrack).where(MusicTrack.id.in_(ids))
                                 .order_by(MusicTrack.plays.desc(), MusicTrack.id)
                                 .offset(p * per).limit(per + 1)))
    return {"items": await msvc.track_cards(db, me.id if me else None, rows[:per]),
            "has_more": len(rows) > per}


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=64),
                 type: Literal["track", "artist", "release", "playlist"] = "track",
                 page: int = 0, request: Request = None,
                 me: User | None = Depends(viewer_optional),
                 db: AsyncSession = Depends(get_db)):
    """搜索(ILIKE,和视频搜索同口径)。每分钟 60 次(§5.10)。"""
    from ..models import MusicPlaylist

    await check_rate_limit("music_search", str(me.id) if me else client_ip(request), 60)
    per, p = 20, _page(page)
    like = f"%{q.strip()}%"
    viewer_id = me.id if me else None
    if type == "track":
        rows = list(await db.scalars(
            select(MusicTrack).join(MusicRelease, MusicRelease.id == MusicTrack.release_id)
            .join(MusicArtist, MusicArtist.id == MusicTrack.artist_id)
            .where(MusicRelease.status == "published", MusicRelease.deleted_at.is_(None),
                   MusicArtist.status == "active", MusicTrack.title.ilike(like))
            .order_by(MusicTrack.plays.desc(), MusicTrack.id).offset(p * per).limit(per + 1)))
        return {"items": await msvc.track_cards(db, viewer_id, rows[:per]),
                "has_more": len(rows) > per}
    if type == "artist":
        rows = list(await db.scalars(select(MusicArtist).where(
            MusicArtist.status == "active", MusicArtist.name.ilike(like))
            .order_by(MusicArtist.id).offset(p * per).limit(per + 1)))
        return {"items": [msvc.artist_brief(a) for a in rows[:per]],
                "has_more": len(rows) > per}
    if type == "release":
        rows = list(await db.scalars(
            select(MusicRelease).join(MusicArtist, MusicArtist.id == MusicRelease.artist_id)
            .where(MusicRelease.status == "published", MusicRelease.deleted_at.is_(None),
                   MusicArtist.status == "active", MusicRelease.title.ilike(like))
            .order_by(MusicRelease.published_at.desc().nulls_last(), MusicRelease.id)
            .offset(p * per).limit(per + 1)))
        return {"items": await msvc.release_cards(db, rows[:per]), "has_more": len(rows) > per}
    rows = list(await db.scalars(select(MusicPlaylist).where(
        MusicPlaylist.deleted_at.is_(None), MusicPlaylist.is_public.is_(True),
        MusicPlaylist.title.ilike(like))
        .order_by(MusicPlaylist.collects.desc(), MusicPlaylist.id)
        .offset(p * per).limit(per + 1)))
    return {"items": await msvc.playlist_cards(db, viewer_id, rows[:per]),
            "has_more": len(rows) > per}


# =====================================================================
# 播放(Range;每次重新判权)
# =====================================================================

@router.get("/stream/{tid}/{q}.m4a")
async def stream(tid: str, q: str, request: Request, u: int | None = None,
                 e: int | None = None, s: str = "",
                 me: User | None = Depends(get_current_user_optional),
                 db: AsyncSession = Depends(get_db)):
    """音频文件(§5.5)。不登录也能听公开作品(M5);签名绑定用户,**每次请求重新判权**。"""
    from .media import file_response

    if q not in ("std", "hq"):
        raise HTTPException(404, "没有这个音质")
    viewer = me
    if u is not None and e and s and msvc.check_stream_sig(tid, u, e, s):
        # 带签名的地址:签名绑定用户,下面照样按这个用户判权(下架了、删了立刻失效)
        signed = await db.get(User, u) if u else None
        viewer = signed if signed is not None and signed.deleted_at is None else None
    t, _, _ = await msvc.viewable_track(db, tid, viewer)
    r = next((x for x in t.renditions or [] if x.get("q") == q), None)
    if r is None:
        raise HTTPException(404, "没有这个音质")
    size = await asyncio.to_thread(storage.stat_size, r["key"], True)
    if size is None:
        raise HTTPException(404, "文件不见了")
    return file_response(request, r["key"], True, size, "audio/mp4")


class PlayIn(BaseModel):
    ms_listened: int = Field(default=0, ge=0)
    #: 没登录时的设备号(只用来去重,服务端哈希后存)
    device_id: str = Field(default="", max_length=64)
    #: 从哪听的:daily / chart / playlist:<pid> / artist:<aid>……只做数据,不参与算分
    context: str = Field(default="", max_length=40)


@router.post("/tracks/{tid}/play")
async def report_play(tid: str, body: PlayIn, request: Request,
                      me: User | None = Depends(viewer_optional),
                      db: AsyncSession = Depends(get_db)):
    """收听上报(§5.5)。听满 min(30 秒, 时长一半) 且 30 分钟内没算过才算一次。"""
    from ..services.video_interact import viewer_key

    key_src = str(me.id) if me else (body.device_id or client_ip(request))
    await check_rate_limit("music_play", key_src, 120)
    t, _, _ = await msvc.viewable_track(db, tid, me)
    key = viewer_key(me, body.device_id or request.headers.get("x-device-id", ""),
                     f"{client_ip(request)}|{request.headers.get('user-agent', '')}")
    out = await act.record_play(db, me, t, ms_listened=body.ms_listened, listener_key=key)
    await db.commit()
    return out


# =====================================================================
# 喜欢、歌单、收藏、最近播放、设置
# =====================================================================

@router.post("/tracks/{tid}/like")
async def like(tid: str, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    t, _, _ = await msvc.viewable_track(db, tid, me)
    out = await act.set_like(db, me, t, True)
    await db.commit()
    return out


@router.delete("/tracks/{tid}/like")
async def unlike(tid: str, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    t, _, _ = await msvc.viewable_track(db, tid, me)
    out = await act.set_like(db, me, t, False)
    await db.commit()
    return out


@router.get("/me/likes")
async def my_likes(cursor: str | None = None, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    return await act.liked_page(db, me, cursor)


@router.get("/me/history")
async def my_history(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    return await act.history_page(db, me)


@router.delete("/me/history")
async def clear_history(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    await act.clear_history(db, me.id)
    await db.commit()
    return {"ok": True}


@router.get("/me/playlists")
async def my_playlists(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    return await act.my_playlists(db, me)


@router.get("/me/settings")
async def my_settings(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    s = await msvc.get_setting(db, me.id)
    await db.commit()
    return {"personalize": s.personalize}


class SettingsIn(BaseModel):
    #: 个性化推荐(§5.4):关掉之后每日推荐只按热歌榜分数,和没登录看到的一样
    personalize: bool | None = None


@router.put("/me/settings")
async def put_settings(body: SettingsIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    s = await msvc.get_setting(db, me.id)
    if body.personalize is not None:
        s.personalize = body.personalize
    s.updated_at = msvc.utcnow()
    await db.commit()
    return {"personalize": s.personalize}


class PlaylistIn(BaseModel):
    title: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    is_public: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    cover_url: str | None = Field(default=None, max_length=300)


@router.post("/playlists")
async def create_playlist(body: PlaylistIn, me: User = Depends(social_user),
                          db: AsyncSession = Depends(get_db)):
    await check_rate_limit("music_playlist", str(me.id), 20)
    p = await act.create_playlist(db, me, body.model_dump(exclude_unset=True))
    await db.commit()
    return await act.playlist_detail(db, p, me)


@router.get("/playlists/{pid}")
async def playlist_detail(pid: str, me: User | None = Depends(viewer_optional),
                          db: AsyncSession = Depends(get_db)):
    p = await act.viewable_playlist(db, pid, me)
    return await act.playlist_detail(db, p, me)


class PlaylistPatch(PlaylistIn):
    title: str | None = Field(default=None, max_length=200)


@router.patch("/playlists/{pid}")
async def patch_playlist(pid: str, body: PlaylistPatch, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    p = await act.own_playlist(db, pid, me)
    await act.edit_playlist(db, p, body.model_dump(exclude_unset=True))
    await db.commit()
    return await act.playlist_detail(db, p, me)


@router.delete("/playlists/{pid}")
async def delete_playlist(pid: str, me: User = Depends(social_user),
                          db: AsyncSession = Depends(get_db)):
    p = await act.own_playlist(db, pid, me)
    await act.delete_playlist(db, p)
    await db.commit()
    return {"ok": True}


class TidsIn(BaseModel):
    tids: list[str] = Field(min_length=1, max_length=200)


@router.post("/playlists/{pid}/tracks")
async def add_to_playlist(pid: str, body: TidsIn, me: User = Depends(social_user),
                          db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    p = await act.own_playlist(db, pid, me)
    out = await act.add_tracks(db, me, p, body.tids)
    await db.commit()
    return out


@router.delete("/playlists/{pid}/tracks/{tid}")
async def remove_from_playlist(pid: str, tid: str, me: User = Depends(social_user),
                               db: AsyncSession = Depends(get_db)):
    p = await act.own_playlist(db, pid, me)
    out = await act.remove_track(db, p, tid)
    await db.commit()
    return out


@router.put("/playlists/{pid}/order")
async def order_playlist(pid: str, body: TidsIn, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    p = await act.own_playlist(db, pid, me)
    out = await act.reorder(db, p, body.tids)
    await db.commit()
    return out


@router.post("/playlists/{pid}/collect")
async def collect_playlist(pid: str, me: User = Depends(social_user),
                           db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    p = await act.get_playlist(db, pid, lock=True)
    out = await act.set_playlist_collect(db, me, p, True)
    await db.commit()
    return out


@router.delete("/playlists/{pid}/collect")
async def uncollect_playlist(pid: str, me: User = Depends(social_user),
                             db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    p = await act.get_playlist(db, pid, lock=True)
    out = await act.set_playlist_collect(db, me, p, False)
    await db.commit()
    return out


@router.post("/releases/{rid}/collect")
async def collect_release(rid: str, me: User = Depends(social_user),
                          db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    r, _ = await msvc.viewable_release(db, rid, me, lock=True)
    out = await act.set_release_collect(db, me, r, True)
    await db.commit()
    return out


@router.delete("/releases/{rid}/collect")
async def uncollect_release(rid: str, me: User = Depends(social_user),
                            db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    r, _ = await msvc.viewable_release(db, rid, me, lock=True)
    out = await act.set_release_collect(db, me, r, False)
    await db.commit()
    return out


# =====================================================================
# 评论
# =====================================================================

@router.get("/tracks/{tid}/comments")
async def comments(tid: str, sort: Literal["hot", "new"] = "hot", cursor: str | None = None,
                   me: User | None = Depends(viewer_optional),
                   db: AsyncSession = Depends(get_db)):
    t, _, _ = await msvc.viewable_track(db, tid, me)
    return await talk.list_comments(db, me, t, sort, cursor)


class CommentIn(BaseModel):
    text: str = Field(max_length=5000)
    #: 回复哪条评论(一级评论或回复都行);不传 = 发一级评论
    parent_id: int | None = None


@router.post("/tracks/{tid}/comments")
async def post_comment(tid: str, body: CommentIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """发评论 / 回复:每 5 秒 1 条、每天 500 条(§5.10);过违禁词;@超级赞号 会通知对方。"""
    t, _, a = await msvc.viewable_track(db, tid, me)
    talk.clean_comment(body.text)
    await check_rate_limit_seconds("music_comment", str(me.id), 1, 5, "评论太快了,5 秒一条")
    await check_daily_limit("music_comment", str(me.id), 500, "今天的评论发满 500 条了,明天再来")
    c = await talk.post_comment(db, me, t, body.text, body.parent_id)
    await db.commit()
    ppl = await msvc.people(db, me.id, {c.user_id, c.reply_to_user_id or c.user_id})
    return talk.comment_out(c, ppl, set(), viewer_id=me.id,
                            author_user_id=a.user_id if a else None)


@router.get("/comments/{comment_id}/replies")
async def replies(comment_id: int, cursor: str | None = None,
                  me: User | None = Depends(viewer_optional),
                  db: AsyncSession = Depends(get_db)):
    c = await talk.get_comment(db, comment_id)
    t = await talk.track_of_comment(db, c, me)
    if c.root_id is not None:
        raise HTTPException(422, "只有一级评论有回复列表")
    return await talk.list_replies(db, me, t, c, cursor)


@router.post("/comments/{comment_id}/like")
async def like_comment(comment_id: int, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    c = await talk.get_comment(db, comment_id, lock=True)
    await talk.track_of_comment(db, c, me)
    out = await talk.set_like(db, me, c, True)
    await db.commit()
    return out


@router.delete("/comments/{comment_id}/like")
async def unlike_comment(comment_id: int, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    c = await talk.get_comment(db, comment_id, lock=True)
    await talk.track_of_comment(db, c, me)
    out = await talk.set_like(db, me, c, False)
    await db.commit()
    return out


@router.delete("/comments/{comment_id}")
async def delete_comment(comment_id: int, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    """删自己的;这首歌的音乐人也能删自己歌下面的(§8.2)。"""
    c = await talk.get_comment(db, comment_id, lock=True)
    t = await talk.track_of_comment(db, c, me)
    await talk.delete_comment(db, me, t, c)
    await db.commit()
    return {"ok": True}


# =====================================================================
# 举报
# =====================================================================

class ReportIn(BaseModel):
    target_type: Literal["track", "release", "comment", "playlist", "artist"]
    #: 公开编号(歌 / 作品 / 歌单 / 音乐人)或评论 id
    target_id: str
    reason_code: str
    note: str = Field(default="", max_length=500)
    #: 版权投诉(M301)必填
    contact: str = Field(default="", max_length=120)


@router.post("/reports")
async def report(body: ReportIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    """举报歌曲、作品、评论、歌单、音乐人(原因代码见 §5.11)。每分钟 10 次(§5.10)。"""
    await check_rate_limit("music_report", str(me.id), 10)
    if body.target_type == "track":
        t, _, _ = await msvc.viewable_track(db, body.target_id, me)
        target_id = t.id
    elif body.target_type == "release":
        r, _ = await msvc.viewable_release(db, body.target_id, me)
        target_id = r.id
    elif body.target_type == "comment":
        c = await talk.get_comment(db, int(body.target_id) if body.target_id.isdigit() else 0)
        await talk.track_of_comment(db, c, me)
        target_id = c.id
    elif body.target_type == "playlist":
        p = await act.viewable_playlist(db, body.target_id, me)
        target_id = p.id
    else:
        a = await _artist(db, body.target_id)
        target_id = a.id
    r = await msvc.create_report(db, me, body.target_type, target_id, body.reason_code,
                                 body.note, body.contact)
    await db.commit()
    return {"id": r.id, "status": r.status, "ok": True}


# =====================================================================
# 音乐人中心 /studio
# =====================================================================

async def _studio_release_out(db: AsyncSession, r: MusicRelease, a: MusicArtist) -> dict:
    tracks = await msvc.tracks_of(db, r.id)
    last = await msvc.last_appealable(db, r)
    can_appeal = (last is not None and last.appeal_at is None
                  and msvc.appeal_still_valid(r, last))
    return {
        **msvc.release_card(r, a, len(tracks)),
        "status": r.status,
        "status_label": mstate.STATUS_LABELS.get(r.status, r.status),
        "description": r.description or "", "genre": r.genre, "language": r.language,
        "submitted_at": msvc.iso(r.submitted_at),
        "reject_code": r.reject_code, "reject_note": r.reject_note,
        "reject_label": msvc.REASON_CODES.get(r.reject_code, ""),
        "editable": mstate.editable(r),
        "can_appeal": can_appeal,
        "cover_media_id": r.cover_media_id,
        "tracks": [{"tid": t.tid, "title": t.title, "track_no": t.track_no,
                    "duration_ms": t.duration_ms, "transcode_status": t.transcode_status,
                    "fail_reason": t.fail_reason, "lyrics_kind": t.lyrics_kind,
                    "credits": t.credits or {}, "explicit": t.explicit,
                    "declaration": t.declaration, "plays": t.plays, "likes": t.likes}
                   for t in tracks],
    }


@router.get("/studio/me")
async def studio_me(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    a = await msvc.artist_of_user(db, me.id)
    if a is None:
        return {"artist": None}
    return {"artist": {**msvc.artist_card(a, fans=await msvc.fans_of(db, me.id)),
                       "status": a.status}}


class ArtistIn(BaseModel):
    name: str = Field(max_length=60)
    bio: str | None = Field(default=None, max_length=1000)
    genres: list[str] | None = Field(default=None, max_length=10)


@router.post("/studio/artist", dependencies=[Depends(music_upload_on)])
async def open_artist(body: ArtistIn, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    """开通音乐人。**不要求实名**(M2、§3.2),冒充走举报。"""
    from ..services.sanctions import check_user

    await check_user(db, me.id, "music_submit")
    a = await msvc.open_artist(db, me, body.name, body.bio or "", body.genres)
    await db.commit()
    return {"artist": {**msvc.artist_card(a), "status": a.status}}


class ArtistPatch(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    bio: str | None = Field(default=None, max_length=1000)
    genres: list[str] | None = Field(default=None, max_length=10)
    avatar_url: str | None = Field(default=None, max_length=300)
    cover_url: str | None = Field(default=None, max_length=300)


@router.patch("/studio/artist")
async def patch_artist(body: ArtistPatch, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    await msvc.edit_artist(db, a, body.model_dump(exclude_unset=True))
    await db.commit()
    return {"artist": {**msvc.artist_card(a, fans=await msvc.fans_of(db, me.id)),
                       "status": a.status}}


@router.get("/studio/releases")
async def studio_releases(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    rows = list(await db.scalars(select(MusicRelease).where(
        MusicRelease.artist_id == a.id, MusicRelease.deleted_at.is_(None))
        .order_by(MusicRelease.id.desc())))
    return {"items": [await _studio_release_out(db, r, a) for r in rows]}


class ReleaseIn(BaseModel):
    title: str = Field(max_length=200)
    kind: str = Field(default="single", max_length=8)
    genre: str = Field(default="", max_length=16)
    language: str = Field(default="", max_length=16)
    description: str | None = Field(default=None, max_length=5000)
    release_date: str | None = Field(default=None, max_length=20)
    cover_media_id: int | None = None


@router.post("/studio/releases", dependencies=[Depends(music_upload_on)])
async def create_release(body: ReleaseIn, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    from ..services.sanctions import check_user

    a = await msvc.my_artist(db, me)
    await check_user(db, me.id, "music_submit")
    await check_rate_limit("music_create", str(me.id), 20)
    r = await msvc.create_release(db, a, body.model_dump(exclude_unset=True))
    await db.commit()
    return await _studio_release_out(db, r, a)


class ReleasePatch(ReleaseIn):
    title: str | None = Field(default=None, max_length=200)
    kind: str | None = Field(default=None, max_length=8)
    genre: str | None = Field(default=None, max_length=16)
    language: str | None = Field(default=None, max_length=16)


@router.patch("/studio/releases/{rid}")
async def patch_release(rid: str, body: ReleasePatch, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    r = await msvc.own_release(db, rid, a)
    await msvc.edit_release(db, a, r, body.model_dump(exclude_unset=True))
    await db.commit()
    return await _studio_release_out(db, r, a)


@router.delete("/studio/releases/{rid}")
async def delete_release(rid: str, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    r = await msvc.own_release(db, rid, a)
    await msvc.delete_release(db, r)
    await db.commit()
    return {"ok": True}


class TrackIn(BaseModel):
    title: str = Field(max_length=200)
    media_id: int
    lyrics: str | None = Field(default=None, max_length=20000)
    credits: dict | None = None
    explicit: bool = False
    declaration: str = Field(max_length=12)


@router.post("/studio/releases/{rid}/tracks", dependencies=[Depends(music_upload_on)])
async def add_track(rid: str, body: TrackIn, me: User = Depends(social_user),
                    db: AsyncSession = Depends(get_db)):
    """加歌,马上开始转码(§5.3 末尾)。`media_id` 是 /media/v1 用途 music、类型 audio_source。"""
    from ..services.sanctions import check_user

    a = await msvc.my_artist(db, me)
    await check_user(db, me.id, "music_submit")
    await check_rate_limit("music_create", str(me.id), 20)
    await check_daily_limit("music_track", str(me.id), 50, "今天加满 50 首歌了,明天再来")
    r = await msvc.own_release(db, rid, a)
    t = await msvc.add_track(db, a, r, body.model_dump(exclude_unset=True))
    await db.commit()
    out = await _studio_release_out(db, r, a)
    out["added_tid"] = t.tid
    return out


class TrackPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    lyrics: str | None = Field(default=None, max_length=20000)
    credits: dict | None = None
    explicit: bool | None = None
    declaration: str | None = Field(default=None, max_length=12)


async def _own_track(db: AsyncSession, tid: str,
                     a: MusicArtist) -> tuple[MusicTrack, MusicRelease]:
    t = await msvc.get_track(db, tid)
    if t.artist_id != a.id:
        raise HTTPException(404, "歌曲不存在或已删除")
    r = await db.scalar(select(MusicRelease).where(MusicRelease.id == t.release_id)
                        .with_for_update().execution_options(populate_existing=True))
    if r is None or r.deleted_at is not None:
        raise HTTPException(404, "歌曲不存在或已删除")
    return t, r


@router.patch("/studio/tracks/{tid}")
async def patch_track(tid: str, body: TrackPatch, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    t, r = await _own_track(db, tid, a)
    await msvc.edit_track(db, r, t, body.model_dump(exclude_unset=True))
    await db.commit()
    return await _studio_release_out(db, r, a)


@router.delete("/studio/tracks/{tid}")
async def delete_track(tid: str, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    t, r = await _own_track(db, tid, a)
    await msvc.delete_track(db, r, t)
    await db.commit()
    return await _studio_release_out(db, r, a)


@router.put("/studio/releases/{rid}/order")
async def order_tracks(rid: str, body: TidsIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    r = await msvc.own_release(db, rid, a)
    if not mstate.editable(r):
        raise HTTPException(409, "已发布的作品不能改曲序,要改请先下架")
    await msvc.renumber_tracks(db, r, body.tids)
    await db.commit()
    return await _studio_release_out(db, r, a)


@router.post("/studio/releases/{rid}/submit", dependencies=[Depends(music_upload_on)])
async def submit_release(rid: str, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    """提交审核(§5.3)。前提:至少 1 首歌、每首都转完码、有封面、每首都勾了声明。"""
    from ..services.sanctions import check_user

    a = await msvc.my_artist(db, me)
    await check_user(db, me.id, "music_submit")
    r = await msvc.own_release(db, rid, a)
    await msvc.submit(db, r)
    await db.commit()
    return await _studio_release_out(db, r, a)


@router.post("/studio/releases/{rid}/cancel")
async def cancel_submit(rid: str, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    r = await msvc.own_release(db, rid, a)
    await msvc.cancel_submit(db, r)
    await db.commit()
    return await _studio_release_out(db, r, a)


@router.post("/studio/releases/{rid}/withdraw")
async def withdraw_release(rid: str, me: User = Depends(social_user),
                           db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    r = await msvc.own_release(db, rid, a)
    await msvc.withdraw(db, r)
    await db.commit()
    return await _studio_release_out(db, r, a)


class AppealIn(BaseModel):
    text: str = Field(max_length=500)


@router.post("/studio/releases/{rid}/appeal")
async def appeal(rid: str, body: AppealIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    """对最近一次驳回 / 下架申诉:每个结论一次,由**另一名**审核员处理(§5.3)。"""
    a = await msvc.my_artist(db, me)
    r = await msvc.own_release(db, rid, a)
    d = await msvc.appeal(db, r, body.text)
    await db.commit()
    return {"decision_id": d.id, "state": "open"}


@router.get("/studio/stats")
async def studio_stats(days: int = Query(30, ge=1, le=90), me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    a = await msvc.my_artist(db, me)
    return await msvc.artist_stats(db, a, days)
