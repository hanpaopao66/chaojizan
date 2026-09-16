"""论坛的审核与治理 `/admin/forum`(DEV-PROMPTS-41 §8.3 后台部分,#380)。

每个写操作同时进两本账:forum_decisions(给作者看的结论、原因代码和说明)和
admin_action_logs(平台内部复盘)。note_internal 只在这里看得到。

接口层面的硬规矩(e2e_forum_moderation 里每条都有先红后绿的用例):
- 下架、隐藏话题必须带 §5.11 的原因代码;选 X999 必须写说明;
- **申诉强制换人**:处理人等于原结论人时拒绝(403)—— 自己复核自己等于没有申诉;
- 热门话题隐藏也要写原因、留痕(§2.2「不偷偷压话题」),而且**只是不上热门榜**:
  话题页照样能打开,帖子照样在。
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import ForumDecision, ForumPost, ForumReport, ForumTag, User
from ..security import require_role
from ..services import forum as fsvc
from ..services import video as vsvc
from ..services.admin_audit import log_admin_action

router = APIRouter(prefix="/admin/forum", tags=["社区治理"])


async def _post(db: AsyncSession, pid: str) -> ForumPost:
    return await fsvc.get_post(db, pid, lock=True)


async def _brief(db: AsyncSession, admin: User, posts: list[ForumPost]) -> dict[int, dict]:
    """后台列表里的帖子简卡:正文、作者、状态、计数、链接。"""
    people = await vsvc.people(db, admin.id, [p.author_id for p in posts])
    return {p.id: {
        "pid": p.pid, "text": p.text, "author": people.get(p.author_id),
        "status": p.status, "removed_code": p.removed_code,
        "removed_label": fsvc.reason_codes().get(p.removed_code, ""),
        "media": [m.get("url") for m in (p.media or [])],
        "is_reply": p.reply_to_id is not None,
        "counts": {"replies": p.replies, "reposts": p.reposts, "quotes": p.quotes,
                   "likes": p.likes, "views": p.views},
        "created_at": fsvc.iso(p.created_at),
        "link": f"{fsvc.PUBLIC_BASE}/forum/p/{p.pid}",
    } for p in posts}


@router.get("/reason-codes")
async def reason_codes(admin: User = Depends(require_role("admin"))):
    """论坛能用的原因代码(§5.11):共用的 C1xx + X999,加 F401–F403。"""
    return {"items": [{"code": k, "label": v} for k, v in fsvc.reason_codes().items()]}


# ---------------- 举报 ----------------

@router.get("/reports")
async def reports(status: Literal["open", "handled", "all"] = "open", limit: int = 100,
                  admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    """帖子举报。举报人不出现在这里(对被举报的一方永远匿名)。"""
    q = select(ForumReport)
    if status == "open":
        q = q.where(ForumReport.status == "open")
    elif status == "handled":
        q = q.where(ForumReport.status.in_(("actioned", "dismissed")))
    rows = list(await db.scalars(q.order_by(ForumReport.id.desc())
                                 .limit(max(1, min(limit, 500)))))
    posts = list(await db.scalars(select(ForumPost).where(
        ForumPost.id.in_([r.post_id for r in rows])))) if rows else []
    briefs = await _brief(db, admin, posts)
    return {"items": [{
        "id": r.id, "reason_code": r.reason_code,
        "reason_label": fsvc.reason_codes().get(r.reason_code, ""),
        "note": r.note, "status": r.status, "resolution": r.resolution,
        "created_at": fsvc.iso(r.created_at), "handled_at": fsvc.iso(r.handled_at),
        "post": briefs.get(r.post_id),
    } for r in rows]}


class HandleIn(BaseModel):
    #: remove 下架 / dismiss 不成立
    action: Literal["remove", "dismiss"]
    reason_code: str = ""
    note: str = Field(default="", max_length=500)
    note_internal: str = Field(default="", max_length=500)


@router.post("/reports/{report_id}/handle")
async def handle_report(report_id: int, body: HandleIn,
                        admin: User = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    """处理举报。同一条帖子上所有没处理的举报一起结案。处置要带原因代码。"""
    r = await db.get(ForumReport, report_id)
    if r is None:
        raise HTTPException(404, "举报不存在")
    if r.status != "open":
        raise HTTPException(409, "这条举报已经处理过了")
    resolution = "举报不成立"
    if body.action == "remove":
        fsvc.reason_ok(body.reason_code, body.note)
        p = await db.scalar(select(ForumPost).where(ForumPost.id == r.post_id)
                            .with_for_update().execution_options(populate_existing=True))
        if p is None:
            raise HTTPException(409, "帖子已经不在了")
        await fsvc.take_down(db, p, admin, body.reason_code, body.note, body.note_internal)
        resolution = f"已下架:{fsvc.reason_codes()[body.reason_code]}"
    now = datetime.now(timezone.utc)
    for x in await db.scalars(select(ForumReport).where(ForumReport.post_id == r.post_id,
                                                        ForumReport.status == "open")):
        x.status = "dismissed" if body.action == "dismiss" else "actioned"
        x.handled_by, x.handled_at, x.resolution = admin.id, now, resolution[:300]
    await log_admin_action(db, admin, f"forum_report.{body.action}",
                           target_type="forum_report", target_id=r.id,
                           detail={"reason_code": body.reason_code})
    await db.commit()
    return {"id": r.id, "status": "dismissed" if body.action == "dismiss" else "actioned",
            "resolution": resolution}


# ---------------- 帖子管理 ----------------

@router.get("/posts")
async def list_posts(q: str | None = None, author: int | None = None,
                     status: Literal["visible", "removed", "deleted", "all"] = "all",
                     limit: int = 100, admin: User = Depends(require_role("admin")),
                     db: AsyncSession = Depends(get_db)):
    """按正文关键词 / 作者找帖子(巡查用)。下架了的、作者删了的也能找到。"""
    stmt = select(ForumPost)
    if q and q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(ForumPost.text.ilike(f"%{term}%", escape="\\"))
    if author:
        stmt = stmt.where(ForumPost.author_id == author)
    if status != "all":
        stmt = stmt.where(ForumPost.status == status)
    rows = list(await db.scalars(stmt.order_by(ForumPost.id.desc())
                                 .limit(max(1, min(limit, 500)))))
    briefs = await _brief(db, admin, rows)
    open_counts = dict((await db.execute(
        select(ForumReport.post_id, func.count()).where(
            ForumReport.post_id.in_([p.id for p in rows]), ForumReport.status == "open")
        .group_by(ForumReport.post_id))).all()) if rows else {}
    return {"items": [{**briefs[p.id], "reports_open": int(open_counts.get(p.id, 0))}
                      for p in rows]}


class RemoveIn(BaseModel):
    reason_code: str
    note: str = Field(default="", max_length=500)
    note_internal: str = Field(default="", max_length=500)


@router.post("/posts/{pid}/remove")
async def remove_post(pid: str, body: RemoveIn, admin: User = Depends(require_role("admin")),
                      db: AsyncSession = Depends(get_db)):
    """下架。原因代码必填,X999 要写说明;作者收到系统通知,可以申诉一次。"""
    p = await _post(db, pid)
    d = await fsvc.take_down(db, p, admin, body.reason_code, body.note, body.note_internal)
    await log_admin_action(db, admin, "forum_post.remove", target_type="forum_post",
                           target_id=p.pid, detail={"reason_code": body.reason_code})
    await db.commit()
    return {"decision_id": d.id, "status": p.status}


class RestoreIn(BaseModel):
    note: str = Field(default="", max_length=500)


@router.post("/posts/{pid}/restore")
async def restore_post(pid: str, body: RestoreIn | None = None,
                       admin: User = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    p = await _post(db, pid)
    d = await fsvc.restore(db, p, admin, (body.note if body else "") or "")
    await log_admin_action(db, admin, "forum_post.restore", target_type="forum_post",
                           target_id=p.pid)
    await db.commit()
    return {"decision_id": d.id, "status": p.status}


# ---------------- 申诉 ----------------

@router.get("/appeals")
async def appeals(status: Literal["open", "resolved", "all"] = "open",
                  admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    """没处理的论坛申诉。`you_decided_original` 为真的,你不能处理(换人复核)。"""
    q = select(ForumDecision).where(ForumDecision.appeal_result != "")
    if status == "open":
        q = q.where(ForumDecision.appeal_result == "open")
    elif status == "resolved":
        q = q.where(ForumDecision.appeal_result.in_(("upheld", "overturned")))
    rows = list(await db.scalars(q.order_by(ForumDecision.id.desc()).limit(200)))
    posts = list(await db.scalars(select(ForumPost).where(
        ForumPost.id.in_([d.post_id for d in rows if d.post_id])))) if rows else []
    briefs = await _brief(db, admin, posts)
    return {"items": [{
        "decision_id": d.id,
        "appeal": {"text": d.appeal_text, "at": fsvc.iso(d.appeal_at),
                   "result": d.appeal_result, "note": d.appeal_note},
        "original": {"action": d.action, "reason_code": d.reason_code,
                     "reason_label": fsvc.reason_codes().get(d.reason_code, ""),
                     "note": d.note, "note_internal": d.note_internal,
                     "admin_id": d.admin_id, "created_at": fsvc.iso(d.created_at)},
        "post": briefs.get(d.post_id),
        "you_decided_original": d.admin_id == admin.id,
    } for d in rows]}


class ResolveIn(BaseModel):
    result: Literal["upheld", "overturned"]
    note: str = Field(default="", max_length=500)


@router.post("/appeals/{decision_id}/resolve")
async def resolve_appeal(decision_id: int, body: ResolveIn,
                         admin: User = Depends(require_role("admin")),
                         db: AsyncSession = Depends(get_db)):
    """处理申诉。**原审核人不能复核自己的决定**(403)。改判就把帖子恢复。"""
    d = await db.get(ForumDecision, decision_id)
    if d is None:
        raise HTTPException(404, "申诉不存在")
    await fsvc.resolve_appeal(db, d, admin, overturn=body.result == "overturned",
                              note=body.note)
    await log_admin_action(db, admin, f"forum_appeal.{body.result}",
                           target_type="forum_decision", target_id=d.id)
    await db.commit()
    p = await db.get(ForumPost, d.post_id) if d.post_id else None
    return {"decision_id": d.id, "result": d.appeal_result,
            "status": p.status if p is not None else None}


# ---------------- 热门话题 ----------------

@router.get("/tags")
async def list_tags(hidden: bool | None = None, q: str | None = None, limit: int = 100,
                    admin: User = Depends(require_role("admin")),
                    db: AsyncSession = Depends(get_db)):
    """话题表(按最近用过排)。`hidden=true` 只看已隐藏的。"""
    stmt = select(ForumTag)
    if hidden is not None:
        stmt = stmt.where(ForumTag.hidden.is_(hidden))
    if q and q.strip():
        term = q.strip().lstrip("#").lower()
        stmt = stmt.where(ForumTag.tag.ilike(f"%{term}%", escape="\\"))
    rows = list(await db.scalars(stmt.order_by(ForumTag.last_used_at.desc())
                                 .limit(max(1, min(limit, 500)))))
    return {"items": [{"tag": t.tag, "display": t.display or t.tag, "posts": t.posts,
                       "hidden": t.hidden, "hidden_code": t.hidden_code,
                       "hidden_label": fsvc.reason_codes().get(t.hidden_code, ""),
                       "last_used_at": fsvc.iso(t.last_used_at)} for t in rows]}


class TagHideIn(BaseModel):
    reason_code: str
    note: str = Field(default="", max_length=500)


async def _tag(db: AsyncSession, tag: str) -> ForumTag:
    from ..services.forum_feed import normalize_tag

    row = await db.scalar(select(ForumTag).where(ForumTag.tag == normalize_tag(tag))
                          .with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "没有这个话题")
    return row


@router.post("/tags/{tag}/hide")
async def hide_tag(tag: str, body: TagHideIn, admin: User = Depends(require_role("admin")),
                   db: AsyncSession = Depends(get_db)):
    """把话题从热门榜上撤下来。**要写原因、留痕**(§2.2);话题页照样能打开,帖子照样在。"""
    t = await _tag(db, tag)
    d = await fsvc.hide_tag(db, t, admin, hidden=True, reason_code=body.reason_code,
                            note=body.note)
    await log_admin_action(db, admin, "forum_tag.hide", target_type="forum_tag",
                           target_id=t.tag, detail={"reason_code": body.reason_code})
    await db.commit()
    return {"decision_id": d.id, "tag": t.tag, "hidden": True}


@router.post("/tags/{tag}/unhide")
async def unhide_tag(tag: str, admin: User = Depends(require_role("admin")),
                     db: AsyncSession = Depends(get_db)):
    t = await _tag(db, tag)
    d = await fsvc.hide_tag(db, t, admin, hidden=False, reason_code="", note="")
    await log_admin_action(db, admin, "forum_tag.unhide", target_type="forum_tag",
                           target_id=t.tag)
    await db.commit()
    return {"decision_id": d.id, "tag": t.tag, "hidden": False}


# ---------------- 数据 ----------------

@router.get("/stats")
async def stats(admin: User = Depends(require_role("admin")),
                db: AsyncSession = Depends(get_db)):
    """近 7 天的发帖量、下架数,以及待处理的举报和申诉(后台看板用)。"""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    posts_7d = int(await db.scalar(select(func.count()).select_from(ForumPost).where(
        ForumPost.created_at >= since)) or 0)
    removed_7d = int(await db.scalar(select(func.count()).select_from(ForumDecision).where(
        ForumDecision.action == "remove", ForumDecision.created_at >= since)) or 0)
    return {
        "posts_7d": posts_7d,
        "removed_7d": removed_7d,
        "visible_total": int(await db.scalar(select(func.count()).select_from(ForumPost)
                                             .where(ForumPost.status == "visible")) or 0),
        "reports_open": int(await db.scalar(select(func.count()).select_from(ForumReport)
                                            .where(ForumReport.status == "open")) or 0),
        "appeals_open": int(await db.scalar(select(func.count()).select_from(ForumDecision)
                                            .where(ForumDecision.appeal_result == "open")) or 0),
        "tags_hidden": int(await db.scalar(select(func.count()).select_from(ForumTag)
                                           .where(ForumTag.hidden.is_(True))) or 0),
        "tags_total": int(await db.scalar(select(func.count()).select_from(ForumTag)) or 0),
    }
