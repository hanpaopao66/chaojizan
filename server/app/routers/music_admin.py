"""音乐的审核与治理 `/admin/music`(DEV-PROMPTS-41 §8.2「后台」,#378)。

每个写操作同时进两本账:music_decisions(给音乐人看的结论、原因代码和说明)和
admin_action_logs(平台内部复盘)。

接口层面的硬规矩(e2e_music_review 里每条都有先红后绿的用例):

- 驳回、下架必须带 §5.11 的原因代码;选 X999 必须写说明;
- 状态迁移走 services/music_state.py,非法迁移 409;
- **申诉强制换人**:处理人等于原结论人时拒绝(403)—— 自己复核自己等于没有申诉;
- 待审列表给审核员**能直接播的地址**:作品还没过审,音频在私密桶里,普通地址放不出来,
  所以这里现签一份绑定这位管理员的播放地址(§5.5,6 小时)。
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (MusicArtist, MusicComment, MusicDecision, MusicPlaylist, MusicRelease,
                      MusicReport, MusicTrack, User)
from ..security import require_role
from ..services import music as msvc
from ..services import music_state as mstate
from ..services import music_talk as talk
from ..services.admin_audit import log_admin_action

router = APIRouter(prefix="/admin/music", tags=["社区治理"])


@router.get("/reason-codes")
async def reason_codes(admin: User = Depends(require_role("admin"))):
    """原因代码表(§5.11:视频的通用项 + 音乐自己的 M3xx)。"""
    return {"items": [{"code": k, "label": v} for k, v in msvc.REASON_CODES.items()],
            "copyright_code": msvc.COPYRIGHT_CODE}


async def _review_item(db: AsyncSession, r: MusicRelease, admin: User) -> dict:
    a = await db.get(MusicArtist, r.artist_id)
    tracks = await msvc.tracks_of(db, r.id)
    people = await msvc.people(db, admin.id, [a.user_id]) if a else {}
    return {
        "rid": r.rid, "title": r.title, "kind": r.kind, "status": r.status,
        "status_label": mstate.STATUS_LABELS.get(r.status, r.status),
        "description": r.description or "", "genre": r.genre,
        "genre_name": msvc.GENRES.get(r.genre, ""), "language": r.language,
        "language_name": msvc.LANGUAGES.get(r.language, ""),
        "release_date": r.release_date.isoformat() if r.release_date else None,
        "submitted_at": msvc.iso(r.submitted_at), "created_at": msvc.iso(r.created_at),
        # 没过审的封面只在私密桶里:给审核员一份带签名的媒体地址(services/media.signed_url)
        "cover": r.cover_url or _cover_url(r, admin.id),
        "artist": ({**msvc.artist_brief(a), "bio": a.bio or "", "status": a.status,
                    "user": people.get(a.user_id)} if a else None),
        "tracks": [{"tid": t.tid, "title": t.title, "track_no": t.track_no,
                    "duration_ms": t.duration_ms, "explicit": t.explicit,
                    "declaration": t.declaration, "lyrics_kind": t.lyrics_kind,
                    "lyrics": t.lyrics or "", "credits": t.credits or {},
                    "transcode_status": t.transcode_status,
                    # 管理员的播放地址:签名绑定他自己,6 小时(§5.5)
                    "stream": msvc.stream_urls(t, admin.id)} for t in tracks],
        "reports_open": int(await db.scalar(select(func.count()).select_from(MusicReport).where(
            MusicReport.target_type == "release", MusicReport.target_id == r.id,
            MusicReport.status.in_(("open", "escalated")))) or 0),
    }


def _cover_url(r: MusicRelease, admin_id: int) -> str:
    from ..services.media import signed_url

    return signed_url(r.cover_media_id, admin_id) if r.cover_media_id else ""


@router.get("/review")
async def review_queue(limit: int = 50, admin: User = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    """待审作品队列,按提交时间先后。每首歌带能直接播的地址。"""
    rows = list(await db.scalars(select(MusicRelease).where(
        MusicRelease.status == "reviewing", MusicRelease.deleted_at.is_(None))
        .order_by(MusicRelease.submitted_at.asc().nulls_last(), MusicRelease.id)
        .limit(max(1, min(limit, 200)))))
    return {"items": [await _review_item(db, r, admin) for r in rows], "count": len(rows)}


@router.get("/releases/{rid}")
async def release_for_admin(rid: str, admin: User = Depends(require_role("admin")),
                            db: AsyncSession = Depends(get_db)):
    r = await msvc.get_release(db, rid)
    out = await _review_item(db, r, admin)
    out["decisions"] = await _decisions_out(db, r)
    return out


async def _decisions_out(db: AsyncSession, r: MusicRelease) -> list[dict]:
    rows = list(await db.scalars(select(MusicDecision).where(MusicDecision.release_id == r.id)
                                 .order_by(MusicDecision.id)))
    return [{"id": d.id, "action": d.action, "reason_code": d.reason_code,
             "reason_label": msvc.REASON_CODES.get(d.reason_code, ""), "note": d.note,
             "admin_id": d.admin_id, "created_at": msvc.iso(d.created_at),
             "appeal_text": d.appeal_text, "appeal_at": msvc.iso(d.appeal_at),
             "appeal_result": d.appeal_result, "appeal_by": d.appeal_by,
             "appeal_note": d.appeal_note} for d in rows]


class DecideIn(BaseModel):
    action: Literal["approve", "reject"]
    reason_code: str = ""
    #: 给音乐人看的说明(驳回时写清楚哪里不行)
    note: str = Field(default="", max_length=500)


@router.post("/releases/{rid}/decide")
async def decide(rid: str, body: DecideIn, admin: User = Depends(require_role("admin")),
                 db: AsyncSession = Depends(get_db)):
    r = await msvc.get_release(db, rid, lock=True)
    d = await msvc.decide(db, r, admin, approve=body.action == "approve",
                          reason_code=body.reason_code, note=body.note)
    await log_admin_action(db, admin, f"music.{d.action}", target_type="music_release",
                           target_id=r.rid, detail={"reason_code": body.reason_code})
    await db.commit()
    return {"decision_id": d.id, "action": d.action, "status": r.status}


class RemoveIn(BaseModel):
    reason_code: str
    note: str = Field(default="", max_length=500)


@router.post("/releases/{rid}/remove")
async def remove(rid: str, body: RemoveIn, admin: User = Depends(require_role("admin")),
                 db: AsyncSession = Depends(get_db)):
    """下架(处罚)。原因代码必填,X999 要写说明;音乐人收到系统通知,可以申诉。"""
    r = await msvc.get_release(db, rid, lock=True)
    d = await msvc.take_down(db, r, admin, body.reason_code, body.note)
    await log_admin_action(db, admin, "music.remove", target_type="music_release",
                           target_id=r.rid, detail={"reason_code": body.reason_code})
    await db.commit()
    return {"decision_id": d.id, "status": r.status}


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=500)


@router.post("/releases/{rid}/restore")
async def restore(rid: str, body: NoteIn | None = None,
                  admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    r = await msvc.get_release(db, rid, lock=True)
    d = await msvc.restore(db, r, admin, (body or NoteIn()).note)
    await log_admin_action(db, admin, "music.restore", target_type="music_release",
                           target_id=r.rid)
    await db.commit()
    return {"decision_id": d.id, "status": r.status}


# ---------------- 申诉(换人复核)----------------

@router.get("/appeals")
async def appeals(admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    """没处理的音乐申诉。`you_decided_original` 为真的,你不能处理(换人复核,§5.3)。"""
    items = []
    for d in await msvc.open_appeals(db):
        r = await db.get(MusicRelease, d.release_id)
        if r is None:
            continue
        a = await db.get(MusicArtist, r.artist_id)
        items.append({
            "decision_id": d.id,
            "appeal": {"text": d.appeal_text, "at": msvc.iso(d.appeal_at)},
            "original": {"action": d.action, "reason_code": d.reason_code,
                         "reason_label": msvc.REASON_CODES.get(d.reason_code, ""),
                         "note": d.note, "admin_id": d.admin_id,
                         "created_at": msvc.iso(d.created_at)},
            "release": {"rid": r.rid, "title": r.title, "status": r.status,
                        "cover": r.cover_url or ""},
            "artist": msvc.artist_brief(a) if a else None,
            "you_decided_original": d.admin_id == admin.id,
        })
    return {"items": items}


class ResolveIn(BaseModel):
    result: Literal["upheld", "overturned"]
    note: str = Field(default="", max_length=500)


@router.post("/appeals/{decision_id}/resolve")
async def resolve(decision_id: int, body: ResolveIn,
                  admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    d = await db.get(MusicDecision, decision_id)
    if d is None:
        raise HTTPException(404, "申诉不存在")
    r = await msvc.resolve_appeal(db, d, admin, overturn=body.result == "overturned",
                                  note=body.note)
    await log_admin_action(db, admin, f"music.appeal.{body.result}",
                           target_type="music_decision", target_id=d.id)
    await db.commit()
    return {"decision_id": d.id, "result": d.appeal_result, "status": r.status}


# ---------------- 举报 ----------------

async def _target_snapshot(db: AsyncSession, r: MusicReport) -> dict:
    if r.target_type == "track":
        t = await db.get(MusicTrack, r.target_id)
        if t is None:
            return {}
        rel = await db.get(MusicRelease, t.release_id)
        a = await db.get(MusicArtist, t.artist_id)
        return {"track": {"tid": t.tid, "title": t.title,
                          "release": {"rid": rel.rid, "title": rel.title,
                                      "status": rel.status} if rel else None,
                          "artist": msvc.artist_brief(a) if a else None}}
    if r.target_type == "release":
        rel = await db.get(MusicRelease, r.target_id)
        a = await db.get(MusicArtist, rel.artist_id) if rel else None
        return {"release": {"rid": rel.rid, "title": rel.title, "status": rel.status,
                            "cover": rel.cover_url or "",
                            "artist": msvc.artist_brief(a) if a else None} if rel else None}
    if r.target_type == "comment":
        c = await db.get(MusicComment, r.target_id)
        t = await db.get(MusicTrack, c.track_id) if c else None
        return {"comment": {"id": c.id, "text": c.text, "user_id": c.user_id,
                            "status": c.status} if c else None,
                "track": {"tid": t.tid, "title": t.title} if t else None}
    if r.target_type == "playlist":
        p = await db.get(MusicPlaylist, r.target_id)
        return {"playlist": {"pid": p.pid, "title": p.title, "owner_id": p.owner_id,
                             "is_public": p.is_public} if p else None}
    a = await db.get(MusicArtist, r.target_id)
    return {"artist": {**msvc.artist_brief(a), "status": a.status, "bio": a.bio or ""}
            if a else None}


@router.get("/reports")
async def reports(status: Literal["open", "all", "handled"] = "open", limit: int = 100,
                  admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    """举报。7 天内 3 人举报同一个对象的(escalated)排最前;版权投诉带联系方式。
    **举报人不出现在这里** —— 举报人对被举报的一方永远匿名。"""
    q = select(MusicReport)
    if status == "open":
        q = q.where(MusicReport.status.in_(("open", "escalated")))
    elif status == "handled":
        q = q.where(MusicReport.status.in_(("actioned", "dismissed")))
    rows = list(await db.scalars(q.order_by(
        (MusicReport.status == "escalated").desc(), MusicReport.id)
        .limit(max(1, min(limit, 500)))))
    items = []
    for r in rows:
        items.append({"id": r.id, "target_type": r.target_type, "target_id": r.target_id,
                      "reason_code": r.reason_code,
                      "reason_label": msvc.REASON_CODES.get(r.reason_code, ""),
                      "note": r.note, "contact": r.contact,
                      "is_copyright": r.reason_code == msvc.COPYRIGHT_CODE,
                      "status": r.status, "resolution": r.resolution,
                      "created_at": msvc.iso(r.created_at), **await _target_snapshot(db, r)})
    return {"items": items}


class HandleIn(BaseModel):
    #: dismiss 不成立 / remove_target 下架作品、删评论、把歌单改私密、停用音乐人
    action: Literal["dismiss", "remove_target"]
    reason_code: str = ""
    note: str = Field(default="", max_length=500)


@router.post("/reports/{report_id}/handle")
async def handle_report(report_id: int, body: HandleIn,
                        admin: User = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    """处理举报。同一个对象上所有没处理的举报一起结案。处置要带原因代码。"""
    from sqlalchemy import update as sql_update

    r = await db.get(MusicReport, report_id)
    if r is None:
        raise HTTPException(404, "举报不存在")
    if r.status not in ("open", "escalated"):
        raise HTTPException(409, "这条举报已经处理过了")
    resolution = "举报不成立"
    if body.action != "dismiss":
        msvc.reason_ok(body.reason_code, body.note)
        resolution = await _remove_target(db, r, admin, body.reason_code, body.note)
    now = msvc.utcnow()
    await db.execute(sql_update(MusicReport).where(
        MusicReport.target_type == r.target_type, MusicReport.target_id == r.target_id,
        MusicReport.status.in_(("open", "escalated")))
        .values(status="dismissed" if body.action == "dismiss" else "actioned",
                handled_by=admin.id, handled_at=now, resolution=resolution[:300])
        .execution_options(synchronize_session=False))
    await log_admin_action(db, admin, f"music_report.{body.action}",
                           target_type="music_report", target_id=r.id,
                           detail={"reason_code": body.reason_code})
    await db.commit()
    return {"id": r.id, "status": "dismissed" if body.action == "dismiss" else "actioned",
            "resolution": resolution}


async def _remove_target(db: AsyncSession, r: MusicReport, admin: User, reason_code: str,
                         note: str) -> str:
    label = msvc.REASON_CODES[reason_code]
    if r.target_type in ("track", "release"):
        # 审核的单位是作品(M3):举报一首歌,下架的是它所在的那个作品
        rel_id = r.target_id
        if r.target_type == "track":
            t = await db.get(MusicTrack, r.target_id)
            if t is None:
                return "对象已不存在"
            rel_id = t.release_id
        rel = await db.scalar(select(MusicRelease).where(MusicRelease.id == rel_id)
                              .with_for_update().execution_options(populate_existing=True))
        if rel is None or rel.deleted_at is not None:
            return "对象已不存在"
        if rel.status != "published":
            return f"作品当前是「{mstate.STATUS_LABELS.get(rel.status, rel.status)}」,无需下架"
        await msvc.take_down(db, rel, admin, reason_code, note)
        return f"已下架:{label}"
    if r.target_type == "comment":
        c = await db.scalar(select(MusicComment).where(MusicComment.id == r.target_id)
                            .with_for_update().execution_options(populate_existing=True))
        if c is None or c.status != "visible":
            return "对象已不存在"
        t = await db.get(MusicTrack, c.track_id)
        await talk.delete_comment(db, None, t, c, by_admin=True, removed=True)
        return f"已删除评论:{label}"
    if r.target_type == "playlist":
        p = await db.scalar(select(MusicPlaylist).where(MusicPlaylist.id == r.target_id)
                            .with_for_update().execution_options(populate_existing=True))
        if p is None or p.deleted_at is not None:
            return "对象已不存在"
        # 歌单不删(是用户自己的东西),改成私密:别人看不到,主人还留着
        p.is_public = False
        return f"已改为私密:{label}"
    a = await db.scalar(select(MusicArtist).where(MusicArtist.id == r.target_id)
                        .with_for_update().execution_options(populate_existing=True))
    if a is None:
        return "对象已不存在"
    a.status = "suspended"
    return f"已停用音乐人:{label}"


# ---------------- 音乐人 ----------------

@router.get("/artists")
async def artists(q: str = "", limit: int = 100, admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    query = select(MusicArtist)
    if q.strip():
        query = query.where(MusicArtist.name.ilike(f"%{q.strip()}%"))
    rows = list(await db.scalars(query.order_by(MusicArtist.id.desc())
                                 .limit(max(1, min(limit, 500)))))
    people = await msvc.people(db, admin.id, [a.user_id for a in rows])
    out = []
    for a in rows:
        ids = await msvc.published_track_ids(db, a.id)
        out.append({**msvc.artist_card(a, fans=await msvc.fans_of(db, a.user_id),
                                       track_count=len(ids)),
                    "status": a.status, "created_at": msvc.iso(a.created_at),
                    "user": people.get(a.user_id)})
    return {"items": out}


async def _artist(db: AsyncSession, aid: str) -> MusicArtist:
    a = await db.scalar(select(MusicArtist).where(MusicArtist.aid == aid).with_for_update()
                        .execution_options(populate_existing=True))
    if a is None:
        raise HTTPException(404, "没有这个音乐人")
    return a


@router.post("/artists/{aid}/suspend")
async def suspend(aid: str, body: NoteIn | None = None,
                  admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    """停用音乐人:主页和全部作品从公开的地方消失,本人还能登录、能申诉。"""
    a = await _artist(db, aid)
    a.status = "suspended"
    await log_admin_action(db, admin, "music.artist.suspend", target_type="music_artist",
                           target_id=a.aid, detail={"note": (body or NoteIn()).note})
    await db.commit()
    return {"aid": a.aid, "status": a.status}


@router.post("/artists/{aid}/restore")
async def restore_artist(aid: str, admin: User = Depends(require_role("admin")),
                         db: AsyncSession = Depends(get_db)):
    a = await _artist(db, aid)
    a.status = "active"
    await log_admin_action(db, admin, "music.artist.restore", target_type="music_artist",
                           target_id=a.aid)
    await db.commit()
    return {"aid": a.aid, "status": a.status}


@router.get("/stats")
async def stats(admin: User = Depends(require_role("admin")),
                db: AsyncSession = Depends(get_db)):
    """近 7 天的审核量、驳回率、下架数,以及待处理的申诉和举报(后台看板用)。"""
    from datetime import timedelta

    since = msvc.utcnow() - timedelta(days=7)
    counts = dict((await db.execute(select(MusicDecision.action, func.count()).where(
        MusicDecision.created_at >= since).group_by(MusicDecision.action))).all())
    approved, rejected = int(counts.get("approve", 0)), int(counts.get("reject", 0))
    return {
        "reviewing": int(await db.scalar(select(func.count()).select_from(MusicRelease).where(
            MusicRelease.status == "reviewing", MusicRelease.deleted_at.is_(None))) or 0),
        "approved_7d": approved, "rejected_7d": rejected,
        "removed_7d": int(counts.get("remove", 0)),
        "reject_rate_7d": round(rejected / (approved + rejected), 4)
        if approved + rejected else 0.0,
        "appeals_open": len(await msvc.open_appeals(db)),
        "reports_open": int(await db.scalar(select(func.count()).select_from(MusicReport)
                                            .where(MusicReport.status.in_(("open",
                                                                           "escalated")))) or 0),
        "artists": int(await db.scalar(select(func.count()).select_from(MusicArtist)) or 0),
        "published_releases": int(await db.scalar(
            select(func.count()).select_from(MusicRelease).where(
                MusicRelease.status == "published", MusicRelease.deleted_at.is_(None))) or 0),
    }
