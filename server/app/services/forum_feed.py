"""两条时间线、帖子串、个人主页各页签、热门话题、话题页、搜索,以及下发形状的组装
(DEV-PROMPTS-41 §5.7、§8.1、§8.3,#380)。

排序公式本身在 forum_rank.py(纯函数);这里只做三件事:**取数**、**过滤**和**拼形状**。

- 取数:四种互动在 72 小时窗口里按人去重的个数,直接从明细表数(window_counts)。
  计数列只用来展示;
- 过滤(§5.7):双向拉黑(任意一方拉黑就互相看不见)、我的屏蔽词、已删 / 已下架;
- 个性化:登录了、而且 `forum_user_settings.personalize` 开着,才用两样和「我」有关的东西 ——
  关注了作者没有、帖子里有没有我近 30 天用过的话题。**关掉之后一样都不用**,推荐结果和
  没登录的人逐条相等(e2e_forum_timeline 断言);
- 「现在」取整到分钟:同一分钟里两次请求算出来的分数一模一样,排序是确定的。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, and_, case, func, or_, select, tuple_
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Follow, ForumBookmark, ForumLike, ForumPin, ForumPoll, ForumPost,
                      ForumPostTag, ForumRepost, ForumTag, SocialBlock, SocialProfile, User,
                      UserRole)
from . import cards
from . import forum as fsvc
from . import forum_rank as rank
from . import video as vsvc
from .social import username_searchable

PAGE = rank.SCREEN_SIZE
#: 分页上限(和视频同一个口径:页码最大 200)
PAGE_MAX = 200


def ranked_now() -> datetime:
    """「现在」取整到分钟。"""
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


def clamp_page(page: int) -> int:
    return max(0, min(int(page or 0), PAGE_MAX))


# ---------------- 窗口计数 ----------------

_WINDOW_SQL = """
SELECT post_id, 'likes' AS k, count(DISTINCT user_id) AS n
  FROM forum_likes WHERE created_at >= :since GROUP BY post_id
UNION ALL
SELECT post_id, 'reposts', count(DISTINCT user_id) FROM forum_reposts
 WHERE created_at >= :since GROUP BY post_id
UNION ALL
SELECT quote_of_id, 'quotes', count(DISTINCT author_id) FROM forum_posts
 WHERE quote_of_id IS NOT NULL AND status = 'visible' AND created_at >= :since
 GROUP BY quote_of_id
UNION ALL
SELECT reply_to_id, 'repliers', count(DISTINCT author_id) FROM forum_posts
 WHERE reply_to_id IS NOT NULL AND status = 'visible' AND created_at >= :since
 GROUP BY reply_to_id
"""


async def window_counts(db: AsyncSession, since: datetime) -> dict[int, rank.Counts]:
    """时间窗里每条帖子的四种互动,每种按人去重(同一个人转发 + 引用 + 回复各算一次)。

    明细表各自带 created_at 索引;窗口外的行根本不碰。引用、回复按**作者**去重 ——
    一个人连回十条,「回复人数」还是 1,刷不出热度。
    """
    rows = (await db.execute(sql_text(_WINDOW_SQL), {"since": since})).all()
    acc: dict[int, dict[str, int]] = {}
    for pid, k, n in rows:
        if pid is not None:
            acc.setdefault(int(pid), {})[k] = int(n)
    return {pid: rank.Counts(**d) for pid, d in acc.items()}


# ---------------- 观众的上下文(拉黑、屏蔽词、个性化)----------------

@dataclass
class Viewer:
    """一次请求里和「我」有关的全部东西。没登录时全是空的。"""

    id: int | None = None
    personalize: bool = False
    followed: frozenset = frozenset()
    blocked: frozenset = frozenset()
    mute_words: tuple = ()
    my_tag_ids: frozenset = frozenset()

    def muted(self, post: ForumPost) -> bool:
        """含我的屏蔽词的帖子不进我的时间线(只对我生效,不影响别人看得到什么)。"""
        if not self.mute_words:
            return False
        hay = (post.text or "").lower()
        return any(w in hay for w in self.mute_words)


async def blocked_ids(db: AsyncSession, viewer_id: int) -> frozenset:
    """和我有拉黑关系的人(我拉黑的 + 拉黑我的)。双向隔离(§3.6)。"""
    rows = (await db.execute(select(SocialBlock.user_id, SocialBlock.blocked_id).where(
        or_(SocialBlock.user_id == viewer_id, SocialBlock.blocked_id == viewer_id)))).all()
    out = set()
    for a, b in rows:
        out.add(b if a == viewer_id else a)
    return frozenset(out)


async def viewer_of(db: AsyncSession, user: User | None, now: datetime | None = None) -> Viewer:
    if user is None:
        return Viewer()
    now = now or ranked_now()
    st = await fsvc.settings_of(db, user.id)
    words = tuple(w.lower() for w in await fsvc.mute_words(db, user.id))
    blocked = await blocked_ids(db, user.id)
    if not st.personalize:
        # 关掉个性化:关注关系、话题一样都不用(§5.7)。拉黑和屏蔽词照旧 ——
        # 那是自我保护,不是推荐信号
        return Viewer(id=user.id, personalize=False, blocked=blocked, mute_words=words)
    followed = frozenset(await db.scalars(select(Follow.followee_id)
                                          .where(Follow.follower_id == user.id)))
    since = now - timedelta(days=rank.TOPIC_LOOKBACK_DAYS)
    # 「我近 30 天发过或点过赞的话题」:我自己发的帖子上的话题,加上我赞过的帖子上的话题
    mine = select(ForumPostTag.tag_id).where(ForumPostTag.author_id == user.id,
                                             ForumPostTag.created_at >= since)
    liked = (select(ForumPostTag.tag_id)
             .join(ForumLike, ForumLike.post_id == ForumPostTag.post_id)
             .where(ForumLike.user_id == user.id, ForumLike.created_at >= since))
    tag_ids = frozenset(await db.scalars(mine.union(liked)))
    return Viewer(id=user.id, personalize=True, followed=followed, blocked=blocked,
                  mute_words=words, my_tag_ids=tag_ids)


def visible_conds(v: Viewer) -> list:
    """SQL 层的可见性:正常的帖子,作者和我没有拉黑关系。"""
    conds = [ForumPost.status == "visible"]
    if v.blocked:
        conds.append(ForumPost.author_id.notin_(list(v.blocked)))
    return conds


# ---------------- 下发形状(§8.1)----------------

async def _ctx(db: AsyncSession, v: Viewer, posts: list[ForumPost]) -> dict:
    """一页帖子共用的上下文:人物简卡、我的赞 / 转发 / 书签、投票、置顶、@ 开关。一页几条查询。"""
    ids = [p.id for p in posts]
    people_ids = {p.author_id for p in posts} | {p.reply_to_user_id for p in posts
                                                 if p.reply_to_user_id}
    ctx: dict = {
        "people": await vsvc.people(db, v.id, people_ids),
        "hidden": await fsvc.mentions_off(db, posts),
        "liked": set(), "reposted": set(), "bookmarked": set(), "pinned": set(),
        "polls": {}, "can_reply": {},
    }
    if ids:
        ctx["polls"] = {row.post_id: row for row in await db.scalars(
            select(ForumPoll).where(ForumPoll.post_id.in_(ids)))}
    if v.id and ids:
        ctx["liked"] = set(await db.scalars(select(ForumLike.post_id).where(
            ForumLike.user_id == v.id, ForumLike.post_id.in_(ids))))
        ctx["reposted"] = set(await db.scalars(select(ForumRepost.post_id).where(
            ForumRepost.user_id == v.id, ForumRepost.post_id.in_(ids))))
        ctx["bookmarked"] = set(await db.scalars(select(ForumBookmark.post_id).where(
            ForumBookmark.user_id == v.id, ForumBookmark.post_id.in_(ids))))
        ctx["pinned"] = set(await db.scalars(select(ForumPin.post_id).where(
            ForumPin.post_id.in_(ids))))
    elif ids:
        ctx["pinned"] = set(await db.scalars(select(ForumPin.post_id)
                                             .where(ForumPin.post_id.in_(ids))))
    return ctx


async def post_out(db: AsyncSession, v: Viewer, p: ForumPost, ctx: dict, *,
                   with_quote: bool = True) -> dict:
    """一条帖子的完整形状(§8.1)。`with_quote=False` 是引用里那一层 —— 不再嵌套。"""
    author = ctx["people"].get(p.author_id)
    out = {
        "pid": p.pid,
        "author": author or {"id": p.author_id, "name": "", "username": None, "avatar": ""},
        "text": p.text or "",
        "entities": fsvc.entities_out(p, ctx["hidden"]),
        "media": list(p.media or []),
        "card": await cards.resolve_or_placeholder(db, p.card, v.id),
        "quote": None,
        "reply_to": None,
        "root_pid": None,
        "poll": await fsvc.poll_out(db, ctx["polls"].get(p.id), p, v.id),
        "reply_policy": p.reply_policy,
        "can_reply": ctx["can_reply"].get(p.id, True),
        "counts": {"replies": p.replies, "reposts": p.reposts, "quotes": p.quotes,
                   "likes": p.likes, "bookmarks": p.bookmarks, "views": p.views},
        "viewer": {"liked": p.id in ctx["liked"], "reposted": p.id in ctx["reposted"],
                   "bookmarked": p.id in ctx["bookmarked"]},
        "edited": p.edited_at is not None,
        "edited_at": fsvc.iso(p.edited_at),
        "created_at": fsvc.iso(p.created_at),
        "pinned": p.id in ctx["pinned"],
    }
    if p.root_id or p.reply_to_id:
        root = await db.get(ForumPost, p.root_id or p.reply_to_id)
        out["root_pid"] = root.pid if root is not None else None
    if p.reply_to_id:
        parent = await db.get(ForumPost, p.reply_to_id)
        if parent is not None:
            who = (await vsvc.people(db, v.id, [parent.author_id])).get(parent.author_id)
            out["reply_to"] = {"pid": parent.pid, "author": who}
    if with_quote and p.quote_of_id:
        q = await db.get(ForumPost, p.quote_of_id)
        if q is None:
            out["quote"] = None
        else:
            reason = await fsvc.invisible_reason(db, q, v.id)
            if reason is not None:
                # 被引用的帖子删了 / 下架了,引用照样在,只显示「这条帖子已不可见」(§5.6)
                out["quote"] = {"pid": q.pid, "unavailable": True, "reason": reason}
            else:
                qctx = await _ctx(db, v, [q])
                out["quote"] = await post_out(db, v, q, qctx, with_quote=False)
    return out


async def posts_out(db: AsyncSession, v: Viewer, posts: list[ForumPost]) -> list[dict]:
    ctx = await _ctx(db, v, posts)
    if v.id:
        for p in posts:
            ctx["can_reply"][p.id] = await fsvc.can_reply_to(db, p, v.id)
    return [await post_out(db, v, p, ctx) for p in posts]


# ---------------- 推荐时间线(§5.7)----------------

async def foryou(db: AsyncSession, user: User | None, page: int = 0) -> dict:
    """推荐:候选是 72 小时内的原帖(不含回复),按 §5.7 的公式排,每屏 20 条、同一作者最多 2 条。"""
    now = ranked_now()
    since = now - timedelta(hours=rank.WINDOW_HOURS)
    v = await viewer_of(db, user, now)
    counts = await window_counts(db, since)
    rows = list(await db.scalars(
        select(ForumPost).where(*visible_conds(v), ForumPost.reply_to_id.is_(None),
                                ForumPost.created_at >= since)
        .order_by(ForumPost.created_at.desc(), ForumPost.id.desc())
        .limit((page + 2) * PAGE * 5)))
    rows = [p for p in rows if not v.muted(p)]
    tag_hits = await _posts_with_my_tags(db, v, [p.id for p in rows])
    scored = []
    for p in rows:
        inp = rank.RankInput(post_id=p.id, author_id=p.author_id, created_at=p.created_at,
                             counts=counts.get(p.id, rank.Counts()))
        b = rank.breakdown(inp, now, followed=v.personalize and p.author_id in v.followed,
                           topic=v.personalize and p.id in tag_hits)
        scored.append((p, b))
    scored.sort(key=lambda x: rank.order_key(x[1]["score"], x[0].created_at, x[0].id))
    screens = rank.paginate_screens(scored, lambda x: x[0].author_id, max_screens=page + 2)
    chunk = screens[page] if page < len(screens) else []
    items = await posts_out(db, v, [p for p, _ in chunk])
    return {"items": [{"type": "post", "post": it, "rank": b}
                      for it, (_, b) in zip(items, chunk)],
            "page": page, "has_more": len(screens) > page + 1, "personalized": v.personalize,
            "ranked_at": now.isoformat()}


async def _posts_with_my_tags(db: AsyncSession, v: Viewer, post_ids: list[int]) -> frozenset:
    """这些帖子里,哪些带着我近 30 天发过或点过赞的话题。"""
    if not v.personalize or not v.my_tag_ids or not post_ids:
        return frozenset()
    return frozenset(await db.scalars(select(ForumPostTag.post_id).where(
        ForumPostTag.post_id.in_(post_ids), ForumPostTag.tag_id.in_(list(v.my_tag_ids)))))


# ---------------- 关注时间线 ----------------

def _cursor(ts: datetime, id_: int) -> str:
    return f"{int(ts.timestamp() * 1_000_000)}_{id_}"


def _parse_cursor(cursor: str | None):
    if not cursor:
        return None
    try:
        a, b = cursor.split("_", 1)
        return datetime.fromtimestamp(int(a) / 1_000_000, tz=timezone.utc), int(b)
    except (ValueError, OverflowError):
        return None


async def following(db: AsyncSession, user: User, cursor: str | None,
                    limit: int = PAGE) -> dict:
    """关注的人的帖子**和转发**,按事件时间倒序(§8.3)。

    转发和原帖是两个事件:「他昨天发的」和「她刚转的」在时间线上是两条,时间各按各的 ——
    所以取两份再按事件时间归并,cursor 也按事件时间走。
    """
    v = await viewer_of(db, user)
    cur = _parse_cursor(cursor)
    who = list(v.followed if v.personalize else await db.scalars(
        select(Follow.followee_id).where(Follow.follower_id == user.id)))
    if not who:
        return {"items": [], "has_more": False, "next_cursor": None}

    q = select(ForumPost).where(*visible_conds(v), ForumPost.author_id.in_(who),
                                ForumPost.reply_to_id.is_(None))
    if cur is not None:
        q = q.where(tuple_(ForumPost.created_at, ForumPost.id) < tuple_(*cur))
    own = list(await db.scalars(q.order_by(ForumPost.created_at.desc(), ForumPost.id.desc())
                                .limit(limit + 1)))

    rq = (select(ForumRepost, ForumPost).join(ForumPost, ForumPost.id == ForumRepost.post_id)
          .where(ForumRepost.user_id.in_(who), *visible_conds(v)))
    if cur is not None:
        rq = rq.where(tuple_(ForumRepost.created_at, ForumRepost.id) < tuple_(*cur))
    reposts = (await db.execute(rq.order_by(ForumRepost.created_at.desc(),
                                            ForumRepost.id.desc()).limit(limit + 1))).all()

    events: list[tuple[datetime, int, str, object, ForumPost]] = []
    for p in own:
        events.append((p.created_at, p.id, "post", None, p))
    for r, p in reposts:
        events.append((r.created_at, r.id, "repost", r, p))
    events.sort(key=lambda e: (e[0], e[1]), reverse=True)
    events = [e for e in events if not v.muted(e[4])]
    more = len(events) > limit
    events = events[:limit]
    by_pid: dict[int, dict] = {}
    outs = await posts_out(db, v, [e[4] for e in events])
    for e, out in zip(events, outs):
        by_pid[id(e[4])] = out
    actors = await vsvc.people(db, v.id, [e[3].user_id for e in events if e[2] == "repost"])
    items = []
    for ts, eid, kind, r, p in events:
        out = by_pid[id(p)]
        if kind == "post":
            items.append({"type": "post", "post": out})
        else:
            items.append({"type": "repost", "by": actors.get(r.user_id),
                          "at": fsvc.iso(r.created_at), "post": out})
    last = events[-1] if events else None
    return {"items": items, "has_more": more,
            "next_cursor": _cursor(last[0], last[1]) if more and last else None}


# ---------------- 帖子串 ----------------

async def thread(db: AsyncSession, user: User | None, p: ForumPost) -> dict:
    """帖子详情 + 上文(§8.3)。看不见的那几条在串里占位,不是消失。"""
    v = await viewer_of(db, user)
    chain: list[ForumPost] = []
    cur = p
    # 上文最多往回走 20 层:再深的串客户端也是折叠显示
    for _ in range(20):
        if not cur.reply_to_id:
            break
        parent = await db.get(ForumPost, cur.reply_to_id)
        if parent is None:
            break
        chain.append(parent)
        cur = parent
    chain.reverse()
    ancestors = []
    visible = []
    for a in chain:
        reason = await fsvc.invisible_reason(db, a, v.id)
        if reason is not None and v.id != a.author_id:
            ancestors.append(fsvc.placeholder(a, reason))
        else:
            visible.append(a)
            ancestors.append(None)
    outs = await posts_out(db, v, visible + [p])
    self_out = outs[-1]
    it = iter(outs[:-1])
    ancestors = [a if a is not None else next(it) for a in ancestors]
    return {"post": self_out, "ancestors": ancestors}


async def replies(db: AsyncSession, user: User | None, p: ForumPost, sort: str,
                  cursor: str | None, limit: int = PAGE) -> dict:
    """某条帖子下面的回复。`top` 按赞数、`new` 按时间。"""
    v = await viewer_of(db, user)
    q = select(ForumPost).where(*visible_conds(v), ForumPost.reply_to_id == p.id)
    if sort == "top":
        rows = list(await db.scalars(q.order_by(ForumPost.likes.desc(),
                                                ForumPost.created_at.asc(), ForumPost.id.asc())
                                     .limit(limit + 1)))
        rows = [r for r in rows if not v.muted(r)]
        return {"items": await posts_out(db, v, rows[:limit]), "has_more": len(rows) > limit,
                "next_cursor": None}
    cur = _parse_cursor(cursor)
    if cur is not None:
        q = q.where(tuple_(ForumPost.created_at, ForumPost.id) > tuple_(*cur))
    rows = list(await db.scalars(q.order_by(ForumPost.created_at.asc(), ForumPost.id.asc())
                                 .limit(limit + 1)))
    rows = [r for r in rows if not v.muted(r)]
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": await posts_out(db, v, rows), "has_more": more,
            "next_cursor": _cursor(rows[-1].created_at, rows[-1].id) if more and rows else None}


async def _cursor_page(db: AsyncSession, v: Viewer, q: Select, cursor: str | None,
                       limit: int) -> dict:
    """按时间倒序的 cursor 分页(帖子表)。"""
    cur = _parse_cursor(cursor)
    if cur is not None:
        q = q.where(tuple_(ForumPost.created_at, ForumPost.id) < tuple_(*cur))
    rows = list(await db.scalars(q.order_by(ForumPost.created_at.desc(), ForumPost.id.desc())
                                 .limit(limit + 1)))
    rows = [r for r in rows if not v.muted(r)]
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": await posts_out(db, v, rows), "has_more": more,
            "next_cursor": _cursor(rows[-1].created_at, rows[-1].id) if more and rows else None}


async def quotes_of(db: AsyncSession, user: User | None, p: ForumPost,
                    cursor: str | None) -> dict:
    v = await viewer_of(db, user)
    return await _cursor_page(db, v, select(ForumPost).where(*visible_conds(v),
                                                             ForumPost.quote_of_id == p.id),
                              cursor, PAGE)


async def likers_of(db: AsyncSession, user: User | None, p: ForumPost,
                    cursor: str | None, limit: int = PAGE) -> dict:
    """点赞的人。拉黑关系里的人不出现。"""
    v = await viewer_of(db, user)
    q = select(ForumLike).where(ForumLike.post_id == p.id)
    if v.blocked:
        q = q.where(ForumLike.user_id.notin_(list(v.blocked)))
    cur = _parse_cursor(cursor)
    if cur is not None:
        q = q.where(tuple_(ForumLike.created_at, ForumLike.user_id) < tuple_(*cur))
    rows = list(await db.scalars(q.order_by(ForumLike.created_at.desc(),
                                            ForumLike.user_id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    people = await vsvc.people(db, v.id, [r.user_id for r in rows])
    mine = set(await db.scalars(select(Follow.followee_id).where(
        Follow.follower_id == v.id,
        Follow.followee_id.in_([r.user_id for r in rows])))) if v.id and rows else set()
    items = [{**people[r.user_id], "followed": r.user_id in mine}
             for r in rows if r.user_id in people]
    last = rows[-1] if rows else None
    return {"items": items, "has_more": more,
            "next_cursor": _cursor(last.created_at, last.user_id) if more and last else None}


# ---------------- 个人主页 ----------------

async def profile(db: AsyncSession, user: User | None, target: User) -> dict:
    v = await viewer_of(db, user)
    card = (await vsvc.people(db, v.id, [target.id])).get(target.id)
    prof = await db.get(SocialProfile, target.id)
    fans, follow_n = await vsvc.follow_counts(db, target.id)
    posts = int(await db.scalar(select(func.count()).select_from(ForumPost).where(
        ForumPost.author_id == target.id, ForumPost.status == "visible",
        ForumPost.reply_to_id.is_(None))) or 0)
    followed = follows_you = False
    if v.id and v.id != target.id:
        pair = set((await db.execute(select(Follow.follower_id, Follow.followee_id).where(
            ((Follow.follower_id == v.id) & (Follow.followee_id == target.id))
            | ((Follow.follower_id == target.id) & (Follow.followee_id == v.id))))).all())
        followed = (v.id, target.id) in pair
        follows_you = (target.id, v.id) in pair
    pin = await db.get(ForumPin, target.id)
    pinned = None
    if pin is not None:
        p = await db.get(ForumPost, pin.post_id)
        if p is not None and await fsvc.invisible_reason(db, p, v.id) is None:
            pinned = (await posts_out(db, v, [p]))[0]
    return {"user": card, "bio": (prof.bio if prof else "") or "",
            "joined_at": fsvc.iso(target.created_at), "posts": posts,
            "following": follow_n, "fans": fans, "followed": followed,
            "follows_you": follows_you, "pinned": pinned}


async def user_posts(db: AsyncSession, user: User | None, target_id: int, tab: str,
                     cursor: str | None, limit: int = PAGE) -> dict:
    """主页页签(§8.3):posts 原帖 + 转发(是 timeline item)、replies 回复、media 带图的、likes 赞过的。"""
    v = await viewer_of(db, user)
    if tab == "replies":
        return await _cursor_page(db, v, select(ForumPost).where(
            *visible_conds(v), ForumPost.author_id == target_id,
            ForumPost.reply_to_id.is_not(None)), cursor, limit)
    if tab == "media":
        return await _cursor_page(db, v, select(ForumPost).where(
            *visible_conds(v), ForumPost.author_id == target_id,
            func.jsonb_array_length(ForumPost.media) > 0), cursor, limit)
    if tab == "likes":
        if v.id != target_id:
            # 赞过的只有本人看得见 —— 别人的「喜欢」是他的浏览史
            raise _forbidden()
        q = (select(ForumPost).join(ForumLike, ForumLike.post_id == ForumPost.id)
             .where(*visible_conds(v), ForumLike.user_id == target_id))
        cur = _parse_cursor(cursor)
        if cur is not None:
            q = q.where(tuple_(ForumLike.created_at, ForumPost.id) < tuple_(*cur))
        rows = list(await db.scalars(q.order_by(ForumLike.created_at.desc(),
                                                ForumPost.id.desc()).limit(limit + 1)))
        more = len(rows) > limit
        rows = rows[:limit]
        out = {"items": await posts_out(db, v, rows), "has_more": more, "next_cursor": None}
        if more and rows:
            like = await db.get(ForumLike, (target_id, rows[-1].id))
            out["next_cursor"] = _cursor(like.created_at, rows[-1].id) if like else None
        return out

    # posts:原帖 + 我的转发,按事件时间倒序(和关注时间线同一个形状)
    cur = _parse_cursor(cursor)
    q = select(ForumPost).where(*visible_conds(v), ForumPost.author_id == target_id,
                                ForumPost.reply_to_id.is_(None))
    if cur is not None:
        q = q.where(tuple_(ForumPost.created_at, ForumPost.id) < tuple_(*cur))
    own = list(await db.scalars(q.order_by(ForumPost.created_at.desc(), ForumPost.id.desc())
                                .limit(limit + 1)))
    rq = (select(ForumRepost, ForumPost).join(ForumPost, ForumPost.id == ForumRepost.post_id)
          .where(ForumRepost.user_id == target_id, *visible_conds(v)))
    if cur is not None:
        rq = rq.where(tuple_(ForumRepost.created_at, ForumRepost.id) < tuple_(*cur))
    reposts = (await db.execute(rq.order_by(ForumRepost.created_at.desc(),
                                            ForumRepost.id.desc()).limit(limit + 1))).all()
    events = [(p.created_at, p.id, "post", None, p) for p in own]
    events += [(r.created_at, r.id, "repost", r, p) for r, p in reposts]
    events.sort(key=lambda e: (e[0], e[1]), reverse=True)
    events = [e for e in events if not v.muted(e[4])]
    more = len(events) > limit
    events = events[:limit]
    outs = await posts_out(db, v, [e[4] for e in events])
    who = (await vsvc.people(db, v.id, [target_id])).get(target_id)
    items = []
    for (ts, eid, kind, r, p), out in zip(events, outs):
        items.append({"type": "post", "post": out} if kind == "post" else
                     {"type": "repost", "by": who, "at": fsvc.iso(r.created_at), "post": out})
    last = events[-1] if events else None
    return {"items": items, "has_more": more,
            "next_cursor": _cursor(last[0], last[1]) if more and last else None}


def _forbidden():
    from fastapi import HTTPException
    return HTTPException(403, "只有本人能看自己喜欢的帖子")


async def bookmarks(db: AsyncSession, user: User, cursor: str | None,
                    limit: int = PAGE) -> dict:
    v = await viewer_of(db, user)
    q = (select(ForumPost).join(ForumBookmark, ForumBookmark.post_id == ForumPost.id)
         .where(*visible_conds(v), ForumBookmark.user_id == user.id))
    cur = _parse_cursor(cursor)
    if cur is not None:
        q = q.where(tuple_(ForumBookmark.created_at, ForumPost.id) < tuple_(*cur))
    rows = list(await db.scalars(q.order_by(ForumBookmark.created_at.desc(),
                                            ForumPost.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    out = {"items": await posts_out(db, v, rows), "has_more": more, "next_cursor": None}
    if more and rows:
        bm = await db.get(ForumBookmark, (user.id, rows[-1].id))
        out["next_cursor"] = _cursor(bm.created_at, rows[-1].id) if bm else None
    return out


# ---------------- 热门话题、话题页 ----------------

async def trending(db: AsyncSession) -> dict:
    """热门话题(§5.7 最后一行)。按人数算,一个人自己刷不出热门;运营隐藏的不上榜。"""
    now = ranked_now()
    t24 = now - timedelta(hours=rank.TREND_WINDOW_HOURS)
    t3 = now - timedelta(hours=rank.TREND_RECENT_HOURS)
    n24 = func.count(func.distinct(ForumPostTag.author_id))
    n3 = func.count(func.distinct(case((ForumPostTag.created_at >= t3,
                                        ForumPostTag.author_id))))
    rows = (await db.execute(
        select(ForumTag.id, ForumTag.tag, ForumTag.display, n24.label("a24"), n3.label("a3"))
        .join(ForumPostTag, ForumPostTag.tag_id == ForumTag.id)
        .join(ForumPost, ForumPost.id == ForumPostTag.post_id)
        .where(ForumPostTag.created_at >= t24, ForumTag.hidden.is_(False),
               ForumPost.status == "visible")
        .group_by(ForumTag.id, ForumTag.tag, ForumTag.display)
        .having(n24 >= rank.TREND_MIN_AUTHORS)
        .order_by(rank.TREND_RECENT_WEIGHT * n3 + n24, ForumTag.tag)
        .limit(rank.TREND_MAX * 2))).all()
    items = []
    for _tid, tag, display, a24, a3 in sorted(
            rows, key=lambda r: (-rank.trend_score(int(r[3]), int(r[4])), r[1])):
        items.append({"tag": tag, "display": display or tag, "authors_24h": int(a24),
                      "authors_3h": int(a3),
                      "score": rank.trend_score(int(a24), int(a3))})
        if len(items) >= rank.TREND_MAX:
            break
    return {"items": items, "updated_at": now.isoformat()}


def normalize_tag(tag: str) -> str:
    return " ".join((tag or "").split()).lstrip("#").rstrip("#").lower()[:fsvc.TAG_MAX]


async def tag_posts(db: AsyncSession, user: User | None, tag: str, sort: str,
                    cursor: str | None, page: int = 0, limit: int = PAGE) -> dict:
    """话题页。**运营隐藏的话题照样能打开** —— 隐藏只是不上热门榜(§2.2 不偷偷压话题)。"""
    v = await viewer_of(db, user)
    low = normalize_tag(tag)
    row = await db.scalar(select(ForumTag).where(ForumTag.tag == low))
    head = {"tag": low, "display": (row.display if row else low) or low,
            "posts": row.posts if row else 0, "hidden": bool(row and row.hidden)}
    if row is None:
        return {**head, "items": [], "has_more": False, "next_cursor": None}
    base = (select(ForumPost).join(ForumPostTag, ForumPostTag.post_id == ForumPost.id)
            .where(*visible_conds(v), ForumPostTag.tag_id == row.id))
    if sort == "top":
        rows = list(await db.scalars(base.order_by(ForumPost.likes.desc(),
                                                   ForumPost.created_at.desc(),
                                                   ForumPost.id.desc())
                                     .offset(clamp_page(page) * limit).limit(limit + 1)))
        rows = [r for r in rows if not v.muted(r)]
        return {**head, "items": await posts_out(db, v, rows[:limit]),
                "page": clamp_page(page), "has_more": len(rows) > limit, "next_cursor": None}
    return {**head, **await _cursor_page(db, v, base, cursor, limit)}


# ---------------- 搜索 ----------------

def _like(q: str) -> str:
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


async def search(db: AsyncSession, user: User | None, q: str, type_: str,
                 page: int = 0, limit: int = PAGE) -> dict:
    """搜索(ILIKE,和视频、商家搜索同一个口径:中文三元组要 3 个字才有选择性)。"""
    v = await viewer_of(db, user)
    term = " ".join((q or "").split())
    page = clamp_page(page)
    if not term:
        return {"items": [], "page": page, "has_more": False, "type": type_}
    like = _like(term)
    if type_ == "users":
        fans = (select(func.count()).select_from(Follow)
                .where(Follow.followee_id == User.id).correlate(User).scalar_subquery())
        rows = (await db.execute(
            select(User.id, fans.label("fans"))
            .outerjoin(SocialProfile, SocialProfile.user_id == User.id)
            .where(User.role == UserRole.customer, User.deleted_at.is_(None),
                   or_(User.name.ilike(like, escape="\\"),
                       and_(func.coalesce(SocialProfile.username, "").ilike(like, escape="\\"),
                            username_searchable(SocialProfile.privacy))))
            .order_by(fans.desc(), User.id).offset(page * limit).limit(limit + 1))).all()
        more = len(rows) > limit
        rows = [r for r in rows[:limit] if r[0] not in v.blocked]
        ids = [uid for uid, _ in rows]
        people = await vsvc.people(db, v.id, ids)
        mine = set(await db.scalars(select(Follow.followee_id).where(
            Follow.follower_id == v.id, Follow.followee_id.in_(ids)))) if v.id and ids else set()
        return {"items": [{**people[uid], "fans": int(f), "followed": uid in mine}
                          for uid, f in rows if uid in people],
                "page": page, "has_more": more, "type": type_}
    if type_ == "tags":
        rows = list(await db.scalars(
            select(ForumTag).where(ForumTag.tag.ilike(like, escape="\\"))
            .order_by(ForumTag.posts.desc(), ForumTag.tag)
            .offset(page * limit).limit(limit + 1)))
        more = len(rows) > limit
        return {"items": [{"tag": t.tag, "display": t.display or t.tag, "posts": t.posts}
                          for t in rows[:limit]],
                "page": page, "has_more": more, "type": type_}
    rows = list(await db.scalars(
        select(ForumPost).where(*visible_conds(v), ForumPost.text.ilike(like, escape="\\"))
        .order_by(ForumPost.created_at.desc(), ForumPost.id.desc())
        .offset(page * limit).limit(limit + 1)))
    more = len(rows) > limit
    rows = [p for p in rows[:limit] if not v.muted(p)]
    return {"items": await posts_out(db, v, rows), "page": page, "has_more": more,
            "type": type_}
