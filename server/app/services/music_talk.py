"""歌曲评论(DEV-PROMPTS-41 §8.2):热评、楼中楼、赞、@、删除。

口径和视频评论一样(services/video_talk.py),差别只有三处:

- 目标是歌(`music_track_id`),互动消息里的文案说「歌」不说「视频」(§5.8);
- 删除是 `status = 'deleted'` 而不是 `deleted_at` —— 举报处置要能区分「自己删的」和
  「被下架的」(`removed`),用一列状态比两列时间清楚;
- 能替作者删评论的是**这首歌的音乐人**(歌的作者),不是视频里的 UP 主。

@ 超级赞号的解析和展示口径直接复用 video_talk:同一个开关(「按超级赞号找到我」)只该有一处判定。
"""
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (MusicArtist, MusicComment, MusicCommentLike, MusicRelease, MusicTrack,
                      User)
from . import music as msvc
from .social import blocked_between
from .video import iso, people, utcnow
from .video_talk import (COMMENT_MAX, MENTIONS_MAX, PAGE, REPLIES_PREVIEW, blocked_ids,
                         clean_comment, mentions_off, parse_mentions)

__all__ = ["COMMENT_MAX", "MENTIONS_MAX", "PAGE", "REPLIES_PREVIEW", "clean_comment",
           "get_comment", "post_comment", "list_comments", "list_replies", "set_like",
           "delete_comment", "comment_out"]


async def get_comment(db: AsyncSession, comment_id: int, *,
                      lock: bool = False) -> MusicComment:
    q = select(MusicComment).where(MusicComment.id == comment_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    c = await db.scalar(q)
    if c is None or c.status != "visible":
        raise HTTPException(404, "评论不存在或已删除")
    return c


async def _artist_user_id(db: AsyncSession, t: MusicTrack) -> int | None:
    a = await db.get(MusicArtist, t.artist_id)
    return a.user_id if a is not None else None


async def post_comment(db: AsyncSession, user: User, t: MusicTrack, text: str,
                       parent_id: int | None) -> MusicComment:
    from .moderation import guard_text
    from .sanctions import check_user
    from .social_notify import notify
    from .video_talk import _resolve_mentions

    await check_user(db, user.id, "comment")   # 禁言、封号(#368,和视频评论同一个执行点)
    author_id = await _artist_user_id(db, t)
    if author_id is not None and await blocked_between(db, user.id, author_id):
        raise HTTPException(403, "你们之间有拉黑关系,不能评论这首歌")
    body = clean_comment(text)
    root: MusicComment | None = None
    parent: MusicComment | None = None
    if parent_id:
        parent = await get_comment(db, parent_id)
        if parent.track_id != t.id:
            raise HTTPException(404, "评论不存在或已删除")
        # 锁住楼主那条(回复数要 +1);楼主被删了就不能再往里回复
        root = await get_comment(db, parent.root_id or parent.id, lock=True)
        if await blocked_between(db, user.id, parent.user_id):
            raise HTTPException(403, "你们之间有拉黑关系,不能回复")
    await guard_text(db, body, "评论")
    mentions = await _resolve_mentions(db, parse_mentions(body))
    c = MusicComment(track_id=t.id, user_id=user.id, root_id=root.id if root else None,
                     parent_id=parent.id if parent else None,
                     # 回复一级评论时不显示「回复 @某人」,回复的是回复才显示
                     reply_to_user_id=parent.user_id if parent is not None
                     and parent.root_id is not None else None,
                     text=body, mentions=mentions, likes=0, reply_count=0, status="visible",
                     created_at=utcnow())
    db.add(c)
    await db.flush()
    await db.execute(update(MusicTrack).where(MusicTrack.id == t.id)
                     .values(comments=MusicTrack.comments + 1)
                     .execution_options(synchronize_session=False))
    if root is not None:
        root.reply_count += 1
    snippet = body[:100]
    notified: set[int] = set()
    if parent is not None:
        if await notify(db, parent.user_id, "reply", actor_id=user.id, music_track_id=t.id,
                        music_comment_id=c.id,
                        data={"target": "mcomment", "text": snippet, "root_id": root.id,
                              "replied_text": parent.text[:50]}):
            notified.add(parent.user_id)
    elif author_id is not None:
        if await notify(db, author_id, "reply", actor_id=user.id, music_track_id=t.id,
                        music_comment_id=c.id,
                        data={"target": "track", "text": snippet, "root_id": c.id}):
            notified.add(author_id)
    for m in mentions:
        if m["user_id"] in notified or m["user_id"] == user.id:
            continue
        if await notify(db, m["user_id"], "at", actor_id=user.id, music_track_id=t.id,
                        music_comment_id=c.id,
                        data={"target": "mcomment", "text": snippet,
                              "root_id": root.id if root else c.id}):
            notified.add(m["user_id"])
    return c


def comment_out(c: MusicComment, ppl: dict, liked: set[int], *,
                viewer_id: int | None = None, author_user_id: int | None = None,
                mentions_hidden: frozenset | set = frozenset()) -> dict:
    ms = [m for m in (c.mentions or [])
          if isinstance(m, dict) and m.get("user_id") not in mentions_hidden]
    return {
        "id": c.id,
        "user": ppl.get(c.user_id),
        "text": c.text,
        "mentions": ms,
        "likes": c.likes,
        "liked": c.id in liked,
        "reply_count": c.reply_count,
        "root_id": c.root_id,
        "reply_to": ppl.get(c.reply_to_user_id) if c.reply_to_user_id else None,
        "created_at": iso(c.created_at),
        "mine": viewer_id is not None and viewer_id == c.user_id,
        "by_artist": author_user_id is not None and c.user_id == author_user_id,
        # 能删这条的:自己写的,或者这首歌的音乐人(§8.2「删自己的(或歌的作者删)」)
        "can_delete": viewer_id is not None and (viewer_id == c.user_id
                                                 or viewer_id == author_user_id),
    }


async def _liked_of(db: AsyncSession, viewer_id: int | None, ids: list[int]) -> set[int]:
    if not viewer_id or not ids:
        return set()
    return set(await db.scalars(select(MusicCommentLike.comment_id).where(
        MusicCommentLike.user_id == viewer_id, MusicCommentLike.comment_id.in_(ids))))


async def _render(db: AsyncSession, viewer_id: int | None, t: MusicTrack,
                  rows: list[MusicComment], hidden: set[int], *,
                  with_replies: bool) -> list[dict]:
    author_user_id = await _artist_user_id(db, t)
    replies: dict[int, list[MusicComment]] = {}
    if with_replies and rows:
        for r in await db.scalars(select(MusicComment).where(
                MusicComment.root_id.in_([c.id for c in rows]),
                MusicComment.status == "visible").order_by(MusicComment.id)):
            if r.user_id not in hidden:
                replies.setdefault(r.root_id, []).append(r)
    every = list(rows) + [r for v in replies.values() for r in v]
    ppl = await people(db, viewer_id, [c.user_id for c in every]
                       + [c.reply_to_user_id for c in every if c.reply_to_user_id])
    liked = await _liked_of(db, viewer_id, [c.id for c in every])
    off = await mentions_off(db, every)
    out = []
    for c in rows:
        item = comment_out(c, ppl, liked, viewer_id=viewer_id, author_user_id=author_user_id,
                           mentions_hidden=off)
        if with_replies:
            kids = replies.get(c.id, [])
            item["replies"] = [comment_out(r, ppl, liked, viewer_id=viewer_id,
                                           author_user_id=author_user_id, mentions_hidden=off)
                               for r in kids[:REPLIES_PREVIEW]]
        out.append(item)
    return out


async def list_comments(db: AsyncSession, viewer: User | None, t: MusicTrack, sort: str,
                        cursor: str | None, limit: int = PAGE) -> dict:
    """一级评论。hot = 按(赞 + 回复数)从高到低;new = 按时间倒序。第一页带 `hot`(最多 3 条热评)。

    分页:new 用上一页最后一条的 id;hot 的名次会变,用偏移量。两种都只认 next_cursor 原样传回。
    """
    viewer_id = viewer.id if viewer else None
    hidden = await blocked_ids(db, viewer_id)
    base = [MusicComment.track_id == t.id, MusicComment.root_id.is_(None),
            MusicComment.status == "visible"]
    if hidden:
        base.append(MusicComment.user_id.notin_(hidden))
    q = select(MusicComment).where(*base)
    next_cursor = None
    if sort == "hot":
        try:
            offset = max(0, int(cursor)) if cursor else 0
        except ValueError:
            offset = 0
        rows = list(await db.scalars(
            q.order_by((MusicComment.likes + MusicComment.reply_count).desc(),
                       MusicComment.id.desc()).offset(offset).limit(limit + 1)))
        if len(rows) > limit:
            next_cursor = str(offset + limit)
    else:
        if cursor:
            try:
                q = q.where(MusicComment.id < int(cursor))
            except ValueError:
                pass
        rows = list(await db.scalars(q.order_by(MusicComment.id.desc()).limit(limit + 1)))
        if len(rows) > limit:
            next_cursor = str(rows[limit - 1].id)
    rows = rows[:limit]
    out = {"items": await _render(db, viewer_id, t, rows, hidden, with_replies=True),
           "has_more": next_cursor is not None, "next_cursor": next_cursor, "sort": sort,
           "total": int(await db.scalar(select(func.count()).select_from(MusicComment).where(
               MusicComment.track_id == t.id, MusicComment.status == "visible")) or 0)}
    if not cursor:
        hot_rows = list(await db.scalars(select(MusicComment).where(*base).order_by(
            (MusicComment.likes + MusicComment.reply_count).desc(), MusicComment.id.desc())
            .limit(REPLIES_PREVIEW)))
        # 一条赞都没有的评论不算「热评」—— 新歌下面的第一条评论顶上去只会误导
        hot_rows = [c for c in hot_rows if c.likes > 0]
        out["hot"] = await _render(db, viewer_id, t, hot_rows, hidden, with_replies=False)
    return out


async def list_replies(db: AsyncSession, viewer: User | None, t: MusicTrack,
                       root: MusicComment, cursor: str | None, limit: int = PAGE) -> dict:
    viewer_id = viewer.id if viewer else None
    hidden = await blocked_ids(db, viewer_id)
    q = select(MusicComment).where(MusicComment.root_id == root.id,
                                   MusicComment.status == "visible")
    if hidden:
        q = q.where(MusicComment.user_id.notin_(hidden))
    if cursor:
        try:
            q = q.where(MusicComment.id > int(cursor))
        except ValueError:
            pass
    rows = list(await db.scalars(q.order_by(MusicComment.id).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": await _render(db, viewer_id, t, rows, hidden, with_replies=False),
            "has_more": more, "next_cursor": str(rows[-1].id) if more and rows else None,
            "total": root.reply_count}


async def set_like(db: AsyncSession, user: User, c: MusicComment, like: bool) -> dict:
    from .social_notify import notify

    if like:
        added = (await db.execute(
            insert(MusicCommentLike).values(user_id=user.id, comment_id=c.id,
                                            created_at=utcnow())
            .on_conflict_do_nothing().returning(MusicCommentLike.comment_id))).scalar()
        if added is not None:
            c.likes += 1
            await notify(db, c.user_id, "like", actor_id=user.id, music_track_id=c.track_id,
                         music_comment_id=c.id, group_key=f"like:mcomment:{c.id}",
                         count=c.likes, data={"target": "mcomment", "text": c.text[:50]})
    else:
        res = await db.execute(delete_comment_like(user.id, c.id))
        if res.rowcount:
            c.likes = max(0, c.likes - 1)
    return {"liked": like, "likes": c.likes}


def delete_comment_like(user_id: int, comment_id: int):
    from sqlalchemy import delete

    return delete(MusicCommentLike).where(MusicCommentLike.user_id == user_id,
                                          MusicCommentLike.comment_id == comment_id)


async def delete_comment(db: AsyncSession, user: User | None, t: MusicTrack, c: MusicComment,
                         *, by_admin: bool = False, removed: bool = False) -> None:
    """作者删自己的;这首歌的音乐人删自己歌下面的;管理员按举报删(removed)。

    删一级评论时楼里的回复一起不再显示(查询都带 root 的状态判断,不用逐条改)。
    """
    if not by_admin:
        author_id = await _artist_user_id(db, t)
        if user is None or (user.id != c.user_id and user.id != author_id
                            and not msvc.is_admin(user)):
            raise HTTPException(403, "只能删自己的评论")
    c.status = "removed" if removed else "deleted"
    await db.execute(update(MusicTrack).where(MusicTrack.id == t.id)
                     .values(comments=func.greatest(MusicTrack.comments - 1, 0))
                     .execution_options(synchronize_session=False))
    if c.root_id:
        root = await db.get(MusicComment, c.root_id)
        if root is not None:
            root.reply_count = max(0, root.reply_count - 1)


async def track_of_comment(db: AsyncSession, c: MusicComment,
                           viewer: User | None) -> MusicTrack:
    """评论所在的歌,顺手判一次可见(作品没过审 / 下架了,评论也跟着看不见)。"""
    t = await db.get(MusicTrack, c.track_id)
    if t is None:
        raise HTTPException(404, "评论不存在或已删除")
    r = await db.get(MusicRelease, t.release_id)
    a = await db.get(MusicArtist, t.artist_id)
    if not msvc.release_visible(r, a, viewer):
        raise HTTPException(404, "评论不存在或已删除")
    return t
