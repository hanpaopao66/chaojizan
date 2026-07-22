import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import text

from .config import settings
from .db import SessionLocal, engine
from .redis_client import get_redis
from fastapi.staticfiles import StaticFiles

from .routers import (
    addresses,
    admin,
    after_sales,
    appeals,
    auth,
    favorites,
    food_safety,
    geo,
    invoices,
    ledger,
    merchants,
    orders,
    payments,
    payout,
    reviews,
    riders,
    screen,
    tax,
    transparency,
    tickets,
    platform,
    uploads,
    vouchers,
)
from .routers.uploads import UPLOAD_DIR
from .services.auto_flow import auto_flow_loop
from . import ws

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SERVER_DIR = Path(__file__).resolve().parent.parent

# Alembic 基线版本号:老库(有表但没有 alembic_version)启动时 stamp 到这里,
# 之后的结构变更一律走 alembic revision --autogenerate,不再手写 ALTER
_BASELINE_REV = "0001"


def _run_alembic_upgrade(stamp_baseline: bool) -> None:
    """在工作线程里跑(alembic env.py 内部 asyncio.run,不能嵌在事件循环里)。"""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    if stamp_baseline:
        command.stamp(cfg, _BASELINE_REV)
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        # 老库识别:建过表(users 存在)但从没跑过 alembic → 先 stamp 基线
        has_users = await conn.scalar(text("SELECT to_regclass('public.users')"))
        has_alembic = await conn.scalar(
            text("SELECT to_regclass('public.alembic_version')"))
    await asyncio.to_thread(
        _run_alembic_upgrade, has_users is not None and has_alembic is None)
    sweeper = (
        asyncio.create_task(auto_flow_loop()) if settings.auto_flow_enabled else None
    )
    yield
    if sweeper is not None:
        sweeper.cancel()
    await engine.dispose()


app = FastAPI(
    title="Super-Z 外卖平台",
    description="低抽成外卖平台 —— 用户端 / 商家端 / 骑手端共用后端",
    version="0.1.0",
    lifespan=lifespan,
)

# 浏览器访问不存在的路径给品牌 404 页;API 客户端(Accept 非 html)仍收 JSON
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def html_aware_errors(request, exc):
    if exc.status_code == 404 and "text/html" in request.headers.get("accept", ""):
        return FileResponse(STATIC_DIR / "404.html", status_code=404)
    return await http_exception_handler(request, exc)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 上线前收紧到实际域名
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(merchants.router)
app.include_router(orders.router)
app.include_router(riders.router)
app.include_router(addresses.router)
app.include_router(geo.router)
app.include_router(reviews.router)
app.include_router(after_sales.router)
app.include_router(favorites.router)
app.include_router(food_safety.router)
app.include_router(uploads.router)
app.include_router(payments.router)
app.include_router(tickets.router)
app.include_router(vouchers.router)
app.include_router(payout.router)
app.include_router(appeals.router)
app.include_router(invoices.router)
app.include_router(tax.router)
app.include_router(platform.router)
app.include_router(ledger.router)
app.include_router(screen.router)
app.include_router(transparency.router)
from .routers import carts, group_cart, referrals
app.include_router(group_cart.router)
app.include_router(carts.router)
app.include_router(referrals.router)
app.include_router(admin.router)
app.include_router(ws.router)

UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# APK 分发目录(生产挂宿主 ~/super-z/appdist):APK 文件 + versions.json
APPDIST_DIR = Path(__file__).resolve().parent.parent / "appdist"
APPDIST_DIR.mkdir(exist_ok=True)


# 下载页:三端 APK + 版本信息(与应用内更新同源)。必须注册在 /appdist 静态
# 挂载之前——否则裸 /appdist 会被 mount 的 307 重定向接管然后 404
# SEO/AIEO 三件套:robots 指路、sitemap 列页面、llms.txt 给 AI 引擎喂事实
@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return FileResponse(STATIC_DIR / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    return FileResponse(STATIC_DIR / "sitemap.xml", media_type="application/xml")


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt():
    return FileResponse(STATIC_DIR / "llms.txt", media_type="text/plain")


@app.get("/download", include_in_schema=False)
async def download_page():
    return FileResponse(Path(__file__).resolve().parent.parent
                        / "static" / "download.html")


@app.get("/appdist", include_in_schema=False)
async def appdist_redirect():
    """历史链接兜底:老页面/聊天记录里的 /appdist 全部落到下载页。"""
    return RedirectResponse("/download")


app.mount("/appdist", StaticFiles(directory=APPDIST_DIR), name="appdist")


@app.get("/app/latest")
async def app_latest(app_name: str = Query(alias="app", pattern="^(user|merchant|rider)$")):
    """应用内更新检查:返回该端最新版本信息。

    versions.json 由发版脚本维护,不存在或无该端记录时 404(客户端静默忽略)。
    格式:{"user": {"version": "0.3.0", "build": 3, "url": "...", "notes": "...", "force": false}, ...}
    """
    versions_file = APPDIST_DIR / "versions.json"
    if not versions_file.exists():
        raise HTTPException(404, "暂无版本信息")
    info = json.loads(versions_file.read_text()).get(app_name)
    if not info:
        raise HTTPException(404, "暂无版本信息")
    return info


@app.get("/health")
async def health():
    """探活:真实检查数据库和 Redis,供监控告警脚本用(deploy/healthcheck-alert.sh)。

    任一依赖不可用返回 503,监控端只需看 HTTP 状态码。
    """
    checks: dict[str, str] = {}
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {type(exc).__name__}"
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        raise HTTPException(503, detail=checks)
    from .routers.transparency import _running_version
    return {"status": "ok", **checks, **_running_version()}


@app.get("/", include_in_schema=False)
async def landing_page():
    """官网:优先 React 版(static/site 构建产物),没构建过就用旧的单页。"""
    site_index = SITE_DIR / "index.html"
    if site_index.exists():
        return FileResponse(site_index)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    """商家入驻审核后台(单文件网页,无需前端构建)。"""
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/nodes", include_in_schema=False)
async def nodes_page():
    """社区见证节点页:实时节点数 + 校验状态 + 如何运行你自己的节点。"""
    return FileResponse(STATIC_DIR / "nodes.html")


@app.get("/screen", include_in_schema=False)
async def screen_page():
    """经营大屏:优先 React+Three.js 版(web/ 构建产物,3D 中国地图+实时播报),
    没构建过就回退旧 ECharts 单页。数据与公开账本同源,店内电视/投屏用。"""
    site_index = SITE_DIR / "index.html"
    if site_index.exists():
        return FileResponse(site_index)
    return FileResponse(STATIC_DIR / "screen.html")


@app.get("/join/{role}", include_in_schema=False)
async def join_pages(role: str):
    """商家入驻/骑手加入落地页(官网前端路由,同一份 index.html)。"""
    if role not in ("merchant", "rider"):
        raise HTTPException(404, "页面不存在")
    site_index = SITE_DIR / "index.html"
    if site_index.exists():
        return FileResponse(site_index)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/brand", include_in_schema=False)
async def brand_page():
    """品牌物料页(官网前端路由,同一份 index.html)。"""
    site_index = SITE_DIR / "index.html"
    if site_index.exists():
        return FileResponse(site_index)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/transparency", include_in_schema=False)
async def transparency_page():
    """透明中心(官网前端路由):核账公示/佣金去向/赔付记录/财报/分账公平。"""
    site_index = SITE_DIR / "index.html"
    if site_index.exists():
        return FileResponse(site_index)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/status", include_in_schema=False)
async def status_page():
    """系统状态页(透明中心的状态区直达入口)。"""
    site_index = SITE_DIR / "index.html"
    if site_index.exists():
        return FileResponse(site_index)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """浏览器默认请求的站点图标(PNG 内容浏览器都认)。"""
    icon = SITE_DIR / "brand" / "favicon_64.png"
    if icon.exists():
        return FileResponse(icon, media_type="image/png")
    raise HTTPException(404, "无图标")


@app.get("/witness.py", include_in_schema=False)
async def witness_script():
    """见证节点脚本直接下载(公开仓发布前的分发通道):
    curl -O https://chaojizan.cc/witness.py && python3 witness.py"""
    return FileResponse(SERVER_DIR.parent / "witness" / "superz_witness.py",
                        media_type="text/x-python",
                        filename="superz_witness.py")


@app.get("/maintenance", include_in_schema=False)
async def maintenance_page():
    """维护兜底页预览。生产用法:把本文件放到 frps 端 nginx 的静态兜底,
    后端不可达时用户看到"火还在,马上回来"而不是连接重置。"""
    return FileResponse(STATIC_DIR / "maintenance.html")


app.mount("/vendor", StaticFiles(directory=STATIC_DIR / "vendor"), name="vendor")

# React+Three.js 官网(web/ 构建产物,见 web/README.md;生产机无需 node)
SITE_DIR = STATIC_DIR / "site"
if SITE_DIR.exists():
    app.mount("/site", StaticFiles(directory=SITE_DIR), name="site")


@app.get("/legal/terms", include_in_schema=False)
async def legal_terms():
    """用户协议(网页版,应用商店审核和备案材料引用)。"""
    return FileResponse(STATIC_DIR / "legal-terms.html")


@app.get("/legal/privacy", include_in_schema=False)
async def legal_privacy():
    """隐私政策(网页版)。"""
    return FileResponse(STATIC_DIR / "legal-privacy.html")
