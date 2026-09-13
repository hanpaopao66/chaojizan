"""互动消息(DEV-PROMPTS-40 #367):回复我的 / @我的 / 收到的赞 / 系统通知。

- **赞按对象合并**:同一个人的同一个对象(我的某个视频、某条评论)只有一行,新的赞来了更新
  actors / count 并重新变成未读 —— 列表里是「小王等 12 人赞了你的视频」,不是 12 行;
- 拉黑的人(任意一方拉黑,S7)产生的互动不进消息;自己给自己的也不进;
- 每产生一条(或已读状态变了),同一个事务里给收件人追加一个用户事件 `notify`
  (`{"kind": …, "unread": {…}}`),提交之后实时下发 —— 客户端的角标靠它实时变,不用轮询。
"""
from datetime import datetime, timezone

from sqlalchemy import func, select, tuple_, update
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import NOTIFY_KINDS, SocialNotification, Video, VideoComment
from .rt_events import append_user_event
from .social import blocked_between

KIND_LABELS = {"reply": "回复我的", "at": "@我的", "like": "收到的赞", "system": "系统通知"}
#: 合并的赞里记住最近几个人
ACTORS_KEEP = 10
PAGE = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def unread_counts(db: AsyncSession, user_id: int) -> dict[str, int]:
    rows = (await db.execute(
        select(SocialNotification.kind, func.count()).where(
            SocialNotification.user_id == user_id, SocialNotification.read_at.is_(None))
        .group_by(SocialNotification.kind))).all()
    out = {k: 0 for k in NOTIFY_KINDS}
    for k, n in rows:
        if k in out:
            out[k] = int(n)
    out["total"] = sum(out[k] for k in NOTIFY_KINDS)
    return out


async def _push_unread(db: AsyncSession, user_id: int, kind: str | None) -> None:
    await db.flush()
    await append_user_event(db, user_id, "notify",
                            {"kind": kind, "unread": await unread_counts(db, user_id)})


async def notify(db: AsyncSession, user_id: int, kind: str, *, actor_id: int | None = None,
                 video_id: int | None = None, comment_id: int | None = None,
                 group_key: str = "", count: int = 1, data: dict | None = None) -> bool:
    """记一条互动消息。返回是否真的记了(自己 / 拉黑的不记)。调用方负责提交。"""
    assert kind in NOTIFY_KINDS, kind
    if actor_id is not None and actor_id == user_id:
        return False
    if actor_id is not None and await blocked_between(db, user_id, actor_id):
        return False
    now = _now()
    if group_key:
        row = await _locked_group_row(db, user_id, group_key)
        if row is None:
            res = await db.execute(
                insert(SocialNotification).values(
                    user_id=user_id, kind=kind, actor_id=actor_id, video_id=video_id,
                    comment_id=comment_id, group_key=group_key, count=max(1, count),
                    actors=[actor_id] if actor_id else [], data=data or {},
                    created_at=now, updated_at=now)
                .on_conflict_do_nothing(index_elements=["user_id", "group_key"],
                                        index_where=sql_text("group_key <> ''"))
                .returning(SocialNotification.id))
            if res.scalar() is None:  # 同时来了两个赞:另一个先插上了,锁住它再合并
                row = await _locked_group_row(db, user_id, group_key)
        if row is not None:
            actors = [a for a in (row.actors or []) if a != actor_id]
            row.actors = ([actor_id] if actor_id else []) + actors[:ACTORS_KEEP - 1]
            row.actor_id = actor_id
            row.count = max(1, count)
            row.data = data or {}
            row.read_at = None
            row.updated_at = now
    else:
        db.add(SocialNotification(user_id=user_id, kind=kind, actor_id=actor_id,
                                  video_id=video_id, comment_id=comment_id, group_key="",
                                  count=1, actors=[actor_id] if actor_id else [],
                                  data=data or {}, created_at=now, updated_at=now))
    await _push_unread(db, user_id, kind)
    return True


async def _locked_group_row(db: AsyncSession, user_id: int, group_key: str):
    # FOR UPDATE 必须配 populate_existing:会话里已经有这一行的旧快照时,
    # 不加它拿到的是旧值(锁是拿到了,数据还是锁之前读的)
    return await db.scalar(
        select(SocialNotification).where(SocialNotification.user_id == user_id,
                                         SocialNotification.group_key == group_key)
        .with_for_update().execution_options(populate_existing=True))


async def system(db: AsyncSession, user_id: int, title: str, text: str, *,
                 video_id: int | None = None, action: str = "", reason_code: str = "",
                 extra: dict | None = None) -> None:
    """系统通知:审核结果、处罚、申诉结果、硬币到账。"""
    from .video import REASON_CODES
    data = {"title": title, "text": text, "action": action, "reason_code": reason_code,
            "reason_label": REASON_CODES.get(reason_code, ""), **(extra or {})}
    await notify(db, user_id, "system", video_id=video_id, data=data)


def _cursor_of(n: SocialNotification) -> str:
    return f"{int(n.updated_at.timestamp() * 1_000_000)}_{n.id}"


def _parse_cursor(cursor: str | None):
    if not cursor:
        return None
    try:
        ts, nid = cursor.split("_", 1)
        return datetime.fromtimestamp(int(ts) / 1_000_000, tz=timezone.utc), int(nid)
    except (ValueError, OverflowError):
        return None


def _title(n: SocialNotification, actor_name: str) -> str:
    d = n.data or {}
    if n.kind == "system":
        return d.get("title") or "系统通知"
    target = "视频" if d.get("target") == "video" else "评论"
    if n.kind == "like":
        return (f"{actor_name}等 {n.count} 人赞了你的{target}" if n.count > 1
                else f"{actor_name} 赞了你的{target}")
    if n.kind == "at":
        return f"{actor_name} 在评论里 @ 了你"
    return f"{actor_name} 评论了你的视频" if d.get("target") == "video" else \
        f"{actor_name} 回复了你的评论"


async def list_items(db: AsyncSession, viewer_id: int, kind: str, cursor: str | None = None,
                     limit: int = PAGE) -> dict:
    from .video import people, video_brief

    q = select(SocialNotification).where(SocialNotification.user_id == viewer_id,
                                         SocialNotification.kind == kind)
    cur = _parse_cursor(cursor)
    if cur is not None:
        q = q.where(tuple_(SocialNotification.updated_at, SocialNotification.id) < tuple_(*cur))
    rows = list(await db.scalars(q.order_by(SocialNotification.updated_at.desc(),
                                            SocialNotification.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    actor_ids = {a for n in rows for a in (n.actors or [])[:3]} | \
        {n.actor_id for n in rows if n.actor_id}
    cards = await people(db, viewer_id, actor_ids)
    vids = {n.video_id for n in rows if n.video_id}
    videos = {v.id: v for v in await db.scalars(select(Video).where(Video.id.in_(vids)))} \
        if vids else {}
    cids = {n.comment_id for n in rows if n.comment_id}
    comments = {c.id: c for c in await db.scalars(
        select(VideoComment).where(VideoComment.id.in_(cids)))} if cids else {}
    items = []
    for n in rows:
        actor = cards.get(n.actor_id) if n.actor_id else None
        v = videos.get(n.video_id) if n.video_id else None
        c = comments.get(n.comment_id) if n.comment_id else None
        items.append({
            "id": n.id,
            "kind": n.kind,
            "title": _title(n, actor["name"] if actor else "有人"),
            "text": (n.data or {}).get("text", "") if not (c and c.deleted_at) else "该评论已删除",
            "actor": actor,
            "actors": [cards[a] for a in (n.actors or [])[:3] if a in cards],
            "count": n.count,
            "video": video_brief(v) if v is not None and v.deleted_at is None else None,
            "comment": {"id": c.id, "root_id": c.root_id or c.id,
                        "deleted": c.deleted_at is not None} if c is not None else None,
            "data": {k: v2 for k, v2 in (n.data or {}).items() if k not in ("text",)},
            "read": n.read_at is not None,
            "created_at": n.created_at.isoformat(),
            "updated_at": n.updated_at.isoformat(),
        })
    return {"items": items, "next_cursor": _cursor_of(rows[-1]) if more and rows else None,
            "unread": await unread_counts(db, viewer_id)}


async def mark_read(db: AsyncSession, user_id: int, *, kind: str | None = None,
                    ids: list[int] | None = None) -> dict[str, int]:
    q = update(SocialNotification).where(SocialNotification.user_id == user_id,
                                         SocialNotification.read_at.is_(None))
    if kind:
        q = q.where(SocialNotification.kind == kind)
    if ids:
        q = q.where(SocialNotification.id.in_(ids))
    await db.execute(q.values(read_at=_now()).execution_options(synchronize_session=False))
    await _push_unread(db, user_id, kind)
    return await unread_counts(db, user_id)
