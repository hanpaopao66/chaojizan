"""推荐 / 热门 / 竖屏流 / 分区 / 排行榜 / 相关 / 搜索 / 热搜 / UP 主空间(#363–#366)。

排序公式本身在 video_rank.py(纯函数);这里只做两件事:**取数**和**过滤**。

- 取数:七种互动在时间窗里按人去重的个数,直接从明细表数(window_counts)。计数列只用来展示;
- 个性化(S9):登录了、且 `personalize_video` 开着,才用三样和「我」有关的东西 ——
  关注的 UP 主、近 30 天常看的分区、看过 >50% 的(7 天内不再推)和「不感兴趣」。
  **关掉之后一样都不用**,推荐的结果和没登录的人逐条相等(e2e_video_feed 断言);
- 「现在」取整到分钟:同一分钟里两次请求算出来的热度一模一样,排序是确定的,也方便以后加缓存;
- 输入只有公开字段(S3),没有任何能买的位置。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Follow, SearchTerm, SearchTermUser, SocialProfile, User, UserRole, Video,
                      VideoNotInterested, WatchHistory)
from . import video as vsvc
from . import video_rank as rank
from .social import ensure_profile, username_searchable

PAGE = rank.SCREEN_SIZE
#: 热搜门槛:24 小时内至少 5 个不同的人搜过(§2.2,防刷)
HOT_TERM_MIN_USERS = 5
HOT_TERM_WINDOW = timedelta(hours=24)
HOT_TERMS_MAX = 10
TERM_MAX = 32
#: 搜索的时长筛选(分钟):1 = 0–10、2 = 10–30、3 = 30–60、4 = 60 以上
DURATION_FILTERS = {1: (0, 10), 2: (10, 30), 3: (30, 60), 4: (60, None)}
SEARCH_ORDERS = ("default", "views", "new", "danmaku")
LEADERBOARD_MAX = 100


def ranked_now() -> datetime:
    """「现在」取整到分钟。"""
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


#: **AI 的互动不进公开排序**(#385,和论坛同一条不变量)。
#: 浏览那一条按 viewer_key 去重(可能是没登录的人),没有 user_id 可判,所以不挂 —— 
#: AI 也不会去"看"视频,它没有播放器。
_NOT_AI = "NOT EXISTS (SELECT 1 FROM users u WHERE u.id = user_id AND u.is_ai)"

_WINDOW_SQL = f"""
SELECT video_id, 'views' AS k, count(DISTINCT viewer_key) AS n
  FROM video_view_days WHERE created_at >= :since GROUP BY video_id
UNION ALL
SELECT video_id, 'likes', count(DISTINCT user_id) FROM video_likes
 WHERE created_at >= :since AND {_NOT_AI} GROUP BY video_id
UNION ALL
SELECT video_id, 'coins', count(DISTINCT user_id) FROM video_coins
 WHERE created_at >= :since AND {_NOT_AI} GROUP BY video_id
UNION ALL
SELECT video_id, 'favorites', count(DISTINCT user_id) FROM fav_items
 WHERE created_at >= :since AND {_NOT_AI} GROUP BY video_id
UNION ALL
SELECT video_id, 'comments', count(DISTINCT user_id) FROM video_comments
 WHERE created_at >= :since AND deleted_at IS NULL AND {_NOT_AI} GROUP BY video_id
UNION ALL
SELECT video_id, 'danmaku', count(DISTINCT user_id) FROM danmaku
 WHERE created_at >= :since AND deleted_at IS NULL AND {_NOT_AI} GROUP BY video_id
UNION ALL
SELECT video_id, 'shares', count(DISTINCT user_id) FROM video_shares
 WHERE created_at >= :since AND {_NOT_AI} GROUP BY video_id
"""


async def window_counts(db: AsyncSession, since: datetime) -> dict[int, rank.Counts]:
    """时间窗里每个视频的七种互动,每种按人去重(同一个人对同一个视频每种互动只算一次)。

    明细表各自带 created_at 索引;窗口外的行根本不碰。赞、币、藏、分享本来就一人一行(或按人去重),
    播放按 viewer_key 去重(一个人三天看了三次,窗口里也只算一个人)。
    """
    rows = (await db.execute(sql_text(_WINDOW_SQL), {"since": since})).all()
    acc: dict[int, dict[str, int]] = {}
    for vid_id, k, n in rows:
        acc.setdefault(vid_id, {})[k] = int(n)
    return {vid_id: rank.Counts(**d) for vid_id, d in acc.items()}


def _listed_filter(*, zone: str | None = None, vertical: bool | None = None) -> list:
    conds = [Video.status == "published", Video.visibility == "public",
             Video.deleted_at.is_(None), Video.published_at.is_not(None)]
    if zone:
        conds.append(Video.zone == zone)
    if vertical is not None:
        conds.append(Video.is_vertical.is_(vertical))
    return conds


@dataclass
class Personal:
    on: bool = False
    followed: frozenset = frozenset()
    top_zones: frozenset = frozenset()
    exclude: frozenset = frozenset()


async def personal_of(db: AsyncSession, viewer: User | None, now: datetime) -> Personal:
    """这个人的个性化信号。没登录 / 关了个性化:什么都没有(S9)。"""
    if viewer is None:
        return Personal()
    prof = await ensure_profile(db, viewer.id)
    if not prof.personalize_video:
        return Personal()
    followed = frozenset(await db.scalars(select(Follow.followee_id)
                                          .where(Follow.follower_id == viewer.id)))
    zone_rows = (await db.execute(
        select(Video.zone, func.count()).join(WatchHistory, WatchHistory.video_id == Video.id)
        .where(WatchHistory.user_id == viewer.id,
               WatchHistory.watched_at >= now - timedelta(days=rank.ZONE_LOOKBACK_DAYS),
               Video.zone != "")
        .group_by(Video.zone).order_by(func.count().desc(), Video.zone)
        .limit(rank.TOP_ZONES))).all()
    watched = (await db.execute(select(WatchHistory.video_id, WatchHistory.position_ms,
                                       WatchHistory.duration_ms).where(
        WatchHistory.user_id == viewer.id,
        WatchHistory.watched_at >= now - timedelta(days=rank.WATCHED_SKIP_DAYS)))).all()
    skip = {vid_id for vid_id, pos, dur in watched if rank.watched_enough(pos, dur)}
    skip |= set(await db.scalars(select(VideoNotInterested.video_id)
                                 .where(VideoNotInterested.user_id == viewer.id)))
    return Personal(on=True, followed=followed, top_zones=frozenset(z for z, _ in zone_rows),
                    exclude=frozenset(skip))


def why(b: dict, up_name: str, zone_name: str) -> list[str]:
    """「为什么推荐」:把公式里起作用的每一项用人话说出来。"""
    out = []
    if b["followed"]:
        out.append(f"你关注了 UP 主「{up_name}」(推荐分 × {1 + rank.FOLLOW_BONUS:g} 的那一项)")
    if b["top_zone"]:
        out.append(f"「{zone_name}」是你近 {rank.ZONE_LOOKBACK_DAYS} 天最常看的分区之一"
                   f"(+{rank.ZONE_BONUS:g})")
    out.append(f"近 {rank.WINDOW_HOURS} 小时互动分 {b['interaction']},发布 {b['hours']:.1f} 小时,"
               f"热度 {b['hot']:.4g}")
    return out


async def _scored(db: AsyncSession, now: datetime, since: datetime, conds: list,
                  look_ahead: int, exclude: frozenset = frozenset()) -> list[tuple[Video, rank.Counts]]:
    """候选:窗口里有互动的全部 + 没有互动的最新 look_ahead 个(它们互动分是 0,按发布时间排在后面)。"""
    counts = await window_counts(db, since)
    active = list(await db.scalars(select(Video).where(*conds, Video.id.in_(list(counts))))) \
        if counts else []
    seen = {v.id for v in active}
    q = select(Video).where(*conds)
    if seen:
        q = q.where(Video.id.notin_(seen))
    quiet = list(await db.scalars(q.order_by(Video.published_at.desc(), Video.id.desc())
                                  .limit(look_ahead)))
    return [(v, counts.get(v.id, rank.Counts())) for v in active + quiet if v.id not in exclude]


async def _items(db: AsyncSession, viewer_id: int | None, rows: list[tuple[Video, dict]]) -> list[dict]:
    ups = await vsvc.people(db, viewer_id, [v.uploader_id for v, _ in rows])
    out = []
    for v, b in rows:
        up = ups.get(v.uploader_id)
        item = vsvc.card(v, up)
        item["rank"] = b
        item["why"] = why(b, up["name"] if up else "", vsvc.ZONES.get(v.zone, ""))
        out.append(item)
    return out


async def rank_feed(db: AsyncSession, viewer: User | None, *, mode: str, page: int = 0,
                    zone: str | None = None) -> dict:
    """mode: recommend(推荐)/ vertical(竖屏流,同推荐)/ hot(热门,不个性化、不去重)。"""
    now = ranked_now()
    since = now - timedelta(hours=rank.WINDOW_HOURS)
    personal = await personal_of(db, viewer, now) if mode in ("recommend", "vertical") \
        else Personal()
    conds = _listed_filter(zone=zone, vertical=True if mode == "vertical" else None)
    pool = await _scored(db, now, since, conds, look_ahead=(page + 2) * PAGE * 3,
                         exclude=personal.exclude)
    scored = []
    for v, counts in pool:
        inp = rank.RankInput(video_id=v.id, uploader_id=v.uploader_id, zone=v.zone,
                             published_at=v.published_at, counts=counts)
        b = rank.breakdown(inp, now, followed=v.uploader_id in personal.followed,
                           top_zone=v.zone in personal.top_zones)
        scored.append((v, b))
    key = "hot" if mode == "hot" else "recommend"
    scored.sort(key=lambda x: rank.order_key(x[1][key], x[0].published_at, x[0].id))
    if mode == "hot":
        chunk = scored[page * PAGE:(page + 1) * PAGE]
        has_more = len(scored) > (page + 1) * PAGE
    else:
        screens = rank.paginate_screens(scored, lambda x: x[0].uploader_id,
                                        max_screens=page + 2)
        chunk = screens[page] if page < len(screens) else []
        has_more = len(screens) > page + 1
    return {"items": await _items(db, viewer.id if viewer else None, chunk), "page": page,
            "has_more": has_more, "personalized": personal.on, "ranked_at": now.isoformat(),
            "sort": key}


async def following_feed(db: AsyncSession, viewer: User, cursor: str | None,
                         limit: int = PAGE) -> dict:
    """关注的 UP 主的新投稿,按发布时间倒序。"""
    q = (select(Video).join(Follow, Follow.followee_id == Video.uploader_id)
         .where(Follow.follower_id == viewer.id, *_listed_filter()))
    cur = _parse_cursor(cursor)
    if cur is not None:
        q = q.where(tuple_(Video.published_at, Video.id) < tuple_(*cur))
    rows = list(await db.scalars(q.order_by(Video.published_at.desc(), Video.id.desc())
                                 .limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": await vsvc.cards(db, viewer.id, rows),
            "next_cursor": _cursor(rows[-1]) if more and rows else None}


def _cursor(v: Video) -> str:
    return f"{int(v.published_at.timestamp() * 1_000_000)}_{v.id}"


def _parse_cursor(cursor: str | None):
    if not cursor:
        return None
    try:
        a, b = cursor.split("_", 1)
        return datetime.fromtimestamp(int(a) / 1_000_000, tz=timezone.utc), int(b)
    except (ValueError, OverflowError):
        return None


async def zones(db: AsyncSession) -> list[dict]:
    rows = dict((await db.execute(select(Video.zone, func.count()).where(*_listed_filter())
                                  .group_by(Video.zone))).all())
    return [{"zone": k, "name": name, "count": int(rows.get(k, 0))}
            for k, name in vsvc.ZONES.items()]


async def zone_page(db: AsyncSession, viewer: User | None, zone: str, order: str,
                    page: int) -> dict:
    if order == "hot":
        out = await rank_feed(db, viewer, mode="hot", page=page, zone=zone)
    else:
        rows = list(await db.scalars(select(Video).where(*_listed_filter(zone=zone))
                                     .order_by(Video.published_at.desc(), Video.id.desc())
                                     .offset(page * PAGE).limit(PAGE + 1)))
        out = {"items": await vsvc.cards(db, viewer.id if viewer else None, rows[:PAGE]),
               "page": page, "has_more": len(rows) > PAGE}
    out.update({"zone": zone, "name": vsvc.ZONES[zone], "order": order})
    return out


async def leaderboard(db: AsyncSession, viewer: User | None, zone: str | None, days: int) -> dict:
    """排行榜 = 某分区(或全站)按「互动分」在 1 / 3 / 7 天窗口里排序。"""
    now = ranked_now()
    since = now - timedelta(days=days)
    counts = await window_counts(db, since)
    videos = list(await db.scalars(select(Video).where(*_listed_filter(zone=zone),
                                                       Video.id.in_(list(counts))))) \
        if counts else []
    rows = []
    for v in videos:
        c = counts[v.id]
        score = rank.interaction(c)
        if score > 0:
            rows.append((v, {"counts": c.as_dict(), "interaction": score}))
    rows.sort(key=lambda x: rank.order_key(x[1]["interaction"], x[0].published_at, x[0].id))
    rows = rows[:LEADERBOARD_MAX]
    ups = await vsvc.people(db, viewer.id if viewer else None, [v.uploader_id for v, _ in rows])
    items = []
    for i, (v, b) in enumerate(rows):
        item = vsvc.card(v, ups.get(v.uploader_id))
        item["rank"] = b
        item["position"] = i + 1
        items.append(item)
    return {"items": items, "zone": zone, "days": days, "ranked_at": now.isoformat(),
            "window_start": since.isoformat()}


async def related(db: AsyncSession, viewer: User | None, v: Video, limit: int = 20) -> dict:
    """相关视频:同 UP 主、同分区、同标签的,排序同 §5.9 的「推荐」。"""
    now = ranked_now()
    since = now - timedelta(hours=rank.WINDOW_HOURS)
    personal = await personal_of(db, viewer, now)
    match = [Video.uploader_id == v.uploader_id]
    if v.zone:
        match.append(Video.zone == v.zone)
    if v.tags:
        match.append(Video.tags.overlap(list(v.tags)))
    conds = [*_listed_filter(), Video.id != v.id, or_(*match)]
    pool = await _scored(db, now, since, conds, look_ahead=limit * 3, exclude=personal.exclude)
    scored = []
    for x, counts in pool:
        inp = rank.RankInput(video_id=x.id, uploader_id=x.uploader_id, zone=x.zone,
                             published_at=x.published_at, counts=counts)
        scored.append((x, rank.breakdown(inp, now, followed=x.uploader_id in personal.followed,
                                         top_zone=x.zone in personal.top_zones)))
    scored.sort(key=lambda t: rank.order_key(t[1]["recommend"], t[0].published_at, t[0].id))
    return {"items": await _items(db, viewer.id if viewer else None, scored[:limit]),
            "ranked_at": now.isoformat()}


# ---------------- 搜索 ----------------

def _like(q: str) -> str:
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def normalize_term(q: str) -> str:
    return " ".join((q or "").split())[:TERM_MAX].lower()


async def search_videos(db: AsyncSession, viewer: User | None, q: str, *, order: str = "default",
                        duration: int = 0, zone: str | None = None, page: int = 0) -> dict:
    """视频搜索:标题 / 标签 / 简介 / UP 主名(ILIKE,和商家搜索同一个口径:
    中文三元组要 3 个字才有选择性,pg_trgm 在这里帮不上)。

    排序:综合 = 标题命中 3 分 + 标签 2 分 + UP 主名 2 分 + 简介 1 分,同分按播放、再按新;
    最多播放;最新;最多弹幕。
    """
    term = " ".join(q.split())
    like = _like(term)
    uploader = User.__table__.alias("up")
    prof = SocialProfile.__table__.alias("sp")
    title_hit = Video.title.ilike(like, escape="\\")
    tag_hit = func.array_to_string(Video.tags, " ").ilike(like, escape="\\")
    desc_hit = Video.description.ilike(like, escape="\\")
    # UP 主的超级赞号只在他没关「按超级赞号找到我」时参与匹配(和 /social/v1/resolve 一个口径)
    up_hit = or_(uploader.c.name.ilike(like, escape="\\"),
                 and_(func.coalesce(prof.c.username, "").ilike(like, escape="\\"),
                      username_searchable(prof.c.privacy)))
    conds = [*_listed_filter(zone=zone), or_(title_hit, tag_hit, desc_hit, up_hit)]
    if duration in DURATION_FILTERS:
        lo, hi = DURATION_FILTERS[duration]
        conds.append(Video.duration_ms >= lo * 60_000)
        if hi is not None:
            conds.append(Video.duration_ms < hi * 60_000)
    score = (case((title_hit, 3), else_=0) + case((tag_hit, 2), else_=0) +
             case((up_hit, 2), else_=0) + case((desc_hit, 1), else_=0))
    orders = {
        "default": (score.desc(), Video.views.desc(), Video.published_at.desc(), Video.id.desc()),
        "views": (Video.views.desc(), Video.id.desc()),
        "new": (Video.published_at.desc(), Video.id.desc()),
        "danmaku": (Video.danmaku_count.desc(), Video.id.desc()),
    }
    stmt = (select(Video).join(uploader, uploader.c.id == Video.uploader_id)
            .outerjoin(prof, prof.c.user_id == Video.uploader_id)
            .where(*conds).order_by(*orders.get(order, orders["default"]))
            .offset(page * PAGE).limit(PAGE + 1))
    rows = list(await db.scalars(stmt))
    return {"items": await vsvc.cards(db, viewer.id if viewer else None, rows[:PAGE]),
            "page": page, "has_more": len(rows) > PAGE, "order": order}


async def record_term(db: AsyncSession, user: User | None, q: str) -> None:
    """热搜只数登录的人:同一个人一天搜同一个词只算一次(设备号能伪造,不拿它算「不同的人」)。"""
    term = normalize_term(q)
    if user is None or not term:
        return
    from .video import bj_day
    day = bj_day()
    res = await db.execute(insert(SearchTermUser).values(day=day, term=term, user_id=user.id)
                           .on_conflict_do_nothing())
    if res.rowcount == 1:
        await db.execute(insert(SearchTerm).values(day=day, term=term, users=1)
                         .on_conflict_do_update(index_elements=["day", "term"],
                                                set_={"users": SearchTerm.users + 1}))


async def hot_terms(db: AsyncSession) -> list[dict]:
    """热搜:24 小时内至少 5 个不同的人搜过的词,按人数排。命中屏蔽词的不上榜。"""
    since = datetime.now(timezone.utc) - HOT_TERM_WINDOW
    n = func.count(func.distinct(SearchTermUser.user_id))
    rows = (await db.execute(select(SearchTermUser.term, n).where(
        SearchTermUser.created_at >= since).group_by(SearchTermUser.term)
        .having(n >= HOT_TERM_MIN_USERS).order_by(n.desc(), SearchTermUser.term)
        .limit(HOT_TERMS_MAX * 2))).all()
    from .moderation import find_banned
    out = []
    for term, users in rows:
        if await find_banned(db, term) is None:
            out.append({"term": term, "users": int(users)})
        if len(out) >= HOT_TERMS_MAX:
            break
    return out


async def search_users(db: AsyncSession, viewer: User | None, q: str, page: int = 0) -> dict:
    """用户搜索:名字或超级赞号包含关键词的用户端账号。按粉丝数排。
    按超级赞号匹配只算没关「按超级赞号找到我」的人。"""
    like = _like(" ".join(q.split()))
    fans = (select(func.count()).select_from(Follow).where(Follow.followee_id == User.id)
            .correlate(User).scalar_subquery())
    rows = (await db.execute(
        select(User.id, fans.label("fans")).outerjoin(SocialProfile,
                                                     SocialProfile.user_id == User.id)
        .where(User.role == UserRole.customer, User.deleted_at.is_(None),
               or_(User.name.ilike(like, escape="\\"),
                   and_(func.coalesce(SocialProfile.username, "").ilike(like, escape="\\"),
                        username_searchable(SocialProfile.privacy))))
        .order_by(fans.desc(), User.id).offset(page * PAGE).limit(PAGE + 1))).all()
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    ids = [uid for uid, _ in rows]
    viewer_id = viewer.id if viewer else None
    cards = await vsvc.people(db, viewer_id, ids)
    mine = set(await db.scalars(select(Follow.followee_id).where(
        Follow.follower_id == viewer_id, Follow.followee_id.in_(ids)))) if viewer_id and ids \
        else set()
    vcount = dict((await db.execute(select(Video.uploader_id, func.count()).where(
        Video.uploader_id.in_(ids), *_listed_filter()).group_by(Video.uploader_id))).all()) \
        if ids else {}
    return {"items": [{**cards[uid], "fans": int(f), "videos": int(vcount.get(uid, 0)),
                       "followed": uid in mine} for uid, f in rows if uid in cards],
            "page": page, "has_more": more}


# ---------------- UP 主空间 ----------------

async def user_videos(db: AsyncSession, viewer: User | None, user_id: int, order: str,
                      page: int) -> dict:
    orders = {"new": (Video.published_at.desc(), Video.id.desc()),
              "views": (Video.views.desc(), Video.id.desc())}
    rows = list(await db.scalars(select(Video).where(Video.uploader_id == user_id,
                                                     *_listed_filter())
                                 .order_by(*orders.get(order, orders["new"]))
                                 .offset(page * PAGE).limit(PAGE + 1)))
    return {"items": await vsvc.cards(db, viewer.id if viewer else None, rows[:PAGE]),
            "page": page, "has_more": len(rows) > PAGE, "order": order}


async def space(db: AsyncSession, viewer: User | None, target: User) -> dict:
    from .video_interact import folders_of

    viewer_id = viewer.id if viewer else None
    card = (await vsvc.people(db, viewer_id, [target.id]))[target.id]
    prof = await db.get(SocialProfile, target.id)
    fans, following = await vsvc.follow_counts(db, target.id)
    likes = await db.scalar(select(func.coalesce(func.sum(Video.likes), 0)).where(
        Video.uploader_id == target.id, *_listed_filter()))
    nvideos = await db.scalar(select(func.count()).select_from(Video).where(
        Video.uploader_id == target.id, *_listed_filter()))
    followed = bool(viewer_id and await db.get(Follow, (viewer_id, target.id)))
    blocked = False
    if viewer_id and viewer_id != target.id:
        from .social import blocked_between
        blocked = await blocked_between(db, viewer_id, target.id)
    # 标签和勋章:和资料页同一个口径(隐藏了的别人看不到,本人看得到并标着),没登录的人按「别人」算
    from .badges import tags_badges_for
    marks = await tags_badges_for(db, target.id, viewer_id)
    return {
        "user": {**card, "bio": (prof.bio if prof else "") or "", **marks},
        "is_self": viewer_id == target.id,
        "followed": followed,
        "can_follow": bool(viewer_id) and viewer_id != target.id and not blocked,
        "stats": {"following": following, "fans": fans, "likes": int(likes or 0),
                  "videos": int(nvideos or 0)},
        "folders": await folders_of(db, target.id, only_public=viewer_id != target.id),
        "videos": await user_videos(db, viewer, target.id, "new", 0),
    }

