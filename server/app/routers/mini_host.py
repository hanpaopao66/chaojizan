"""托管出口:把不可变的版本文件发出去(#322,DEV-PROMPTS-39 §5.6)。

## 为什么是 API 直出,不是 nginx auth_request

设计稿写的是 nginx 用 auth_request 问 API「这个版本能不能出、CSP 是什么」,再从桶里直出。
实际实现改成 API 自己出文件,nginx 只做 TLS 和反代:

- 「隔离立即 404」只有一个判定点(这里读 quarantined),不存在 nginx 缓存 30 秒的窗口;
- 本地、CI、生产走同一段代码 —— e2e 测的就是生产的返回头,不是一份「和生产一致」的仿制品;
- 文件按 (version_id, path) 缓存在进程内(内容不可变,缓存永远不会脏),审核状态每次查库。

## 两种入口

- 生产:`https://<appid>.<托管域名>/v/<version_id>/<path>`。MiniHostMiddleware 按 Host 头
  严格匹配 `^sz[0-9a-f]{16}\\.<托管域名>$`(大小写变体、带端口、非法 appid 一律 404),
  改写成下面的内部路径;托管域名下除了 /v/ 和 /_sdk/ 什么都不出。
- 开发(没配托管域名):`<API>/_mini-host/<appid>/v/<version_id>/<path>`,和 API 同源,
  **只在 APP_ENV=dev 时开**。生产上主域名访问 /_mini-host/ 一律 404 —— 托管页和主站同源
  就能读主站的 localStorage,那是整个隔离模型的反面。
"""
import json
import logging
import re
from collections import OrderedDict

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import MiniApp, MiniAppVersion
from ..services import storage
from ..services.mini_app_v2 import public_keys
from ..services.miniapp_package import PERMISSIONS_POLICY, build_csp, content_type
from ..services.miniapp_platform import frame_ancestors, version_servable
from ..services.miniapp_publish import object_key

logger = logging.getLogger("superz.miniapp.host")
router = APIRouter(tags=["小程序托管"], include_in_schema=False)

STATIC_SDK = storage.SERVER_DIR / "static" / "sdk"
_APPID = re.compile(r"^sz[0-9a-f]{16}$")


class _BlobCache:
    """(version_id, path) → bytes。内容不可变,只需要按容量淘汰。"""

    def __init__(self, cap: int = 64 * 1024 * 1024):
        self.cap = cap
        self.size = 0
        self.items: OrderedDict[tuple[int, str], bytes] = OrderedDict()

    def get(self, key):
        data = self.items.get(key)
        if data is not None:
            self.items.move_to_end(key)
        return data

    def put(self, key, data: bytes) -> None:
        if len(data) > self.cap // 8:
            return
        self.items[key] = data
        self.size += len(data)
        while self.size > self.cap and self.items:
            _, old = self.items.popitem(last=False)
            self.size -= len(old)


_cache = _BlobCache()


def _not_found() -> Response:
    # 不走全局 404 处理(那个会给浏览器回主站的品牌 404 页 —— 不该出现在应用的 origin 上)
    return Response("Not Found", status_code=404, media_type="text/plain; charset=utf-8",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


class MiniHostMiddleware:
    """托管域名的请求改写到内部路径;主域名上的内部路径在生产挡掉。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        domain = settings.mini_app_host_domain.strip().lower()
        path = scope.get("path", "")
        host = ""
        for k, v in scope.get("headers", []):
            if k == b"host":
                host = v.decode("latin-1")
                break
        bare = host.lower().split(":")[0]
        if domain and (bare == domain or bare.endswith("." + domain)):
            m = re.fullmatch(r"(sz[0-9a-f]{16})\." + re.escape(domain), host)
            if not m or scope.get("method") not in ("GET", "HEAD"):
                return await _not_found()(scope, receive, send)
            appid = m.group(1)
            if path.startswith("/v/"):
                new = f"/_mini-host/{appid}{path}"
            elif path.startswith("/_sdk/"):
                new = f"/_mini-host/_sdk/{path[len('/_sdk/'):]}"
            else:
                return await _not_found()(scope, receive, send)
            scope = dict(scope, path=new, raw_path=new.encode())
            scope["state"] = {**scope.get("state", {}), "mini_host_appid": appid}
            return await self.app(scope, receive, send)
        if path.startswith("/_mini-host/") and not (settings.is_dev and not domain):
            return await _not_found()(scope, receive, send)
        return await self.app(scope, receive, send)


def _host_ok(request: Request, appid: str) -> bool:
    """这次请求是不是从正确的入口进来的(见模块文档「两种入口」)。"""
    if settings.mini_app_host_domain:
        return getattr(request.state, "mini_host_appid", None) == appid
    return settings.is_dev


def _report_uri(request: Request) -> str:
    base = (settings.public_base_url if settings.mini_app_host_domain
            else str(request.base_url)).rstrip("/")
    return f"{base}/mini-apps/csp-report"


def host_headers(request: Request, app: MiniApp, *, html: bool) -> dict:
    return {
        "Content-Security-Policy": build_csp(
            request_domains=list(app.request_domains or []),
            frame_ancestors=frame_ancestors(), report_uri=_report_uri(request)),
        "Permissions-Policy": PERMISSIONS_POLICY,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cross-Origin-Opener-Policy": "same-origin",
        # 入口 HTML 每次回源确认(隔离后要立刻打不开);其余文件地址带版本号,永久缓存
        "Cache-Control": "no-cache" if html else "public, max-age=31536000, immutable",
    }


@router.get("/_mini-host/_sdk/{path:path}")
async def hosted_sdk(path: str, request: Request):
    """每个托管 origin 下都有一份 SDK(§5.6):script-src 只需要 'self'。"""
    return _sdk_file(path)


@router.get("/sdk/{path:path}")
async def public_sdk(path: str):
    """主站上的 SDK(文档、外部地址条目、自己打包前先试用)。带 CORS,便于配 SRI。"""
    return _sdk_file(path)


@router.get("/_sdk/{path:path}")
async def dev_host_sdk(path: str):
    """开发模式下托管页和 API 同源,页面照生产的写法引 /_sdk/2/sz-webapp.js 也得能拿到。
    (生产上托管域名的 /_sdk/ 由 MiniHostMiddleware 改写到 /_mini-host/_sdk/;
    主域名上多出这一份也无妨 —— SDK 本来就是公开文件)"""
    return _sdk_file(path)


def _sdk_file(path: str) -> Response:
    target = (STATIC_SDK / path).resolve()
    if not path or ".." in path or not target.is_file() \
            or not target.is_relative_to(STATIC_SDK.resolve()):
        return _not_found()
    immutable = re.match(r"^\d+\.\d+\.\d+/", path) is not None
    media = content_type(path) or "application/octet-stream"
    return FileResponse(target, media_type=media, headers={
        "Access-Control-Allow-Origin": "*",
        "X-Content-Type-Options": "nosniff",
        # 2.x.y/ 下的文件永不改;2/ 是「最新 2.x」,短缓存
        "Cache-Control": "public, max-age=31536000, immutable" if immutable
        else "public, max-age=300",
    })


@router.get("/_mini-host/{appid}/v/{version_id}/{path:path}")
async def hosted_file(appid: str, version_id: int, path: str, request: Request,
                      db: AsyncSession = Depends(get_db)):
    if not _APPID.match(appid) or not _host_ok(request, appid):
        return _not_found()
    app = (await db.execute(select(MiniApp).where(MiniApp.appid == appid))).scalar_one_or_none()
    if app is None or app.status == "removed" or app.hosting != "hosted":
        return _not_found()
    v = await db.get(MiniAppVersion, version_id)
    if v is None or v.app_id != app.id or not version_servable(v):
        return _not_found()
    manifest = v.manifest or {}
    files = manifest.get("files") or {}
    if path == "" or path.endswith("/"):
        path += "index.html"
    if path not in files:
        leaf = path.rsplit("/", 1)[-1]
        if (manifest.get("superz") or {}).get("spa_fallback") and "." not in leaf:
            path = "index.html"
        else:
            return _not_found()
    meta = files[path]
    html = path.endswith(".html")
    headers = host_headers(request, app, html=html)
    etag = f'"{meta.get("sha256", "")}"'
    headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    data = _cache.get((v.id, path))
    if data is None:
        try:
            data = storage.backend().get(object_key(app.appid, v.id, path), private=True)
        except storage.StorageError as exc:
            logger.error("托管文件读取失败 %s/%s/%s:%s", appid, v.id, path, exc)
            return Response("Service Unavailable", status_code=503,
                            headers={"Cache-Control": "no-store"})
        if data is None:
            logger.error("托管文件缺失 %s/%s/%s(清单里有、桶里没有)", appid, v.id, path)
            return _not_found()
        _cache.put((v.id, path), data)
    return Response(data, media_type=meta.get("type") or content_type(path)
                    or "application/octet-stream", headers=headers)


@router.get("/.well-known/superz-webapp-keys.json")
async def webapp_keys():
    """平台 Ed25519 公钥。开发者后端用它验 initData 的 signature,不必碰 AppSecret(§5.3)。"""
    try:
        keys = public_keys()
    except RuntimeError as exc:
        logger.error("公钥发布失败:%s", exc)
        return Response('{"detail":"签名密钥未配置"}', status_code=503,
                        media_type="application/json")
    return Response(
        content=json.dumps({"keys": keys}, ensure_ascii=False),
        media_type="application/json",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})
