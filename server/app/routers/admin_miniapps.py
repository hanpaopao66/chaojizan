"""小程序审核与治理 `/admin/mini-apps`(#332)。

每个写操作同时进两本账:mini_app_decisions(给开发者看、透明中心投影)和
admin_action_logs(平台内部复盘)。note_internal 只在这里看得到。

几条接口层面的硬规矩(e2e_miniapp_review 里每条都有一个先红后绿的用例):
- 驳回、处罚必须带 §5.9 的原因代码和给开发者看的说明(schemas 层就拒);
- 状态迁移走 services/miniapp_state.py,非法迁移 409;
- **申诉强制换人**:处理人等于原结论人时拒绝(403)—— 自己复核自己等于没有申诉;
- 申诉成立 = 撤销原结论。这是唯一允许从「驳回」「移除」这类终态回来的路径,
  不走正常的状态迁移表,改判的每一步都写进记录。
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (Developer, DeveloperInvite, MiniApp, MiniAppCapability, MiniAppCuration,
                      MiniAppDecision, MiniAppReport, MiniAppVersion, PlatformFlag, User)
from ..schemas_miniapp import (AppealResolveIn, CapabilityDecisionIn, CurationIn, InviteIn,
                               LaunchIn, PunishIn, ReportHandleIn, VerifyDecisionIn,
                               VersionDecisionIn)
from ..security import require_role
from ..services import miniapp_publish as pub
from ..services.admin_audit import log_admin_action
from ..services.developer_signup import FLAG as SIGNUP_FLAG
from ..services.developer_signup import MODES as SIGNUP_MODES
from ..services.developer_signup import invite_key, signup_mode
from ..services.crypto import decrypt, pseudonym
from ..services.miniapp_platform import (APPID_PATTERN, REASON_CODES, REPORT_REVIEW_THRESHOLD,
                                         app_by_appid, app_card, developer_card, now,
                                         record_decision, version_servable)
from ..services.miniapp_state import LABELS, assert_transition
from ..state_machine import TransitionError
from .dev_miniapps import ACTION_LABELS, sim_payload, version_dev

router = APIRouter(prefix="/admin/mini-apps", tags=["小程序治理"])
AppId = Path(pattern=APPID_PATTERN)


def _transition(machine: str, cur: str, target: str) -> None:
    try:
        assert_transition(machine, cur, target)
    except TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc


def _reason_ok(code: str) -> None:
    if code not in REASON_CODES:
        raise HTTPException(422, "原因代码不存在(见 §5.9)")


def decision_admin(d: MiniAppDecision, *, app_name: str = "", actor_name: str = "") -> dict:
    return {
        "id": d.id, "target_type": d.target_type, "target_id": d.target_id,
        "app_id": d.app_id, "app_name": app_name, "developer_id": d.developer_id,
        "action": d.action, "action_label": ACTION_LABELS.get(d.action, d.action),
        "reason_code": d.reason_code, "reason_label": REASON_CODES.get(d.reason_code, ""),
        "note_public": d.note_public, "note_internal": d.note_internal,
        "actor_id": d.actor_id, "actor_name": actor_name, "appeal_of": d.appeal_of,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


async def _decisions(db: AsyncSession, rows: list[MiniAppDecision]) -> list[dict]:
    app_ids = {d.app_id for d in rows if d.app_id}
    actor_ids = {d.actor_id for d in rows if d.actor_id}
    names = dict((await db.execute(select(MiniApp.id, MiniApp.name).where(
        MiniApp.id.in_(app_ids)))).all()) if app_ids else {}
    actors = dict((await db.execute(select(User.id, User.name).where(
        User.id.in_(actor_ids)))).all()) if actor_ids else {}
    return [decision_admin(d, app_name=names.get(d.app_id, ""),
                           actor_name=actors.get(d.actor_id, "") or "") for d in rows]


# =====================================================================
# 总览、应用
# =====================================================================

@router.get("/overview")
async def overview(admin: User = Depends(require_role("admin")),
                   db: AsyncSession = Depends(get_db)):
    async def count(model, *conds):
        return await db.scalar(select(func.count()).select_from(model).where(*conds))

    open_appeals = await _open_appeals(db)
    return {
        "developers": dict((await db.execute(select(Developer.status, func.count()).group_by(
            Developer.status))).all()),
        "apps": dict((await db.execute(select(MiniApp.status, func.count()).group_by(
            MiniApp.status))).all()),
        "reviewing": await count(MiniAppVersion, MiniAppVersion.status == "reviewing"),
        "developer_pending": await count(Developer, Developer.status == "pending"),
        "capabilities_pending": await count(MiniAppCapability,
                                            MiniAppCapability.status == "requested"),
        "reports_open": await count(MiniAppReport, MiniAppReport.status == "open"),
        "appeals_open": len(open_appeals),
        "signup_mode": await signup_mode(db),
    }


@router.get("/apps")
async def list_apps(status: str | None = Query(default=None, max_length=10),
                    q: str = Query(default="", max_length=40),
                    admin: User = Depends(require_role("admin")),
                    db: AsyncSession = Depends(get_db)):
    stmt = select(MiniApp).order_by(MiniApp.id.desc())
    if status:
        stmt = stmt.where(MiniApp.status == status)
    if q.strip():
        stmt = stmt.where(MiniApp.name.contains(q.strip()) | (MiniApp.appid == q.strip()))
    apps = list((await db.execute(stmt.limit(300))).scalars())
    devs = {d.id: d for d in (await db.execute(select(Developer).where(
        Developer.id.in_({a.developer_id for a in apps if a.developer_id})))).scalars()} \
        if apps else {}
    return {"items": [{**app_card(a, devs.get(a.developer_id)), "status": a.status,
                       "status_label": LABELS.get(a.status, a.status)} for a in apps]}


@router.get("/apps/{appid}")
async def app_detail(appid: str = AppId, admin: User = Depends(require_role("admin")),
                     db: AsyncSession = Depends(get_db)):
    app = await app_by_appid(db, appid)
    dev = await db.get(Developer, app.developer_id) if app.developer_id else None
    versions = list((await db.execute(select(MiniAppVersion).where(
        MiniAppVersion.app_id == app.id).order_by(MiniAppVersion.build.desc()))).scalars())
    decisions = list((await db.execute(select(MiniAppDecision).where(
        MiniAppDecision.app_id == app.id).order_by(MiniAppDecision.id.desc()).limit(200))).scalars())
    reports = await db.scalar(select(func.count()).select_from(MiniAppReport).where(
        MiniAppReport.app_id == app.id, MiniAppReport.status == "open"))
    return {**app_card(app, dev), "status": app.status,
            "status_label": LABELS.get(app.status, app.status),
            "developer_id": app.developer_id, "description": app.description,
            "privacy_policy": app.privacy_policy, "data_declaration": app.data_declaration,
            "request_domains": app.request_domains, "listing_draft": app.listing_draft,
            "versions": [version_dev(v, app) for v in versions],
            "decisions": await _decisions(db, decisions), "open_reports": reports}


# =====================================================================
# 开发者认证
# =====================================================================

def developer_admin(d: Developer) -> dict:
    real = decrypt(d.real_name_enc) if d.real_name_enc else ""
    return {
        "id": d.id, "user_id": d.user_id, "kind": d.kind, "display_name": d.display_name,
        "status": d.status, "status_label": LABELS.get(d.status, d.status),
        "public": developer_card(d),
        # 审核也只看到遮住的真名和证号尾号:企业认证不需要个人证件,个人认证是机器核的
        "real_name_masked": (real[0] + "*" * (len(real) - 1)) if real else "",
        "id_no_tail": d.id_no_tail, "company_name": d.company_name, "uscc": d.uscc,
        "license_key": d.license_key, "contact_name": d.contact_name,
        "contact_email": d.contact_email, "reject_reason": d.reject_reason,
        "is_official": d.is_official,
        "submitted_at": d.submitted_at.isoformat() if d.submitted_at else None,
        "verified_at": d.verified_at.isoformat() if d.verified_at else None,
    }


@router.get("/developers")
async def list_developers(status: str | None = Query(default=None, max_length=16),
                          admin: User = Depends(require_role("admin")),
                          db: AsyncSession = Depends(get_db)):
    stmt = select(Developer).order_by(Developer.submitted_at.asc().nullslast(), Developer.id)
    if status:
        stmt = stmt.where(Developer.status == status)
    return {"items": [developer_admin(d) for d in (await db.execute(stmt.limit(300))).scalars()]}


@router.post("/developers/{developer_id}/verify")
async def verify_developer(developer_id: int, body: VerifyDecisionIn,
                           admin: User = Depends(require_role("admin")),
                           db: AsyncSession = Depends(get_db)):
    d = await db.get(Developer, developer_id, with_for_update=True)
    if d is None:
        raise HTTPException(404, "开发者不存在")
    target = "verified" if body.approve else "rejected"
    if not body.approve and len(body.reason.strip()) < 4:
        raise HTTPException(422, "驳回要写明原因(开发者看得到)")
    _transition("developer", d.status, target)
    d.status = target
    d.reviewed_by = admin.id
    if body.approve:
        d.verified_at = now()
        d.reject_reason = ""
    else:
        d.reject_reason = body.reason.strip()
    await record_decision(db, target_type="developer", target_id=d.id,
                          action="verify" if body.approve else "developer_reject",
                          developer_id=d.id, note_public=body.reason.strip(), actor=admin,
                          reason_code="" if body.approve else "R701")
    await log_admin_action(db, admin, "miniapp.developer." + target, target_type="developer",
                           target_id=d.id)
    await db.commit()
    return developer_admin(d)


@router.post("/developers/{developer_id}/suspend")
async def suspend_developer(developer_id: int, body: PunishIn,
                            admin: User = Depends(require_role("admin")),
                            db: AsyncSession = Depends(get_db)):
    _reason_ok(body.reason_code)
    d = await db.get(Developer, developer_id, with_for_update=True)
    if d is None:
        raise HTTPException(404, "开发者不存在")
    _transition("developer", d.status, "suspended")
    d.status = "suspended"
    await record_decision(db, target_type="developer", target_id=d.id, action="developer_suspend",
                          developer_id=d.id, reason_code=body.reason_code,
                          note_public=body.note_public, note_internal=body.note_internal,
                          actor=admin)
    await log_admin_action(db, admin, "miniapp.developer.suspend", target_type="developer",
                           target_id=d.id, detail={"reason_code": body.reason_code})
    await db.commit()
    return developer_admin(d)


@router.post("/developers/{developer_id}/restore")
async def restore_developer(developer_id: int, body: dict,
                            admin: User = Depends(require_role("admin")),
                            db: AsyncSession = Depends(get_db)):
    d = await db.get(Developer, developer_id, with_for_update=True)
    if d is None:
        raise HTTPException(404, "开发者不存在")
    _transition("developer", d.status, "verified")
    d.status = "verified"
    await record_decision(db, target_type="developer", target_id=d.id, action="developer_restore",
                          developer_id=d.id, note_public=str(body.get("note", ""))[:500],
                          actor=admin)
    await log_admin_action(db, admin, "miniapp.developer.restore", target_type="developer",
                           target_id=d.id)
    await db.commit()
    return developer_admin(d)


# =====================================================================
# 版本审核
# =====================================================================

@router.get("/reviews")
async def review_queue(admin: User = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    """审核队列:先交先审(按提交时间)。"""
    rows = (await db.execute(
        select(MiniAppVersion, MiniApp).join(MiniApp, MiniApp.id == MiniAppVersion.app_id)
        .where(MiniAppVersion.status == "reviewing").order_by(MiniAppVersion.submitted_at))).all()
    out = []
    for v, a in rows:
        dev = await db.get(Developer, a.developer_id) if a.developer_id else None
        out.append({"version": version_dev(v, a), "app": {**app_card(a, dev), "status": a.status},
                    "waiting_hours": round((now() - v.submitted_at).total_seconds() / 3600, 1)
                    if v.submitted_at else None})
    return {"items": out, "checklist": pub.CHECKLIST, "checklist_version": pub.CHECKLIST_VERSION}


async def _version(db: AsyncSession, version_id: int) -> tuple[MiniAppVersion, MiniApp]:
    v = await db.get(MiniAppVersion, version_id, with_for_update=True)
    if v is None:
        raise HTTPException(404, "版本不存在")
    app = await db.get(MiniApp, v.app_id, with_for_update=True)
    return v, app


@router.get("/reviews/{version_id}")
async def review_detail(version_id: int, admin: User = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    v = await db.get(MiniAppVersion, version_id)
    if v is None:
        raise HTTPException(404, "版本不存在")
    app = await db.get(MiniApp, v.app_id)
    dev = await db.get(Developer, app.developer_id) if app.developer_id else None
    base = await pub.baseline_for(db, app, v)
    history = list((await db.execute(select(MiniAppDecision).where(
        MiniAppDecision.app_id == app.id).order_by(MiniAppDecision.id.desc()).limit(50))).scalars())
    files = (v.manifest or {}).get("files", {})
    return {
        "version": {**version_dev(v, app),
                    "files": [{"path": p, **m} for p, m in sorted(files.items())],
                    "listing": (v.manifest or {}).get("listing"),
                    "request_domains": (v.manifest or {}).get("request_domains", []),
                    "capabilities": (v.manifest or {}).get("capabilities", []),
                    "package_url": f"/files/{v.package_key}" if v.package_key else ""},
        "app": {**app_card(app, dev), "status": app.status, "kind": app.kind},
        "developer": developer_admin(dev) if dev else None,
        "diff": pub.version_diff(base, v),
        "checklist": pub.CHECKLIST, "checklist_version": pub.CHECKLIST_VERSION,
        "reason_codes": REASON_CODES,
        "history": await _decisions(db, history),
        "file_base": f"/files/{pub.object_key(app.appid, v.id, '')}",
    }


@router.post("/reviews/{version_id}/decide")
async def decide(version_id: int, body: VersionDecisionIn,
                 admin: User = Depends(require_role("admin")),
                 db: AsyncSession = Depends(get_db)):
    if not body.approve:
        _reason_ok(body.reason_code)
    v, app = await _version(db, version_id)
    keys = {c["key"] for c in pub.CHECKLIST}
    if body.approve and not all(body.checklist.get(k) is True for k in keys):
        raise HTTPException(422, "审核清单要逐项确认通过,才能给「通过」")
    await pub.decide(db, app, v, admin, approve=body.approve, reason_code=body.reason_code,
                     note_public=body.note_public, note_internal=body.note_internal,
                     checklist={k: body.checklist.get(k) for k in sorted(keys)})
    await log_admin_action(db, admin, "miniapp.version." + ("approve" if body.approve else "reject"),
                           target_type="mini_app_version", target_id=v.id,
                           detail={"reason_code": body.reason_code})
    await db.commit()
    await db.refresh(v)
    return version_dev(v, app)


@router.post("/versions/{version_id}/preview")
async def preview(version_id: int, request: Request, body: LaunchIn | None = None,
                  admin: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    """审核预览:和开发者模拟器同一个宿主协议,initData 带 env=sim,身份是审核员自己的。"""
    v = await db.get(MiniAppVersion, version_id)
    if v is None:
        raise HTTPException(404, "版本不存在")
    app = await db.get(MiniApp, v.app_id)
    if app.hosting != "hosted":
        raise HTTPException(409, "外部地址的条目没有托管版本")
    if not version_servable(v):
        raise HTTPException(409, "这个版本已被隔离,预览不了(隔离的对象只能从 /files 取包)")
    return await sim_payload(db, request, app, v, admin, body or LaunchIn())


# =====================================================================
# 处罚:暂停、恢复、移除、紧急隔离
# =====================================================================

@router.post("/apps/{appid}/suspend")
async def suspend_app(body: PunishIn, appid: str = AppId,
                      admin: User = Depends(require_role("admin")),
                      db: AsyncSession = Depends(get_db)):
    _reason_ok(body.reason_code)
    app = await app_by_appid(db, appid, for_update=True)
    _transition("app", app.status, "suspended")
    app.status = "suspended"
    await record_decision(db, target_type="app", target_id=app.id, action="suspend", app=app,
                          reason_code=body.reason_code, note_public=body.note_public,
                          note_internal=body.note_internal, actor=admin)
    if body.quarantine and app.current_version_id:
        await _quarantine(db, app, app.current_version_id, admin, body)
    await log_admin_action(db, admin, "miniapp.app.suspend", target_type="mini_app",
                           target_id=app.id, detail={"reason_code": body.reason_code,
                                                     "quarantine": body.quarantine})
    await db.commit()
    return {"appid": app.appid, "status": app.status}


@router.post("/apps/{appid}/restore")
async def restore_app(body: dict, appid: str = AppId,
                      admin: User = Depends(require_role("admin")),
                      db: AsyncSession = Depends(get_db)):
    """整改后复审通过:暂停 → 在线。要写明依据(比如哪个版本复审通过了)。"""
    note = str(body.get("note", "")).strip()
    if len(note) < 4:
        raise HTTPException(422, "恢复要写明依据(开发者和透明中心看得到)")
    app = await app_by_appid(db, appid, for_update=True)
    _transition("app", app.status, "online")
    app.status = "online"
    await record_decision(db, target_type="app", target_id=app.id, action="restore", app=app,
                          note_public=note[:500], actor=admin)
    await log_admin_action(db, admin, "miniapp.app.restore", target_type="mini_app",
                           target_id=app.id)
    await db.commit()
    return {"appid": app.appid, "status": app.status}


@router.post("/apps/{appid}/remove")
async def remove_app(body: PunishIn, appid: str = AppId,
                     admin: User = Depends(require_role("admin")),
                     db: AsyncSession = Depends(get_db)):
    _reason_ok(body.reason_code)
    app = await app_by_appid(db, appid, for_update=True)
    _transition("app", app.status, "removed")
    app.status = "removed"
    app.removed_at = now()
    await record_decision(db, target_type="app", target_id=app.id, action="remove", app=app,
                          reason_code=body.reason_code, note_public=body.note_public,
                          note_internal=body.note_internal, actor=admin)
    await db.execute(delete(MiniAppCuration).where(MiniAppCuration.app_id == app.id))
    await log_admin_action(db, admin, "miniapp.app.remove", target_type="mini_app",
                           target_id=app.id, detail={"reason_code": body.reason_code})
    await db.commit()
    return {"appid": app.appid, "status": app.status}


async def _quarantine(db: AsyncSession, app: MiniApp, version_id: int, admin: User,
                      body: PunishIn) -> MiniAppVersion:
    v = await db.get(MiniAppVersion, version_id, with_for_update=True)
    if v is None or v.app_id != app.id:
        raise HTTPException(404, "版本不存在")
    if v.quarantined:
        raise HTTPException(409, "已经隔离了")
    v.quarantined = True
    await record_decision(db, target_type="version", target_id=v.id, action="quarantine",
                          app=app, reason_code=body.reason_code, note_public=body.note_public,
                          note_internal=body.note_internal, actor=admin)
    return v


@router.post("/versions/{version_id}/quarantine")
async def quarantine_version(version_id: int, body: PunishIn,
                             admin: User = Depends(require_role("admin")),
                             db: AsyncSession = Depends(get_db)):
    """紧急隔离:托管出口立即 404,已经打开的会话在下一次查状态或调云存储时被宿主关掉。"""
    _reason_ok(body.reason_code)
    v, app = await _version(db, version_id)
    await _quarantine(db, app, v.id, admin, body)
    await log_admin_action(db, admin, "miniapp.version.quarantine", target_type="mini_app_version",
                           target_id=v.id, detail={"reason_code": body.reason_code})
    await db.commit()
    return {"id": v.id, "quarantined": True}


@router.post("/versions/{version_id}/unquarantine")
async def unquarantine_version(version_id: int, body: dict,
                               admin: User = Depends(require_role("admin")),
                               db: AsyncSession = Depends(get_db)):
    note = str(body.get("note", "")).strip()
    if len(note) < 4:
        raise HTTPException(422, "解除隔离要写明依据")
    v, app = await _version(db, version_id)
    if not v.quarantined:
        raise HTTPException(409, "没有被隔离")
    v.quarantined = False
    await record_decision(db, target_type="version", target_id=v.id, action="unquarantine",
                          app=app, note_public=note[:500], actor=admin)
    await log_admin_action(db, admin, "miniapp.version.unquarantine",
                           target_type="mini_app_version", target_id=v.id)
    await db.commit()
    return {"id": v.id, "quarantined": False}


# =====================================================================
# 能力审批
# =====================================================================

@router.get("/capabilities")
async def list_capabilities(status: str = Query(default="requested", max_length=12),
                            admin: User = Depends(require_role("admin")),
                            db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(MiniAppCapability, MiniApp).join(
        MiniApp, MiniApp.id == MiniAppCapability.app_id).where(
        MiniAppCapability.status == status).order_by(MiniAppCapability.id))).all()
    return {"items": [{"id": c.id, "capability": c.capability, "status": c.status,
                       "justification": c.justification, "note": c.note,
                       "app": {"appid": a.appid, "name": a.name, "privacy_policy": a.privacy_policy,
                               "data_declaration": a.data_declaration}} for c, a in rows]}


@router.post("/capabilities/{cap_id}/decide")
async def decide_capability(cap_id: int, body: CapabilityDecisionIn,
                            admin: User = Depends(require_role("admin")),
                            db: AsyncSession = Depends(get_db)):
    c = await db.get(MiniAppCapability, cap_id, with_for_update=True)
    if c is None:
        raise HTTPException(404, "申请不存在")
    if not body.approve and len(body.note.strip()) < 4:
        raise HTTPException(422, "驳回要写明原因")
    target = "approved" if body.approve else "rejected"
    _transition("capability", c.status, target)
    c.status = target
    c.decided_by = admin.id
    c.decided_at = now()
    c.note = body.note.strip()
    app = await db.get(MiniApp, c.app_id)
    await record_decision(db, target_type="capability", target_id=c.id,
                          action="capability_approve" if body.approve else "capability_reject",
                          app=app, reason_code="" if body.approve else "R701",
                          note_public=f"{c.capability}:{body.note.strip()}", actor=admin)
    await log_admin_action(db, admin, "miniapp.capability." + target,
                           target_type="mini_app_capability", target_id=c.id)
    await db.commit()
    return {"id": c.id, "status": c.status}


# =====================================================================
# 投诉
# =====================================================================

@router.get("/reports")
async def list_reports(status: str = Query(default="open", max_length=12),
                       admin: User = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    """按应用聚合:一个应用 7 天内被 5 个不同的人投诉会自动进复审(flag_review 记录)。"""
    rows = (await db.execute(select(MiniAppReport, MiniApp).join(
        MiniApp, MiniApp.id == MiniAppReport.app_id).where(MiniAppReport.status == status)
        .order_by(MiniAppReport.id.desc()).limit(500))).all()
    groups: dict[str, dict] = {}
    for r, a in rows:
        g = groups.setdefault(a.appid, {"appid": a.appid, "name": a.name, "status": a.status,
                                        "reporters": set(), "items": []})
        g["reporters"].add(r.reporter_user_id)
        # 举报人只给到尾号:审核要能看出是不是同一个人在刷,但用不着完整身份
        g["items"].append({"id": r.id, "reason_code": r.reason_code,
                           "reason_label": REASON_CODES.get(r.reason_code, ""),
                           "detail": r.detail, "evidence_keys": r.evidence_keys,
                           "reporter": pseudonym(str(r.reporter_user_id), "miniapp-report")[:8],
                           "status": r.status, "resolution": r.resolution,
                           "created_at": r.created_at.isoformat()})
    out = []
    for g in groups.values():
        n = len(g.pop("reporters"))
        out.append({**g, "distinct_reporters": n, "flagged": n >= REPORT_REVIEW_THRESHOLD})
    out.sort(key=lambda g: (-g["distinct_reporters"], g["appid"]))
    return {"groups": out, "threshold": REPORT_REVIEW_THRESHOLD}


@router.post("/reports/{report_id}/handle")
async def handle_report(report_id: int, body: ReportHandleIn,
                        admin: User = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    r = await db.get(MiniAppReport, report_id, with_for_update=True)
    if r is None:
        raise HTTPException(404, "投诉不存在")
    if r.status != "open":
        raise HTTPException(409, "已经处理过了")
    r.status = "dismissed" if body.dismiss else "handled"
    r.handled_by = admin.id
    r.handled_at = now()
    r.resolution = body.resolution.strip()
    app = await db.get(MiniApp, r.app_id)
    await record_decision(db, target_type="report", target_id=r.id, action="report_handled",
                          app=app, note_public=r.resolution, actor=admin)
    await log_admin_action(db, admin, "miniapp.report." + r.status, target_type="mini_app_report",
                           target_id=r.id)
    await db.commit()
    return {"id": r.id, "status": r.status}


# =====================================================================
# 申诉(强制换人)
# =====================================================================

async def _open_appeals(db: AsyncSession) -> list[MiniAppDecision]:
    appeals = list((await db.execute(select(MiniAppDecision).where(
        MiniAppDecision.action == "appeal").order_by(MiniAppDecision.id))).scalars())
    if not appeals:
        return []
    done = set((await db.execute(select(MiniAppDecision.appeal_of).where(
        MiniAppDecision.action.in_(("appeal_upheld", "appeal_overturned")),
        MiniAppDecision.appeal_of.in_([a.id for a in appeals])))).scalars())
    return [a for a in appeals if a.id not in done]


@router.get("/appeals")
async def list_appeals(admin: User = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    appeals = await _open_appeals(db)
    originals = {d.id: d for d in (await db.execute(select(MiniAppDecision).where(
        MiniAppDecision.id.in_({a.appeal_of for a in appeals})))).scalars()} if appeals else {}
    out = []
    for a, row in zip(appeals, await _decisions(db, appeals)):
        orig = originals.get(a.appeal_of)
        o = (await _decisions(db, [orig]))[0] if orig else None
        out.append({"appeal": row, "original": o,
                    # 前端据此把「处理」按钮置灰:原结论人不能复核自己
                    "you_decided_original": bool(orig and orig.actor_id == admin.id)})
    return {"items": out}


async def _overturn(db: AsyncSession, orig: MiniAppDecision, admin: User) -> None:
    """撤销原结论。只处理「不利于开发者」的那几种(APPEALABLE_ACTIONS)。"""
    if orig.target_type == "version":
        v = await db.get(MiniAppVersion, orig.target_id, with_for_update=True)
        if orig.action == "reject" and v is not None and v.status == "rejected":
            v.status = "approved"
            v.reject_code = ""
            v.reject_note = ""
            app = await db.get(MiniApp, v.app_id, with_for_update=True)
            if app.auto_release and app.status in ("draft", "online", "offline"):
                await pub.release(db, app, v, admin, commit=False, auto=True)
        elif orig.action == "quarantine" and v is not None:
            v.quarantined = False
    elif orig.target_type == "app":
        app = await db.get(MiniApp, orig.target_id, with_for_update=True)
        if orig.action == "suspend" and app.status == "suspended":
            app.status = "online"
        elif orig.action == "remove" and app.status == "removed":
            # 移除是终态;申诉成立是唯一回来的路,回到「下架」由开发者自己决定何时上架
            app.status = "offline"
            app.removed_at = None
    elif orig.target_type == "capability":
        c = await db.get(MiniAppCapability, orig.target_id, with_for_update=True)
        if c is not None and c.status == "rejected":
            c.status = "approved"
            c.decided_by = admin.id
            c.decided_at = now()
    elif orig.target_type == "developer":
        d = await db.get(Developer, orig.target_id, with_for_update=True)
        if d is not None and d.status in ("rejected", "suspended"):
            d.status = "verified"
            d.verified_at = d.verified_at or now()
            d.reject_reason = ""


@router.post("/appeals/{appeal_id}/resolve")
async def resolve_appeal(appeal_id: int, body: AppealResolveIn,
                         admin: User = Depends(require_role("admin")),
                         db: AsyncSession = Depends(get_db)):
    a = await db.get(MiniAppDecision, appeal_id)
    if a is None or a.action != "appeal":
        raise HTTPException(404, "申诉不存在")
    if a.id not in {x.id for x in await _open_appeals(db)}:
        raise HTTPException(409, "这条申诉已经处理过了")
    orig = await db.get(MiniAppDecision, a.appeal_of)
    if orig is None:
        raise HTTPException(404, "原结论不存在")
    if orig.actor_id == admin.id:
        raise HTTPException(403, "原结论是你作出的,申诉必须由另一名审核员处理")
    if body.overturn:
        await _overturn(db, orig, admin)
    app = await db.get(MiniApp, a.app_id) if a.app_id else None
    await record_decision(db, target_type=orig.target_type, target_id=orig.target_id,
                          action="appeal_overturned" if body.overturn else "appeal_upheld",
                          app=app, developer_id=a.developer_id, note_public=body.note_public,
                          note_internal=body.note_internal, actor=admin, appeal_of=a.id)
    await log_admin_action(db, admin, "miniapp.appeal." + ("overturn" if body.overturn else "uphold"),
                           target_type="mini_app_decision", target_id=a.id)
    await db.commit()
    return {"appeal_id": a.id, "overturned": body.overturn}


# =====================================================================
# 精选(人工,每次变动公示理由)
# =====================================================================

@router.get("/curation")
async def list_curation(admin: User = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(MiniAppCuration, MiniApp).join(
        MiniApp, MiniApp.id == MiniAppCuration.app_id).order_by(MiniAppCuration.position))).all()
    return {"items": [{"appid": a.appid, "name": a.name, "position": c.position,
                       "reason": c.reason, "added_at": c.added_at.isoformat()} for c, a in rows]}


@router.post("/curation")
async def add_curation(body: CurationIn, admin: User = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    app = await app_by_appid(db, body.appid)
    if app.status != "online":
        raise HTTPException(409, "只有在线的应用能进精选")
    row = await db.get(MiniAppCuration, app.id)
    if row is None:
        db.add(MiniAppCuration(app_id=app.id, position=body.position, reason=body.reason.strip(),
                               added_by=admin.id))
    else:
        row.position = body.position
        row.reason = body.reason.strip()
        row.added_by = admin.id
        row.added_at = now()
    await record_decision(db, target_type="app", target_id=app.id, action="curate", app=app,
                          note_public=f"精选第 {body.position} 位:{body.reason.strip()}",
                          actor=admin)
    await log_admin_action(db, admin, "miniapp.curate", target_type="mini_app", target_id=app.id,
                           detail={"position": body.position})
    await db.commit()
    return {"appid": app.appid, "position": body.position}


@router.delete("/curation/{appid}")
async def remove_curation(appid: str = AppId, reason: str = Query(min_length=4, max_length=200),
                          admin: User = Depends(require_role("admin")),
                          db: AsyncSession = Depends(get_db)):
    app = await app_by_appid(db, appid)
    row = await db.get(MiniAppCuration, app.id)
    if row is None:
        raise HTTPException(404, "不在精选里")
    await db.delete(row)
    await record_decision(db, target_type="app", target_id=app.id, action="uncurate", app=app,
                          note_public=reason.strip(), actor=admin)
    await log_admin_action(db, admin, "miniapp.uncurate", target_type="mini_app", target_id=app.id)
    await db.commit()
    return {"appid": app.appid, "removed": True}


# =====================================================================
# 开发者注册:邀请制开关(D5)与邀请名单(闸门本身在 services/developer_signup.py)
# =====================================================================

@router.put("/signup-mode")
async def set_signup_mode(body: dict, admin: User = Depends(require_role("admin")),
                          db: AsyncSession = Depends(get_db)):
    mode = str(body.get("mode", ""))
    if mode not in SIGNUP_MODES:
        raise HTTPException(422, f"mode 只能是 {' / '.join(SIGNUP_MODES)}")
    flag = await db.get(PlatformFlag, SIGNUP_FLAG)
    if flag is None:
        db.add(PlatformFlag(key=SIGNUP_FLAG, value=mode))
    else:
        flag.value = mode
    await log_admin_action(db, admin, "miniapp.signup_mode", target_type="flag",
                           target_id=SIGNUP_FLAG, detail={"mode": mode})
    await db.commit()
    return {"mode": mode, "label": SIGNUP_MODES[mode]}


@router.get("/invites")
async def list_invites(admin: User = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(DeveloperInvite).order_by(DeveloperInvite.id.desc())
                             .limit(500))).scalars()
    return {"items": [{"id": i.id, "phone_tail": i.phone_tail,
                       "created_at": i.created_at.isoformat(),
                       "used_at": i.used_at.isoformat() if i.used_at else None} for i in rows],
            "mode": await signup_mode(db)}


@router.post("/invites")
async def add_invite(body: InviteIn, admin: User = Depends(require_role("admin")),
                     db: AsyncSession = Depends(get_db)):
    key = invite_key(body.phone)
    if await db.scalar(select(DeveloperInvite.id).where(DeveloperInvite.phone_pseudonym == key)):
        raise HTTPException(409, "已经邀请过了")
    inv = DeveloperInvite(phone_pseudonym=key, phone_tail=body.phone[-4:], created_by=admin.id)
    db.add(inv)
    await log_admin_action(db, admin, "miniapp.invite", target_type="developer_invite",
                           target_id=body.phone[-4:])
    await db.commit()
    return {"id": inv.id, "phone_tail": inv.phone_tail}


@router.delete("/invites/{invite_id}")
async def delete_invite(invite_id: int, admin: User = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    inv = await db.get(DeveloperInvite, invite_id)
    if inv is None:
        raise HTTPException(404, "邀请不存在")
    await db.delete(inv)
    await log_admin_action(db, admin, "miniapp.invite.delete", target_type="developer_invite",
                           target_id=invite_id)
    await db.commit()
    return {"removed": True}


# =====================================================================
# 统计(透明中心那一栏的数也从 transparency_miniapps 算,这里给后台看明细)
# =====================================================================

@router.get("/stats")
async def stats(days: int = Query(default=30, ge=1, le=365),
                admin: User = Depends(require_role("admin")),
                db: AsyncSession = Depends(get_db)):
    from ..services.miniapp_transparency import review_stats
    return await review_stats(db, since=now() - timedelta(days=days))
