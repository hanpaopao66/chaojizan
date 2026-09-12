"""小程序开放平台的公共件:查应用、体验者、启动地址、审核记录、序列化(DEV-PROMPTS-39)。

各路由(mini_apps / mini_host / dev_miniapps / admin_miniapps)共用这里,不各写一份 ——
「这个版本能不能出」「这个人是不是体验者」这类判断写两份迟早分叉。
"""
import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlencode, urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import (Developer, MiniApp, MiniAppCapability, MiniAppCuration,
                      MiniAppDailyUser, MiniAppDecision, MiniAppGrant, MiniAppOpenId,
                      MiniAppTester, MiniAppUsageDaily, MiniAppUserPref, MiniAppVersion,
                      PlatformFlag, User)
from . import mini_app_v2 as v2
from .crypto import decrypt, encrypt, pseudonym
from .miniapp_state import SERVABLE_VERSION_STATES

logger = logging.getLogger("superz.miniapp")

APPID_PATTERN = r"^sz[0-9a-f]{16}$"
CATEGORIES = {
    "tools": "工具", "productivity": "效率", "life": "生活", "learning": "学习",
    "casual": "休闲益智", "puzzle": "益智解谜",
}
#: 所有应用都有的能力(不用申请)
BASIC_CAPABILITIES = ("initData", "storage", "share", "haptics", "popup", "openLink")
#: 只给小游戏
GAME_CAPABILITIES = ("fullscreen", "orientation")
#: 要申请 + 审核的能力。M2 只开 profile;其余是 M3,申请接口回「暂未开放」
REQUESTABLE_CAPABILITIES = {"profile": "昵称和头像"}
FUTURE_CAPABILITIES = {"location": "定位", "scanQr": "扫码", "clipboard": "读取剪贴板",
                       "phone": "手机号"}

#: 急停闸(PlatformFlag,管理后台「平台开关」页改;改动带原因进透明中心的治理时间线,#337)。
#: **缺省是开**,写成 off 才关 —— 这些是出了问题先拉下来的闸,不是逐步放量的开关:
#: - 托管小程序:关了托管应用一律打不开(启动回 4009、已开着的下一次轮询就关)、托管文件 404、
#:   从目录和「最近使用」里消失;外部地址条目(透明中心、公开账本)不受影响;
#: - 小程序目录:关了目录只列官方小程序,第三方应用只能从直达链接和自己的「最近使用」进;
#: - 昵称头像:关了 profile 能力对所有应用收回,requestProfile 一律 4001。
SWITCH_HOSTED = "miniapp_hosted"
SWITCH_CATALOG = "miniapp_catalog"
SWITCH_PROFILE = "miniapp_profile"
SWITCHES = (SWITCH_HOSTED, SWITCH_CATALOG, SWITCH_PROFILE)
REASON_CODES = {
    "R101": "打不开或核心功能不可用", "R102": "与名称、描述、截图不符", "R103": "空壳、测试页、半成品",
    "R201": "违法违规内容", "R202": "色情低俗", "R203": "赌博、彩票、博彩",
    "R204": "诱导分享、诱导关注、诱导下载", "R205": "虚假宣传、夸大功效", "R206": "侵害未成年人权益",
    "R207": "引导站外交易、绕开平台规则", "R301": "隐私政策缺失或与实际不符",
    "R302": "超出声明范围收集信息", "R303": "未经同意获取敏感信息", "R401": "缺少类目要求的资质",
    "R402": "游戏缺少版号、含内购或广告", "R501": "仿冒平台界面、钓鱼", "R502": "恶意代码、挖矿、刷量",
    "R503": "请求了未声明的服务器域名", "R601": "商标、著作权侵权", "R701": "其他",
}
USERS_DISPLAY_FLOOR = 10

# ---- 配额与限流(§5.10,公开写进开发者规则;规则页直接读这些常量)----
MAX_APPS = {"individual": 5, "company": 50}
MAX_TESTERS = 20
LAUNCH_PER_MINUTE = 30
REPORTS_PER_DAY = 10
DOMAIN_CHANGES_PER_MONTH = 50
APPEAL_WINDOW_DAYS = 7
#: 7 天内有这么多个不同的人举报同一个应用,自动进复审队列
REPORT_REVIEW_THRESHOLD = 5
#: 应用移除后用户数据保留多少天供导出
REMOVED_DATA_RETENTION_DAYS = 30
#: 日活明细保留天数(只为算 users,之后删)
DAILY_USERS_RETENTION_DAYS = 35
#: 结论里哪些可以申诉(不利于开发者的那些)
APPEALABLE_ACTIONS = {"reject", "suspend", "remove", "quarantine", "capability_reject",
                      "developer_reject", "developer_suspend"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def today_bj() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


# ---------------- 查询 ----------------

async def app_by_appid(db: AsyncSession, appid: str, *, for_update: bool = False) -> MiniApp:
    stmt = select(MiniApp).where(MiniApp.appid == appid)
    if for_update:
        stmt = stmt.with_for_update()
    app = (await db.execute(stmt)).scalar_one_or_none()
    if app is None:
        raise HTTPException(404, "小程序不存在")
    return app


async def developer_of(db: AsyncSession, app: MiniApp) -> Developer | None:
    return await db.get(Developer, app.developer_id) if app.developer_id else None


async def is_tester(db: AsyncSession, app: MiniApp, user: User) -> bool:
    key = pseudonym(user.phone, "miniapp-tester")
    return bool(await db.scalar(select(MiniAppTester.id).where(
        MiniAppTester.app_id == app.id, MiniAppTester.phone_pseudonym == key)))


def tester_key(phone: str) -> str:
    return pseudonym(phone, "miniapp-tester")


async def switch_on(db: AsyncSession, key: str) -> bool:
    """急停闸开着没有(见 SWITCHES)。没写过 = 开。每次现查,不缓存 —— 拉闸要立刻生效。"""
    flag = await db.get(PlatformFlag, key)
    return flag is None or flag.value != "off"


async def capabilities_of(db: AsyncSession, app: MiniApp) -> list[str]:
    caps = list(BASIC_CAPABILITIES)
    if app.kind == "game":
        caps += list(GAME_CAPABILITIES)
    granted = list((await db.execute(select(MiniAppCapability.capability).where(
        MiniAppCapability.app_id == app.id, MiniAppCapability.status == "approved"))).scalars())
    if "profile" in granted and not await switch_on(db, SWITCH_PROFILE):
        granted.remove("profile")
    caps += granted
    return caps


# ---------------- AppSecret ----------------

def issue_secret(app: MiniApp) -> str:
    secret = v2.new_app_secret()
    app.secret_enc = encrypt(secret)
    app.secret_rotated_at = now()
    return secret


def app_secret(app: MiniApp) -> str:
    secret = decrypt(app.secret_enc) if app.secret_enc else ""
    if not secret:
        raise HTTPException(503, "这个小程序的密钥读不出来,请开发者在后台重置密钥")
    return secret


# ---------------- 托管地址 ----------------

_host_domain_warned = False


def host_domain() -> str:
    """实际生效的托管域名(D1),没有就是空串。

    可以用主站域名下专门的一级,比如 `mp.chaojizan.cc`(应用在 `<appid>.mp.chaojizan.cc`,
    和主站、和别的应用都不同源)。**不能是主站域名本身,也不能是主站的上级域名**:那样主站和它的
    其他子域名(www 之类)的请求全会被当成托管请求,整站 404。配成那样时按没配处理
    (托管小程序打不开,主站照常),记一条错误日志。
    """
    global _host_domain_warned
    domain = settings.mini_app_host_domain.strip().lower().strip(".")
    if not domain:
        return ""
    main = (urlsplit(settings.public_base_url).hostname or "").lower()
    if main and (main == domain or main.endswith("." + domain)):
        if not _host_domain_warned:
            _host_domain_warned = True
            logger.error("MINI_APP_HOST_DOMAIN=%s 是主站 %s 本身或它的上级域名,已忽略;"
                         "要用主站的域名就配一个专门的下级,比如 mp.%s", domain, main, main)
        return ""
    return domain


def hosted_origin(request: Request, app: MiniApp) -> str:
    """托管页的 origin。生产:https://<appid>.<托管域名>;开发:API 自己的 origin(同源,仅联调)。"""
    domain = host_domain()
    if domain:
        return f"https://{app.appid}.{domain}"
    if not settings.is_dev:
        raise HTTPException(503, "托管域名还没配置,托管小程序暂不能打开")
    base = str(request.base_url).rstrip("/")
    return base


def hosted_base(request: Request, app: MiniApp) -> str:
    """托管文件的 URL 前缀(到 appid 这一级,后面接 /v/<version_id>/…)。"""
    origin = hosted_origin(request, app)
    if host_domain():
        return origin
    return f"{origin}/_mini-host/{app.appid}"


def frame_ancestors() -> list[str]:
    if settings.is_dev and not host_domain():
        return ["*"]  # 本地联调:web 版宿主、模拟器在各种 localhost 端口上
    out = [_origin(settings.public_base_url)]
    for o in settings.mini_app_frame_ancestors.split(","):
        if o.strip():
            out.append(_origin(o.strip()))
    return [o for o in dict.fromkeys(out) if o]


def _origin(url: str) -> str:
    p = urlsplit(url.strip())
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


def entry_path(version: MiniAppVersion) -> str:
    return f"/v/{version.id}/index.html"


def launch_fragment(init_data: str, *, platform: str, theme: dict | None,
                    start_param: str | None) -> str:
    params = [("szWebAppData", init_data), ("szWebAppVersion", "2.0"),
              ("szWebAppPlatform", platform or "unknown")]
    if theme:
        import json
        params.append(("szWebAppThemeParams", json.dumps(theme, separators=(",", ":"),
                                                          ensure_ascii=False)))
    if start_param:
        params.append(("szWebAppStartParam", start_param))
    return "#" + urlencode(params, quote_via=quote)


def version_servable(v: MiniAppVersion | None) -> bool:
    return bool(v) and not v.quarantined and v.status in SERVABLE_VERSION_STATES


# ---------------- 身份 ----------------

async def open_id_for(db: AsyncSession, user_id: int, app: MiniApp) -> str:
    row = await db.get(MiniAppOpenId, (user_id, app.id))
    if row:
        return row.open_id
    oid = v2.new_open_id()
    await db.execute(insert(MiniAppOpenId).values(
        user_id=user_id, app_id=app.id, open_id=oid).on_conflict_do_nothing())
    await db.commit()
    row = await db.get(MiniAppOpenId, (user_id, app.id))
    return row.open_id


async def has_grant(db: AsyncSession, user_id: int, app_id: int, scope: str) -> bool:
    return bool(await db.scalar(select(MiniAppGrant.id).where(
        MiniAppGrant.user_id == user_id, MiniAppGrant.app_id == app_id,
        MiniAppGrant.scope == scope, MiniAppGrant.revoked_at.is_(None))))


def masked_name(user: User) -> str:
    name = (user.name or "").strip()
    return name[:16] if name else "超级赞用户"


async def sign_for(db: AsyncSession, app: MiniApp, user: User, *, start_param: str | None = None,
                   env: str | None = None, with_profile: bool | None = None) -> str:
    open_id = await open_id_for(db, user.id, app)
    payload = {"open_id": open_id, "language_code": "zh-CN"}
    if with_profile is None:
        with_profile = await has_grant(db, user.id, app.id, "profile")
    if with_profile:
        payload["nickname"] = masked_name(user)
        if getattr(user, "avatar_url", None):
            payload["avatar_url"] = user.avatar_url
    try:
        return v2.build_init_data(app_id=app.appid, app_secret=app_secret(app), user=payload,
                                  start_param=start_param, env=env)
    except RuntimeError as exc:
        logger.error("initData 签发失败:%s", exc)
        raise HTTPException(503, str(exc)) from exc


# ---------------- 用量 ----------------

async def record_open(db: AsyncSession, app: MiniApp, user: User) -> None:
    ts = now()
    day = today_bj()
    await db.execute(insert(MiniAppUserPref).values(
        user_id=user.id, app_id=app.id, starred=False, last_opened_at=ts, open_count=1
    ).on_conflict_do_update(index_elements=["user_id", "app_id"], set_={
        "last_opened_at": ts, "open_count": MiniAppUserPref.open_count + 1}))
    res = await db.execute(insert(MiniAppDailyUser).values(
        app_id=app.id, day=day, user_id=user.id).on_conflict_do_nothing())
    new_user = res.rowcount == 1
    await db.execute(insert(MiniAppUsageDaily).values(
        app_id=app.id, day=day, opens=1, users=1 if new_user else 0
    ).on_conflict_do_update(index_elements=["app_id", "day"], set_={
        "opens": MiniAppUsageDaily.opens + 1,
        "users": MiniAppUsageDaily.users + (1 if new_user else 0)}))
    await db.commit()


# ---------------- 审核记录 ----------------

async def record_decision(db: AsyncSession, *, target_type: str, target_id: int, action: str,
                          app: MiniApp | None = None, developer_id: int | None = None,
                          reason_code: str = "", note_public: str = "", note_internal: str = "",
                          actor: User | None = None, appeal_of: int | None = None,
                          commit: bool = False) -> MiniAppDecision:
    d = MiniAppDecision(
        target_type=target_type, target_id=target_id, action=action,
        app_id=app.id if app else None,
        developer_id=developer_id if developer_id is not None else (app.developer_id if app else None),
        reason_code=reason_code, note_public=note_public[:500], note_internal=note_internal[:500],
        actor_id=actor.id if actor else None, appeal_of=appeal_of)
    db.add(d)
    if commit:
        await db.commit()
    return d


# ---------------- 序列化 ----------------

def developer_card(dev: Developer | None) -> dict:
    if dev is None:
        return {"name": "", "kind": "", "verified": False, "official": False}
    if dev.kind == "company":
        name = dev.company_name or dev.display_name
    else:
        name = dev.display_name or "个人开发者"
    return {"name": name, "kind": dev.kind, "verified": dev.status == "verified",
            "official": dev.is_official,
            "label": "官方" if dev.is_official else (
                "企业 · 已认证" if dev.kind == "company" and dev.status == "verified"
                else "个人开发者 · 已实名" if dev.status == "verified" else "未认证")}


def app_card(app: MiniApp, dev: Developer | None, *, curated: bool = False) -> dict:
    return {
        "appid": app.appid, "id": app.id, "name": app.name, "icon": app.icon,
        "tagline": app.tagline, "kind": app.kind, "category": app.category,
        "category_label": CATEGORIES.get(app.category, app.category),
        "hosting": app.hosting, "is_official": app.is_official, "curated": curated,
        "developer": developer_card(dev),
        "first_released_at": app.first_released_at.isoformat() if app.first_released_at else None,
    }


def version_public(v: MiniAppVersion | None) -> dict | None:
    if v is None:
        return None
    return {"id": v.id, "version": v.version, "build": v.build, "sha256": v.sha256,
            "size": v.size, "file_count": v.file_count,
            "released_at": v.released_at.isoformat() if v.released_at else None}


async def curated_ids(db: AsyncSession) -> dict[int, int]:
    rows = (await db.execute(select(MiniAppCuration.app_id, MiniAppCuration.position))).all()
    return {a: p for a, p in rows}
