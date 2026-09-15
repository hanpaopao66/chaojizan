"""小程序安全审计(DEV-PROMPTS-39 #335)里能在进程内验的几条守卫。

- Host 头:托管域名下只认 `sz<16 位十六进制>.<托管域名>`;大小写变体、带端口、多一级子域名、
  非 GET/HEAD、/v/ 和 /_sdk/ 以外的路径一律 404;主域名上的内部路径 /_mini-host/ 在生产 404;
- 托管域名可以是主站下专门的一级(mp.chaojizan.cc),配成主站本身或它的上级按没配处理,不能把主站吞掉;
- 点击劫持:生产的 frame-ancestors 只有主站和配置的宿主 origin,没有 `*`;
- CSP:脚本只许同源(不许 unsafe-inline / unsafe-eval),不许嵌 iframe / object、不许提交表单;
- CSP 违规报告:日志只记被拦的 origin,不记路径和参数 —— 被拦下的请求里可能正是想外带的用户数据;
- 前端没有原始 HTML 的写入口:开发者写的名称、描述、更新说明只能当文字渲染。
  唯一例外是官网文档页,它放的是构建时从仓库 Markdown 转出来的 HTML(全部转义,
  scripts/check_sdk_docs.mjs 另有一条检查)。
"""
import asyncio
import json
import logging
import re
from pathlib import Path

import pytest

from app.config import settings
from app.routers import mini_apps, mini_host
from app.services.miniapp_package import build_csp
from app.services.miniapp_platform import frame_ancestors, host_domain

APPID = "sz0123456789abcdef"
DOMAIN = "szapps.example.cn"
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def prod(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "mini_app_host_domain", DOMAIN)
    monkeypatch.setattr(settings, "public_base_url", "https://chaojizan.cc")
    monkeypatch.setattr(settings, "mini_app_frame_ancestors", "https://app.chaojizan.cc/")


def through(host: str, path: str = "/v/7/index.html", method: str = "GET"):
    """把一个请求过一遍 MiniHostMiddleware,返回(状态码, 路由看到的 path, 标记的 appid)。"""
    seen = {}

    async def inner(scope, receive, send):
        seen["path"] = scope["path"]
        seen["appid"] = (scope.get("state") or {}).get("mini_host_appid")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(),
             "headers": [(b"host", host.encode())], "query_string": b"", "scheme": "https",
             "server": ("test", 443), "client": ("127.0.0.1", 1)}
    asyncio.run(mini_host.MiniHostMiddleware(inner)(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, seen.get("path"), seen.get("appid")


def test_host_header_only_exact_appid_subdomain(prod):
    assert through(f"{APPID}.{DOMAIN}") == (200, f"/_mini-host/{APPID}/v/7/index.html", APPID)
    assert through(f"{APPID}.{DOMAIN}", "/_sdk/2/sz-webapp.js")[:2] == \
        (200, "/_mini-host/_sdk/2/sz-webapp.js")
    for bad in (f"SZ0123456789ABCDEF.{DOMAIN}",      # 大小写变体
                f"{APPID}.{DOMAIN.upper()}",
                f"{APPID}.{DOMAIN}:443",              # 带端口
                f"evil.{APPID}.{DOMAIN}",             # 多一级子域名
                f"sz0123456789abcde.{DOMAIN}",        # 15 位
                f"sz0123456789abcdefg.{DOMAIN}",      # 17 位
                f"sz0123456789abcdeg.{DOMAIN}",       # 非十六进制
                f"x{APPID}.{DOMAIN}",
                DOMAIN):                               # 裸托管域名
        status, path, _ = through(bad)
        assert status == 404 and path is None, f"{bad!r} 应该 404"


def test_host_only_serves_versions_and_sdk_with_get(prod):
    for path in ("/", "/index.html", "/mini-apps/catalog", "/admin", "/_mini-host/x", "/auth/sms-code"):
        assert through(f"{APPID}.{DOMAIN}", path)[0] == 404, path
    for method in ("POST", "PUT", "DELETE", "OPTIONS"):
        assert through(f"{APPID}.{DOMAIN}", method=method)[0] == 404, method
    assert through(f"{APPID}.{DOMAIN}", method="HEAD")[0] == 200


def test_internal_path_closed_on_main_domain_in_prod(prod, monkeypatch):
    assert through("chaojizan.cc", f"/_mini-host/{APPID}/v/7/index.html")[0] == 404
    # 生产没配托管域名:内部路径同样不出(不能退回主域名同源托管 —— 那样应用和主站同 origin)
    monkeypatch.setattr(settings, "mini_app_host_domain", "")
    assert through("chaojizan.cc", f"/_mini-host/{APPID}/v/7/index.html")[0] == 404
    # 主站其余路径不受影响
    assert through("chaojizan.cc", "/mini-apps/catalog")[0] == 200


def test_host_domain_can_be_a_dedicated_level_under_the_main_domain(prod, monkeypatch):
    """用主站下专门的一级(mp.chaojizan.cc):应用子域名照常改写,主站和它别的子域名原样放行。"""
    monkeypatch.setattr(settings, "mini_app_host_domain", "mp.chaojizan.cc")
    assert host_domain() == "mp.chaojizan.cc"
    assert through(f"{APPID}.mp.chaojizan.cc") == (200, f"/_mini-host/{APPID}/v/7/index.html", APPID)
    assert through("chaojizan.cc", "/mini-apps/catalog") == (200, "/mini-apps/catalog", None)
    assert through("www.chaojizan.cc", "/") == (200, "/", None)
    assert through(f"{APPID}.chaojizan.cc") == (200, "/v/7/index.html", None), "不在托管那一级下的不改写"
    assert through("mp.chaojizan.cc")[0] == 404, "裸托管域名什么都不出"


def test_host_domain_cannot_swallow_the_main_site(prod, monkeypatch):
    """托管域名配成主站本身或它的上级:按没配处理 —— 主站照常,托管小程序打不开。
    不拦的话,主站(和 www 之类的子域名)的每个请求都会被当成托管请求,整站 404。"""
    for bad in ("chaojizan.cc", "CHAOJIZAN.CC", ".chaojizan.cc", "cc"):
        monkeypatch.setattr(settings, "mini_app_host_domain", bad)
        assert host_domain() == "", bad
        assert through("chaojizan.cc", "/mini-apps/catalog") == (200, "/mini-apps/catalog", None), bad
        assert through("www.chaojizan.cc", "/") == (200, "/", None), bad
        assert through("chaojizan.cc", f"/_mini-host/{APPID}/v/7/index.html")[0] == 404, bad


def test_frame_ancestors_in_prod_are_explicit_origins(prod):
    assert frame_ancestors() == ["https://chaojizan.cc", "https://app.chaojizan.cc"]


def _directives(csp: str) -> dict[str, str]:
    out = {}
    for part in csp.split(";"):
        name, _, value = part.strip().partition(" ")
        out[name] = value
    return out


def test_csp_blocks_inline_script_frames_and_undeclared_hosts():
    d = _directives(build_csp(request_domains=["https://api.example.com"],
                              frame_ancestors=["https://chaojizan.cc"],
                              report_uri="https://chaojizan.cc/mini-apps/csp-report"))
    assert d["default-src"] == "'self'"
    assert d["script-src"] == "'self' 'wasm-unsafe-eval'", "脚本只许同源,不许内联、不许 eval"
    assert d["connect-src"] == "'self' https://api.example.com", "只能连声明过的服务器"
    assert d["frame-src"] == "'none'" and d["object-src"] == "'none'"
    assert d["form-action"] == "'none'" and d["base-uri"] == "'self'"
    assert d["frame-ancestors"] == "https://chaojizan.cc", "点击劫持:只许宿主嵌"
    assert d["report-uri"] == "https://chaojizan.cc/mini-apps/csp-report"
    # 一个都没声明:只剩同源
    d = _directives(build_csp(request_domains=[], frame_ancestors=[], report_uri="/r"))
    assert d["connect-src"] == "'self'" and d["frame-ancestors"] == "'none'"


def test_csp_report_logs_blocked_origin_only(monkeypatch, caplog):
    async def no_limit(*_a, **_k):
        return None

    def no_redis():
        raise RuntimeError("单测不连 redis")

    monkeypatch.setattr(mini_apps, "check_rate_limit", no_limit)
    monkeypatch.setattr("app.redis_client.get_redis", no_redis)
    canary = "o_canaryopenid2222222222222"
    raw = json.dumps({"csp-report": {
        "document-uri": f"https://{APPID}.{DOMAIN}/v/7/index.html?note={canary}",
        "blocked-uri": f"https://evil.example.com/collect?open_id={canary}&text=%E6%97%A5%E8%AE%B0",
        "violated-directive": "connect-src"}}).encode()

    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/mini-apps/csp-report",
                       "headers": [(b"content-type", b"application/csp-report")],
                       "query_string": b"", "client": ("203.0.113.9", 1)}, receive)
    with caplog.at_level(logging.INFO, logger="superz.miniapp"):
        resp = asyncio.run(mini_apps.csp_report(request))
    assert resp.status_code == 204
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "https://evil.example.com" in text and APPID in text, text
    assert canary not in text and "collect" not in text and "%E6" not in text, \
        f"CSP 报告的日志里只许有 origin:{text}"


# ---- 前端:开发者写的内容只能当文字渲染 ----

SCAN = ["admin-web/src", "developer-web/src", "web/src", "miniapps/notepad", "miniapps/2048",
        "miniapps/shared", "miniapps/snake", "miniapps/blocks", "miniapps/minesweeper", "miniapps/_template",
        "packages/miniapp-sdk/src"]
SINK = re.compile(r"dangerouslySetInnerHTML|\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML"
                  r"|document\.write\(|v-html")
#: 允许的例外,写明为什么安全
ALLOW = {
    "web/src/developers/DevelopersPage.jsx":
        "文档正文是构建时从仓库 docs/miniapp/*.md 转的 HTML,转换不透传任何原始 HTML",
}


def test_no_raw_html_sinks_in_frontends():
    found = []
    for base in SCAN:
        for path in sorted((ROOT / base).rglob("*")):
            if path.suffix not in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".html", ".vue") \
                    or "node_modules" in path.parts or "dist" in path.parts:
                continue
            rel = str(path.relative_to(ROOT))
            for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                if SINK.search(line) and rel not in ALLOW:
                    found.append(f"{rel}:{n}: {line.strip()[:120]}")
    assert not found, "开发者写的名称、描述可能被当成 HTML 渲染:\n" + "\n".join(found)
    for rel in ALLOW:
        assert (ROOT / rel).exists(), f"例外清单里的 {rel} 不存在了,删掉这一条"
