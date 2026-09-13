"""视频的互动:点赞、收藏(收藏夹)、分享、三连、播放计数与历史、关注、稍后再看、不感兴趣
(DEV-PROMPTS-40 #361 #363 #366)。投币在 video.give_coins(和硬币余额放一起)。

计数的口径(§5.9):
- 展示用的累计数在 videos 的计数列上,用 `UPDATE … SET x = x + 1` 改(并发不丢);
- 同一个人对同一个视频:赞只有一行、收藏按人去重(放进三个收藏夹也只算一个人收藏)、
  分享只记一行 —— 排序「每种互动只算一次」靠的就是这些明细表;
- 播放:同一个人(没登录按设备)同一个视频每天只算一次,且看满 5 秒或 30% 才算。
"""
import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (FavFolder, FavItem, Follow, SocialProfile, User, UserRole, Video,
                      VideoLike, VideoNotInterested, VideoPart, VideoShare, VideoUserSetting,
                      VideoViewDay, WatchHistory, WatchLater)
from . import video as vsvc
from .social import blocked_between, ensure_profile

#: 播放计数门槛:看满 5 秒或 30%
VIEW_MIN_MS = 5000
VIEW_MIN_RATIO = 0.3
FOLDERS_MAX = 50
FOLDER_ITEMS_MAX = 1000
FOLDER_TITLE_MAX = 20
WATCH_LATER_MAX = 100
DEFAULT_FOLDER_TITLE = "默认收藏夹"
SHARE_CHANNELS = ("link", "chat", "qr", "other")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- 赞 ----------------

async def set_like(db: AsyncSession, user: User, v: Video, like: bool) -> dict:
    if like:
        res = await db.execute(insert(VideoLike).values(video_id=v.id, user_id=user.id,
                                                        created_at=utcnow())
                               .on_conflict_do_nothing())
        if res.rowcount == 1:
            likes = await db.scalar(update(Video).where(Video.id == v.id)
                                    .values(likes=Video.likes + 1).returning(Video.likes)
                                    .execution_options(synchronize_session=False))
            await vsvc.bump_stat(db, v.id, likes=1)
            from .social_notify import notify
            await notify(db, v.uploader_id, "like", actor_id=user.id, video_id=v.id,
                         group_key=f"like:video:{v.id}", count=int(likes or 1),
                         data={"target": "video"})
    else:
        res = await db.execute(delete(VideoLike).where(VideoLike.video_id == v.id,
                                                       VideoLike.user_id == user.id))
        if res.rowcount == 1:
            await db.execute(update(Video).where(Video.id == v.id)
                             .values(likes=func.greatest(Video.likes - 1, 0))
                             .execution_options(synchronize_session=False))
    likes = await db.scalar(select(Video.likes).where(Video.id == v.id))
    return {"liked": like, "likes": int(likes or 0)}


# ---------------- 收藏夹 ----------------

async def default_folder(db: AsyncSession, user_id: int) -> FavFolder:
    f = await db.scalar(select(FavFolder).where(FavFolder.user_id == user_id,
                                                FavFolder.is_default.is_(True)))
    if f is not None:
        return f
    await db.execute(insert(FavFolder).values(user_id=user_id, title=DEFAULT_FOLDER_TITLE,
                                              is_default=True, public=False, item_count=0)
                     .on_conflict_do_nothing(index_elements=["user_id"],
                                             index_where=sql_text("is_default")))
    f = await db.scalar(select(FavFolder).where(FavFolder.user_id == user_id,
                                                FavFolder.is_default.is_(True)))
    assert f is not None
    return f


def folder_out(f: FavFolder, cover: str = "") -> dict:
    return {"id": f.id, "title": f.title, "is_default": f.is_default, "public": f.public,
            "count": f.item_count, "cover": cover, "updated_at": vsvc.iso(f.updated_at)}


async def folders_of(db: AsyncSession, user_id: int, *, only_public: bool = False) -> list[dict]:
    if not only_public:
        # 看自己的收藏夹时才补建默认收藏夹;别人看你的空间不该替你写库
        await default_folder(db, user_id)
    q = select(FavFolder).where(FavFolder.user_id == user_id)
    if only_public:
        q = q.where(FavFolder.public.is_(True))
    rows = list(await db.scalars(q.order_by(FavFolder.is_default.desc(), FavFolder.id)))
    # 每个收藏夹最近收进来的那个视频当封面
    covers: dict[int, str] = {}
    if rows:
        latest = (await db.execute(
            select(FavItem.folder_id, Video.cover_url).join(Video, Video.id == FavItem.video_id)
            .where(FavItem.folder_id.in_([f.id for f in rows]), Video.deleted_at.is_(None))
            .order_by(FavItem.folder_id, FavItem.created_at.desc(), FavItem.video_id.desc())
            .distinct(FavItem.folder_id))).all()
        covers = {fid: c or "" for fid, c in latest}
    return [folder_out(f, covers.get(f.id, "")) for f in rows]


async def own_folder(db: AsyncSession, user_id: int, folder_id: int, *, lock: bool = False) -> FavFolder:
    q = select(FavFolder).where(FavFolder.id == folder_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    f = await db.scalar(q)
    if f is None or f.user_id != user_id:
        raise HTTPException(404, "没有这个收藏夹")
    return f


async def create_folder(db: AsyncSession, user: User, title: str, public: bool) -> FavFolder:
    title = " ".join((title or "").split())
    if not title or len(title) > FOLDER_TITLE_MAX:
        raise HTTPException(422, f"收藏夹名字 1–{FOLDER_TITLE_MAX} 个字")
    from .moderation import guard_text
    await guard_text(db, title, "收藏夹名字")
    await default_folder(db, user.id)
    n = await db.scalar(select(func.count()).select_from(FavFolder)
                        .where(FavFolder.user_id == user.id))
    if (n or 0) >= FOLDERS_MAX + 1:
        raise HTTPException(422, f"自建收藏夹最多 {FOLDERS_MAX} 个")
    f = FavFolder(user_id=user.id, title=title, is_default=False, public=bool(public),
                  item_count=0, created_at=utcnow(), updated_at=utcnow())
    db.add(f)
    await db.flush()
    return f


async def _user_fav_count(db: AsyncSession, user_id: int, video_id: int) -> int:
    return int(await db.scalar(select(func.count()).select_from(FavItem).where(
        FavItem.user_id == user_id, FavItem.video_id == video_id)) or 0)


async def _fav_counter(db: AsyncSession, video_id: int, before: int, after: int) -> None:
    """收藏数按人算:这个人从「没收藏」变成「收藏了」+1,反过来 −1。"""
    if before == 0 and after > 0:
        await db.execute(update(Video).where(Video.id == video_id)
                         .values(favorites=Video.favorites + 1)
                         .execution_options(synchronize_session=False))
        await vsvc.bump_stat(db, video_id, favorites=1)
    elif before > 0 and after == 0:
        await db.execute(update(Video).where(Video.id == video_id)
                         .values(favorites=func.greatest(Video.favorites - 1, 0))
                         .execution_options(synchronize_session=False))


async def _add_items(db: AsyncSession, user_id: int, folder: FavFolder, video_ids: list[int]) -> int:
    added = 0
    for vid_id in video_ids:
        if folder.item_count >= FOLDER_ITEMS_MAX:
            raise HTTPException(422, f"「{folder.title}」满了(最多 {FOLDER_ITEMS_MAX} 个)")
        res = await db.execute(insert(FavItem).values(folder_id=folder.id, video_id=vid_id,
                                                      user_id=user_id, created_at=utcnow())
                               .on_conflict_do_nothing())
        if res.rowcount == 1:
            folder.item_count += 1
            added += 1
    if added:
        folder.updated_at = utcnow()
    return added


async def _remove_items(db: AsyncSession, folder: FavFolder, video_ids: list[int]) -> int:
    if not video_ids:
        return 0
    res = await db.execute(delete(FavItem).where(FavItem.folder_id == folder.id,
                                                 FavItem.video_id.in_(video_ids)))
    n = res.rowcount or 0
    folder.item_count = max(0, folder.item_count - n)
    if n:
        folder.updated_at = utcnow()
    return n


async def set_favorite(db: AsyncSession, user: User, v: Video,
                       folder_ids: list[int] | None) -> dict:
    """把这个视频放进哪些收藏夹(给的是**全部**目标收藏夹;空列表 = 取消收藏)。
    不给 folder_ids = 收进默认收藏夹。"""
    if folder_ids is None:
        folder_ids = [(await default_folder(db, user.id)).id]
    target = list(dict.fromkeys(int(x) for x in folder_ids))
    folders = {f.id: f for f in await db.scalars(
        select(FavFolder).where(FavFolder.id.in_(target)).with_for_update()
        .execution_options(populate_existing=True))} if target else {}
    if any(fid not in folders or folders[fid].user_id != user.id for fid in target):
        raise HTTPException(404, "没有这个收藏夹")
    current = set(await db.scalars(select(FavItem.folder_id).where(
        FavItem.user_id == user.id, FavItem.video_id == v.id)))
    before = len(current)
    for fid in target:
        if fid not in current:
            await _add_items(db, user.id, folders[fid], [v.id])
    for fid in current - set(target):
        f = await own_folder(db, user.id, fid, lock=True)
        await _remove_items(db, f, [v.id])
    after = await _user_fav_count(db, user.id, v.id)
    await _fav_counter(db, v.id, before, after)
    favs = await db.scalar(select(Video.favorites).where(Video.id == v.id))
    return {"favorited": after > 0, "folder_ids": sorted(target), "favorites": int(favs or 0)}


async def folder_items(db: AsyncSession, viewer: User | None, folder: FavFolder,
                       before: str | None, limit: int = 20) -> dict:
    """收藏夹里的视频,新收的在前。失效的(删了、下架了、改私密了)显示成「已失效」。"""
    q = (select(FavItem, Video).join(Video, Video.id == FavItem.video_id)
         .where(FavItem.folder_id == folder.id))
    cur = _parse_ts_cursor(before)
    if cur is not None:
        q = q.where(tuple_(FavItem.created_at, FavItem.video_id) < tuple_(*cur))
    rows = (await db.execute(q.order_by(FavItem.created_at.desc(), FavItem.video_id.desc())
                             .limit(limit + 1))).all()
    more = len(rows) > limit
    rows = rows[:limit]
    viewer_id = viewer.id if viewer else None
    ups = await vsvc.people(db, viewer_id, [v.uploader_id for _, v in rows])
    items = []
    for it, v in rows:
        ok = vsvc.can_view(v, viewer) and v.status == "published"
        items.append({"video": vsvc.card(v, ups.get(v.uploader_id)) if ok else
                      {"vid": v.vid, "title": "视频已失效", "cover": "", "invalid": True},
                      "added_at": vsvc.iso(it.created_at)})
    return {"folder": folder_out(folder), "items": items,
            "next_cursor": _ts_cursor(rows[-1][0].created_at, rows[-1][0].video_id)
            if more and rows else None}


async def move_items(db: AsyncSession, user: User, src: FavFolder, dst_id: int | None,
                     vids: list[str]) -> dict:
    """把几个视频从一个收藏夹挪到另一个(dst_id 为空 = 从这个收藏夹移除)。"""
    videos = list(await db.scalars(select(Video).where(Video.vid.in_(vids))))
    ids = [v.id for v in videos]
    befores = {vid_id: await _user_fav_count(db, user.id, vid_id) for vid_id in ids}
    moved = await _remove_items(db, src, ids)
    if dst_id is not None:
        dst = await own_folder(db, user.id, dst_id, lock=True)
        await _add_items(db, user.id, dst, ids)
    for vid_id in ids:
        await _fav_counter(db, vid_id, befores[vid_id], await _user_fav_count(db, user.id, vid_id))
    return {"moved": moved}


async def delete_folder(db: AsyncSession, user: User, f: FavFolder) -> None:
    if f.is_default:
        raise HTTPException(422, "默认收藏夹不能删除")
    ids = list(await db.scalars(select(FavItem.video_id).where(FavItem.folder_id == f.id)))
    befores = {i: await _user_fav_count(db, user.id, i) for i in ids}
    await db.execute(delete(FavItem).where(FavItem.folder_id == f.id))
    await db.delete(f)
    await db.flush()
    for i in ids:
        await _fav_counter(db, i, befores[i], await _user_fav_count(db, user.id, i))


# ---------------- 分享 ----------------

async def share(db: AsyncSession, user: User, v: Video, channel: str) -> dict:
    channel = channel if channel in SHARE_CHANNELS else "other"
    res = await db.execute(
        insert(VideoShare).values(video_id=v.id, user_id=user.id, channel=channel, times=1,
                                  created_at=utcnow())
        .on_conflict_do_update(index_elements=["video_id", "user_id"],
                               set_={"times": VideoShare.times + 1, "channel": channel})
        .returning(VideoShare.times))
    if res.scalar() == 1:  # 这个人第一次分享它:计数 +1(排序只算一次)
        await db.execute(update(Video).where(Video.id == v.id).values(shares=Video.shares + 1)
                         .execution_options(synchronize_session=False))
        await vsvc.bump_stat(db, v.id, shares=1)
    n = await db.scalar(select(Video.shares).where(Video.id == v.id))
    return {"shares": int(n or 0), "link": f"{vsvc.PUBLIC_BASE}/v/{v.vid}"}


# ---------------- 三连 ----------------

async def triple(db: AsyncSession, user: User, v: Video) -> dict:
    """长按三连:赞 + 投满(自制 2 / 转载 1,余额不够就投能投的)+ 收进默认收藏夹。
    已经做过的那一项跳过;自己的视频不投币。"""
    liked = await set_like(db, user, v, True)
    coins_given = 0
    coin_note = ""
    if user.id != v.uploader_id:
        from ..models import VideoCoin
        have = await db.get(VideoCoin, (v.id, user.id))
        cap = vsvc.COIN_MAX.get(v.copyright, 1)
        want = cap - (have.amount if have else 0)
        prof = await ensure_profile(db, user.id)
        bal = await db.scalar(select(SocialProfile.coins).where(SocialProfile.user_id == user.id))
        amount = min(want, int(bal or prof.coins or 0))
        if amount > 0:
            await vsvc.give_coins(db, user, v, amount)
            coins_given = amount
            coin_note = "" if amount == want else "硬币不够,只投了一部分"
        elif want > 0:
            coin_note = "硬币不够了"
    else:
        coin_note = "自己的视频不能投币"
    folders = set(await db.scalars(select(FavItem.folder_id).where(
        FavItem.user_id == user.id, FavItem.video_id == v.id)))
    if not folders:
        fav = await set_favorite(db, user, v, None)
    else:
        fav = {"favorited": True, "folder_ids": sorted(folders)}
    v2 = await db.scalar(select(Video).where(Video.id == v.id)
                         .execution_options(populate_existing=True))
    me = await vsvc.my_state(db, user.id, v2)
    return {"liked": liked["liked"], "coins_given": coins_given, "coin_note": coin_note,
            "favorited": fav["favorited"], "likes": v2.likes, "coins": v2.coins,
            "favorites": v2.favorites, "me": me}


# ---------------- 播放计数与历史 ----------------

def viewer_key(user: User | None, device_id: str, fallback: str) -> str:
    """同一个人(没登录按设备)。设备号是客户端给的,只拿来去重,哈希后再存。"""
    if user is not None:
        return f"u{user.id}"
    raw = (device_id or "").strip()[:64] or fallback
    return "d" + hashlib.sha256(f"superz-viewer:{raw}".encode()).hexdigest()[:32]


def view_counts(played_ms: int, duration_ms: int) -> bool:
    """看满 5 秒或 30% 才算一次播放(§5.9)。纯函数。"""
    if played_ms >= VIEW_MIN_MS:
        return True
    return duration_ms > 0 and played_ms >= duration_ms * VIEW_MIN_RATIO


async def history_paused(db: AsyncSession, user_id: int) -> bool:
    s = await db.get(VideoUserSetting, user_id)
    return bool(s and s.history_paused)


async def record_view(db: AsyncSession, user: User | None, v: Video, *, part: VideoPart | None,
                      position_ms: int, played_ms: int, key: str) -> dict:
    """播放心跳(每 15 秒一次):记历史(登录了、没暂停),够门槛就计一次播放(每人每天一次)。"""
    dur = part.duration_ms if part is not None else v.duration_ms
    counted = False
    if view_counts(played_ms, dur):
        res = await db.execute(insert(VideoViewDay).values(
            video_id=v.id, day=vsvc.bj_day(), viewer_key=key, created_at=utcnow())
            .on_conflict_do_nothing())
        if res.rowcount == 1:
            counted = True
            await db.execute(update(Video).where(Video.id == v.id).values(views=Video.views + 1)
                             .execution_options(synchronize_session=False))
            await vsvc.bump_stat(db, v.id, views=1)
    if user is not None and not await history_paused(db, user.id):
        pos = max(0, min(int(position_ms), dur or int(position_ms)))
        await db.execute(insert(WatchHistory).values(
            user_id=user.id, video_id=v.id, part_idx=part.idx if part is not None else 0,
            position_ms=pos, duration_ms=dur, watched_at=utcnow())
            .on_conflict_do_update(index_elements=["user_id", "video_id"],
                                   set_={"part_idx": part.idx if part is not None else 0,
                                         "position_ms": pos, "duration_ms": dur,
                                         "watched_at": utcnow()}))
    views = await db.scalar(select(Video.views).where(Video.id == v.id))
    return {"counted": counted, "views": int(views or 0)}


def _ts_cursor(ts: datetime, vid_id: int) -> str:
    return f"{int(ts.timestamp() * 1_000_000)}_{vid_id}"


def _parse_ts_cursor(cursor: str | None):
    if not cursor:
        return None
    try:
        a, b = cursor.split("_", 1)
        return datetime.fromtimestamp(int(a) / 1_000_000, tz=timezone.utc), int(b)
    except (ValueError, OverflowError):
        return None


async def history_page(db: AsyncSession, user: User, cursor: str | None, limit: int = 20) -> dict:
    q = (select(WatchHistory, Video).join(Video, Video.id == WatchHistory.video_id)
         .where(WatchHistory.user_id == user.id))
    cur = _parse_ts_cursor(cursor)
    if cur is not None:
        q = q.where(tuple_(WatchHistory.watched_at, WatchHistory.video_id) < tuple_(*cur))
    rows = (await db.execute(q.order_by(WatchHistory.watched_at.desc(),
                                        WatchHistory.video_id.desc()).limit(limit + 1))).all()
    more = len(rows) > limit
    rows = rows[:limit]
    ups = await vsvc.people(db, user.id, [v.uploader_id for _, v in rows])
    items = []
    for h, v in rows:
        ok = vsvc.can_view(v, user)
        items.append({"video": vsvc.card(v, ups.get(v.uploader_id)) if ok else
                      {"vid": v.vid, "title": "视频已失效", "cover": "", "invalid": True},
                      "part_idx": h.part_idx, "position_ms": h.position_ms,
                      "duration_ms": h.duration_ms, "watched_at": vsvc.iso(h.watched_at)})
    return {"items": items, "paused": await history_paused(db, user.id),
            "next_cursor": _ts_cursor(rows[-1][0].watched_at, rows[-1][0].video_id)
            if more and rows else None}


async def set_settings(db: AsyncSession, user: User, *, personalize: bool | None,
                       history_paused_: bool | None) -> dict:
    prof = await ensure_profile(db, user.id)
    if personalize is not None:
        prof.personalize_video = personalize
    if history_paused_ is not None:
        await db.execute(insert(VideoUserSetting).values(user_id=user.id,
                                                         history_paused=history_paused_)
                         .on_conflict_do_update(index_elements=["user_id"],
                                                set_={"history_paused": history_paused_}))
    return await get_settings(db, user)


async def get_settings(db: AsyncSession, user: User) -> dict:
    prof = await ensure_profile(db, user.id)
    return {"personalize": prof.personalize_video,
            "history_paused": await history_paused(db, user.id)}


# ---------------- 关注 ----------------

async def set_follow(db: AsyncSession, user: User, target_id: int, follow: bool) -> dict:
    if target_id == user.id:
        raise HTTPException(422, "不能关注自己")
    t = await db.get(User, target_id)
    if t is None or t.deleted_at is not None or t.role not in (UserRole.customer, UserRole.bot):
        raise HTTPException(404, "没有这个用户")
    if follow:
        if await blocked_between(db, user.id, target_id):
            raise HTTPException(403, "你们之间有拉黑关系,不能关注")
        await db.execute(insert(Follow).values(follower_id=user.id, followee_id=target_id,
                                               created_at=utcnow()).on_conflict_do_nothing())
    else:
        await db.execute(delete(Follow).where(Follow.follower_id == user.id,
                                              Follow.followee_id == target_id))
    fans, _ = await vsvc.follow_counts(db, target_id)
    return {"followed": follow, "fans": fans}


async def follow_page(db: AsyncSession, viewer: User | None, user_id: int, *, fans: bool,
                      cursor: str | None, limit: int = 20) -> dict:
    """关注列表(fans=False)或粉丝列表(fans=True),新关注的在前。"""
    me_col, other_col = (Follow.followee_id, Follow.follower_id) if fans else \
        (Follow.follower_id, Follow.followee_id)
    q = select(Follow).where(me_col == user_id)
    cur = _parse_ts_cursor(cursor)
    if cur is not None:
        q = q.where(tuple_(Follow.created_at, other_col) < tuple_(*cur))
    rows = list(await db.scalars(q.order_by(Follow.created_at.desc(), other_col.desc())
                                 .limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    ids = [(r.follower_id if fans else r.followee_id) for r in rows]
    viewer_id = viewer.id if viewer else None
    cards = await vsvc.people(db, viewer_id, ids)
    mine = set(await db.scalars(select(Follow.followee_id).where(
        Follow.follower_id == viewer_id, Follow.followee_id.in_(ids)))) if viewer_id and ids \
        else set()
    profiles = {p.user_id: p for p in await db.scalars(
        select(SocialProfile).where(SocialProfile.user_id.in_(ids)))} if ids else {}
    items = []
    for r, uid in zip(rows, ids):
        c = cards.get(uid)
        if c is None:
            continue
        p = profiles.get(uid)
        items.append({**c, "bio": (p.bio if p else "") or "", "followed": uid in mine,
                      "since": vsvc.iso(r.created_at)})
    last = rows[-1] if rows else None
    return {"items": items,
            "next_cursor": _ts_cursor(last.created_at, last.follower_id if fans else
                                      last.followee_id) if more and last else None}


# ---------------- 稍后再看、不感兴趣 ----------------

async def add_watch_later(db: AsyncSession, user: User, v: Video) -> None:
    n = await db.scalar(select(func.count()).select_from(WatchLater)
                        .where(WatchLater.user_id == user.id))
    if (n or 0) >= WATCH_LATER_MAX:
        raise HTTPException(422, f"稍后再看最多 {WATCH_LATER_MAX} 个,先看掉几个吧")
    await db.execute(insert(WatchLater).values(user_id=user.id, video_id=v.id,
                                               created_at=utcnow()).on_conflict_do_nothing())


async def watch_later_page(db: AsyncSession, user: User) -> dict:
    rows = (await db.execute(select(WatchLater, Video).join(Video, Video.id == WatchLater.video_id)
                             .where(WatchLater.user_id == user.id)
                             .order_by(WatchLater.created_at.desc(), WatchLater.video_id.desc())
                             )).all()
    ups = await vsvc.people(db, user.id, [v.uploader_id for _, v in rows])
    items = []
    for w, v in rows:
        ok = vsvc.can_view(v, user)
        items.append({"video": vsvc.card(v, ups.get(v.uploader_id)) if ok else
                      {"vid": v.vid, "title": "视频已失效", "cover": "", "invalid": True},
                      "added_at": vsvc.iso(w.created_at)})
    return {"items": items, "count": len(items), "max": WATCH_LATER_MAX}


async def not_interested(db: AsyncSession, user: User, v: Video) -> None:
    await db.execute(insert(VideoNotInterested).values(user_id=user.id, video_id=v.id,
                                                       created_at=utcnow())
                     .on_conflict_do_nothing())


async def recent_watched(db: AsyncSession, user_id: int, since: datetime) -> list[WatchHistory]:
    return list(await db.scalars(select(WatchHistory).where(
        WatchHistory.user_id == user_id, WatchHistory.watched_at >= since)))

