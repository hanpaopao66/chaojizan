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
    brands,
    errands,
    favorites,
    food_safety,
    geo,
    invoices,
    ledger,
    merchants,
    mini_apps,
    ocr,
    open_api,
    orders,
    payments,
    payout,
    reviews,
    riders,
    screen,
    stays,
    tax,
    transparency,
    tickets,
    platform,
    queue,
    uploads,
    vouchers,
)
from .routers.uploads import PRIVATE_DIR, UPLOAD_DIR
from .services.auto_flow import auto_flow_loop
from . import ws

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SERVER_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动动作。**两件事都是可关的,因为它们都只该跑一份。**

    生产上 api 容器两个开关都关:迁移交给一次性的 migrate 容器,
    清扫交给常驻的 sweeper 容器(见 deploy/docker-compose.prod.yml)。
    本地开发两个都开着,`uvicorn app.main:app` 一条命令即可,零配置。

    历史包袱:这两件事原本无条件写在这里,而 api 是 `--workers 4` 起的,
    于是迁移被四个进程同时执行、清扫循环同时跑四份。见 app/startup.py
    和 app/sweeper.py 顶部的说明。
    """
    if settings.run_migrations_on_startup:
        from .startup import prepare_database
        await prepare_database()
    sweeper = (
        asyncio.create_task(auto_flow_loop()) if settings.auto_flow_enabled else None
    )
    yield
    if sweeper is not None:
        sweeper.cancel()
    # 共享的推送 HTTP 客户端(连接池)随进程一起收掉
    from .services.push import aclose_push_client
    await aclose_push_client()
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


# ---------------------------------------------------------------------------
# 下面三个中间件都写成**纯 ASGI**,而不是 @app.middleware("http")。
#
# 那个装饰器背后是 Starlette 的 BaseHTTPMiddleware,它给**每一个请求**
# 起一个 anyio task group 加两条内存对象流,好处是能拿到 Request/Response
# 对象。而这三件事一件都用不上:两个只读请求头,一个只包一层 try。
#
# 三端所有接口、每一个请求都要穿过这一层,所以这里省下的是**乘以总请求数**
# 的开销 —— 首页那种 7ms 的接口感觉不明显,但 /orders/{no}/rider-location
# 这类 4ms 的高频轮询里,它占的比例并不小。
# ---------------------------------------------------------------------------


class SelectShopMiddleware:
    """连锁门店选择:X-Shop-Id 头写进 ContextVar,供权限解析读取。

    **这个头只是「选哪家」不是「有权限」** —— services.staff.resolve_shop
    拿到之后照样走完整校验,伪造别家的 id 只会拿到 404。
    没有这个头时一切照旧(单店商家零感知)。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from .services.staff import current_shop_id

        raw = ""
        for k, v in scope["headers"]:
            if k == b"x-shop-id":
                raw = v.decode("latin-1")
                break
        token = current_shop_id.set(int(raw)) if raw.isdigit() else None
        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                current_shop_id.reset(token)


class ObserveAppBuildMiddleware:
    """记录客户端上报的 X-App-Build。**只记录,不拦截。**

    现在我们答不上来「线上还有多少旧版在跑」这个问题 ——
    客户端不上报版本,服务端也就无从统计。而不知道分布就没法定阈值:
    直接拍一个 min_build 上去,可能一刀切掉 30% 的活跃用户,
    也可能定得太松等于没定。所以顺序是**先看见,再决定**。

    这一步只做"看见":把 build 号打进日志,过一阵子拿日志一聚合,
    就知道各版本占比和衰减速度,那时再谈拦不拦、阈值定多少。

    客户端加请求头由另一包做,所以现在这个头**大概率是空的** ——
    空的不记,免得刷屏。头不合法(不是数字)也不记、不报错:
    版本上报绝不能变成一个能把请求打挂的东西。

    `/health` 这类高频探活不记,不然日志里全是它。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # 绝大多数请求根本没有这个头,所以先扫一遍头、没有就立刻放行:
        # 不要为了极少数上报的请求让所有请求都去构造 Request 对象
        if scope["type"] == "http":
            build = platform = ""
            for k, v in scope["headers"]:
                if k == b"x-app-build":
                    build = v.decode("latin-1")
                elif k == b"x-app-platform":
                    platform = v.decode("latin-1")
            if build.isdigit() and scope.get("path") not in ("/health",):
                import logging as _logging

                _logging.getLogger("superz.appbuild").info(
                    "app_build=%s platform=%s path=%s",
                    build[:12], (platform or "?")[:16], scope.get("path"))
        await self.app(scope, receive, send)


class LogUnhandledErrorsMiddleware:
    """未捕获异常统一留痕(#130)。

    此前线上报错只能翻 docker logs 的原始 traceback,而日志既没轮转上限、
    也没人主动看。这里至少让 5xx 带上方法/路径/traceback,便于事后定位。

    **绝不记录请求体和查询串** —— 里面有手机号、收货地址、订单内容。
    把用户数据写进日志等于给自己造了第二个数据泄露面:
    日志会被复制、会被转发、会进备份,而且不受 /files 那套判权保护。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        except Exception:
            import logging
            import traceback

            logging.getLogger("superz.error").error(
                "未处理异常 %s %s\n%s",
                scope.get("method"), scope.get("path"),
                traceback.format_exc())
            raise


# 加入顺序 = 由内到外,和原先三个装饰器的嵌套顺序保持一致:
# CORS → 异常留痕 → 版本上报 → 门店选择 → 路由
app.add_middleware(SelectShopMiddleware)
app.add_middleware(ObserveAppBuildMiddleware)
app.add_middleware(LogUnhandledErrorsMiddleware)

# 收紧到白名单(#130)。原先是 ["*"] —— 任何网站都能拿着用户浏览器里的
# 凭据打我们的接口。原生 App 不发 Origin 头、不受 CORS 约束,
# 所以这一改只影响官网/管理后台,三端不会因此挂掉
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(merchants.router)
app.include_router(brands.router)
app.include_router(orders.router)
app.include_router(errands.router)
app.include_router(riders.router)
app.include_router(addresses.router)
app.include_router(geo.router)
app.include_router(reviews.router)
app.include_router(after_sales.router)
app.include_router(favorites.router)
app.include_router(food_safety.router)
app.include_router(uploads.router)
app.include_router(ocr.router)
app.include_router(open_api.router)
app.include_router(payments.router)
app.include_router(tickets.router)
app.include_router(vouchers.router)
app.include_router(stays.router)
app.include_router(payout.router)
app.include_router(appeals.router)
app.include_router(invoices.router)
app.include_router(tax.router)
app.include_router(platform.router)
app.include_router(ledger.router)
app.include_router(screen.router)
app.include_router(transparency.router)
app.include_router(mini_apps.router)
from .routers import carts, group_cart, referrals
app.include_router(queue.router)
app.include_router(group_cart.router)
app.include_router(carts.router)
app.include_router(referrals.router)
app.include_router(admin.router)
app.include_router(ws.router)

UPLOAD_DIR.mkdir(exist_ok=True)
PRIVATE_DIR.mkdir(exist_ok=True)
# 这里**故意不再 mount StaticFiles**(#124)。
# 老口径是 app.mount("/uploads", StaticFiles(...)),它把整个目录无鉴权直出 ——
# 而那个目录里同时躺着菜品图和骑手身份证。静态挂载是绕过鉴权的一条路,
# 只要它还在,routers/uploads.py 里的判权就形同虚设。
# 现在 /uploads/{name} 由 routers/uploads.py 的 legacy_file 接管。

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


@app.get("/s/{code}", include_in_schema=False)
async def shop_landing(code: str):
    """商家专属码落地页(#116):海报二维码扫出来就是它。
    页面自己拿 code 调 /merchants/by-code/{code} 取店铺信息,
    找不到就提示已下架 —— 短码不存在也返回 200 页面而不是裸 404。"""
    return FileResponse(STATIC_DIR / "shop.html")


@app.get("/appdist", include_in_schema=False)
async def appdist_redirect():
    """历史链接兜底:老页面/聊天记录里的 /appdist 全部落到下载页。"""
    return RedirectResponse("/download")


app.mount("/appdist", StaticFiles(directory=APPDIST_DIR), name="appdist")


@app.get("/app/latest")
async def app_latest(app_name: str = Query(alias="app", pattern="^(user|merchant|rider)$")):
    """应用内更新检查:返回该端最新版本信息。

    versions.json 由发版脚本维护,不存在或无该端记录时 404(客户端静默忽略)。
    格式:{"user": {"version": "0.3.0", "build": 3, "url": "...",
           "notes": "...", "force": false, "min_build": 0}, ...}

    ## min_build:最低可用版本号

    `force` 说的是"这个版本建议强制更新",`min_build` 说的是
    "低于这个 build 的客户端不该继续用"。两者不是一回事:
    force 是**发版当时**的一次性决定,min_build 是**持续有效**的下限 ——
    今天发 build 12 说不强更,不代表半年后 build 3 还能用。

    没有 min_build 之前,服务端**没有任何办法拒绝一个过旧的客户端**:
    协议改了、算费口径改了、隐私口径改了,老版本照样在跑,
    而我们连"还有多少人在跑老版本"都答不上来(客户端根本不上报版本)。

    这一包只把字段透出去 + 开始记录上报,**服务端不拦截**。
    拦截要等有了真实的版本分布数据再定阈值 —— 先拍一个数字然后
    把一批人挡在门外,是比不拦更糟的选择。
    """
    versions_file = APPDIST_DIR / "versions.json"
    if not versions_file.exists():
        raise HTTPException(404, "暂无版本信息")
    info = json.loads(versions_file.read_text()).get(app_name)
    if not info:
        raise HTTPException(404, "暂无版本信息")
    # 老的 versions.json 没有这个字段;补 0 = 不设下限,
    # 客户端拿到 0 就知道"没有最低版本要求",不用区分缺字段和不限制
    info.setdefault("min_build", 0)
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

# 商家网页工作台(merchant-web/ 构建产物;同源部署,生产机无需 node)。
# SPA:资源命中直接回文件,其余路径都回 index.html(前端路由刷新不 404)
MERCHANT_WEB_DIR = STATIC_DIR / "merchant"


@app.get("/merchant", include_in_schema=False)
@app.get("/merchant/{path:path}", include_in_schema=False)
async def merchant_console(path: str = ""):
    if not MERCHANT_WEB_DIR.exists():
        raise HTTPException(404, "商家工作台尚未构建(merchant-web/ 执行 npm run build)")
    candidate = (MERCHANT_WEB_DIR / path).resolve()
    # 防路径穿越:只允许构建目录内的文件
    if path and candidate.is_file() \
            and candidate.is_relative_to(MERCHANT_WEB_DIR.resolve()):
        return FileResponse(candidate)
    return FileResponse(MERCHANT_WEB_DIR / "index.html")


# 平台管理后台(React SPA)。
#
# ⚠️ 路径**不能**叫 /admin —— 那是 79 个管理接口的前缀,
# 而且 /admin 本身已经是老的单文件审核页(static/admin.html)。
ADMIN_WEB_DIR = STATIC_DIR / "admin"


@app.get("/admin-console", include_in_schema=False)
@app.get("/admin-console/{path:path}", include_in_schema=False)
async def admin_console(path: str = ""):
    if not ADMIN_WEB_DIR.exists():
        raise HTTPException(404, "平台后台尚未构建(admin-web/ 执行 npm run build)")
    candidate = (ADMIN_WEB_DIR / path).resolve()
    # 防路径穿越:只允许构建目录内的文件
    if path and candidate.is_file() \
            and candidate.is_relative_to(ADMIN_WEB_DIR.resolve()):
        return FileResponse(candidate)
    return FileResponse(ADMIN_WEB_DIR / "index.html")


@app.get("/mini-app-bridge.js", include_in_schema=False)
async def mini_app_bridge():
    """小程序桥脚本(#292)。**公开、无需鉴权** —— 它本身不含任何机密。

    页面在 <head> 里引这一个文件就有了 window.superz。

    为什么需要它:手机端小程序跑在原生 WebView 里,宿主可以注入 JS;
    但 web 端跑在**跨域 iframe** 里,浏览器的同源策略明确禁止父页面注入 ——
    这不是权限没开,是安全模型本身。Telegram 也是这么解决的
    (它要求页面引 telegram-web-app.js)。

    带 CORS 头是因为小程序部署在别人的域名下,而 <script src> 跨域取脚本
    在带 crossorigin 属性时会走 CORS 检查。
    """
    return FileResponse(
        STATIC_DIR / "mini-app-bridge.js",
        media_type="application/javascript",
        headers={
            "Access-Control-Allow-Origin": "*",
            # 桥的协议是稳定的,让 CDN 和浏览器缓存住;
            # 真要改协议就改文件名(bridge-v2.js),不靠让缓存失效
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/legal/terms", include_in_schema=False)
async def legal_terms():
    """用户协议(网页版,应用商店审核和备案材料引用)。"""
    return FileResponse(STATIC_DIR / "legal-terms.html")


@app.get("/legal/privacy", include_in_schema=False)
async def legal_privacy():
    """隐私政策(网页版)。"""
    return FileResponse(STATIC_DIR / "legal-privacy.html")
