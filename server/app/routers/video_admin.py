"""视频的审核与治理 `/admin/social/…`(DEV-PROMPTS-40 #368 视频部分)。

每个写操作同时进两本账:video_decisions(给 UP 主看的结论、原因代码和说明)和
admin_action_logs(平台内部复盘)。note_internal 只在这里看得到。

接口层面的硬规矩(e2e_video_upload 里每条都有先红后绿的用例):
- 驳回、下架必须带 §5.11 的原因代码;选 X999 必须写说明(S6);
- 状态迁移走 services/video_state.py,非法迁移 409;
- **申诉强制换人**:处理人等于原结论人时拒绝(403)—— 自己复核自己等于没有申诉;
- 举报:7 天内 3 个不同的人举报同一个对象的排在最前(escalated)。
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Danmaku, User, Video, VideoComment, VideoDecision, VideoReport
from ..security import require_role
from ..services import video as vsvc
from ..services import video_state as vstate
from ..services import video_talk as talk
from ..services.admin_audit import log_admin_action

router = APIRouter(prefix="/admin/social", tags=["社区治理"])


async def _video(db: AsyncSession, vid: str) -> Video:
    v = await vsvc.get_video(db, vid, lock=True)
    return v


@router.get("/reason-codes")
async def reason_codes(admin: User = Depends(require_role("admin"))):
    """原因代码表(§5.11,审核、处罚、举报共用)。"""
    return {"items": [{"code": k, "label": v} for k, v in vsvc.REASON_CODES.items()]}


@router.get("/videos/review")
async def review_queue(limit: int = 50, admin: User = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    """审核队列:从没发布过的新稿件(reviewing)+ 已发布稿件的改动(pending reviewing),按提交时间先后。"""
    rows = list(await db.scalars(select(Video).where(
        Video.deleted_at.is_(None),
        or_(Video.status == "reviewing",
            Video.status.in_(vstate.LIVE_STATUSES)
            & (Video.pending_changes["state"].astext == "reviewing")))
        .order_by(Video.submitted_at.asc().nulls_last(), Video.id).limit(max(1, min(limit, 200)))))
    ups = await vsvc.people(db, admin.id, [v.uploader_id for v in rows])
    return {"items": [{**vsvc.creator_card(v), "review": vsvc.review_state(v),
                       "uploader": ups.get(v.uploader_id)} for v in rows],
            "count": len(rows)}


@router.get("/videos/{vid}")
async def video_for_admin(vid: str, admin: User = Depends(require_role("admin")),
                          db: AsyncSession = Depends(get_db)):
    """审核员看的完整稿件:线上版本、待审改动、每 P 的播放地址(按审核员签名)、封面、审核记录、举报数。"""
    v = await vsvc.get_video(db, vid)
    out = await vsvc.creator_detail(db, v, admin)
    out["review"] = vsvc.review_state(v)
    out["uploader"] = (await vsvc.people(db, admin.id, [v.uploader_id])).get(v.uploader_id)
    out["reports_open"] = int(await db.scalar(select(func.count()).select_from(VideoReport).where(
        VideoReport.video_id == v.id, VideoReport.status.in_(("open", "escalated")))) or 0)
    return out


class DecideIn(BaseModel):
    approve: bool
    reason_code: str = ""
    #: 给 UP 主看的说明(驳回时写清楚哪里不行)
    note: str = Field(default="", max_length=500)
    #: 只在后台看得到
    note_internal: str = Field(default="", max_length=500)


@router.post("/videos/{vid}/decide")
async def decide(vid: str, body: DecideIn, admin: User = Depends(require_role("admin")),
                 db: AsyncSession = Depends(get_db)):
    v = await _video(db, vid)
    d = await vsvc.decide(db, v, admin, approve=body.approve, reason_code=body.reason_code,
                          note=body.note, note_internal=body.note_internal)
    await log_admin_action(db, admin, f"video.{d.action}", target_type="video", target_id=v.vid,
                           detail={"reason_code": body.reason_code})
    await db.commit()
    return {"decision_id": d.id, "action": d.action, "status": v.status,
            "pending": vstate.pending_state(v)}


class RemoveIn(BaseModel):
    reason_code: str
    note: str = Field(default="", max_length=500)
    note_internal: str = Field(default="", max_length=500)


@router.post("/videos/{vid}/remove")
async def remove(vid: str, body: RemoveIn, admin: User = Depends(require_role("admin")),
                 db: AsyncSession = Depends(get_db)):
    """下架(处罚)。原因代码必填,X999 要写说明;UP 主收到系统通知,可以申诉。"""
    v = await _video(db, vid)
    d = await vsvc.take_down(db, v, admin, body.reason_code, body.note, body.note_internal)
    await log_admin_action(db, admin, "video.remove", target_type="video", target_id=v.vid,
                           detail={"reason_code": body.reason_code})
    await db.commit()
    return {"decision_id": d.id, "status": v.status}


@router.get("/appeals")
async def appeals(admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    """没处理的视频申诉。`you_decided_original` 为真的,你不能处理(换人复核,S6)。"""
    items = []
    for a in await vsvc.open_appeals(db):
        orig = await db.get(VideoDecision, a.appeal_of)
        v = await db.get(Video, a.video_id)
        if orig is None or v is None:
            continue
        items.append({
            "appeal": {"id": a.id, "text": a.note, "created_at": vsvc.iso(a.created_at)},
            "original": {"id": orig.id, "action": orig.action,
                         "action_label": vsvc.DECISION_LABELS.get(orig.action, ""),
                         "reason_code": orig.reason_code,
                         "reason_label": vsvc.REASON_CODES.get(orig.reason_code, ""),
                         "note": orig.note, "note_internal": orig.note_internal,
                         "actor_id": orig.actor_id, "created_at": vsvc.iso(orig.created_at)},
            "video": {**vsvc.video_brief(v), "status": v.status},
            "you_decided_original": orig.actor_id == admin.id,
        })
    return {"items": items}


class ResolveIn(BaseModel):
    overturn: bool
    note: str = Field(default="", max_length=500)
    note_internal: str = Field(default="", max_length=500)


@router.post("/appeals/{appeal_id}/resolve")
async def resolve(appeal_id: int, body: ResolveIn, admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    ap = await db.get(VideoDecision, appeal_id)
    if ap is None or ap.action != "appeal":
        raise HTTPException(404, "申诉不存在")
    d = await vsvc.resolve_appeal(db, ap, admin, overturn=body.overturn, note=body.note,
                                  note_internal=body.note_internal)
    await log_admin_action(db, admin, "video.appeal." + ("overturn" if body.overturn else "uphold"),
                           target_type="video_decision", target_id=ap.id)
    await db.commit()
    v = await db.get(Video, ap.video_id)
    return {"appeal_id": ap.id, "decision_id": d.id, "overturned": body.overturn,
            "status": v.status if v else None}


async def _target_snapshot(db: AsyncSession, r: VideoReport) -> dict:
    if r.target_type == "video":
        v = await db.get(Video, r.target_id)
        return {"video": {**vsvc.video_brief(v), "status": v.status}} if v else {}
    if r.target_type == "comment":
        c = await db.get(VideoComment, r.target_id)
        v = await db.get(Video, r.video_id) if r.video_id else None
        return {"comment": {"id": c.id, "text": c.text, "user_id": c.user_id,
                            "deleted": c.deleted_at is not None} if c else None,
                "video": vsvc.video_brief(v) if v else None}
    d = await db.get(Danmaku, r.target_id)
    v = await db.get(Video, r.video_id) if r.video_id else None
    return {"danmaku": {"id": d.id, "text": d.text, "user_id": d.user_id, "time_ms": d.time_ms,
                        "deleted": d.deleted_at is not None} if d else None,
            "video": vsvc.video_brief(v) if v else None}


@router.get("/video-reports")
async def reports(status: Literal["open", "all", "handled"] = "open", limit: int = 100,
                  admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    """视频 / 评论 / 弹幕的举报。7 天内 3 人举报的(escalated)排最前。举报人不出现在这里。"""
    q = select(VideoReport)
    if status == "open":
        q = q.where(VideoReport.status.in_(("open", "escalated")))
    elif status == "handled":
        q = q.where(VideoReport.status.in_(("actioned", "dismissed")))
    rows = list(await db.scalars(q.order_by(
        (VideoReport.status == "escalated").desc(), VideoReport.id).limit(max(1, min(limit, 500)))))
    items = []
    for r in rows:
        items.append({"id": r.id, "target_type": r.target_type, "target_id": r.target_id,
                      "reason_code": r.reason_code,
                      "reason_label": vsvc.REASON_CODES.get(r.reason_code, ""),
                      "note": r.note, "status": r.status, "resolution": r.resolution,
                      "created_at": vsvc.iso(r.created_at), **await _target_snapshot(db, r)})
    return {"items": items}


class HandleIn(BaseModel):
    #: dismiss 不成立 / delete 删除评论或弹幕 / remove 下架视频
    action: Literal["dismiss", "delete", "remove"]
    reason_code: str = ""
    note: str = Field(default="", max_length=500)


@router.post("/video-reports/{report_id}/handle")
async def handle_report(report_id: int, body: HandleIn,
                        admin: User = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    """处理举报。同一个对象上所有没处理的举报一起结案。处置要带原因代码(S6)。"""
    r = await db.get(VideoReport, report_id)
    if r is None:
        raise HTTPException(404, "举报不存在")
    if r.status not in ("open", "escalated"):
        raise HTTPException(409, "这条举报已经处理过了")
    resolution = "举报不成立"
    if body.action != "dismiss":
        vsvc.reason_ok(body.reason_code, body.note)
        if body.action == "remove":
            if r.target_type != "video":
                raise HTTPException(422, "下架只对视频")
            v = await db.scalar(select(Video).where(Video.id == r.target_id).with_for_update()
                                .execution_options(populate_existing=True))
            if v is None or v.deleted_at is not None:
                raise HTTPException(409, "视频已经删除了")
            await vsvc.take_down(db, v, admin, body.reason_code, body.note)
            resolution = f"已下架:{vsvc.REASON_CODES[body.reason_code]}"
        else:
            if r.target_type == "comment":
                c = await db.scalar(select(VideoComment).where(VideoComment.id == r.target_id)
                                    .with_for_update().execution_options(populate_existing=True))
                if c is not None and c.deleted_at is None:
                    v = await db.get(Video, c.video_id)
                    await talk.delete_comment(db, None, v, c, by_admin=True)
            elif r.target_type == "danmaku":
                d = await db.get(Danmaku, r.target_id)
                if d is not None and d.deleted_at is None:
                    v = await db.get(Video, d.video_id)
                    await talk.delete_danmaku(db, None, d, v, by_admin=True)
            else:
                raise HTTPException(422, "视频请用「下架」")
            resolution = f"已删除:{vsvc.REASON_CODES[body.reason_code]}"
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for x in await db.scalars(select(VideoReport).where(
            VideoReport.target_type == r.target_type, VideoReport.target_id == r.target_id,
            VideoReport.status.in_(("open", "escalated")))):
        x.status = "dismissed" if body.action == "dismiss" else "actioned"
        x.handled_by, x.handled_at, x.resolution = admin.id, now, resolution[:300]
    await log_admin_action(db, admin, f"video_report.{body.action}", target_type="video_report",
                           target_id=r.id, detail={"reason_code": body.reason_code})
    await db.commit()
    return {"id": r.id, "status": "dismissed" if body.action == "dismiss" else "actioned",
            "resolution": resolution}


@router.get("/videos-stats")
async def stats(admin: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """近 7 天的审核量、驳回率、下架数,以及待处理的申诉和举报(后台看板用)。"""
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=7)
    counts = dict((await db.execute(select(VideoDecision.action, func.count()).where(
        VideoDecision.created_at >= since).group_by(VideoDecision.action))).all())
    approved = int(counts.get("approve", 0)) + int(counts.get("approve_changes", 0))
    rejected = int(counts.get("reject", 0)) + int(counts.get("reject_changes", 0))
    reviewing = int(await db.scalar(select(func.count()).select_from(Video).where(
        Video.status == "reviewing", Video.deleted_at.is_(None))) or 0)
    return {"reviewing": reviewing, "approved_7d": approved, "rejected_7d": rejected,
            "removed_7d": int(counts.get("remove", 0)),
            "reject_rate_7d": round(rejected / (approved + rejected), 4)
            if approved + rejected else 0.0,
            "appeals_open": len(await vsvc.open_appeals(db)),
            "reports_open": int(await db.scalar(select(func.count()).select_from(VideoReport)
                                                .where(VideoReport.status.in_(("open",
                                                                               "escalated"))))
                                or 0)}
