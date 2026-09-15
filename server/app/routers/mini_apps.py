"""小程序:目录、详情、启动、云存储、授权与数据(#277 → DEV-PROMPTS-39 #321/#325/#326)。

小程序就是网页:目录告诉客户端「有哪些」,启动接口给出「版本化地址 + initData v2」,
initData 告诉小程序后端「这确实是超级赞 App 里的这个用户在这个应用里的 open_id」。
协议见 services/mini_app_v2.py 的 docstring(那就是第三方的对接文档)。

边界(不变量,DEV-PROMPTS-39 §3):
- I1 登录 token 永远不进 WebView:这里的接口都由**宿主原生侧**代页面调用;
- I2 应用只拿到 open_id,拿不到 user_id、手机号;
- I3 目录排序是 services/miniapp_catalog.py 里的纯函数,不读任何可以买的字段;
- I8 用户能看、导出、清空自己在每个小程序里的数据。

v1(`GET /mini-apps`、`POST /mini-apps/{id}/init-data`、`/mini-apps/admin*`)原样保留给老版本 App:
老 App 跑不了托管应用,v1 清单只回外部地址的条目(§8 最后一行)。
"""
import json
import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import (Developer, MiniApp, MiniAppDecision, MiniAppGrant, MiniAppKVUsage,
                      MiniAppReport, MiniAppUserPref, MiniAppVersion, User)
from ..ratelimit import check_rate_limit, client_ip
from ..schemas import MiniAppIn, MiniAppOut
from ..schemas_miniapp import LaunchIn, ReportIn, StorageIn
from ..security import get_current_user, get_current_user_optional, require_role
from ..services import miniapp_kv as kv
from ..services.mini_app import sign_init_data
from ..services.miniapp_catalog import CatalogItem, catalog_order, search
from ..services.miniapp_platform import (APPID_PATTERN, CATEGORIES, REASON_CODES,
                                         REPORT_REVIEW_THRESHOLD, REPORTS_PER_DAY,
                                         LAUNCH_PER_MINUTE, SWITCH_CATALOG, SWITCH_HOSTED,
                                         app_by_appid, app_card, capabilities_of, curated_ids,
                                         developer_of, entry_path, has_grant, hosted_base,
                                         hosted_origin, is_tester, launch_fragment, now,
                                         record_decision, record_open, sign_for, switch_on,
                                         today_bj, version_public, version_servable)
from ..services.miniapp_state import LABELS, assert_transition
from ..state_machine import TransitionError

logger = logging.getLogger("superz.miniapp")
router = APIRouter(prefix="/mini-apps", tags=["小程序"])

AppId = Path(pattern=APPID_PATTERN)
SORT_RULE = ("精选位在前(人工挑选,每次变动的理由在透明中心公示);其余按首次上架时间从新到旧 ——"
             "发新版本不会往前挪。搜索时按名称精确命中 > 前缀 > 包含 > 一句话介绍或开发者名。"
             "没有竞价、没有付费位置。")


def bridge_error(status: int, code: int, message: str) -> HTTPException:
    """桥错误码(§5.4)。detail 是 {code, message},宿主原样转给页面。"""
    return HTTPException(status, detail={"code": code, "message": message})


# =====================================================================
# v1(老版本 App)—— 行为不变
# =====================================================================

@router.get("", response_model=list[MiniAppOut])
async def list_mini_apps(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """老版本 App 的下拉面板数据源:只回**外部地址**且在线的条目。

    托管应用要容器 v2 才能跑,老 App 看见了也打不开 —— 那就别让它看见。
    空清单时客户端不呼出面板。
    """
    rows = await db.scalars(
        select(MiniApp).where(MiniApp.status == "online", MiniApp.hosting == "external")
        .order_by(MiniApp.sort, MiniApp.id))
    return rows.all()


@router.post("/{app_id}/init-data")
async def issue_init_data(
    app_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """v1 身份包(**已废弃**,新接入用 initData v2 —— POST /mini-apps/{appid}/launch)。

    时效分钟级(services/mini_app.py 的 MAX_AGE_SECONDS),页面要长会话
    自己换 —— 平台不给长期凭据,泄露面就只有这几分钟。
    """
    app = await db.get(MiniApp, app_id)
    if app is None or app.status != "online" or app.hosting != "external":
        raise HTTPException(404, "小程序不存在或已下架")
    return sign_init_data(app.id, user.id, user.name or "用户")


# =====================================================================
# 公开(免登录)
# =====================================================================

async def _cards(db: AsyncSession, apps: list[MiniApp]) -> list[dict]:
    dev_ids = {a.developer_id for a in apps if a.developer_id}
    devs = {}
    if dev_ids:
        devs = {d.id: d for d in (await db.execute(
            select(Developer).where(Developer.id.in_(dev_ids)))).scalars()}
    curated = await curated_ids(db)
    return [app_card(a, devs.get(a.developer_id), curated=a.id in curated) for a in apps]


async def _listable(db: AsyncSession, *, discovery: bool = False) -> list[MiniApp]:
    """能列出来的:在线,且托管应用的当前版本能出(没被隔离)。

    急停闸(miniapp_platform.SWITCHES):托管小程序关了,托管应用哪儿都不列;
    discovery=True(公开目录)时再看「小程序目录」闸 —— 关了只列官方的。
    用户自己的「最近使用」「我的小程序」不受目录闸影响。
    """
    apps = list((await db.execute(select(MiniApp).where(MiniApp.status == "online"))).scalars())
    if not await switch_on(db, SWITCH_HOSTED):
        apps = [a for a in apps if a.hosting != "hosted"]
    if discovery and not await switch_on(db, SWITCH_CATALOG):
        apps = [a for a in apps if a.is_official]
    vids = [a.current_version_id for a in apps if a.hosting == "hosted" and a.current_version_id]
    ok = set()
    if vids:
        for v in (await db.execute(select(MiniAppVersion).where(
                MiniAppVersion.id.in_(vids)))).scalars():
            if version_servable(v):
                ok.add(v.id)
    return [a for a in apps if a.hosting == "external" or a.current_version_id in ok]


@router.get("/catalog")
async def catalog(
    kind: str | None = Query(default=None, pattern=r"^(app|game)$"),
    category: str | None = Query(default=None, max_length=16),
    q: str = Query(default="", max_length=40),
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """公开目录。**不需要登录** —— 想用的人得先看得见有什么。

    排序是纯函数(services/miniapp_catalog.py),输入只有名称、首次上架时间、精选位置、
    一句话介绍和开发者名;打开次数、评分、付费这类字段根本不进这个函数(I3,有守卫测试)。
    """
    apps = await _listable(db, discovery=True)
    if kind:
        apps = [a for a in apps if a.kind == kind]
    if category:
        apps = [a for a in apps if a.category == category]
    cards = {c["appid"]: c for c in await _cards(db, apps)}
    curated = await curated_ids(db)
    items = [CatalogItem(appid=a.appid, name=a.name, first_released_at=a.first_released_at,
                         curation_position=curated.get(a.id), tagline=a.tagline or "",
                         developer_name=cards[a.appid]["developer"]["name"]) for a in apps]
    ordered = search(items, q) if q.strip() else catalog_order(items)
    page = ordered[cursor:cursor + limit]
    nxt = cursor + limit if cursor + limit < len(ordered) else None
    return {
        "items": [cards[i.appid] for i in page],
        "total": len(ordered),
        "next_cursor": nxt,
        "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()],
        "sort_rule": SORT_RULE,
    }


# =====================================================================
# 用户:我的小程序、授权与数据
# =====================================================================

@router.get("/me")
async def my_mini_apps(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """最近使用(≤ 8)+ 我的小程序(收藏)。多端同步 —— 存在服务端,不在手机上。"""
    rows = (await db.execute(
        select(MiniAppUserPref, MiniApp).join(MiniApp, MiniApp.id == MiniAppUserPref.app_id)
        .where(MiniAppUserPref.user_id == user.id))).all()
    listable = {a.id for a in await _listable(db)}
    rows = [(p, a) for p, a in rows if a.id in listable]
    recent = sorted((r for r in rows if r[0].last_opened_at), key=lambda r: r[0].last_opened_at,
                    reverse=True)[:8]
    starred = sorted((r for r in rows if r[0].starred), key=lambda r: (r[1].name, r[1].appid))
    recent_cards = await _cards(db, [a for _, a in recent])
    starred_cards = await _cards(db, [a for _, a in starred])
    for c, (p, _) in zip(recent_cards, recent):
        c["last_opened_at"] = p.last_opened_at.isoformat()
    return {"recent": recent_cards, "starred": starred_cards}


@router.get("/me/data")
async def my_mini_app_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """「设置 → 小程序授权与数据」:用过的每个小程序的授权、云存储用量、最近打开。"""
    app_ids = set()
    prefs = {p.app_id: p for p in (await db.execute(select(MiniAppUserPref).where(
        MiniAppUserPref.user_id == user.id))).scalars()}
    usage = {u.app_id: u for u in (await db.execute(select(MiniAppKVUsage).where(
        MiniAppKVUsage.user_id == user.id))).scalars()}
    grants: dict[int, list[str]] = {}
    for g in (await db.execute(select(MiniAppGrant).where(
            MiniAppGrant.user_id == user.id, MiniAppGrant.revoked_at.is_(None)))).scalars():
        grants.setdefault(g.app_id, []).append(g.scope)
    app_ids = set(prefs) | set(usage) | set(grants)
    if not app_ids:
        return {"items": []}
    apps = list((await db.execute(select(MiniApp).where(MiniApp.id.in_(app_ids)))).scalars())
    cards = await _cards(db, apps)
    out = []
    for a, c in zip(apps, cards):
        u = usage.get(a.id)
        p = prefs.get(a.id)
        out.append({**c, "status": a.status, "status_label": LABELS.get(a.status, a.status),
                    "grants": sorted(grants.get(a.id, [])),
                    "usage": {"keys": u.keys if u else 0, "bytes": u.bytes if u else 0,
                              "max_keys": kv.MAX_KEYS, "max_bytes": kv.MAX_TOTAL_BYTES},
                    "last_opened_at": p.last_opened_at.isoformat() if p and p.last_opened_at
                    else None})
    out.sort(key=lambda x: x["last_opened_at"] or "", reverse=True)
    return {"items": out}


# =====================================================================
# CSP 违规上报(托管页的 report-uri)
# =====================================================================

_HOST_RE = re.compile(r"^https?://(sz[0-9a-f]{16})\.")
_PATH_RE = re.compile(r"/_mini-host/(sz[0-9a-f]{16})/")


@router.post("/csp-report", include_in_schema=False)
async def csp_report(request: Request):
    """浏览器发来的 CSP 违规报告。**不落库,不记请求体原文**:只记是哪个应用、
    哪条指令、被拦的是哪个 origin(去掉路径和参数)。开发者在模拟器里看实时的那份。"""
    try:
        await check_rate_limit("miniapp_csp", client_ip(request), 60)
    except HTTPException:
        return Response(status_code=204)
    raw = await request.body()
    if len(raw) > 16 * 1024:
        return Response(status_code=204)
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return Response(status_code=204)
    reports = body if isinstance(body, list) else [body]
    for rep in reports[:10]:
        if not isinstance(rep, dict):
            continue
        r = rep.get("csp-report") or rep.get("body") or {}
        if not isinstance(r, dict):
            continue
        doc = str(r.get("document-uri") or r.get("documentURL") or "")
        m = _HOST_RE.match(doc) or _PATH_RE.search(doc)
        blocked = str(r.get("blocked-uri") or r.get("blockedURL") or "")
        blocked_origin = re.sub(r"^(\w+://[^/?#]+).*$", r"\1", blocked)[:120]
        directive = str(r.get("violated-directive") or r.get("effectiveDirective") or "")[:60]
        logger.info("CSP 拦截 app=%s directive=%s blocked=%s",
                    m.group(1) if m else "?", directive, blocked_origin)
        if m:
            try:
                from ..redis_client import get_redis
                # 按北京时间的日期记:开发者后台的数据页按北京时间的天读(dev_miniapps.stats)
                key = f"miniapp:csp:{m.group(1)}:{today_bj().strftime('%Y%m%d')}"
                r2 = get_redis()
                await r2.incr(key)
                await r2.expire(key, 40 * 86400)
            except Exception:  # 计数失败不影响任何事
                pass
    return Response(status_code=204)


# =====================================================================
# v1 管理(admin.html 面板以后再挂,先保证 curl 能管)
# 新的管理接口在 /admin/mini-apps(routers/admin_miniapps.py)
# =====================================================================

async def _official_developer_id(db: AsyncSession) -> int | None:
    return await db.scalar(select(Developer.id).where(Developer.is_official.is_(True))
                           .order_by(Developer.id).limit(1))


@router.get("/admin", response_model=list[MiniAppOut])
async def admin_list(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """管理侧看外部地址的条目全量(含下架),仍复用 MiniAppOut。"""
    rows = await db.scalars(select(MiniApp).where(MiniApp.hosting == "external")
                            .order_by(MiniApp.sort, MiniApp.id))
    return rows.all()


@router.post("/admin", response_model=MiniAppOut)
async def admin_create(
    body: MiniAppIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """新建一条**官方的外部地址条目**。第三方应用只能走开发者后台 + 托管(D3)。"""
    from ..services.mini_app_v2 import new_appid
    from ..services.miniapp_platform import issue_secret

    app = MiniApp(**body.model_dump(), appid=new_appid(), hosting="external",
                  developer_id=await _official_developer_id(db), is_official=True,
                  status="online", first_released_at=now())
    issue_secret(app)
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


@router.put("/admin/{app_id}", response_model=MiniAppOut)
async def admin_update(
    app_id: int,
    body: MiniAppIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    app = await db.get(MiniApp, app_id)
    if app is None or app.hosting != "external":
        raise HTTPException(404, "小程序不存在")
    for k, v in body.model_dump().items():
        setattr(app, k, v)
    await db.commit()
    await db.refresh(app)
    return app


@router.post("/admin/{app_id}/toggle")
async def admin_toggle(
    app_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """上架 ⇄ 下架。返回值保持 v1 的 on/off(老脚本按它判断)。"""
    app = await db.get(MiniApp, app_id)
    if app is None or app.hosting != "external":
        raise HTTPException(404, "小程序不存在")
    target = "offline" if app.status == "online" else "online"
    try:
        assert_transition("app", app.status, target)
    except TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    app.status = target
    await record_decision(db, target_type="app", target_id=app.id,
                          action="online" if target == "online" else "offline",
                          app=app, actor=admin, note_public="官方条目上下架")
    await db.commit()
    return {"id": app.id, "status": "on" if app.status == "online" else "off"}


# =====================================================================
# 单个应用(路径参数是 appid;上面的固定路径要先声明)
# =====================================================================

@router.get("/{appid}")
async def detail(
    appid: str = AppId,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """详情。**不需要登录**。当前版本的 SHA-256 公示在这里 —— 任何人都能拿开源仓的构建产物来对。"""
    app = await app_by_appid(db, appid)
    tester = bool(user) and await is_tester(db, app, user)
    if app.status == "draft" and not tester:
        raise HTTPException(404, "小程序不存在")
    dev = await developer_of(db, app)
    curated = await curated_ids(db)
    card = app_card(app, dev, curated=app.id in curated)
    cur = await db.get(MiniAppVersion, app.current_version_id) if app.current_version_id else None
    available = app.status == "online" and (app.hosting == "external" or (
        version_servable(cur) and await switch_on(db, SWITCH_HOSTED)))
    me = None
    if user:
        pref = await db.get(MiniAppUserPref, (user.id, app.id))
        me = {"starred": bool(pref and pref.starred), "tester": tester,
              "profile_granted": await has_grant(db, user.id, app.id, "profile")}
    return {
        **card,
        "status": app.status, "status_label": LABELS.get(app.status, app.status),
        "available": available,
        "description": app.description, "screenshots": app.screenshots or [],
        "privacy_policy": app.privacy_policy, "data_declaration": app.data_declaration or [],
        "capabilities": await capabilities_of(db, app),
        "request_domains": app.request_domains or [],
        "version": version_public(cur) if app.hosting == "hosted" else None,
        "entry_url": app.entry_url if app.hosting == "external" else None,
        "link": f"{settings.public_base_url.rstrip('/')}/m/{app.appid}",
        "me": me,
    }


@router.get("/{appid}/status")
async def status(
    appid: str = AppId,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """宿主每分钟、以及回到前台时查一次:应用被暂停或当前版本被隔离时,宿主关掉它(§5.4 的 4009)。"""
    app = await app_by_appid(db, appid)
    cur = await db.get(MiniAppVersion, app.current_version_id) if app.current_version_id else None
    blocked = app.status in ("suspended", "removed") or bool(cur and cur.quarantined) or (
        app.hosting == "hosted" and not await switch_on(db, SWITCH_HOSTED))
    return {"status": app.status, "blocked": blocked,
            "current_version_id": app.current_version_id}


#: 宿主下发的主题色键数上限。现在是 16 个(Telegram 的 15 个 + line_color);
#: 留出余量 —— 撞上限的后果是启动 422、小程序整个打不开,不能卡在正好够用
MAX_THEME_KEYS = 32


def _theme_ok(theme: dict | None) -> dict | None:
    if not theme:
        return None
    if len(theme) > MAX_THEME_KEYS:
        raise HTTPException(422, "主题参数太多")
    out = {}
    for k, v in theme.items():
        if not re.match(r"^[a-z_]{1,32}$", str(k)) or not re.match(r"^#[0-9A-Fa-f]{6}$", str(v)):
            raise HTTPException(422, "主题参数只能是 键名: #RRGGBB")
        out[k] = v
    return out


@router.post("/{appid}/launch")
async def launch(
    body: LaunchIn,
    request: Request,
    appid: str = AppId,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """启动:校验 → 取或建 open_id → 签 initData v2 → 返回版本化地址 + 能力清单(§6 启动时序)。

    返回的 url 已经带好启动片段(§5.2):片段不进 HTTP 请求、不进 Referer。
    """
    await check_rate_limit("miniapp_launch", str(user.id), LAUNCH_PER_MINUTE)
    app = await app_by_appid(db, appid)
    theme = _theme_ok(body.theme)
    if app.hosting == "hosted" and not await switch_on(db, SWITCH_HOSTED):
        # 急停闸拉下来了(见 miniapp_platform.SWITCHES):体验版也不开
        raise bridge_error(503, 4009, "平台暂停了托管小程序,稍后再试")
    v = None
    if body.trial:
        if not await is_tester(db, app, user):
            raise HTTPException(403, "你不是这个小程序的体验者")
        if app.status in ("suspended", "removed"):
            raise bridge_error(423, 4009, "该小程序已被暂停")
        v = await db.get(MiniAppVersion, app.trial_version_id) if app.trial_version_id else None
        if not version_servable(v):
            raise HTTPException(404, "还没有可用的体验版")
    else:
        if app.status == "suspended":
            raise bridge_error(423, 4009, "该小程序已被暂停")
        if app.status != "online":
            raise HTTPException(404, "小程序不存在或已下架")
        if app.hosting == "hosted":
            v = await db.get(MiniAppVersion, app.current_version_id) \
                if app.current_version_id else None
            if not version_servable(v):
                raise bridge_error(423, 4009, "该小程序暂时无法打开")
    if app.hosting == "hosted":
        url = hosted_base(request, app) + entry_path(v)
        origins = [hosted_origin(request, app)]
    else:
        url = app.entry_url
        origins = list(app.allowed_origins or [])
        if not app.secret_enc:
            # 存量外部条目回填时没有密钥;首次启动补一把(只有平台知道,开发者要用就去后台重置)
            from ..services.miniapp_platform import issue_secret
            issue_secret(app)
            await db.commit()
    init_data = await sign_for(db, app, user, start_param=body.start_param)
    fragment = launch_fragment(init_data, platform=body.platform, theme=theme,
                               start_param=body.start_param)
    if not body.trial:
        await record_open(db, app, user)
    dev = await developer_of(db, app)
    curated = await curated_ids(db)
    superz = ((v.manifest or {}).get("superz") or {}) if v else {}
    return {
        "url": url + fragment,
        "init_data": init_data,
        "app": {
            **app_card(app, dev, curated=app.id in curated),
            "background_color": superz.get("background_color", "#F0EEE6"),
            "orientation": superz.get("orientation", "portrait"),
            "allowed_origins": origins,
            "capabilities": await capabilities_of(db, app),
            "bridge": 2 if app.hosting == "hosted" else 1,
        },
        "version": version_public(v),
        "trial": body.trial,
    }


async def _pref(db: AsyncSession, user: User, app: MiniApp, starred: bool) -> None:
    await db.execute(insert(MiniAppUserPref).values(
        user_id=user.id, app_id=app.id, starred=starred, open_count=0
    ).on_conflict_do_update(index_elements=["user_id", "app_id"], set_={"starred": starred}))
    await db.commit()


@router.post("/{appid}/star")
async def star(appid: str = AppId, user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    app = await app_by_appid(db, appid)
    if app.status != "online":
        raise HTTPException(404, "小程序不存在或已下架")
    await _pref(db, user, app, True)
    return {"starred": True}


@router.delete("/{appid}/star")
async def unstar(appid: str = AppId, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    app = await app_by_appid(db, appid)
    await _pref(db, user, app, False)
    return {"starred": False}


@router.post("/{appid}/report")
async def report(
    body: ReportIn,
    appid: str = AppId,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """投诉。举报人身份永不公开、不给开发者;7 天内 5 个不同的人举报同一个应用,自动进复审。"""
    app = await app_by_appid(db, appid)
    if app.status == "draft":
        raise HTTPException(404, "小程序不存在")
    if body.reason_code not in REASON_CODES:
        raise HTTPException(422, "原因代码不存在")
    if body.reason_code == "R701" and len(body.detail.strip()) < 5:
        raise HTTPException(422, "选「其他」要写明具体情况")
    for key in body.evidence_keys:
        if not re.match(rf"^/files/miniapp_report/u{user.id}-[0-9a-f]{{32}}\.(jpg|jpeg|png|webp)$",
                        key):
            raise HTTPException(422, "截图要先用 /upload(purpose=miniapp_report)上传")
    since = now() - timedelta(days=1)
    today = await db.scalar(select(func.count()).select_from(MiniAppReport).where(
        MiniAppReport.reporter_user_id == user.id, MiniAppReport.created_at >= since))
    if today >= REPORTS_PER_DAY:
        raise HTTPException(429, f"每天最多投诉 {REPORTS_PER_DAY} 次")
    r = MiniAppReport(app_id=app.id, reporter_user_id=user.id, reason_code=body.reason_code,
                      detail=body.detail.strip(), evidence_keys=body.evidence_keys)
    db.add(r)
    await db.flush()
    week = now() - timedelta(days=7)
    reporters = await db.scalar(select(func.count(func.distinct(MiniAppReport.reporter_user_id)))
                                .where(MiniAppReport.app_id == app.id,
                                       MiniAppReport.status == "open",
                                       MiniAppReport.created_at >= week))
    flagged = await db.scalar(select(MiniAppDecision.id).where(
        MiniAppDecision.app_id == app.id, MiniAppDecision.action == "flag_review",
        MiniAppDecision.created_at >= week))
    if reporters >= REPORT_REVIEW_THRESHOLD and not flagged:
        await record_decision(db, target_type="app", target_id=app.id, action="flag_review",
                              app=app, note_public=f"7 天内 {reporters} 人投诉,进入复审")
    await db.commit()
    return {"id": r.id, "status": "open"}


# ---------------- 授权 ----------------

async def _grant(db: AsyncSession, user: User, app: MiniApp, scope: str) -> None:
    if scope not in await capabilities_of(db, app):
        raise bridge_error(403, 4001, "这个小程序没有申请到这项能力")
    await db.execute(insert(MiniAppGrant).values(
        user_id=user.id, app_id=app.id, scope=scope, granted_at=now(), revoked_at=None
    ).on_conflict_do_update(constraint="uq_miniapp_grant",
                            set_={"revoked_at": None, "granted_at": now()}))
    await db.commit()


@router.post("/{appid}/grants")
async def grant(
    body: dict,
    appid: str = AppId,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = str(body.get("scope") or "")
    if scope != "profile":
        raise HTTPException(422, "目前只有 profile(昵称和头像)需要授权")
    app = await app_by_appid(db, appid)
    await _grant(db, user, app, scope)
    return {"scope": scope, "granted": True}


@router.delete("/{appid}/grants/{scope}")
async def revoke(
    scope: str,
    appid: str = AppId,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_by_appid(db, appid)
    await db.execute(update(MiniAppGrant).where(
        MiniAppGrant.user_id == user.id, MiniAppGrant.app_id == app.id,
        MiniAppGrant.scope == scope, MiniAppGrant.revoked_at.is_(None)
    ).values(revoked_at=now()))
    await db.commit()
    return {"scope": scope, "granted": False}


@router.post("/{appid}/profile")
async def request_profile(
    appid: str = AppId,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户在宿主的授权弹窗里点了「允许」之后,宿主调这里:记授权 + **当场签一份新的 initData**。

    页面自己报上来的昵称不可信;开发者后端照常验签,拿到的昵称才算数。
    """
    app = await app_by_appid(db, appid)
    if app.status in ("suspended", "removed"):
        raise bridge_error(423, 4009, "该小程序已被暂停")
    await _grant(db, user, app, "profile")
    init_data = await sign_for(db, app, user, with_profile=True)
    return {"init_data": init_data}


# ---------------- 数据:看、导出、清空(I8) ----------------

@router.get("/{appid}/data")
async def my_data(
    appid: str = AppId,
    export: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_by_appid(db, appid)
    grants = list((await db.execute(select(MiniAppGrant.scope).where(
        MiniAppGrant.user_id == user.id, MiniAppGrant.app_id == app.id,
        MiniAppGrant.revoked_at.is_(None)))).scalars())
    out = {"appid": app.appid, "name": app.name, "usage": await kv.usage(db, app.id, user.id),
           "grants": sorted(grants)}
    if export:
        out["items"] = await kv.export(db, app.id, user.id)
        out["exported_at"] = now().isoformat()
    return out


@router.delete("/{appid}/data")
async def clear_my_data(
    appid: str = AppId,
    scope: str = Query(default="storage", pattern=r"^(storage|all)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """storage:清空云存储;all:再加撤回全部授权、从最近使用和我的小程序里移除。"""
    app = await app_by_appid(db, appid)
    removed = await kv.clear(db, app.id, user.id)
    if scope == "all":
        await db.execute(update(MiniAppGrant).where(
            MiniAppGrant.user_id == user.id, MiniAppGrant.app_id == app.id,
            MiniAppGrant.revoked_at.is_(None)).values(revoked_at=now()))
        await db.execute(delete(MiniAppUserPref).where(
            MiniAppUserPref.user_id == user.id, MiniAppUserPref.app_id == app.id))
        await db.commit()
    return {"removed_keys": removed, "scope": scope}


# ---------------- 云存储(宿主代页面调用,§5.5) ----------------

async def _storage_gate(db: AsyncSession, app: MiniApp, user: User) -> None:
    if app.status in ("suspended", "removed"):
        raise bridge_error(423, 4009, "该小程序已被暂停")
    if app.current_version_id:
        cur = await db.get(MiniAppVersion, app.current_version_id)
        if cur is not None and cur.quarantined:
            raise bridge_error(423, 4009, "该小程序已被暂停")
    if app.status != "online" and not await is_tester(db, app, user):
        raise bridge_error(404, 4001, "小程序不存在或已下架")


_KV_STATUS = {4004: 422, 4006: 413, 4007: 409}


@router.post("/{appid}/storage/{op}")
async def storage_op(
    body: StorageIn,
    op: str = Path(pattern=r"^(get|set|remove|keys|usage)$"),
    appid: str = AppId,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await app_by_appid(db, appid)
    await _storage_gate(db, app, user)
    try:
        await check_rate_limit("miniapp_kv", f"{app.id}:{user.id}", kv.RATE_PER_MINUTE)
    except HTTPException as exc:
        if exc.status_code == 429:
            raise bridge_error(429, 4005, "调用太频繁,请稍后再试") from exc
        raise
    return await run_storage(db, app.id, user.id, op, body)


async def run_storage(db: AsyncSession, app_id: int, user_id: int, op: str,
                      body: StorageIn) -> dict:
    """云存储的五个操作。模拟器(dev_miniapps)也走这里,只是 user_id 是开发者自己。"""
    try:
        if op == "get":
            return {"items": await kv.get_items(db, app_id, user_id, body.keys)}
        if op == "set":
            if body.key is None or body.value is None:
                raise kv.KVError(4004, "set 要 key 和 value")
            return await kv.set_item(db, app_id, user_id, body.key, body.value, body.if_rev)
        if op == "remove":
            return await kv.remove_items(db, app_id, user_id, body.keys)
        if op == "keys":
            return await kv.get_keys(db, app_id, user_id, prefix=body.prefix,
                                     cursor=body.cursor, limit=body.limit)
        return await kv.usage(db, app_id, user_id)
    except kv.KVError as exc:
        await db.rollback()
        raise bridge_error(_KV_STATUS.get(exc.code, 422), exc.code, exc.message) from exc
