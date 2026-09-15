"""音乐的互动:收听上报、喜欢、歌单、收藏、最近播放(DEV-PROMPTS-41 §5.4、§5.5、§8.2)。

**收听计数是这个模块最容易被刷的地方**,所以门槛有三层(§5.5):

1. 客户端报的 `ms_listened` 先截到歌的时长以内 —— 报一个小时也只算一首歌的时长;
2. 要听满 `min(30 秒, 时长一半)`(services/music_rank.counted);
3. 同一个人(登录按账号,没登录按设备)同一首歌 **30 分钟内只算一次** —— 用 Redis 的
   SET NX EX 占坑,拿不到坑就不算。Redis 不可用时放行(和限流一个立场:防护不能变成单点故障),
   但榜单那一层还有 COUNT(DISTINCT listener_key) 兜底,刷不出人数来。
"""
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (MusicArtist, MusicHistory, MusicPlay, MusicPlaylist, MusicPlaylistCollect,
                      MusicPlaylistTrack, MusicRelease, MusicReleaseCollect, MusicTrack,
                      MusicTrackLike, User)
from . import music as msvc
from . import music_rank as rank
from .video import bj_day, iso, utcnow

logger = logging.getLogger("superz.music")


# ---------------- 收听上报(§5.5)----------------

async def _dedup_ok(listener_key: str, track_id: int) -> bool:
    """30 分钟内这个人算过这首歌没有。占到坑返回 True。"""
    from ..redis_client import get_redis

    try:
        r = get_redis()
        return bool(await r.set(f"music:play:{listener_key}:{track_id}", 1, nx=True,
                                ex=rank.LISTEN_DEDUP_MINUTES * 60))
    except Exception:
        logger.warning("收听去重检查失败,放行", exc_info=True)
        return True


async def record_play(db: AsyncSession, user: User | None, t: MusicTrack, *, ms_listened: int,
                      listener_key: str) -> dict:
    """收听上报。返回 {counted, plays}。"""
    ms = max(0, min(int(ms_listened or 0), t.duration_ms or 0))
    if user is not None:
        await touch_history(db, user.id, t)
    if not rank.counted(ms, t.duration_ms):
        return {"counted": False, "plays": t.plays,
                "threshold_ms": rank.listen_threshold_ms(t.duration_ms)}
    if not await _dedup_ok(listener_key, t.id):
        return {"counted": False, "plays": t.plays, "deduped": True}
    now = utcnow()
    db.add(MusicPlay(track_id=t.id, listener_key=listener_key,
                     user_id=user.id if user else None, ms_listened=ms, created_at=now,
                     day=bj_day(now)))
    await db.execute(update(MusicTrack).where(MusicTrack.id == t.id)
                     .values(plays=MusicTrack.plays + 1)
                     .execution_options(synchronize_session=False))
    return {"counted": True, "plays": t.plays + 1}


async def touch_history(db: AsyncSession, user_id: int, t: MusicTrack) -> None:
    """最近播放(§7.1):每人每首歌一行,重听就把时间往前挪。留最近 300 首,清扫时截。

    这里**不**每次都去截 300 首 —— 那是一次窗口函数删除,放在热路径上不划算;
    超出的由 services/music.sweep_music 定期清(多留几首不影响任何判据)。
    """
    now = utcnow()
    await db.execute(insert(MusicHistory).values(user_id=user_id, track_id=t.id, played_at=now)
                     .on_conflict_do_update(index_elements=["user_id", "track_id"],
                                            set_={"played_at": now}))


# ---------------- 喜欢 ----------------

async def set_like(db: AsyncSession, user: User, t: MusicTrack, like: bool) -> dict:
    if like:
        added = (await db.execute(
            insert(MusicTrackLike).values(user_id=user.id, track_id=t.id, created_at=utcnow())
            .on_conflict_do_nothing().returning(MusicTrackLike.track_id))).scalar()
        if added is not None:
            t.likes += 1
    else:
        res = await db.execute(delete(MusicTrackLike).where(
            MusicTrackLike.user_id == user.id, MusicTrackLike.track_id == t.id))
        if res.rowcount:
            t.likes = max(0, t.likes - 1)
    return {"liked": like, "likes": t.likes}


async def liked_page(db: AsyncSession, user: User, cursor: str | None,
                     limit: int = 30) -> dict:
    """我喜欢的音乐,新的在前。游标是上一页最后一条的 created_at。"""
    q = select(MusicTrackLike).where(MusicTrackLike.user_id == user.id)
    cur = _parse_ts_cursor(cursor)
    if cur is not None:
        from sqlalchemy import tuple_
        q = q.where(tuple_(MusicTrackLike.created_at, MusicTrackLike.track_id) < tuple_(*cur))
    rows = list(await db.scalars(q.order_by(MusicTrackLike.created_at.desc(),
                                            MusicTrackLike.track_id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    tracks = await _visible_tracks(db, [r.track_id for r in rows])
    return {"items": await msvc.track_cards(db, user.id, tracks), "has_more": more,
            "next_cursor": (f"{int(rows[-1].created_at.timestamp() * 1_000_000)}_"
                            f"{rows[-1].track_id}") if more and rows else None}


def _parse_ts_cursor(cursor: str | None):
    if not cursor:
        return None
    try:
        ts, rid = cursor.split("_", 1)
        from datetime import timezone
        return datetime.fromtimestamp(int(ts) / 1_000_000, tz=timezone.utc), int(rid)
    except (ValueError, OverflowError):
        return None


async def _visible_tracks(db: AsyncSession, ids: list[int]) -> list[MusicTrack]:
    """按给定顺序取「现在还看得见」的歌:作品要还在、还是已发布、音乐人没被停用。

    下架的歌从「我喜欢的」「最近播放」「歌单」里消失,但**行不删** —— 恢复上架之后还在。
    """
    if not ids:
        return []
    rows = {t.id: t for t in await db.scalars(
        select(MusicTrack).join(MusicRelease, MusicRelease.id == MusicTrack.release_id)
        .join(MusicArtist, MusicArtist.id == MusicTrack.artist_id)
        .where(MusicTrack.id.in_(ids), MusicRelease.status == "published",
               MusicRelease.deleted_at.is_(None), MusicArtist.status == "active"))}
    return [rows[i] for i in ids if i in rows]


async def history_page(db: AsyncSession, user: User) -> dict:
    rows = list(await db.scalars(select(MusicHistory).where(MusicHistory.user_id == user.id)
                                 .order_by(MusicHistory.played_at.desc())
                                 .limit(msvc.HISTORY_KEEP)))
    tracks = await _visible_tracks(db, [r.track_id for r in rows])
    return {"items": await msvc.track_cards(db, user.id, tracks), "max": msvc.HISTORY_KEEP}


# ---------------- 歌单 ----------------

async def get_playlist(db: AsyncSession, pid: str, *, lock: bool = False) -> MusicPlaylist:
    if not msvc.valid_id("playlist", pid):
        raise HTTPException(404, "歌单不存在或已删除")
    q = select(MusicPlaylist).where(MusicPlaylist.pid == pid)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    p = await db.scalar(q)
    if p is None or p.deleted_at is not None:
        raise HTTPException(404, "歌单不存在或已删除")
    return p


async def viewable_playlist(db: AsyncSession, pid: str, user: User | None) -> MusicPlaylist:
    p = await get_playlist(db, pid)
    if not p.is_public and (user is None or user.id != p.owner_id):
        raise HTTPException(404, "歌单不存在或已删除")
    return p


async def own_playlist(db: AsyncSession, pid: str, user: User, *,
                       lock: bool = True) -> MusicPlaylist:
    p = await get_playlist(db, pid, lock=lock)
    if p.owner_id != user.id:
        raise HTTPException(404, "歌单不存在或已删除")
    return p


async def create_playlist(db: AsyncSession, user: User, body: dict) -> MusicPlaylist:
    from .moderation import guard_text

    title = " ".join((body.get("title") or "").split())[:msvc.PLAYLIST_TITLE_MAX]
    if not title:
        raise HTTPException(422, "歌单名不能为空")
    await guard_text(db, title, "歌单名")
    desc = (body.get("description") or "").strip()[:msvc.PLAYLIST_DESC_MAX]
    if desc:
        await guard_text(db, desc, "歌单简介")
    p = MusicPlaylist(pid=msvc.new_id("playlist"), owner_id=user.id, title=title,
                      description=desc, tags=_clean_tags(body.get("tags")),
                      is_public=bool(body.get("is_public", True)),
                      cover_url=msvc.check_public_image(body.get("cover_url") or "",
                                                        "music_cover"),
                      created_at=utcnow())
    db.add(p)
    await db.flush()
    return p


def _clean_tags(tags) -> list[str]:
    out = [" ".join(str(t).split())[:12] for t in (tags or [])]
    return [t for t in dict.fromkeys(out) if t][:msvc.PLAYLIST_TAGS_MAX]


async def edit_playlist(db: AsyncSession, p: MusicPlaylist, body: dict) -> None:
    from .moderation import guard_text

    if "title" in body and body["title"] is not None:
        title = " ".join(body["title"].split())[:msvc.PLAYLIST_TITLE_MAX]
        if not title:
            raise HTTPException(422, "歌单名不能为空")
        await guard_text(db, title, "歌单名")
        p.title = title
    if "description" in body and body["description"] is not None:
        desc = body["description"].strip()[:msvc.PLAYLIST_DESC_MAX]
        if desc:
            await guard_text(db, desc, "歌单简介")
        p.description = desc
    if "tags" in body and body["tags"] is not None:
        p.tags = _clean_tags(body["tags"])
    if "is_public" in body and body["is_public"] is not None:
        p.is_public = bool(body["is_public"])
    if "cover_url" in body and body["cover_url"] is not None:
        p.cover_url = msvc.check_public_image(body["cover_url"], "music_cover")
    p.updated_at = utcnow()


async def add_tracks(db: AsyncSession, user: User, p: MusicPlaylist, tids: list[str]) -> dict:
    """加歌:去重、按现在的末尾往后排、最多 1000 首(§8.2)。看不到的歌直接跳过。"""
    tids = list(dict.fromkeys(tids))[:msvc.PLAYLIST_TRACKS_MAX]
    if not tids:
        raise HTTPException(422, "没有要加的歌")
    rows = list(await db.scalars(select(MusicTrack).where(MusicTrack.tid.in_(tids))))
    by_tid = {t.tid: t for t in rows}
    ok = await _visible_tracks(db, [by_tid[x].id for x in tids if x in by_tid])
    have = set(await db.scalars(select(MusicPlaylistTrack.track_id).where(
        MusicPlaylistTrack.playlist_id == p.id)))
    room = msvc.PLAYLIST_TRACKS_MAX - len(have)
    if room <= 0:
        raise HTTPException(409, f"一个歌单最多 {msvc.PLAYLIST_TRACKS_MAX} 首歌")
    pos = int(await db.scalar(select(func.coalesce(func.max(MusicPlaylistTrack.position), 0))
                              .where(MusicPlaylistTrack.playlist_id == p.id)) or 0)
    now = utcnow()
    added = 0
    for t in ok:
        if t.id in have or added >= room:
            continue
        pos += 1
        added += 1
        db.add(MusicPlaylistTrack(playlist_id=p.id, track_id=t.id, position=pos, added_at=now,
                                  added_by=user.id))
    p.track_count = len(have) + added
    p.updated_at = now
    await db.flush()
    return {"added": added, "track_count": p.track_count}


async def remove_track(db: AsyncSession, p: MusicPlaylist, tid: str) -> dict:
    t = await db.scalar(select(MusicTrack).where(MusicTrack.tid == tid))
    if t is not None:
        res = await db.execute(delete(MusicPlaylistTrack).where(
            MusicPlaylistTrack.playlist_id == p.id, MusicPlaylistTrack.track_id == t.id))
        if res.rowcount:
            p.track_count = max(0, p.track_count - 1)
            p.updated_at = utcnow()
    return {"ok": True, "track_count": p.track_count}


async def reorder(db: AsyncSession, p: MusicPlaylist, tids: list[str]) -> dict:
    """全量新顺序(§8.2 PUT …/order)。必须正好是歌单里现在的那些歌。"""
    rows = list(await db.scalars(select(MusicPlaylistTrack).where(
        MusicPlaylistTrack.playlist_id == p.id)))
    id_by_tid = {t.tid: t.id for t in await db.scalars(
        select(MusicTrack).where(MusicTrack.id.in_([r.track_id for r in rows])))}
    want = [id_by_tid.get(x) for x in dict.fromkeys(tids)]
    if None in want or set(want) != {r.track_id for r in rows}:
        raise HTTPException(422, "新顺序必须正好是这个歌单里的全部歌曲")
    by_track = {r.track_id: r for r in rows}
    for i, track_id in enumerate(want, 1):
        by_track[track_id].position = i
    p.updated_at = utcnow()
    return {"ok": True}


async def playlist_detail(db: AsyncSession, p: MusicPlaylist, viewer: User | None) -> dict:
    viewer_id = viewer.id if viewer else None
    rows = (await db.execute(
        select(MusicPlaylistTrack.track_id).where(MusicPlaylistTrack.playlist_id == p.id)
        .order_by(MusicPlaylistTrack.position, MusicPlaylistTrack.track_id))).scalars().all()
    tracks = await _visible_tracks(db, list(rows))
    collected = False
    if viewer_id:
        collected = await db.scalar(select(MusicPlaylistCollect.playlist_id).where(
            MusicPlaylistCollect.user_id == viewer_id,
            MusicPlaylistCollect.playlist_id == p.id)) is not None
    owner = (await msvc.people(db, viewer_id, [p.owner_id])).get(p.owner_id)
    return {**msvc.playlist_card(p, owner), "description": p.description or "",
            "created_at": iso(p.created_at), "updated_at": iso(p.updated_at),
            "collected": collected, "mine": viewer_id == p.owner_id,
            "tracks": await msvc.track_cards(db, viewer_id, tracks)}


async def set_playlist_collect(db: AsyncSession, user: User, p: MusicPlaylist,
                               collect: bool) -> dict:
    if collect and p.owner_id == user.id:
        raise HTTPException(422, "这是你自己的歌单,不用收藏")
    if collect and not p.is_public:
        raise HTTPException(404, "歌单不存在或已删除")
    if collect:
        added = (await db.execute(
            insert(MusicPlaylistCollect)
            .values(user_id=user.id, playlist_id=p.id, created_at=utcnow())
            .on_conflict_do_nothing().returning(MusicPlaylistCollect.playlist_id))).scalar()
        if added is not None:
            p.collects += 1
    else:
        res = await db.execute(delete(MusicPlaylistCollect).where(
            MusicPlaylistCollect.user_id == user.id, MusicPlaylistCollect.playlist_id == p.id))
        if res.rowcount:
            p.collects = max(0, p.collects - 1)
    return {"collected": collect, "collects": p.collects}


async def set_release_collect(db: AsyncSession, user: User, r: MusicRelease,
                              collect: bool) -> dict:
    if collect:
        added = (await db.execute(
            insert(MusicReleaseCollect)
            .values(user_id=user.id, release_id=r.id, created_at=utcnow())
            .on_conflict_do_nothing().returning(MusicReleaseCollect.release_id))).scalar()
        if added is not None:
            r.collects += 1
    else:
        res = await db.execute(delete(MusicReleaseCollect).where(
            MusicReleaseCollect.user_id == user.id, MusicReleaseCollect.release_id == r.id))
        if res.rowcount:
            r.collects = max(0, r.collects - 1)
    return {"collected": collect, "collects": r.collects}


async def my_playlists(db: AsyncSession, user: User) -> dict:
    created = list(await db.scalars(select(MusicPlaylist).where(
        MusicPlaylist.owner_id == user.id, MusicPlaylist.deleted_at.is_(None))
        .order_by(MusicPlaylist.updated_at.desc())))
    coll_ids = list(await db.scalars(select(MusicPlaylistCollect.playlist_id).where(
        MusicPlaylistCollect.user_id == user.id)
        .order_by(MusicPlaylistCollect.created_at.desc())))
    collected = []
    if coll_ids:
        by = {p.id: p for p in await db.scalars(select(MusicPlaylist).where(
            MusicPlaylist.id.in_(coll_ids), MusicPlaylist.deleted_at.is_(None),
            MusicPlaylist.is_public.is_(True)))}
        collected = [by[i] for i in coll_ids if i in by]
    rel_ids = list(await db.scalars(select(MusicReleaseCollect.release_id).where(
        MusicReleaseCollect.user_id == user.id)
        .order_by(MusicReleaseCollect.created_at.desc())))
    releases: list[MusicRelease] = []
    if rel_ids:
        by_r = {r.id: r for r in await db.scalars(select(MusicRelease).where(
            MusicRelease.id.in_(rel_ids), MusicRelease.status == "published",
            MusicRelease.deleted_at.is_(None)))}
        releases = [by_r[i] for i in rel_ids if i in by_r]
    return {"created": await msvc.playlist_cards(db, user.id, created),
            "collected": await msvc.playlist_cards(db, user.id, collected),
            "collected_releases": await msvc.release_cards(db, releases)}


async def delete_playlist(db: AsyncSession, p: MusicPlaylist) -> None:
    """软删。收藏过它的人那边跟着消失(my_playlists 只取 deleted_at 为空的)。"""
    p.deleted_at = utcnow()
    p.is_public = False


#: 清空最近播放时顺手把很久以前的收听明细留着 —— 那是榜单的数据来源,不是「我的记录」
async def clear_history(db: AsyncSession, user_id: int) -> None:
    await db.execute(delete(MusicHistory).where(MusicHistory.user_id == user_id))


def recent_window(days: int) -> datetime:
    return utcnow() - timedelta(days=days)
