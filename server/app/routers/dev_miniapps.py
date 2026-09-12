"""开发者接口 `/dev/v1`(#322、#329、#330、#331)。

只给 developer 角色。每个 `/apps/{appid}/…` 都先确认**这个应用是你的** —— 不是你的一律 404,
不回 403:别人的应用存不存在,也不该从这里探出来(#335 的 IDOR 一项)。

认证前能做的:建应用、传开发版、设体验版、加体验者、用模拟器。认证后才能提交审核(#329)。
"""
import re
from dataclasses import dataclass
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import (Developer, MiniApp, MiniAppCapability, MiniAppDecision, MiniAppReport,
                      MiniAppTester, MiniAppUsageDaily, MiniAppVersion, RuleRevision, User)
from ..ratelimit import check_rate_limit
from ..schemas_miniapp import (AgreementAcceptIn, AppealIn, AutoReleaseIn, CapabilityIn,
                               DevAppCreateIn, DevAppUpdateIn, DevProfileIn,
                               DevVerifyCompanyIn, DevVerifyIndividualIn, DomainsIn, LaunchIn,
                               RollbackIn, StorageIn, SubmitIn, TesterIn)
from ..security import require_role
from ..services import miniapp_kv as kv
from ..services import miniapp_publish as pub
from ..services.crypto import decrypt, encrypt
from ..services.mini_app_v2 import new_appid
from ..services.miniapp_package import MAX_ZIP
from ..services.miniapp_platform import (APPEAL_WINDOW_DAYS, APPEALABLE_ACTIONS, APPID_PATTERN,
                                         CATEGORIES, DOMAIN_CHANGES_PER_MONTH,
                                         FUTURE_CAPABILITIES, MAX_APPS, MAX_TESTERS,
                                         REASON_CODES, REQUESTABLE_CAPABILITIES,
                                         USERS_DISPLAY_FLOOR, app_card, capabilities_of,
                                         developer_card, entry_path, hosted_base, hosted_origin,
                                         issue_secret, launch_fragment, now, record_decision,
                                         sign_for, tester_key, today_bj, version_servable)
from ..services.miniapp_rules import current_revision
from ..services.miniapp_state import LABELS, assert_transition
from ..state_machine import TransitionError
from .mini_apps import bridge_error, run_storage

router = APIRouter(prefix="/dev/v1", tags=["小程序开发者"])
AppId = Path(pattern=APPID_PATTERN)

#: 非官方应用的名称里不许出现的字样(仿冒平台,R501)
RESERVED_NAME_WORDS = ("超级赞", "官方", "客服", "支付", "钱包", "SuperZ", "superz")


@dataclass
class Ctx:
    user: User
    dev: Developer


async def ctx(user: User = Depends(require_role("developer")),
              db: AsyncSession = Depends(get_db)) -> Ctx:
    dev = await db.scalar(select(Developer).where(Developer.user_id == user.id))
    if dev is None:
        # 注册时就建了;这里兜住「迁移前注册的号」和并发
        dev = Developer(user_id=user.id, kind="individual",
                        display_name=(user.name or f"开发者{user.phone[-4:]}")[:40],
                        status="unverified")
        db.add(dev)
        await db.commit()
        await db.refresh(dev)
    if dev.status == "closed":
        raise HTTPException(403, "开发者账号已注销")
    return Ctx(user=user, dev=dev)


def _transition(machine: str, cur: str, target: str) -> None:
    try:
        assert_transition(machine, cur, target)
    except TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc


async def own_app(db: AsyncSession, c: Ctx, appid: str, *, for_update: bool = False) -> MiniApp:
    stmt = select(MiniApp).where(MiniApp.appid == appid, MiniApp.developer_id == c.dev.id)
    if for_update:
        stmt = stmt.with_for_update()
    app = (await db.execute(stmt)).scalar_one_or_none()
    if app is None:
        raise HTTPException(404, "小程序不存在")
    return app


async def own_version(db: AsyncSession, app: MiniApp, version_id: int) -> MiniAppVersion:
    v = await db.get(MiniAppVersion, version_id)
    if v is None or v.app_id != app.id:
        raise HTTPException(404, "版本不存在")
    return v


def _mask_name(name: str) -> str:
    return name[0] + "*" * (len(name) - 1) if name else ""


def version_dev(v: MiniAppVersion | None, app: MiniApp | None = None) -> dict | None:
    if v is None:
        return None
    return {
        "id": v.id, "version": v.version, "build": v.build, "status": v.status,
        "status_label": LABELS.get(v.status, v.status), "sha256": v.sha256, "size": v.size,
        "file_count": v.file_count, "changelog": v.changelog, "review_note": v.review_note,
        "quarantined": v.quarantined, "reject_code": v.reject_code,
        "reject_label": REASON_CODES.get(v.reject_code, "") if v.reject_code else "",
        "reject_note": v.reject_note,
        "warnings": (v.manifest or {}).get("warnings", []),
        "superz": (v.manifest or {}).get("superz", {}),
        "is_current": bool(app and app.current_version_id == v.id),
        "is_trial": bool(app and app.trial_version_id == v.id),
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "submitted_at": v.submitted_at.isoformat() if v.submitted_at else None,
        "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None,
        "released_at": v.released_at.isoformat() if v.released_at else None,
    }


async def app_dev(db: AsyncSession, request: Request, app: MiniApp, dev: Developer) -> dict:
    cur = await db.get(MiniAppVersion, app.current_version_id) if app.current_version_id else None
    trial = await db.get(MiniAppVersion, app.trial_version_id) if app.trial_version_id else None
    reviewing = await db.scalar(select(MiniAppVersion).where(
        MiniAppVersion.app_id == app.id, MiniAppVersion.status == "reviewing").limit(1))
    testers = await db.scalar(select(func.count()).select_from(MiniAppTester).where(
        MiniAppTester.app_id == app.id))
    caps = list((await db.execute(select(MiniAppCapability).where(
        MiniAppCapability.app_id == app.id))).scalars())
    month = today_bj().strftime("%Y-%m")
    try:
        origin = hosted_origin(request, app) if app.hosting == "hosted" else ""
    except HTTPException:
        origin = ""
    return {
        **app_card(app, dev), "status": app.status,
        "status_label": LABELS.get(app.status, app.status),
        "description": app.description, "screenshots": app.screenshots or [],
        "privacy_policy": app.privacy_policy, "data_declaration": app.data_declaration or [],
        "listing_draft": app.listing_draft,
        "request_domains": app.request_domains or [], "auto_release": app.auto_release,
        "hosted_origin": origin,
        "secret": {"rotated_at": app.secret_rotated_at.isoformat() if app.secret_rotated_at
                   else None, "pending": bool(app.secret_pending_enc)},
        "current_version": version_dev(cur, app), "trial_version": version_dev(trial, app),
        "reviewing_version": version_dev(reviewing, app),
        "testers": testers, "max_testers": MAX_TESTERS,
        "capabilities": await capabilities_of(db, app),
        "capability_requests": [
            {"id": x.id, "capability": x.capability, "status": x.status,
             "status_label": LABELS.get(x.status, x.status), "justification": x.justification,
             "note": x.note} for x in caps],
        "domain_changes": {
            "used": app.domain_changes_count if app.domain_changes_month == month else 0,
            "limit": DOMAIN_CHANGES_PER_MONTH},
        "trial_link": f"{settings.public_base_url.rstrip('/')}/m/{app.appid}?v=trial",
        "removed_at": app.removed_at.isoformat() if app.removed_at else None,
    }


# =====================================================================
# 账号、认证、协议
# =====================================================================

async def _me(db: AsyncSession, c: Ctx) -> dict:
    dev = c.dev
    required = await current_revision(db)
    real = decrypt(dev.real_name_enc) if dev.real_name_enc else ""
    apps = await db.scalar(select(func.count()).select_from(MiniApp).where(
        MiniApp.developer_id == dev.id, MiniApp.status != "removed"))
    return {
        "id": dev.id, "kind": dev.kind, "display_name": dev.display_name,
        "status": dev.status, "status_label": LABELS.get(dev.status, dev.status),
        "public": developer_card(dev),
        "real_name_masked": _mask_name(real), "id_no_tail": dev.id_no_tail,
        "company_name": dev.company_name, "uscc": dev.uscc,
        "license_uploaded": bool(dev.license_key), "contact_name": dev.contact_name,
        "contact_email": dev.contact_email, "reject_reason": dev.reject_reason,
        "phone_tail": c.user.phone[-4:],
        "agreement": {"accepted": dev.agreement_version, "required": required,
                      "ok": dev.agreement_version >= required and required > 0,
                      "rules_url": "/rules/developer"},
        "can_submit": dev.status == "verified" and dev.agreement_version >= required,
        "apps": apps,
        "limits": {"max_apps": MAX_APPS["company" if dev.kind == "company"
                                        and dev.status == "verified" else "individual"],
                   "max_testers": MAX_TESTERS},
    }


@router.get("/me")
async def me(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    return await _me(db, c)


@router.put("/me/profile")
async def update_profile(body: DevProfileIn, c: Ctx = Depends(ctx),
                         db: AsyncSession = Depends(get_db)):
    name = body.display_name.strip()
    if any(w.lower() in name.lower() for w in RESERVED_NAME_WORDS):
        raise HTTPException(422, "开发者名里不能有「超级赞」「官方」等字样")
    if body.contact_email and not re.match(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", body.contact_email):
        raise HTTPException(422, "邮箱格式不对")
    c.dev.display_name = name
    c.dev.contact_email = body.contact_email.strip()
    await db.commit()
    return await _me(db, c)


@router.post("/me/verify/individual")
async def verify_individual(body: DevVerifyIndividualIn, c: Ctx = Depends(ctx),
                            db: AsyncSession = Depends(get_db)):
    """个人实名:本地校验证号 + 满 18 岁 + 三方二要素(配置后)。通过即认证。

    真名、证号只存密文,接口只回尾号;公开页只显示你自取的开发者名 +「个人开发者 · 已实名」。
    """
    from ..services.idcheck import is_adult, validate_id_no, verify_two_elements

    dev = c.dev
    if dev.status not in ("unverified", "rejected"):
        raise HTTPException(409, "当前状态不能提交认证")
    await check_rate_limit("dev_verify", str(c.user.id), 5)
    id_no = body.id_no.strip().upper()
    birth, err = validate_id_no(id_no)
    if err:
        raise HTTPException(422, err)
    if not is_adult(birth):
        raise HTTPException(422, "开发者须年满 18 周岁")
    try:
        ok = await verify_two_elements(body.real_name.strip(), id_no)
    except RuntimeError as exc:
        raise HTTPException(503, f"{exc},请稍后再试") from exc
    if not ok:
        raise HTTPException(422, "姓名与身份证号不一致")
    if dev.status == "rejected":
        _transition("developer", dev.status, "pending")
        dev.status = "pending"
    _transition("developer", dev.status, "verified")
    dev.kind = "individual"
    dev.real_name_enc = encrypt(body.real_name.strip())
    dev.id_no_enc = encrypt(id_no)
    dev.id_no_tail = id_no[-4:]
    dev.status = "verified"
    dev.verified_at = dev.submitted_at = now()
    dev.reject_reason = ""
    await record_decision(db, target_type="developer", target_id=dev.id, action="verify",
                          developer_id=dev.id, note_public="个人实名核验通过")
    await db.commit()
    return await _me(db, c)


@router.post("/me/verify/company")
async def verify_company(body: DevVerifyCompanyIn, c: Ctx = Depends(ctx),
                         db: AsyncSession = Depends(get_db)):
    """企业认证:营业执照(私有桶)+ 统一社会信用代码,人工审核。企业名公开展示。"""
    dev = c.dev
    if dev.status not in ("unverified", "rejected"):
        raise HTTPException(409, "当前状态不能提交认证")
    if not re.match(rf"^/files/dev_license/u{c.user.id}-[0-9a-f]{{32}}\.(jpg|jpeg|png|webp)$",
                    body.license_key):
        raise HTTPException(422, "营业执照要先用 /upload(purpose=dev_license)上传")
    _transition("developer", dev.status, "pending")
    dev.kind = "company"
    dev.company_name = body.company_name.strip()
    dev.uscc = body.uscc
    dev.license_key = body.license_key
    dev.contact_name = body.contact_name.strip()
    dev.status = "pending"
    dev.submitted_at = now()
    dev.reject_reason = ""
    await record_decision(db, target_type="developer", target_id=dev.id, action="verify_submit",
                          developer_id=dev.id)
    await db.commit()
    return await _me(db, c)


@router.post("/me/agreement")
async def accept_agreement(body: AgreementAcceptIn, c: Ctx = Depends(ctx),
                           db: AsyncSession = Depends(get_db)):
    required = await current_revision(db)
    if body.revision != required:
        raise HTTPException(409, f"规则现在是第 {required} 版,请刷新后阅读最新版本再接受")
    c.dev.agreement_version = required
    c.dev.agreement_accepted_at = now()
    await db.commit()
    return await _me(db, c)


@router.get("/messages")
async def messages(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """消息:审核结果、处罚、申诉结果(来自审核记录),以及接受之后的规则变更。"""
    rows = list((await db.execute(select(MiniAppDecision).where(
        MiniAppDecision.developer_id == c.dev.id,
        MiniAppDecision.action.notin_(("submit", "withdraw", "release", "auto_release",
                                       "rollback", "verify_submit", "appeal")),
    ).order_by(MiniAppDecision.id.desc()).limit(50))).scalars())
    names = {}
    ids = {d.app_id for d in rows if d.app_id}
    if ids:
        names = dict((await db.execute(select(MiniApp.id, MiniApp.name).where(
            MiniApp.id.in_(ids)))).all())
    rules = list((await db.execute(select(RuleRevision).where(
        RuleRevision.audience == "developer",
        RuleRevision.revision > c.dev.agreement_version).order_by(RuleRevision.revision)
    )).scalars())
    return {
        "decisions": [decision_dev(d, names.get(d.app_id, "")) for d in rows],
        "rule_updates": [{"revision": r.revision, "at": r.created_at.isoformat()} for r in rules],
    }


def decision_dev(d: MiniAppDecision, app_name: str = "") -> dict:
    """给开发者看的审核记录:**不含 note_internal、不含审核员身份**。"""
    return {
        "id": d.id, "target_type": d.target_type, "target_id": d.target_id,
        "app_id": d.app_id, "app_name": app_name, "action": d.action,
        "action_label": ACTION_LABELS.get(d.action, d.action),
        "reason_code": d.reason_code, "reason_label": REASON_CODES.get(d.reason_code, ""),
        "note_public": d.note_public, "appeal_of": d.appeal_of,
        "appealable": d.action in APPEALABLE_ACTIONS
        and d.created_at is not None and d.created_at >= now() - timedelta(days=APPEAL_WINDOW_DAYS),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


ACTION_LABELS = {
    "submit": "提交审核", "withdraw": "撤回审核", "approve": "审核通过", "reject": "审核驳回",
    "release": "发布", "auto_release": "自动发布", "rollback": "回滚",
    "suspend": "暂停", "restore": "恢复", "remove": "移除", "quarantine": "紧急隔离",
    "unquarantine": "解除隔离", "capability_approve": "能力申请通过",
    "capability_reject": "能力申请驳回", "capability_revoke": "能力收回",
    "verify": "认证通过", "verify_submit": "提交认证", "developer_reject": "认证驳回",
    "developer_suspend": "开发者暂停", "developer_restore": "开发者恢复",
    "appeal": "申诉", "appeal_upheld": "申诉未成立(维持原结论)",
    "appeal_overturned": "申诉成立(撤销原结论)", "flag_review": "投诉达到阈值,进入复审",
    "online": "上架", "offline": "下架", "curate": "进入精选", "uncurate": "移出精选",
    "report_handled": "投诉已处理",
}


# =====================================================================
# 应用
# =====================================================================

async def _check_name(db: AsyncSession, name: str, *, exclude_id: int | None = None,
                      official: bool = False) -> str:
    name = name.strip()
    if not official and any(w.lower() in name.lower() for w in RESERVED_NAME_WORDS):
        raise HTTPException(422, "名称里不能有「超级赞」「官方」「客服」「支付」等字样")
    stmt = select(MiniApp.id).where(func.lower(MiniApp.name) == name.lower(),
                                    MiniApp.status != "removed")
    if exclude_id:
        stmt = stmt.where(MiniApp.id != exclude_id)
    if await db.scalar(stmt.limit(1)):
        raise HTTPException(409, "已有同名的小程序,换一个名称")
    return name


@router.get("/apps")
async def list_apps(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    apps = list((await db.execute(select(MiniApp).where(MiniApp.developer_id == c.dev.id)
                                  .order_by(MiniApp.id.desc()))).scalars())
    out = []
    for a in apps:
        cur = await db.get(MiniAppVersion, a.current_version_id) if a.current_version_id else None
        reviewing = await db.scalar(select(func.count()).select_from(MiniAppVersion).where(
            MiniAppVersion.app_id == a.id, MiniAppVersion.status == "reviewing"))
        out.append({**app_card(a, c.dev), "status": a.status,
                    "status_label": LABELS.get(a.status, a.status),
                    "current_version": cur.version if cur else None,
                    "reviewing": bool(reviewing)})
    return {"items": out}


@router.post("/apps")
async def create_app(body: DevAppCreateIn, request: Request, c: Ctx = Depends(ctx),
                     db: AsyncSession = Depends(get_db)):
    if c.dev.status == "suspended":
        raise HTTPException(403, "开发者账号已暂停,不能创建应用")
    if body.category not in CATEGORIES:
        raise HTTPException(422, "分类不存在")
    limit = MAX_APPS["company" if c.dev.kind == "company" and c.dev.status == "verified"
                     else "individual"]
    count = await db.scalar(select(func.count()).select_from(MiniApp).where(
        MiniApp.developer_id == c.dev.id, MiniApp.status != "removed"))
    if count >= limit:
        raise HTTPException(409, f"最多创建 {limit} 个应用")
    name = await _check_name(db, body.name, official=c.dev.is_official)
    app = MiniApp(appid=new_appid(), developer_id=c.dev.id, name=name, icon=name[0],
                  tagline=body.tagline.strip(), kind=body.kind, category=body.category,
                  hosting="hosted", status="draft", entry_url="", allowed_origins=[], perms=[],
                  sort=0, is_official=c.dev.is_official)
    secret = issue_secret(app)
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return {"app": await app_dev(db, request, app, c.dev), "app_secret": secret,
            "notice": "AppSecret 只显示这一次,请立即保存到你的服务端配置里"}


@router.get("/apps/{appid}")
async def get_app(request: Request, appid: str = AppId, c: Ctx = Depends(ctx),
                  db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid)
    return await app_dev(db, request, app, c.dev)


@router.put("/apps/{appid}")
async def update_app(body: DevAppUpdateIn, request: Request, appid: str = AppId,
                     c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """改展示信息。**上架过的应用,改动随下一个版本送审**(见 MiniApp.listing_draft)。"""
    app = await own_app(db, c, appid, for_update=True)
    if app.status == "removed":
        raise HTTPException(409, "应用已移除")
    changes = body.model_dump(exclude_none=True)
    if "name" in changes:
        changes["name"] = await _check_name(db, changes["name"], exclude_id=app.id,
                                            official=c.dev.is_official)
    if "category" in changes and changes["category"] not in CATEGORIES:
        raise HTTPException(422, "分类不存在")
    for k in ("tagline", "description", "privacy_policy"):
        if k in changes:
            changes[k] = changes[k].strip()
    if app.first_released_at is None:
        pub.apply_listing(app, changes)
        app.listing_draft = None
    else:
        draft = {**pub.effective_listing(app), **changes}
        app.listing_draft = None if draft == pub.listing_of(app) else draft
    await db.commit()
    await db.refresh(app)
    return await app_dev(db, request, app, c.dev)


@router.post("/apps/{appid}/offline")
async def take_offline(request: Request, appid: str = AppId, c: Ctx = Depends(ctx),
                       db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    _transition("app", app.status, "offline")
    app.status = "offline"
    await record_decision(db, target_type="app", target_id=app.id, action="offline", app=app,
                          actor=c.user, note_public="开发者自己下架")
    await db.commit()
    return await app_dev(db, request, app, c.dev)


@router.post("/apps/{appid}/online")
async def bring_online(request: Request, appid: str = AppId, c: Ctx = Depends(ctx),
                       db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    if app.status == "draft":
        raise HTTPException(409, "还没有发布过版本:审核通过后点「发布」才会上线")
    if app.status == "suspended":
        raise HTTPException(409, "应用被平台暂停,整改后提交新版本,复审通过由平台恢复")
    _transition("app", app.status, "online")
    app.status = "online"
    await record_decision(db, target_type="app", target_id=app.id, action="online", app=app,
                          actor=c.user, note_public="开发者重新上架")
    await db.commit()
    return await app_dev(db, request, app, c.dev)


@router.post("/apps/{appid}/remove")
async def remove_app(body: dict, appid: str = AppId, c: Ctx = Depends(ctx),
                     db: AsyncSession = Depends(get_db)):
    """永久移除(终态)。要把应用名称原样再输一遍。用户数据保留 30 天供导出。"""
    app = await own_app(db, c, appid, for_update=True)
    if str(body.get("confirm_name", "")).strip() != app.name:
        raise HTTPException(422, "请输入应用名称确认")
    _transition("app", app.status, "removed")
    app.status = "removed"
    app.removed_at = now()
    await record_decision(db, target_type="app", target_id=app.id, action="remove", app=app,
                          actor=c.user, note_public="开发者移除")
    await db.commit()
    return {"appid": app.appid, "status": app.status}


# ---------------- 版本 ----------------

@router.post("/apps/{appid}/versions")
async def upload_version(
    request: Request,
    appid: str = AppId,
    file: UploadFile = File(...),
    version: str = Form(default="", max_length=32),
    changelog: str = Form(default="", max_length=1000),
    c: Ctx = Depends(ctx),
    db: AsyncSession = Depends(get_db),
):
    """上传 zip:按 §5.6 逐条校验,产出校验报告;通过的存成不可变版本。"""
    app = await own_app(db, c, appid)
    if c.dev.status == "suspended":
        raise HTTPException(403, "开发者账号已暂停")
    limit = MAX_ZIP.get(app.kind, MAX_ZIP["app"])
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"包超过 {limit // 1024 // 1024} MB")
    if version and not re.match(r"^[0-9A-Za-z.+-]{1,32}$", version):
        raise HTTPException(422, "版本号只能用字母、数字和 . + -")
    v, report = await pub.create_version(db, app, data, version=version, changelog=changelog,
                                         actor=c.user)
    if v is None:
        raise HTTPException(422, detail={"message": "包没有通过校验", "report": report.public()})
    app = await own_app(db, c, appid)
    return {"version": version_dev(v, app), "report": report.public()}


@router.get("/apps/{appid}/versions")
async def list_versions(appid: str = AppId, c: Ctx = Depends(ctx),
                        db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid)
    rows = (await db.execute(select(MiniAppVersion).where(MiniAppVersion.app_id == app.id)
                             .order_by(MiniAppVersion.build.desc()))).scalars()
    return {"items": [version_dev(v, app) for v in rows]}


@router.get("/apps/{appid}/versions/{version_id}")
async def get_version(version_id: int, appid: str = AppId, c: Ctx = Depends(ctx),
                      db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid)
    v = await own_version(db, app, version_id)
    files = (v.manifest or {}).get("files", {})
    return {**version_dev(v, app),
            "files": [{"path": p, **meta} for p, meta in sorted(files.items())]}


@router.post("/apps/{appid}/versions/{version_id}/trial")
async def set_trial(request: Request, version_id: int, appid: str = AppId,
                    c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    v = await own_version(db, app, version_id)
    await pub.set_trial(db, app, v)
    return await app_dev(db, request, app, c.dev)


@router.post("/apps/{appid}/versions/{version_id}/submit")
async def submit_version(body: SubmitIn, request: Request, version_id: int,
                         appid: str = AppId, c: Ctx = Depends(ctx),
                         db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    v = await own_version(db, app, version_id)
    await pub.submit(db, app, v, c.dev, review_note=body.review_note,
                     required_revision=await current_revision(db))
    return version_dev(v, app)


@router.post("/apps/{appid}/versions/{version_id}/withdraw")
async def withdraw_version(version_id: int, appid: str = AppId, c: Ctx = Depends(ctx),
                           db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    v = await own_version(db, app, version_id)
    await pub.withdraw(db, app, v)
    return version_dev(v, app)


@router.post("/apps/{appid}/versions/{version_id}/release")
async def release_version(request: Request, version_id: int, appid: str = AppId,
                          c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    v = await own_version(db, app, version_id)
    await pub.release(db, app, v, c.user)
    await db.refresh(app)
    return await app_dev(db, request, app, c.dev)


@router.post("/apps/{appid}/rollback")
async def rollback(body: RollbackIn, request: Request, appid: str = AppId,
                   c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    v = await own_version(db, app, body.version_id)
    await pub.rollback(db, app, v, c.user)
    await db.refresh(app)
    return await app_dev(db, request, app, c.dev)


@router.put("/apps/{appid}/auto-release")
async def auto_release(body: AutoReleaseIn, request: Request, appid: str = AppId,
                       c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    app.auto_release = body.enabled
    await db.commit()
    return await app_dev(db, request, app, c.dev)


# ---------------- 体验者 ----------------

@router.get("/apps/{appid}/testers")
async def list_testers(appid: str = AppId, c: Ctx = Depends(ctx),
                       db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid)
    rows = (await db.execute(select(MiniAppTester).where(MiniAppTester.app_id == app.id)
                             .order_by(MiniAppTester.id))).scalars()
    return {"items": [{"id": t.id, "phone_tail": t.phone_tail,
                       "added_at": t.added_at.isoformat()} for t in rows],
            "max": MAX_TESTERS}


@router.post("/apps/{appid}/testers")
async def add_tester(body: TesterIn, appid: str = AppId, c: Ctx = Depends(ctx),
                     db: AsyncSession = Depends(get_db)):
    """按手机号加体验者:存假名 + 尾号,不存明文。对方用这个手机号登录用户端就能扫码打开体验版。"""
    app = await own_app(db, c, appid, for_update=True)
    n = await db.scalar(select(func.count()).select_from(MiniAppTester).where(
        MiniAppTester.app_id == app.id))
    if n >= MAX_TESTERS:
        raise HTTPException(409, f"每个应用最多 {MAX_TESTERS} 个体验者")
    key = tester_key(body.phone)
    if await db.scalar(select(MiniAppTester.id).where(MiniAppTester.app_id == app.id,
                                                      MiniAppTester.phone_pseudonym == key)):
        raise HTTPException(409, "已经是体验者了")
    t = MiniAppTester(app_id=app.id, phone_pseudonym=key, phone_tail=body.phone[-4:])
    db.add(t)
    await db.commit()
    return {"id": t.id, "phone_tail": t.phone_tail}


@router.delete("/apps/{appid}/testers/{tester_id}")
async def remove_tester(tester_id: int, appid: str = AppId, c: Ctx = Depends(ctx),
                        db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid)
    t = await db.get(MiniAppTester, tester_id)
    if t is None or t.app_id != app.id:
        raise HTTPException(404, "体验者不存在")
    await db.delete(t)
    await db.commit()
    return {"removed": True}


# ---------------- 能力 ----------------

@router.post("/apps/{appid}/capabilities")
async def request_capability(body: CapabilityIn, appid: str = AppId, c: Ctx = Depends(ctx),
                             db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid)
    if body.capability in FUTURE_CAPABILITIES:
        raise HTTPException(422, f"「{FUTURE_CAPABILITIES[body.capability]}」能力暂未开放申请")
    if body.capability not in REQUESTABLE_CAPABILITIES:
        raise HTTPException(422, "没有这项能力(基础能力不用申请)")
    row = await db.scalar(select(MiniAppCapability).where(
        MiniAppCapability.app_id == app.id, MiniAppCapability.capability == body.capability))
    if row is None:
        row = MiniAppCapability(app_id=app.id, capability=body.capability, status="requested",
                                justification=body.justification.strip())
        db.add(row)
    else:
        try:
            assert_transition("capability", row.status, "requested")
        except TransitionError as exc:
            raise HTTPException(409, "已经在申请中或已经通过了" if row.status in (
                "requested", "approved") else str(exc)) from exc
        row.status = "requested"
        row.justification = body.justification.strip()
        row.note = ""
    await db.commit()
    return {"id": row.id, "capability": row.capability, "status": row.status}


# ---------------- 密钥(两步轮换) ----------------

@router.post("/apps/{appid}/secret/rotate")
async def rotate_secret(appid: str = AppId, c: Ctx = Depends(ctx),
                        db: AsyncSession = Depends(get_db)):
    """第一步:生成待生效的新密钥(只显示这一次)。部署到你的服务端之后,再调 activate 切换。
    切换前平台仍用旧密钥签发 —— 两边永远不会对不上。"""
    from ..services.mini_app_v2 import new_app_secret

    app = await own_app(db, c, appid, for_update=True)
    secret = new_app_secret()
    app.secret_pending_enc = encrypt(secret)
    await db.commit()
    return {"app_secret_pending": secret,
            "notice": "新密钥只显示这一次。先把它部署到你的服务端(新旧两把都能验),再点「切换」"}


@router.post("/apps/{appid}/secret/activate")
async def activate_secret(appid: str = AppId, c: Ctx = Depends(ctx),
                          db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    if not app.secret_pending_enc:
        raise HTTPException(409, "没有待生效的密钥,先生成")
    app.secret_enc = app.secret_pending_enc
    app.secret_pending_enc = ""
    app.secret_rotated_at = now()
    await db.commit()
    return {"activated": True, "rotated_at": app.secret_rotated_at.isoformat()}


@router.post("/apps/{appid}/secret/cancel")
async def cancel_secret(appid: str = AppId, c: Ctx = Depends(ctx),
                        db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid, for_update=True)
    app.secret_pending_enc = ""
    await db.commit()
    return {"cancelled": True}


# ---------------- 服务器域名 ----------------

@router.put("/apps/{appid}/domains")
async def set_domains(body: DomainsIn, request: Request, appid: str = AppId,
                      c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """声明的服务器域名进托管页 CSP 的 connect-src / img-src / media-src。只对新启动生效。"""
    app = await own_app(db, c, appid, for_update=True)
    domains = list(dict.fromkeys(d.lower() for d in body.request_domains))
    if domains == list(app.request_domains or []):
        return await app_dev(db, request, app, c.dev)
    month = today_bj().strftime("%Y-%m")
    used = app.domain_changes_count if app.domain_changes_month == month else 0
    if used >= DOMAIN_CHANGES_PER_MONTH:
        raise HTTPException(429, f"每个应用每月最多改 {DOMAIN_CHANGES_PER_MONTH} 次服务器域名")
    app.request_domains = domains
    app.domain_changes_month = month
    app.domain_changes_count = used + 1
    await db.commit()
    return await app_dev(db, request, app, c.dev)


# ---------------- 数据、投诉、审核记录 ----------------

@router.get("/apps/{appid}/stats")
async def stats(appid: str = AppId, days: int = Query(default=30, ge=1, le=90),
                c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """每日打开次数与用户数。用户数 < 10 的那天只显示「< 10」—— 防止反推到个人。"""
    app = await own_app(db, c, appid)
    since = today_bj() - timedelta(days=days - 1)
    rows = (await db.execute(select(MiniAppUsageDaily).where(
        MiniAppUsageDaily.app_id == app.id, MiniAppUsageDaily.day >= since)
        .order_by(MiniAppUsageDaily.day))).scalars()
    csp = {}
    try:
        from ..redis_client import get_redis
        r = get_redis()
        for i in range(min(days, 30)):
            day = today_bj() - timedelta(days=i)
            val = await r.get(f"miniapp:csp:{app.appid}:{day.strftime('%Y%m%d')}")
            if val:
                csp[day.isoformat()] = int(val)
    except Exception:
        csp = {}
    return {"items": [{"day": x.day.isoformat(), "opens": x.opens,
                       "users": x.users if x.users >= USERS_DISPLAY_FLOOR
                       else f"< {USERS_DISPLAY_FLOOR}"} for x in rows],
            "csp_blocked": csp, "floor": USERS_DISPLAY_FLOOR}


@router.get("/apps/{appid}/reports")
async def app_reports(appid: str = AppId, c: Ctx = Depends(ctx),
                      db: AsyncSession = Depends(get_db)):
    """用户投诉:只有原因、状态和处理结果。**举报人身份、说明原文、截图都不给开发者。**"""
    app = await own_app(db, c, appid)
    rows = (await db.execute(select(MiniAppReport).where(MiniAppReport.app_id == app.id)
                             .order_by(MiniAppReport.id.desc()).limit(100))).scalars()
    return {"items": [{"id": r.id, "reason_code": r.reason_code,
                       "reason_label": REASON_CODES.get(r.reason_code, ""), "status": r.status,
                       "resolution": r.resolution,
                       "created_at": r.created_at.isoformat()} for r in rows]}


@router.get("/apps/{appid}/decisions")
async def app_decisions(appid: str = AppId, c: Ctx = Depends(ctx),
                        db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid)
    rows = (await db.execute(select(MiniAppDecision).where(MiniAppDecision.app_id == app.id)
                             .order_by(MiniAppDecision.id.desc()).limit(200))).scalars()
    rows = list(rows)
    appealed = {d.appeal_of for d in rows if d.action == "appeal"}
    out = []
    for d in rows:
        item = decision_dev(d, app.name)
        item["appealable"] = item["appealable"] and d.id not in appealed
        out.append(item)
    return {"items": out}


@router.get("/decisions")
async def my_decisions(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    rows = list((await db.execute(select(MiniAppDecision).where(
        MiniAppDecision.developer_id == c.dev.id).order_by(MiniAppDecision.id.desc())
        .limit(200))).scalars())
    appealed = {d.appeal_of for d in rows if d.action == "appeal"}
    out = []
    for d in rows:
        item = decision_dev(d)
        item["appealable"] = item["appealable"] and d.id not in appealed
        out.append(item)
    return {"items": out}


@router.post("/decisions/{decision_id}/appeal")
async def appeal(decision_id: int, body: AppealIn, c: Ctx = Depends(ctx),
                 db: AsyncSession = Depends(get_db)):
    """对不利结论申诉:7 天内、每个结论一次。系统强制换一名审核员处理(admin_miniapps.resolve_appeal)。"""
    d = await db.get(MiniAppDecision, decision_id)
    if d is None or d.developer_id != c.dev.id:
        raise HTTPException(404, "记录不存在")
    if d.action not in APPEALABLE_ACTIONS:
        raise HTTPException(409, "这条记录不是可以申诉的结论")
    if d.created_at < now() - timedelta(days=APPEAL_WINDOW_DAYS):
        raise HTTPException(409, f"已超过 {APPEAL_WINDOW_DAYS} 天申诉期")
    if await db.scalar(select(MiniAppDecision.id).where(MiniAppDecision.appeal_of == d.id,
                                                        MiniAppDecision.action == "appeal")):
        raise HTTPException(409, "每个结论只能申诉一次")
    app = await db.get(MiniApp, d.app_id) if d.app_id else None
    a = await record_decision(db, target_type=d.target_type, target_id=d.target_id,
                              action="appeal", app=app, developer_id=c.dev.id,
                              note_public=body.text.strip(), actor=c.user, appeal_of=d.id)
    await db.commit()
    return {"id": a.id, "appeal_of": d.id, "status": "open"}


# =====================================================================
# 模拟器(#331):真签名的 initData,env=sim,用开发者自己的测试身份
# =====================================================================

@router.post("/apps/{appid}/sim/launch")
async def sim_launch(body: LaunchIn, request: Request, appid: str = AppId,
                     version_id: int = Query(...), c: Ctx = Depends(ctx),
                     db: AsyncSession = Depends(get_db)):
    """模拟器启动。initData 带 env=sim:**你的后端应据此区分测试流量**。
    open_id 是开发者账号自己的 —— 和任何真实用户都不同,云存储也就天然是独立的一份。"""
    await check_rate_limit("miniapp_sim", str(c.user.id), 60)
    app = await own_app(db, c, appid)
    v = await own_version(db, app, version_id)
    if not version_servable(v):
        raise HTTPException(409, "这个版本已被隔离或不可用")
    return await sim_payload(db, request, app, v, c.user, body)


async def sim_payload(db: AsyncSession, request: Request, app: MiniApp, v: MiniAppVersion,
                      user: User, body: LaunchIn) -> dict:
    """模拟器和管理后台审核预览共用。"""
    from .mini_apps import _theme_ok

    init_data = await sign_for(db, app, user, start_param=body.start_param, env="sim")
    url = hosted_base(request, app) + entry_path(v)
    superz = (v.manifest or {}).get("superz") or {}
    fragment = launch_fragment(init_data, platform=body.platform, theme=_theme_ok(body.theme),
                               start_param=body.start_param)
    dev = await db.get(Developer, app.developer_id) if app.developer_id else None
    return {
        "url": url + fragment, "init_data": init_data,
        "app": {**app_card(app, dev), "background_color": superz.get("background_color", "#F0EEE6"),
                "orientation": superz.get("orientation", "portrait"),
                "allowed_origins": [hosted_origin(request, app)],
                "capabilities": await capabilities_of(db, app), "bridge": 2},
        "version": version_dev(v, app), "trial": False, "env": "sim",
    }


@router.post("/apps/{appid}/sim/storage/{op}")
async def sim_storage(body: StorageIn, op: str = Path(pattern=r"^(get|set|remove|keys|usage)$"),
                      appid: str = AppId, c: Ctx = Depends(ctx),
                      db: AsyncSession = Depends(get_db)):
    app = await own_app(db, c, appid)
    try:
        await check_rate_limit("miniapp_kv", f"{app.id}:{c.user.id}", kv.RATE_PER_MINUTE)
    except HTTPException as exc:
        if exc.status_code == 429:
            raise bridge_error(429, 4005, "调用太频繁,请稍后再试") from exc
        raise
    return await run_storage(db, app.id, c.user.id, op, body)


@router.post("/apps/{appid}/sim/profile")
async def sim_profile(appid: str = AppId, c: Ctx = Depends(ctx),
                      db: AsyncSession = Depends(get_db)):
    """模拟器里的 requestProfile:应用得先申请到 profile 能力,和真机一样当场查。"""
    app = await own_app(db, c, appid)
    if "profile" not in await capabilities_of(db, app):
        raise bridge_error(403, 4001, "这个小程序没有申请到这项能力")
    return {"init_data": await sign_for(db, app, c.user, env="sim", with_profile=True)}
