"""音乐榜单、每日推荐、推荐歌单的排序(DEV-PROMPTS-41 §5.4)。**公开,算分是纯函数。**

公式原文(和 docs/DEV-PROMPTS-41.md §5.4 逐字一致,tests/unit/test_music_rank.py 对着文档比):

```text
收听人数:听满 min(30 秒, 时长一半) 算一次收听,按人去重(登录用户按账号,没登录按设备)
热歌榜分数 = 近7天收听人数 + 3 × 近7天新增喜欢人数 + 5 × 近7天加入歌单人数
新歌榜:只收发布 14 天内的歌,分数 = 近7天收听人数 + 3 × 近7天新增喜欢人数
飙升榜:近24小时收听人数 L 至少 5 人才上榜,分数 = (L − 前24小时收听人数 P) ÷ max(P, 5)
同分按发布时间新的在前,再按歌曲编号;每个榜最多 100 首,同一位音乐人在一个榜里最多 10 首
每日推荐分数 = 热歌榜分数 + 20 × min(我近30天喜欢或听过的同曲风歌数, 10) + 200 × [我关注了这位音乐人] + 20 × min(我喜欢过这位音乐人的歌数, 5)
每日推荐取前 20 首,近7天听过的不推,同一位音乐人最多 3 首;关掉个性化后只按热歌榜分数
推荐歌单分数 = 5 × 近30天新增收藏人数 + 总收藏人数;至少 5 首歌的公开歌单才推荐
```

为什么输入这么少(§3.1 不收钱、§3.5 公式公开):

- 算分只吃**公开的**东西 —— 按人去重的收听 / 喜欢 / 加歌单数、发布时间、音乐人是谁、曲风;
  个性化再加三个我自己的数(同曲风听过几首、关注没有、喜欢过他几首)。
  **没有任何付费、运营加权的入口**:这里加一个字段,单测就红;
- 每一项都带着算出它的那几个数(`rank: {score, parts, why}`),客户端「为什么在榜上」直接展示,
  谁都能拿计算器复算;
- 「按人去重」由取数那一层保证(下面几个 SQL 都是 COUNT(DISTINCT listener_key / user_id)),
  算分函数只管算。
"""
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

FORMULA = """收听人数:听满 min(30 秒, 时长一半) 算一次收听,按人去重(登录用户按账号,没登录按设备)
热歌榜分数 = 近7天收听人数 + 3 × 近7天新增喜欢人数 + 5 × 近7天加入歌单人数
新歌榜:只收发布 14 天内的歌,分数 = 近7天收听人数 + 3 × 近7天新增喜欢人数
飙升榜:近24小时收听人数 L 至少 5 人才上榜,分数 = (L − 前24小时收听人数 P) ÷ max(P, 5)
同分按发布时间新的在前,再按歌曲编号;每个榜最多 100 首,同一位音乐人在一个榜里最多 10 首
每日推荐分数 = 热歌榜分数 + 20 × min(我近30天喜欢或听过的同曲风歌数, 10) + 200 × [我关注了这位音乐人] + 20 × min(我喜欢过这位音乐人的歌数, 5)
每日推荐取前 20 首,近7天听过的不推,同一位音乐人最多 3 首;关掉个性化后只按热歌榜分数
推荐歌单分数 = 5 × 近30天新增收藏人数 + 总收藏人数;至少 5 首歌的公开歌单才推荐"""

# ---- 收听门槛(§5.5 的判据也是它)----
#: 听满 min(30 秒, 时长一半)
LISTEN_MIN_MS = 30_000
LISTEN_MIN_RATIO = 0.5
#: 同一个人同一首歌 30 分钟内只算一次
LISTEN_DEDUP_MINUTES = 30

# ---- 榜单 ----
HOT_WINDOW_DAYS = 7
LIKE_WEIGHT = 3
PLAYLIST_WEIGHT = 5
NEW_RELEASE_DAYS = 14
RISING_WINDOW_HOURS = 24
#: 近 24 小时至少这么多人听过才上飙升榜(基数太小的涨幅没有意义)
RISING_MIN_LISTENERS = 5
#: 分母的下限:前 24 小时 0 个人也不能除以 0
RISING_FLOOR = 5
CHART_SIZE = 100
PER_ARTIST_PER_CHART = 10

# ---- 每日推荐 ----
DAILY_SIZE = 20
DAILY_PER_ARTIST = 3
DAILY_LOOKBACK_DAYS = 30
DAILY_SKIP_RECENT_DAYS = 7
GENRE_WEIGHT = 20
GENRE_CAP = 10
FOLLOW_BONUS = 200
ARTIST_LIKE_WEIGHT = 20
ARTIST_LIKE_CAP = 5

# ---- 推荐歌单 ----
PLAYLIST_RECENT_DAYS = 30
PLAYLIST_RECENT_WEIGHT = 5
PLAYLIST_MIN_TRACKS = 5

#: `/music/v1/rank/formula` 原样返回这一份。公式里出现的每个数字都在这里
PARAMS: dict[str, float] = {
    "listen_min_ms": LISTEN_MIN_MS,
    "listen_min_ratio": LISTEN_MIN_RATIO,
    "listen_dedup_minutes": LISTEN_DEDUP_MINUTES,
    "hot_window_days": HOT_WINDOW_DAYS,
    "like_weight": LIKE_WEIGHT,
    "playlist_weight": PLAYLIST_WEIGHT,
    "new_release_days": NEW_RELEASE_DAYS,
    "rising_window_hours": RISING_WINDOW_HOURS,
    "rising_min_listeners": RISING_MIN_LISTENERS,
    "rising_floor": RISING_FLOOR,
    "chart_size": CHART_SIZE,
    "per_artist_per_chart": PER_ARTIST_PER_CHART,
    "daily_size": DAILY_SIZE,
    "daily_per_artist": DAILY_PER_ARTIST,
    "daily_lookback_days": DAILY_LOOKBACK_DAYS,
    "daily_skip_recent_days": DAILY_SKIP_RECENT_DAYS,
    "genre_weight": GENRE_WEIGHT,
    "genre_cap": GENRE_CAP,
    "follow_bonus": FOLLOW_BONUS,
    "artist_like_weight": ARTIST_LIKE_WEIGHT,
    "artist_like_cap": ARTIST_LIKE_CAP,
    "playlist_recent_days": PLAYLIST_RECENT_DAYS,
    "playlist_recent_weight": PLAYLIST_RECENT_WEIGHT,
    "playlist_min_tracks": PLAYLIST_MIN_TRACKS,
}

#: 三个榜(§8.2 的 key)
CHARTS = {"hot": "热歌榜", "new": "新歌榜", "rising": "飙升榜"}


# ---------------- 纯函数(单测逐条锁住)----------------

def listen_threshold_ms(duration_ms: int) -> int:
    """听满多久算一次收听:min(30 秒, 时长一半)。"""
    return min(LISTEN_MIN_MS, int(max(0, duration_ms) * LISTEN_MIN_RATIO))


def counted(ms_listened: int, duration_ms: int) -> bool:
    """这次上报算不算一次收听(时长为 0 的歌 —— 还没转码完 —— 一律不算)。"""
    if duration_ms <= 0:
        return False
    return ms_listened >= listen_threshold_ms(duration_ms)


def hot_score(listeners: int, likers: int, playlisters: int) -> float:
    """热歌榜分数 = 近7天收听人数 + 3 × 近7天新增喜欢人数 + 5 × 近7天加入歌单人数"""
    return listeners + LIKE_WEIGHT * likers + PLAYLIST_WEIGHT * playlisters


def new_score(listeners: int, likers: int) -> float:
    """新歌榜分数 = 近7天收听人数 + 3 × 近7天新增喜欢人数"""
    return listeners + LIKE_WEIGHT * likers


def rising_eligible(listeners_24h: int) -> bool:
    """近24小时收听人数 L 至少 5 人才上榜。"""
    return listeners_24h >= RISING_MIN_LISTENERS


def rising_score(listeners_24h: int, prev_24h: int) -> float:
    """飙升榜分数 = (L − 前24小时收听人数 P) ÷ max(P, 5)"""
    return (listeners_24h - prev_24h) / max(prev_24h, RISING_FLOOR)


def daily_score(hot: float, genre_hits: int, followed: bool, artist_likes: int) -> float:
    """每日推荐分数 = 热歌榜分数 + 20 × min(同曲风歌数, 10) + 200 × [关注了] + 20 × min(喜欢过他几首, 5)

    关掉个性化时调用方把后三个都传 0 / False(「只按热歌榜分数」)。
    """
    return (hot
            + GENRE_WEIGHT * min(max(0, genre_hits), GENRE_CAP)
            + FOLLOW_BONUS * bool(followed)
            + ARTIST_LIKE_WEIGHT * min(max(0, artist_likes), ARTIST_LIKE_CAP))


def playlist_score(recent_collectors: int, total_collects: int) -> float:
    """推荐歌单分数 = 5 × 近30天新增收藏人数 + 总收藏人数"""
    return PLAYLIST_RECENT_WEIGHT * recent_collectors + total_collects


def order_key(score: float, published_at: datetime | None, track_id: int) -> tuple:
    """分高的在前;同分时发布时间新的在前;再同就按歌曲编号 —— 保证同一分钟内两次请求逐条相等。"""
    ts = published_at.timestamp() if published_at is not None else 0.0
    return (-score, -ts, -track_id)


def cap_per_artist(items: Iterable, artist_of: Callable, *, cap: int, size: int) -> list:
    """按排好的顺序取前 size 个,同一位音乐人最多 cap 个。

    超出的**丢掉**,不像视频推荐那样顺延到下一屏 —— 榜是一张固定长度的表,
    不是无限往下翻的流,一个人占满十个位置之后剩下的就该让给别人。
    """
    out: list = []
    seen: dict = {}
    for it in items:
        a = artist_of(it)
        if seen.get(a, 0) >= cap:
            continue
        out.append(it)
        seen[a] = seen.get(a, 0) + 1
        if len(out) >= size:
            break
    return out


def hot_why(listeners: int, likers: int, playlisters: int) -> str:
    bits = [f"近 7 天 {listeners} 人收听"]
    if likers:
        bits.append(f"{likers} 人喜欢")
    if playlisters:
        bits.append(f"{playlisters} 人加入歌单")
    return "、".join(bits)


def rising_why(listeners: int, prev: int) -> str:
    return f"近 24 小时 {listeners} 人收听,前 24 小时 {prev} 人"


def rank_out(score: float, parts: dict, why: str) -> dict:
    """每一项下发的 rank(§5.4「每一项都下发 rank: {score, parts, why}」)。"""
    return {"score": round(float(score), 4), "parts": parts, "why": why}


# ---------------- 取数(按人去重的 SQL)----------------

def _utcnow() -> datetime:
    from .video import utcnow
    return utcnow()


async def _published_track_rows(db: AsyncSession, *, genre: str | None = None,
                                since_published: datetime | None = None) -> dict[int, dict]:
    """在榜候选:已发布作品里、转码好了的歌。返回 {track_id: {artist_id, published_at, genre}}。"""
    from ..models import MusicArtist, MusicRelease, MusicTrack

    q = (select(MusicTrack.id, MusicTrack.artist_id, MusicArtist.user_id,
                MusicRelease.published_at, MusicRelease.genre)
         .join(MusicRelease, MusicRelease.id == MusicTrack.release_id)
         .join(MusicArtist, MusicArtist.id == MusicTrack.artist_id)
         .where(MusicRelease.status == "published", MusicRelease.deleted_at.is_(None),
                MusicArtist.status == "active", MusicTrack.transcode_status == "ready"))
    if genre:
        q = q.where(MusicRelease.genre == genre)
    if since_published is not None:
        q = q.where(MusicRelease.published_at >= since_published)
    return {tid: {"artist_id": aid, "artist_user_id": uid, "published_at": pub, "genre": g}
            for tid, aid, uid, pub, g in (await db.execute(q)).all()}


async def _listeners(db: AsyncSession, track_ids, since: datetime,
                     until: datetime | None = None) -> dict[int, int]:
    """时间窗里每首歌的收听**人数**(按 listener_key 去重,登录按账号、没登录按设备)。"""
    from ..models import MusicPlay

    if not track_ids:
        return {}
    q = (select(MusicPlay.track_id, func.count(func.distinct(MusicPlay.listener_key)))
         .where(MusicPlay.track_id.in_(track_ids), MusicPlay.created_at >= since))
    if until is not None:
        q = q.where(MusicPlay.created_at < until)
    return {t: int(n) for t, n in (await db.execute(q.group_by(MusicPlay.track_id))).all()}


async def _likers(db: AsyncSession, track_ids, since: datetime) -> dict[int, int]:
    """喜欢的**人数**。**AI 号不算**(#385):榜单公式是公开可复算的,
    把自己生成的互动算进去等于自己骗自己。"""
    from ..models import MusicTrackLike, User

    if not track_ids:
        return {}
    rows = (await db.execute(
        select(MusicTrackLike.track_id, func.count(func.distinct(MusicTrackLike.user_id)))
        .join(User, User.id == MusicTrackLike.user_id)
        .where(MusicTrackLike.track_id.in_(track_ids), MusicTrackLike.created_at >= since,
               User.is_ai.is_(False))
        .group_by(MusicTrackLike.track_id))).all()
    return {t: int(n) for t, n in rows}


async def _playlisters(db: AsyncSession, track_ids, since: datetime) -> dict[int, int]:
    """加进歌单的**人数**:同一个人把一首歌加进十个自己的歌单只算一个(防自刷)。"""
    from ..models import MusicPlaylistTrack

    if not track_ids:
        return {}
    from ..models import User

    rows = (await db.execute(
        select(MusicPlaylistTrack.track_id,
               func.count(func.distinct(MusicPlaylistTrack.added_by)))
        .join(User, User.id == MusicPlaylistTrack.added_by)
        .where(MusicPlaylistTrack.track_id.in_(track_ids),
               MusicPlaylistTrack.added_at >= since,
               MusicPlaylistTrack.added_by.is_not(None),
               # AI 加进歌单不算人头(#385,和喜欢同一条不变量)
               User.is_ai.is_(False))
        .group_by(MusicPlaylistTrack.track_id))).all()
    return {t: int(n) for t, n in rows}


async def hot_scores(db: AsyncSession, *, genre: str | None = None,
                     now: datetime | None = None) -> tuple[dict[int, dict], dict[int, dict]]:
    """热歌榜的分数(曲风页也用它)。返回 (候选行, {track_id: {score, parts, why}})。"""
    now = now or _utcnow()
    since = now - timedelta(days=HOT_WINDOW_DAYS)
    rows = await _published_track_rows(db, genre=genre)
    ids = list(rows)
    listeners = await _listeners(db, ids, since)
    likers = await _likers(db, ids, since)
    playlisters = await _playlisters(db, ids, since)
    scored = {}
    for tid in ids:
        ls, lk, pl = listeners.get(tid, 0), likers.get(tid, 0), playlisters.get(tid, 0)
        scored[tid] = rank_out(hot_score(ls, lk, pl),
                               {"listeners_7d": ls, "likers_7d": lk, "playlisters_7d": pl},
                               hot_why(ls, lk, pl))
    return rows, scored


async def new_scores(db: AsyncSession, now: datetime | None = None
                     ) -> tuple[dict[int, dict], dict[int, dict]]:
    now = now or _utcnow()
    since = now - timedelta(days=HOT_WINDOW_DAYS)
    rows = await _published_track_rows(
        db, since_published=now - timedelta(days=NEW_RELEASE_DAYS))
    ids = list(rows)
    listeners = await _listeners(db, ids, since)
    likers = await _likers(db, ids, since)
    scored = {}
    for tid in ids:
        ls, lk = listeners.get(tid, 0), likers.get(tid, 0)
        scored[tid] = rank_out(new_score(ls, lk), {"listeners_7d": ls, "likers_7d": lk},
                               hot_why(ls, lk, 0))
    return rows, scored


async def rising_scores(db: AsyncSession, now: datetime | None = None
                        ) -> tuple[dict[int, dict], dict[int, dict]]:
    now = now or _utcnow()
    cut = now - timedelta(hours=RISING_WINDOW_HOURS)
    prev_cut = now - timedelta(hours=RISING_WINDOW_HOURS * 2)
    rows = await _published_track_rows(db)
    ids = list(rows)
    cur = await _listeners(db, ids, cut)
    prev = await _listeners(db, ids, prev_cut, cut)
    scored = {}
    for tid in ids:
        L, P = cur.get(tid, 0), prev.get(tid, 0)
        if not rising_eligible(L):
            continue    # 基数太小的涨幅没有意义(§5.4「至少 5 人才上榜」)
        scored[tid] = rank_out(rising_score(L, P),
                               {"listeners_24h": L, "listeners_prev_24h": P,
                                "min_listeners": RISING_MIN_LISTENERS},
                               rising_why(L, P))
    return rows, scored


_CHART_SCORERS = {"hot": hot_scores, "new": new_scores, "rising": rising_scores}


async def chart(db: AsyncSession, key: str, now: datetime | None = None) -> list[tuple[int, dict]]:
    """一个榜的最终名次:[(track_id, rank)],已经按分排好、去过重、截到 100。"""
    rows, scored = await _CHART_SCORERS[key](db, now=now)
    ordered = sorted(scored, key=lambda t: order_key(
        scored[t]["score"], rows[t]["published_at"], t))
    keep = cap_per_artist(ordered, lambda t: rows[t]["artist_id"],
                          cap=PER_ARTIST_PER_CHART, size=CHART_SIZE)
    return [(t, scored[t]) for t in keep]


async def genre_page(db: AsyncSession, genre: str, page: int, per: int = 20
                     ) -> tuple[list[int], dict[int, dict], bool]:
    """一个曲风下的歌,按热歌榜分数排(§8.2 GET /genres/{key}/tracks)。这里不做每人上限 ——
    曲风页是「这个曲风有什么」,不是榜单。"""
    rows, scored = await hot_scores(db, genre=genre)
    ordered = sorted(scored, key=lambda t: order_key(
        scored[t]["score"], rows[t]["published_at"], t))
    chunk = ordered[page * per: page * per + per + 1]
    return chunk[:per], scored, len(chunk) > per


async def daily(db: AsyncSession, user_id: int | None, personalize: bool,
                now: datetime | None = None) -> list[tuple[int, dict]]:
    """每日推荐(§5.4)。关掉个性化 / 没登录时只按热歌榜分数。"""
    from ..models import Follow, MusicHistory, MusicTrackLike

    now = now or _utcnow()
    rows, hot = await hot_scores(db, now=now)
    genre_hits: dict[str, int] = {}
    artist_likes: dict[int, int] = {}
    followed: set[int] = set()
    skip: set[int] = set()
    if user_id and personalize:
        since = now - timedelta(days=DAILY_LOOKBACK_DAYS)
        # 我近 30 天喜欢或听过的歌 → 按曲风计数
        mine = set(await db.scalars(select(MusicTrackLike.track_id).where(
            MusicTrackLike.user_id == user_id, MusicTrackLike.created_at >= since)))
        mine |= set(await db.scalars(select(MusicHistory.track_id).where(
            MusicHistory.user_id == user_id, MusicHistory.played_at >= since)))
        for tid in mine:
            g = (rows.get(tid) or {}).get("genre") or ""
            if g:
                genre_hits[g] = genre_hits.get(g, 0) + 1
        liked_all = set(await db.scalars(select(MusicTrackLike.track_id).where(
            MusicTrackLike.user_id == user_id)))
        for tid in liked_all:
            a = (rows.get(tid) or {}).get("artist_id")
            if a:
                artist_likes[a] = artist_likes.get(a, 0) + 1
        followed = set(await db.scalars(select(Follow.followee_id).where(
            Follow.follower_id == user_id)))
    if user_id:
        # 近 7 天听过的不推(不管个性化开没开:重复推昨天刚听的歌没有意义)
        skip = set(await db.scalars(select(MusicHistory.track_id).where(
            MusicHistory.user_id == user_id,
            MusicHistory.played_at >= now - timedelta(days=DAILY_SKIP_RECENT_DAYS))))
    scored: dict[int, dict] = {}
    for tid, meta in rows.items():
        if tid in skip:
            continue
        base = hot[tid]["score"]
        if user_id and personalize:
            g = meta.get("genre") or ""
            gh = genre_hits.get(g, 0)
            al = artist_likes.get(meta["artist_id"], 0)
            # 关注的是音乐人背后的**用户**(#377 关注全站一张表),不是 music_artists 行
            fo = meta["artist_user_id"] in followed
        else:
            gh, al, fo = 0, 0, False
        s = daily_score(base, gh, fo, al)
        scored[tid] = rank_out(s, {**hot[tid]["parts"], "hot": base, "genre_hits_30d": gh,
                                   "followed": bool(fo), "artist_likes": al},
                               hot[tid]["why"] + ("、你关注了这位音乐人" if fo else ""))
    ordered = sorted(scored, key=lambda t: order_key(
        scored[t]["score"], rows[t]["published_at"], t))
    keep = cap_per_artist(ordered, lambda t: rows[t]["artist_id"],
                          cap=DAILY_PER_ARTIST, size=DAILY_SIZE)
    return [(t, scored[t]) for t in keep]


async def recommended_playlists(db: AsyncSession, page: int, per: int = 20
                                ) -> tuple[list[int], dict[int, dict], bool]:
    """推荐歌单(§5.4):至少 5 首歌的公开歌单。"""
    from ..models import MusicPlaylist, MusicPlaylistCollect

    now = _utcnow()
    since = now - timedelta(days=PLAYLIST_RECENT_DAYS)
    rows = list(await db.scalars(select(MusicPlaylist).where(
        MusicPlaylist.deleted_at.is_(None), MusicPlaylist.is_public.is_(True),
        MusicPlaylist.track_count >= PLAYLIST_MIN_TRACKS)))
    ids = [p.id for p in rows]
    recent = {}
    if ids:
        recent = {p: int(n) for p, n in (await db.execute(
            select(MusicPlaylistCollect.playlist_id,
                   func.count(func.distinct(MusicPlaylistCollect.user_id)))
            .where(MusicPlaylistCollect.playlist_id.in_(ids),
                   MusicPlaylistCollect.created_at >= since)
            .group_by(MusicPlaylistCollect.playlist_id))).all()}
    scored = {}
    for p in rows:
        rc = recent.get(p.id, 0)
        scored[p.id] = rank_out(playlist_score(rc, p.collects),
                                {"recent_collectors_30d": rc, "collects": p.collects},
                                f"近 30 天 {rc} 人收藏,共 {p.collects} 人收藏")
    ordered = sorted(scored, key=lambda p: (-scored[p]["score"], -p))
    chunk = ordered[page * per: page * per + per + 1]
    return chunk[:per], scored, len(chunk) > per
