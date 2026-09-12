"""版本的上传、送审、审核、发布、回滚、隔离(#322、#332)。

开发者后台(routers/dev_miniapps.py)、管理后台(routers/admin_miniapps.py)和
官方应用的发布脚本(scripts/publish_official_miniapp.py)**走的是这同一套函数** ——
官方应用不开后门(#337):同一个校验器、同一条审核记录、同一个状态机。

## 对象只写一次(I4)

每个版本的文件存在私有桶 `miniapps/<appid>/<version_id>/<path>`,原始 zip 存在
`miniapps/<appid>/<version_id>.zip`。version_id 是新行的主键(序列不回退),
写之前再查一次键是否存在 —— 存在就整笔失败,绝不覆盖。
审核员看的、用户打开的、详情页公示 SHA-256 的,是同一份字节。

## 展示信息随版本送审

上架后改名称、图标、描述、隐私政策,改动先放在 listing_draft,送审时连同代码一起
快照进版本,发布时才生效。审核员看得到展示信息的差异。
"""
import asyncio
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Developer, MiniApp, MiniAppVersion, User
from ..state_machine import TransitionError
from . import storage
from .miniapp_package import PackageReport, validate_package
from .miniapp_platform import capabilities_of, now, record_decision
from .miniapp_state import assert_transition

LISTING_FIELDS = ("name", "icon", "tagline", "description", "category", "screenshots",
                  "privacy_policy", "data_declaration")
UPLOADS_PER_HOUR = 30
#: 审核清单(结构化表单)。改清单要改版本号 —— 每条审核记录都写着它按哪一版清单审的
CHECKLIST_VERSION = 1
CHECKLIST = [
    {"key": "opens", "label": "能打开,核心功能可用(R101)"},
    {"key": "matches", "label": "与名称、描述、截图一致(R102)"},
    {"key": "complete", "label": "不是空壳、测试页、半成品(R103)"},
    {"key": "content", "label": "内容合法,无色情、赌博、诱导分享(R201–R206)"},
    {"key": "no_offsite_trade", "label": "不引导站外交易、不绕开平台规则(R207)"},
    {"key": "privacy", "label": "隐私政策与数据声明齐全且与实际一致(R301–R303)"},
    {"key": "game_rules", "label": "小游戏无内购、无广告(R402)"},
    {"key": "no_phishing", "label": "不仿冒平台界面(R501)"},
    {"key": "no_malware", "label": "无恶意代码、挖矿、刷量(R502)"},
    {"key": "domains", "label": "网络请求只去声明过的服务器域名(R503)"},
]


def object_key(appid: str, version_id: int, path: str) -> str:
    return f"miniapps/{appid}/{version_id}/{path}"


def package_key(appid: str, version_id: int) -> str:
    return f"miniapps/{appid}/{version_id}.zip"


def listing_of(app: MiniApp) -> dict:
    return {f: getattr(app, f) for f in LISTING_FIELDS}


def effective_listing(app: MiniApp) -> dict:
    """送审时用的展示信息:有待生效的改动用改动,没有就用当前的。"""
    return dict(app.listing_draft) if app.listing_draft else listing_of(app)


def apply_listing(app: MiniApp, listing: dict) -> None:
    for f in LISTING_FIELDS:
        if f in listing:
            setattr(app, f, listing[f])


def _transition(machine: str, current: str, target: str) -> None:
    try:
        assert_transition(machine, current, target)
    except TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc


# ---------------- 上传 ----------------

def _write_objects(appid: str, version_id: int, report: PackageReport, data: bytes) -> None:
    be = storage.backend()
    keys = [(object_key(appid, version_id, p), blob) for p, blob in report.blobs.items()]
    keys.append((package_key(appid, version_id), data))
    for key, _ in keys:
        if be.exists(key, private=True):
            # 走到这里说明主键序列被重置过,或者有人手工往桶里放了东西。
            # 哪一种都不该靠覆盖来「修」
            raise storage.StorageError(f"对象 {key} 已存在,拒绝覆盖")
    for key, blob in keys:
        be.put(blob, key, private=True)


async def create_version(db: AsyncSession, app: MiniApp, data: bytes, *, version: str,
                         changelog: str, actor: User | None,
                         check_rate: bool = True) -> tuple[MiniAppVersion | None, PackageReport]:
    """校验 → 建行 → 写对象。校验不过返回 (None, 报告),什么都不写。"""
    if app.hosting != "hosted":
        raise HTTPException(409, "外部地址的条目没有托管版本")
    if app.status == "removed":
        raise HTTPException(409, "应用已移除")
    if check_rate:
        recent = await db.scalar(select(func.count()).select_from(MiniAppVersion).where(
            MiniAppVersion.app_id == app.id,
            MiniAppVersion.created_at >= now() - timedelta(hours=1)))
        if recent >= UPLOADS_PER_HOUR:
            raise HTTPException(429, f"每个应用每小时最多上传 {UPLOADS_PER_HOUR} 次")
    report = await asyncio.to_thread(validate_package, data, kind=app.kind)
    if not report.ok:
        return None, report
    build = (await db.scalar(select(func.max(MiniAppVersion.build)).where(
        MiniAppVersion.app_id == app.id)) or 0) + 1
    v = MiniAppVersion(
        app_id=app.id, version=version.strip()[:32] or f"0.0.{build}", build=build,
        sha256=report.sha256, size=report.size, file_count=len(report.files),
        manifest={"superz": report.manifest, "files": report.files,
                  "warnings": report.warnings},
        changelog=changelog[:1000], status="uploaded",
        created_by=actor.id if actor else None)
    db.add(v)
    await db.flush()
    try:
        await asyncio.to_thread(_write_objects, app.appid, v.id, report, data)
    except storage.StorageError as exc:
        await db.rollback()
        raise HTTPException(503, f"存储暂时不可用({exc})") from exc
    v.package_key = package_key(app.appid, v.id)
    await db.commit()
    await db.refresh(v)
    return v, report


# ---------------- 体验版 ----------------

async def set_trial(db: AsyncSession, app: MiniApp, v: MiniAppVersion) -> None:
    if v.quarantined:
        raise HTTPException(409, "这个版本已被隔离")
    if app.trial_version_id and app.trial_version_id != v.id:
        old = await db.get(MiniAppVersion, app.trial_version_id)
        if old is not None and old.status == "trial":
            _transition("version", old.status, "uploaded")
            old.status = "uploaded"
    if v.status == "uploaded":
        _transition("version", v.status, "trial")
        v.status = "trial"
    elif v.status not in ("trial", "reviewing", "withdrawn", "approved", "released",
                          "superseded"):
        raise HTTPException(409, "这个版本不能设为体验版")
    app.trial_version_id = v.id
    await db.commit()


# ---------------- 送审 / 撤回 ----------------

def listing_problems(listing: dict, kind: str) -> list[str]:
    out = []
    if not (listing.get("name") or "").strip():
        out.append("缺名称")
    if not (listing.get("icon") or "").strip():
        out.append("缺图标")
    if not (listing.get("tagline") or "").strip():
        out.append("缺一句话介绍")
    if len((listing.get("description") or "").strip()) < 10:
        out.append("描述至少 10 个字")
    if len((listing.get("privacy_policy") or "").strip()) < 20:
        out.append("隐私政策至少 20 个字(不收集任何信息也要写明)")
    return out


async def submit(db: AsyncSession, app: MiniApp, v: MiniAppVersion, dev: Developer,
                 *, review_note: str, required_revision: int) -> None:
    if dev.status != "verified":
        raise HTTPException(403, "认证通过后才能提交审核")
    if required_revision and dev.agreement_version < required_revision:
        raise HTTPException(403, "开发者规则有更新,接受最新版本后才能提交审核")
    if app.status in ("suspended", "removed"):
        raise HTTPException(409, "应用被暂停或已移除,不能提交审核")
    if v.quarantined:
        raise HTTPException(409, "这个版本已被隔离")
    busy = await db.scalar(select(MiniAppVersion.id).where(
        MiniAppVersion.app_id == app.id, MiniAppVersion.status == "reviewing",
        MiniAppVersion.id != v.id))
    if busy:
        raise HTTPException(409, "已有一个版本在审核中,撤回它或等结论后再提交")
    listing = effective_listing(app)
    problems = listing_problems(listing, app.kind)
    if problems:
        raise HTTPException(422, "展示信息还不完整:" + "、".join(problems))
    _transition("version", v.status, "reviewing")
    v.status = "reviewing"
    v.submitted_at = now()
    v.review_note = review_note[:1000]
    v.manifest = {**(v.manifest or {}), "listing": listing,
                  "request_domains": list(app.request_domains or []),
                  "capabilities": await capabilities_of(db, app)}
    await record_decision(db, target_type="version", target_id=v.id, action="submit", app=app)
    await db.commit()


async def withdraw(db: AsyncSession, app: MiniApp, v: MiniAppVersion) -> None:
    _transition("version", v.status, "withdrawn")
    v.status = "withdrawn"
    await record_decision(db, target_type="version", target_id=v.id, action="withdraw", app=app)
    await db.commit()


# ---------------- 审核 ----------------

async def decide(db: AsyncSession, app: MiniApp, v: MiniAppVersion, reviewer: User, *,
                 approve: bool, reason_code: str, note_public: str, note_internal: str,
                 checklist: dict) -> None:
    target = "approved" if approve else "rejected"
    _transition("version", v.status, target)
    v.status = target
    v.reviewed_at = now()
    v.reviewed_by = reviewer.id
    if not approve:
        v.reject_code = reason_code
        v.reject_note = note_public[:500]
    v.manifest = {**(v.manifest or {}),
                  "checklist": {"version": CHECKLIST_VERSION, "items": checklist}}
    await record_decision(db, target_type="version", target_id=v.id,
                          action="approve" if approve else "reject", app=app,
                          reason_code="" if approve else reason_code,
                          note_public=note_public, note_internal=note_internal, actor=reviewer)
    await db.flush()
    if approve and app.auto_release and app.status in ("draft", "online", "offline"):
        await release(db, app, v, reviewer, commit=False, auto=True)
    await db.commit()


# ---------------- 发布 / 回滚 ----------------

async def release(db: AsyncSession, app: MiniApp, v: MiniAppVersion, actor: User | None, *,
                  commit: bool = True, auto: bool = False) -> None:
    if app.status not in ("draft", "online", "offline"):
        raise HTTPException(409, "应用被暂停或已移除,不能发布")
    if v.quarantined:
        raise HTTPException(409, "这个版本已被隔离")
    _transition("version", v.status, "released")
    ts = now()
    if app.current_version_id and app.current_version_id != v.id:
        old = await db.get(MiniAppVersion, app.current_version_id)
        if old is not None and old.status == "released":
            _transition("version", old.status, "superseded")
            old.status = "superseded"
    v.status = "released"
    v.released_at = ts
    app.current_version_id = v.id
    listing = (v.manifest or {}).get("listing")
    if listing:
        apply_listing(app, listing)
        if app.listing_draft and dict(app.listing_draft) == listing:
            app.listing_draft = None
    if app.status == "draft":
        _transition("app", app.status, "online")
        app.status = "online"
    if app.first_released_at is None:
        app.first_released_at = ts
    await record_decision(db, target_type="version", target_id=v.id,
                          action="auto_release" if auto else "release", app=app, actor=actor)
    if commit:
        await db.commit()


async def rollback(db: AsyncSession, app: MiniApp, target: MiniAppVersion,
                   actor: User | None) -> None:
    if target.id == app.current_version_id:
        raise HTTPException(409, "它已经是当前版本")
    if target.status != "superseded":
        raise HTTPException(409, "只能回滚到发布过的历史版本")
    if target.quarantined:
        raise HTTPException(409, "这个版本已被隔离,不能回滚过去")
    if app.status not in ("online", "offline"):
        raise HTTPException(409, "应用被暂停或已移除,不能回滚")
    cur = await db.get(MiniAppVersion, app.current_version_id) if app.current_version_id else None
    if cur is not None and cur.status == "released":
        _transition("version", cur.status, "superseded")
        cur.status = "superseded"
    _transition("version", target.status, "released")
    target.status = "released"
    app.current_version_id = target.id
    await record_decision(db, target_type="version", target_id=target.id, action="rollback",
                          app=app, actor=actor,
                          note_public=f"回滚到 {target.version}(build {target.build})")
    await db.commit()


# ---------------- 差异(审核队列用) ----------------

async def baseline_for(db: AsyncSession, app: MiniApp, v: MiniAppVersion) -> MiniAppVersion | None:
    """上一个审核通过过的版本(不含自己)。"""
    return await db.scalar(select(MiniAppVersion).where(
        MiniAppVersion.app_id == app.id, MiniAppVersion.id != v.id,
        MiniAppVersion.status.in_(("approved", "released", "superseded"))
    ).order_by(MiniAppVersion.id.desc()).limit(1))


def version_diff(base: MiniAppVersion | None, v: MiniAppVersion) -> dict:
    new = v.manifest or {}
    old = (base.manifest or {}) if base else {}
    nf, of = new.get("files", {}), old.get("files", {})
    files = {
        "added": sorted(set(nf) - set(of)),
        "removed": sorted(set(of) - set(nf)),
        "changed": sorted(p for p in set(nf) & set(of)
                          if nf[p].get("sha256") != of[p].get("sha256")),
    }

    def changed(a: dict, b: dict) -> dict:
        keys = sorted(set(a) | set(b))
        return {k: {"before": b.get(k), "after": a.get(k)} for k in keys if a.get(k) != b.get(k)}

    nd, od = set(new.get("request_domains", [])), set(old.get("request_domains", []))
    nc, oc = set(new.get("capabilities", [])), set(old.get("capabilities", []))
    return {
        "baseline": {"id": base.id, "version": base.version, "build": base.build}
        if base else None,
        "files": files,
        "superz": changed(new.get("superz", {}), old.get("superz", {})),
        "listing": changed(new.get("listing", {}), old.get("listing", {})),
        "domains": {"added": sorted(nd - od), "removed": sorted(od - nd)},
        "capabilities": {"added": sorted(nc - oc), "removed": sorted(oc - nc)},
    }
