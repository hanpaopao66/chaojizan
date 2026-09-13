"""弹幕(§5.10,#360)和评论(#362)。

两边共同的规矩:
- 屏蔽词(services/moderation.guard_text,和评价、昵称同一张词表)命中 → 422「包含不允许发布的内容」;
- 拉黑(S7,任意一方拉黑都算):对方的弹幕、评论对我不显示;也不能在拉黑了我的(或我拉黑了的)UP 主的视频下
  发弹幕、评论,不能回复对方的评论;
- UP 主能删自己视频下的弹幕和评论;发的人能删自己的;
- 限流(§5.7)在路由里:弹幕每人每 3 秒 1 条、每天 1,000 条;评论每人每 5 秒 1 条、每天 500 条。

弹幕的 `user_hash` 是发送人 id 的 8 位 HMAC(用服务端密钥),客户端拿它做「屏蔽此人」,
**反推不出 id**(B 站用的是 crc32,穷举几秒就能还原,这里不学)。
"""
import hashlib
import hmac
import math
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import (CommentVote, Danmaku, SocialBlock, User, Username, Video, VideoComment,
                      VideoPart)
from . import video as vsvc
from .social import blocked_between

# ---------------- 弹幕 ----------------

#: 拉取按 6 分钟一段
SEGMENT_MS = 6 * 60 * 1000
DANMAKU_MAX = 100
#: 1 滚动 / 4 底部 / 5 顶部
DANMAKU_MODES = (1, 4, 5)
#: 18 小 / 25 标准
DANMAKU_SIZES = (18, 25)
WHITE = 16777215
#: 一段最多下发这么多条(按时间先后),再多屏幕上也放不下
SEGMENT_CAP = 3000
#: 高能进度条的桶宽
DENSITY_BUCKET_MS = 5000
#: 不许出现在弹幕里的「换行类」字符:弹幕只能一行
_LINE_BREAKS = re.compile(r"[\r\n\t\v\f\u0085\u2028\u2029]")


def user_hash(user_id: int) -> str:
    key = hashlib.sha256(f"superz-danmaku:{settings.jwt_secret}".encode()).digest()
    return hmac.new(key, str(user_id).encode(), hashlib.sha256).hexdigest()[:8]


def clean_danmaku(text: str, time_ms: int, mode: int, color: int, size: int,
                  duration_ms: int) -> str:
    """校验一条弹幕(纯函数,单测锁住)。不合规抛 422,合规返回整理好的文字。"""
    if not isinstance(text, str):
        raise HTTPException(422, "弹幕不能为空")
    if _LINE_BREAKS.search(text):
        raise HTTPException(422, "弹幕只能一行")
    t = text.strip()
    if not t:
        raise HTTPException(422, "弹幕不能为空")
    if len(t) > DANMAKU_MAX:
        raise HTTPException(422, f"弹幕最多 {DANMAKU_MAX} 字")
    if mode not in DANMAKU_MODES:
        raise HTTPException(422, "弹幕模式只能是 1 滚动 / 4 底部 / 5 顶部")
    if size not in DANMAKU_SIZES:
        raise HTTPException(422, "弹幕字号只能是 18 小 / 25 标准")
    if isinstance(color, bool) or not isinstance(color, int) or not 0 <= color <= 0xFFFFFF:
        raise HTTPException(422, "弹幕颜色是 0–16777215 的整数(24 位 RGB)")
    if time_ms < 0 or (duration_ms and time_ms > duration_ms):
        raise HTTPException(422, "弹幕时间超出了视频长度")
    return t


async def blocked_ids(db: AsyncSession, viewer_id: int | None) -> set[int]:
    """和我有拉黑关系的人(我拉黑的 + 拉黑我的)。"""
    if not viewer_id:
        return set()
    rows = (await db.execute(select(SocialBlock.user_id, SocialBlock.blocked_id).where(or_(
        SocialBlock.user_id == viewer_id, SocialBlock.blocked_id == viewer_id)))).all()
    return {b if a == viewer_id else a for a, b in rows}


def danmaku_out(d: Danmaku, viewer_id: int | None) -> dict:
    return {"id": d.id, "time_ms": d.time_ms, "mode": d.mode, "color": d.color, "size": d.size,
            "text": d.text, "user_hash": user_hash(d.user_id), "mine": d.user_id == viewer_id,
            "created_at": vsvc.iso(d.created_at)}


def _talkable(v: Video) -> None:
    if v.status != "published":
        raise HTTPException(409, "视频还没公开,不能发弹幕和评论")


async def post_danmaku(db: AsyncSession, user: User, v: Video, part: VideoPart, *, text: str,
                       time_ms: int, mode: int, color: int, size: int) -> Danmaku:
    _talkable(v)
    if not v.allow_danmaku:
        raise HTTPException(403, "UP 主关闭了这个视频的弹幕")
    if await blocked_between(db, user.id, v.uploader_id):
        raise HTTPException(403, "你们之间有拉黑关系,不能在这个视频下发弹幕")
    t = clean_danmaku(text, time_ms, mode, color, size, part.duration_ms)
    from .moderation import guard_text
    await guard_text(db, t, "弹幕")
    d = Danmaku(video_id=v.id, part_id=part.id, user_id=user.id, time_ms=int(time_ms),
                mode=mode, color=color, size=size, text=t,
                created_at=datetime.now(timezone.utc))
    db.add(d)
    await db.flush()
    await db.execute(update(Video).where(Video.id == v.id)
                     .values(danmaku_count=Video.danmaku_count + 1)
                     .execution_options(synchronize_session=False))
    await vsvc.bump_stat(db, v.id, danmaku=1)
    return d


async def list_danmaku(db: AsyncSession, viewer: User | None, v: Video, part: VideoPart,
                       segment: int) -> dict:
    viewer_id = viewer.id if viewer else None
    hidden = await blocked_ids(db, viewer_id)
    lo, hi = segment * SEGMENT_MS, (segment + 1) * SEGMENT_MS
    q = select(Danmaku).where(Danmaku.part_id == part.id, Danmaku.deleted_at.is_(None),
                              Danmaku.time_ms >= lo, Danmaku.time_ms < hi)
    if hidden:
        q = q.where(Danmaku.user_id.notin_(hidden))
    rows = list(await db.scalars(q.order_by(Danmaku.time_ms, Danmaku.id).limit(SEGMENT_CAP)))
    return {"part_id": part.id, "segment": segment, "segment_ms": SEGMENT_MS,
            "segments": max(1, math.ceil((part.duration_ms or 1) / SEGMENT_MS)),
            "allow_danmaku": v.allow_danmaku,
            "items": [danmaku_out(d, viewer_id) for d in rows]}


async def danmaku_density(db: AsyncSession, viewer: User | None, part: VideoPart) -> dict:
    """高能进度条:5 秒一桶的弹幕数。"""
    hidden = await blocked_ids(db, viewer.id if viewer else None)
    bucket = func.floor(Danmaku.time_ms / DENSITY_BUCKET_MS)
    q = select(bucket, func.count()).where(Danmaku.part_id == part.id,
                                           Danmaku.deleted_at.is_(None))
    if hidden:
        q = q.where(Danmaku.user_id.notin_(hidden))
    rows = dict((int(b), int(n)) for b, n in (await db.execute(q.group_by(bucket))).all())
    n = max(1, math.ceil((part.duration_ms or 1) / DENSITY_BUCKET_MS))
    return {"part_id": part.id, "bucket_ms": DENSITY_BUCKET_MS,
            "counts": [rows.get(i, 0) for i in range(n)]}


async def delete_danmaku(db: AsyncSession, user: User | None, d: Danmaku, v: Video, *,
                         by_admin: bool = False) -> None:
    """发的人删自己的;UP 主删自己视频下任何人的;审核员处置举报时也走这里。"""
    if not by_admin and (user is None or user.id not in (d.user_id, v.uploader_id)):
        raise HTTPException(403, "只有发弹幕的人和 UP 主能删")
    if d.deleted_at is not None:
        return
    d.deleted_at = datetime.now(timezone.utc)
    await db.execute(update(Video).where(Video.id == v.id)
                     .values(danmaku_count=func.greatest(Video.danmaku_count - 1, 0))
                     .execution_options(synchronize_session=False))


# ---------------- 评论 ----------------

COMMENT_MAX = 1000
REPLIES_PREVIEW = 3
PAGE = 20
MENTIONS_MAX = 10
_MENTION_RE = re.compile(r"@([A-Za-z](?:[A-Za-z0-9]|_(?!_)){3,30}[A-Za-z0-9])(?![A-Za-z0-9_])")


def clean_comment(text: str) -> str:
    """校验评论正文(纯函数):不能空、最多 1000 字。评论可以多行,只把首尾空白去掉。"""
    if not isinstance(text, str):
        raise HTTPException(422, "评论不能为空")
    t = text.strip()
    if not t:
        raise HTTPException(422, "评论不能为空")
    if len(t) > COMMENT_MAX:
        raise HTTPException(422, f"评论最多 {COMMENT_MAX} 字")
    return t


def parse_mentions(text: str) -> list[str]:
    """文中的 @用户名(规则同 §5.1 用户名),小写去重,最多 10 个。纯函数。"""
    out: list[str] = []
    for m in _MENTION_RE.finditer(text or ""):
        name = m.group(1).lower()
        if name not in out:
            out.append(name)
        if len(out) >= MENTIONS_MAX:
            break
    return out


async def _resolve_mentions(db: AsyncSession, names: list[str]) -> list[dict]:
    if not names:
        return []
    rows = (await db.execute(select(Username.username_lc, Username.owner_id).where(
        Username.username_lc.in_(names), Username.owner_type == "user"))).all()
    by = {n: uid for n, uid in rows}
    return [{"user_id": by[n], "username": n} for n in names if n in by]


async def get_comment(db: AsyncSession, comment_id: int, *, lock: bool = False) -> VideoComment:
    q = select(VideoComment).where(VideoComment.id == comment_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    c = await db.scalar(q)
    if c is None or c.deleted_at is not None:
        raise HTTPException(404, "评论不存在或已删除")
    return c


async def post_comment(db: AsyncSession, user: User, v: Video, text: str,
                       parent_id: int | None) -> VideoComment:
    _talkable(v)
    if not v.allow_comments:
        raise HTTPException(403, "UP 主关闭了这个视频的评论")
    if await blocked_between(db, user.id, v.uploader_id):
        raise HTTPException(403, "你们之间有拉黑关系,不能评论这个视频")
    t = clean_comment(text)
    root: VideoComment | None = None
    parent: VideoComment | None = None
    if parent_id:
        parent = await get_comment(db, parent_id)
        if parent.video_id != v.id:
            raise HTTPException(404, "评论不存在或已删除")
        # 锁住楼主那条(回复数要 +1);楼主被删了就不能再往里回复
        root = await get_comment(db, parent.root_id or parent.id, lock=True)
        if await blocked_between(db, user.id, parent.user_id):
            raise HTTPException(403, "你们之间有拉黑关系,不能回复")
    from .moderation import guard_text
    await guard_text(db, t, "评论")
    mentions = await _resolve_mentions(db, parse_mentions(t))
    c = VideoComment(video_id=v.id, user_id=user.id, root_id=root.id if root else None,
                     parent_id=parent.id if parent else None,
                     # 回复的是一级评论时不显示「回复 @某人」(和 B 站一样),回复的是回复才显示
                     reply_to_user_id=parent.user_id if parent is not None and
                     parent.root_id is not None else None,
                     text=t, mentions=mentions, likes=0, dislikes=0, reply_count=0,
                     pinned=False, created_at=datetime.now(timezone.utc))
    db.add(c)
    await db.flush()
    await db.execute(update(Video).where(Video.id == v.id)
                     .values(comment_count=Video.comment_count + 1)
                     .execution_options(synchronize_session=False))
    if root is not None:
        root.reply_count += 1
    await vsvc.bump_stat(db, v.id, comments=1)
    # 互动消息:回复我的 / @我的
    from .social_notify import notify
    snippet = t[:100]
    notified: set[int] = set()
    if parent is not None:
        if await notify(db, parent.user_id, "reply", actor_id=user.id, video_id=v.id,
                        comment_id=c.id, data={"target": "comment", "text": snippet,
                                               "root_id": root.id, "replied_text": parent.text[:50]}):
            notified.add(parent.user_id)
    else:
        if await notify(db, v.uploader_id, "reply", actor_id=user.id, video_id=v.id,
                        comment_id=c.id, data={"target": "video", "text": snippet,
                                               "root_id": c.id}):
            notified.add(v.uploader_id)
    for m in mentions:
        if m["user_id"] in notified or m["user_id"] == user.id:
            continue
        if await notify(db, m["user_id"], "at", actor_id=user.id, video_id=v.id, comment_id=c.id,
                        data={"target": "comment", "text": snippet,
                              "root_id": root.id if root else c.id}):
            notified.add(m["user_id"])
    return c


async def _votes_of(db: AsyncSession, viewer_id: int | None, ids: list[int]) -> dict[int, int]:
    if not viewer_id or not ids:
        return {}
    rows = (await db.execute(select(CommentVote.comment_id, CommentVote.vote).where(
        CommentVote.user_id == viewer_id, CommentVote.comment_id.in_(ids)))).all()
    return {cid: int(vt) for cid, vt in rows}


def comment_out(c: VideoComment, v: Video, people: dict, votes: dict, *,
                replies: list[dict] | None = None) -> dict:
    """评论对象。**点踩数不出现**(只用于内部治理)。"""
    rt = people.get(c.reply_to_user_id) if c.reply_to_user_id else None
    out = {"id": c.id, "vid": v.vid, "root_id": c.root_id, "parent_id": c.parent_id,
           "user": people.get(c.user_id) or {"id": c.user_id, "name": "", "username": None,
                                             "avatar": ""},
           "reply_to": {"id": rt["id"], "name": rt["name"]} if rt else None,
           "text": c.text, "mentions": c.mentions or [], "likes": c.likes,
           "my_vote": votes.get(c.id, 0), "reply_count": c.reply_count, "pinned": c.pinned,
           "is_up": c.user_id == v.uploader_id, "created_at": vsvc.iso(c.created_at)}
    if c.root_id is None:
        out["replies"] = replies or []
    return out


async def _render(db: AsyncSession, viewer_id: int | None, v: Video, roots: list[VideoComment],
                  hidden: set[int], *, with_replies: bool) -> list[dict]:
    replies: dict[int, list[VideoComment]] = {}
    if with_replies and roots:
        # 每条一级评论带最早的 3 条回复(一条 SQL:窗口函数按根分组编号)
        rn = func.row_number().over(partition_by=VideoComment.root_id,
                                    order_by=VideoComment.id).label("rn")
        sub = select(VideoComment.id, rn).where(
            VideoComment.root_id.in_([r.id for r in roots]), VideoComment.deleted_at.is_(None))
        if hidden:
            sub = sub.where(VideoComment.user_id.notin_(hidden))
        sub = sub.subquery()
        rows = list(await db.scalars(select(VideoComment).join(sub, sub.c.id == VideoComment.id)
                                     .where(sub.c.rn <= REPLIES_PREVIEW)
                                     .order_by(VideoComment.id)))
        for r in rows:
            replies.setdefault(r.root_id, []).append(r)
    all_c = roots + [r for rs in replies.values() for r in rs]
    ppl = await vsvc.people(db, viewer_id, {c.user_id for c in all_c} |
                            {c.reply_to_user_id for c in all_c if c.reply_to_user_id})
    votes = await _votes_of(db, viewer_id, [c.id for c in all_c])
    return [comment_out(r, v, ppl, votes,
                        replies=[comment_out(x, v, ppl, votes) for x in replies.get(r.id, [])])
            for r in roots]


async def list_comments(db: AsyncSession, viewer: User | None, v: Video, sort: str,
                        cursor: str | None, limit: int = PAGE) -> dict:
    """一级评论。hot = 置顶在前,再按(赞 + 回复数)从高到低;new = 置顶在前,再按时间倒序。

    分页:new 用上一页最后一条的 id;hot 的名次会变,用偏移量。两种都只认 `next_cursor` 原样传回。
    置顶的那条只在第一页出现。
    """
    viewer_id = viewer.id if viewer else None
    hidden = await blocked_ids(db, viewer_id)
    base = [VideoComment.video_id == v.id, VideoComment.root_id.is_(None),
            VideoComment.deleted_at.is_(None)]
    if hidden:
        base.append(VideoComment.user_id.notin_(hidden))
    pinned: list[VideoComment] = []
    if not cursor:
        pinned = list(await db.scalars(select(VideoComment).where(*base, VideoComment.pinned)
                                       .order_by(VideoComment.id).limit(1)))
    q = select(VideoComment).where(*base, VideoComment.pinned.is_(False))
    next_cursor = None
    take = limit - len(pinned)   # 置顶的那条占第一页的一个位置,一页总共还是 limit 条
    if sort == "hot":
        try:
            offset = max(0, int(cursor)) if cursor else 0
        except ValueError:
            offset = 0
        rows = list(await db.scalars(q.order_by((VideoComment.likes + VideoComment.reply_count)
                                                .desc(), VideoComment.id.desc())
                                     .offset(offset).limit(take + 1)))
        if len(rows) > take:
            next_cursor = str(offset + take)
    else:
        if cursor:
            try:
                q = q.where(VideoComment.id < int(cursor))
            except ValueError:
                pass
        rows = list(await db.scalars(q.order_by(VideoComment.id.desc()).limit(take + 1)))
        if len(rows) > take:
            next_cursor = str(rows[take - 1].id)
    rows = rows[:take]
    items = await _render(db, viewer_id, v, pinned + rows, hidden, with_replies=True)
    return {"items": items, "next_cursor": next_cursor, "sort": sort,
            "count": v.comment_count, "allow_comments": v.allow_comments}


async def list_replies(db: AsyncSession, viewer: User | None, v: Video, root: VideoComment,
                       cursor: str | None, limit: int = PAGE) -> dict:
    viewer_id = viewer.id if viewer else None
    hidden = await blocked_ids(db, viewer_id)
    q = select(VideoComment).where(VideoComment.root_id == root.id,
                                   VideoComment.deleted_at.is_(None))
    if hidden:
        q = q.where(VideoComment.user_id.notin_(hidden))
    if cursor:
        try:
            q = q.where(VideoComment.id > int(cursor))
        except ValueError:
            pass
    rows = list(await db.scalars(q.order_by(VideoComment.id).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    ppl = await vsvc.people(db, viewer_id, {c.user_id for c in rows + [root]} |
                            {c.reply_to_user_id for c in rows if c.reply_to_user_id})
    votes = await _votes_of(db, viewer_id, [c.id for c in rows + [root]])
    return {"root": comment_out(root, v, ppl, votes),
            "items": [comment_out(c, v, ppl, votes) for c in rows],
            "next_cursor": str(rows[-1].id) if more and rows else None}


async def vote(db: AsyncSession, user: User, v: Video, c: VideoComment, value: int) -> dict:
    """赞(1)/ 踩(-1)/ 取消(0)。点踩数不对外;被赞了进对方的「收到的赞」(按评论合并)。"""
    if value not in (1, -1, 0):
        raise HTTPException(422, "vote 只能是 1 / -1 / 0")
    if await blocked_between(db, user.id, c.user_id):
        raise HTTPException(404, "评论不存在或已删除")
    old_row = await db.get(CommentVote, (c.id, user.id))
    old = old_row.vote if old_row else 0
    if value != old:
        if value == 0:
            await db.execute(delete(CommentVote).where(CommentVote.comment_id == c.id,
                                                       CommentVote.user_id == user.id))
        else:
            await db.execute(insert(CommentVote).values(
                comment_id=c.id, user_id=user.id, vote=value,
                created_at=datetime.now(timezone.utc))
                .on_conflict_do_update(index_elements=["comment_id", "user_id"],
                                       set_={"vote": value}))
        likes_d = (value == 1) - (old == 1)
        dis_d = (value == -1) - (old == -1)
        new_likes = await db.scalar(
            update(VideoComment).where(VideoComment.id == c.id)
            .values(likes=func.greatest(VideoComment.likes + likes_d, 0),
                    dislikes=func.greatest(VideoComment.dislikes + dis_d, 0))
            .returning(VideoComment.likes).execution_options(synchronize_session=False))
        if value == 1:
            from .social_notify import notify
            await notify(db, c.user_id, "like", actor_id=user.id, video_id=v.id,
                         comment_id=c.id, group_key=f"like:comment:{c.id}",
                         count=int(new_likes or 1),
                         data={"target": "comment", "text": c.text[:50]})
    likes = await db.scalar(select(VideoComment.likes).where(VideoComment.id == c.id))
    return {"id": c.id, "likes": int(likes or 0), "my_vote": value}


async def pin(db: AsyncSession, user: User, v: Video, c: VideoComment, pinned: bool) -> dict:
    """UP 主置顶一条一级评论(置顶新的,旧的自动取消)。"""
    if user.id != v.uploader_id:
        raise HTTPException(403, "只有 UP 主能置顶评论")
    if c.root_id is not None:
        raise HTTPException(422, "只能置顶一级评论")
    if pinned:
        await db.execute(update(VideoComment).where(VideoComment.video_id == v.id,
                                                    VideoComment.pinned.is_(True),
                                                    VideoComment.id != c.id)
                         .values(pinned=False).execution_options(synchronize_session=False))
    c.pinned = pinned
    return {"id": c.id, "pinned": pinned}


async def delete_comment(db: AsyncSession, user: User | None, v: Video, c: VideoComment, *,
                         by_admin: bool = False) -> None:
    """删评论:作者、UP 主(自己视频下的)、或者审核员。删一级评论连同它的回复一起不再显示。"""
    if not by_admin and (user is None or user.id not in (c.user_id, v.uploader_id)):
        raise HTTPException(403, "只有评论的作者和 UP 主能删")
    now = datetime.now(timezone.utc)
    c.deleted_at = now
    c.pinned = False
    if c.root_id is None:
        visible_replies = await db.scalar(select(func.count()).select_from(VideoComment).where(
            VideoComment.root_id == c.id, VideoComment.deleted_at.is_(None)))
        gone = 1 + int(visible_replies or 0)
    else:
        gone = 1
        await db.execute(update(VideoComment).where(VideoComment.id == c.root_id)
                         .values(reply_count=func.greatest(VideoComment.reply_count - 1, 0))
                         .execution_options(synchronize_session=False))
    await db.execute(update(Video).where(Video.id == v.id)
                     .values(comment_count=func.greatest(Video.comment_count - gone, 0))
                     .execution_options(synchronize_session=False))
