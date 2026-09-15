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


#: 目标列(#367 视频两个,#378 音乐三个)。加新模块的目标时只往这里加一行 ——
#: notify() 的签名和插入语句都从它生成,不用改三处
TARGET_COLUMNS = ("video_id", "comment_id", "music_track_id", "music_comment_id",
                  "music_release_id")


async def notify(db: AsyncSession, user_id: int, kind: str, *, actor_id: int | None = None,
                 video_id: int | None = None, comment_id: int | None = None,
                 group_key: str = "", count: int = 1, data: dict | None = None,
                 **targets) -> bool:
    """记一条互动消息。返回是否真的记了(自己 / 拉黑的不记)。调用方负责提交。

    `targets` 是别的模块的目标列(音乐:music_track_id / music_comment_id / music_release_id),
    见 TARGET_COLUMNS —— 不认识的键直接报错,免得写错列名之后消息静默地少一个跳转目标。
    """
    assert kind in NOTIFY_KINDS, kind
    bad = set(targets) - set(TARGET_COLUMNS)
    assert not bad, bad
    cols = {"video_id": video_id, "comment_id": comment_id,
            **{k: targets.get(k) for k in TARGET_COLUMNS if k not in ("video_id", "comment_id")}}
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
                    user_id=user_id, kind=kind, actor_id=actor_id, **cols,
                    group_key=group_key, count=max(1, count),
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
        db.add(SocialNotification(user_id=user_id, kind=kind, actor_id=actor_id, **cols,
                                  group_key="", count=1,
                                  actors=[actor_id] if actor_id else [],
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
                 reason_label: str | None = None, extra: dict | None = None,
                 **targets) -> None:
    """系统通知:审核结果、处罚、申诉结果、硬币到账。

    `reason_label` 不给时按视频的原因代码表翻;音乐、论坛的代码不在那张表里,
    调用方自己把翻好的文字传进来(各模块的代码表见各自的 REASON_CODES)。
    """
    from .video import REASON_CODES
    data = {"title": title, "text": text, "action": action, "reason_code": reason_code,
            "reason_label": reason_label if reason_label is not None
            else REASON_CODES.get(reason_code, ""), **(extra or {})}
    await notify(db, user_id, "system", video_id=video_id, data=data, **targets)


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
    if n.kind == "follow":
        # 一天的新粉丝合并成一行(video_interact.set_follow 的 group_key 按北京日)
        return (f"{actor_name}等 {n.count} 人关注了你" if n.count > 1
                else f"{actor_name} 关注了你")
    # 音乐(#378 §5.8):目标是歌 / 歌曲评论,文案要说「歌」,不能沿用视频那一套
    if d.get("target") in ("track", "mcomment"):
        target = "歌" if d["target"] == "track" else "评论"
        if n.kind == "like":
            return (f"{actor_name}等 {n.count} 人赞了你的{target}" if n.count > 1
                    else f"{actor_name} 赞了你的{target}")
        if n.kind == "at":
            return f"{actor_name} 在歌曲评论里 @ 了你"
        return (f"{actor_name} 评论了你的歌" if d["target"] == "track"
                else f"{actor_name} 回复了你的评论")
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
    music = await _music_targets(db, rows)
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
            # 音乐(§5.8):客户端按有哪个字段决定点开去哪。没有的一律 None,不是缺键
            "track": music["tracks"].get(n.music_track_id) if n.music_track_id else None,
            "release": music["releases"].get(n.music_release_id) if n.music_release_id else None,
            "music_comment": (music["comments"].get(n.music_comment_id)
                              if n.music_comment_id else None),
        })
    return {"items": items, "next_cursor": _cursor_of(rows[-1]) if more and rows else None,
            "unread": await unread_counts(db, viewer_id)}


async def _music_targets(db: AsyncSession, rows) -> dict[str, dict]:
    """这一页里被指到的歌、作品、歌曲评论(#378 §5.8)。一次查完,不在循环里查库。"""
    from ..models import MusicComment, MusicRelease, MusicTrack

    tids = {n.music_track_id for n in rows if n.music_track_id}
    rids = {n.music_release_id for n in rows if n.music_release_id}
    cids = {n.music_comment_id for n in rows if n.music_comment_id}
    tracks: dict[int, dict] = {}
    releases: dict[int, dict] = {}
    comments: dict[int, dict] = {}
    if tids:
        covers = dict((await db.execute(
            select(MusicTrack.id, MusicRelease.cover_url)
            .join(MusicRelease, MusicRelease.id == MusicTrack.release_id)
            .where(MusicTrack.id.in_(tids)))).all())
        for t in await db.scalars(select(MusicTrack).where(MusicTrack.id.in_(tids))):
            tracks[t.id] = {"tid": t.tid, "title": t.title, "cover": covers.get(t.id) or ""}
    if rids:
        for r in await db.scalars(select(MusicRelease).where(MusicRelease.id.in_(rids))):
            releases[r.id] = {"rid": r.rid, "title": r.title}
    if cids:
        for c in await db.scalars(select(MusicComment).where(MusicComment.id.in_(cids))):
            comments[c.id] = {"id": c.id, "root_id": c.root_id or c.id,
                              "deleted": c.status != "visible"}
    return {"tracks": tracks, "releases": releases, "comments": comments}


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
