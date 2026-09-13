"""链接预览的 SSRF 防护(DEV-PROMPTS-40 #373):只许公网地址、钉住解析出来的 IP 去连、每一跳重新判。"""
import asyncio

import httpx
import pytest

from app.services import link_preview as lp


@pytest.mark.parametrize("ip,ok", [
    ("8.8.8.8", True), ("93.184.216.34", True), ("::ffff:8.8.8.8", True),
    ("127.0.0.1", False), ("10.0.0.5", False), ("172.16.3.1", False), ("192.168.1.1", False),
    ("169.254.169.254", False),   # 云厂商元数据地址
    ("0.0.0.0", False), ("100.64.0.1", False), ("224.0.0.1", False), ("240.0.0.1", False),
    ("::1", False), ("fc00::1", False), ("fe80::1", False), ("::ffff:127.0.0.1", False),
    ("not-an-ip", False),
])
def test_is_public_ip(ip, ok):
    assert lp.is_public_ip(ip) is ok


DNS = {"public.test": ["93.184.216.34"], "internal.test": ["10.0.0.7"],
       "mixed.test": ["93.184.216.34", "127.0.0.1"], "meta.test": ["169.254.169.254"]}


@pytest.fixture
def net(monkeypatch):
    """假 DNS + 假 HTTP:记下每个真正发出去的请求。"""
    sent: list[httpx.Request] = []
    routes: dict[str, httpx.Response] = {}

    async def resolve(host, port):
        return DNS.get(host, [])

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(req)
        return routes.get(req.headers["host"], httpx.Response(404))

    real = httpx.AsyncClient

    def client(**kw):
        kw.pop("follow_redirects", None)
        return real(transport=httpx.MockTransport(handler), follow_redirects=False, **kw)

    monkeypatch.setattr(lp, "_resolve", resolve)
    monkeypatch.setattr(lp.httpx, "AsyncClient", client)
    return sent, routes


def fetch(url, max_bytes=1024):
    return asyncio.run(lp.safe_fetch(url, max_bytes=max_bytes, accept=("text/html",)))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://public.test/", "gopher://public.test/",
                                 "http:///nohost", "javascript:alert(1)"])
def test_only_http_https(net, url):
    sent, _ = net
    assert fetch(url) is None and not sent


@pytest.mark.parametrize("host", ["internal.test", "mixed.test", "meta.test", "nxdomain.test"])
def test_private_or_unresolvable_never_connects(net, host):
    sent, _ = net
    assert fetch(f"http://{host}/") is None
    assert not sent, "解析出内网地址就不该发出任何请求"


def test_pinned_ip_and_host_header(net):
    sent, routes = net
    routes["public.test"] = httpx.Response(200, headers={"content-type": "text/html"}, content=b"<title>x</title>")
    got = fetch("http://public.test/a?b=1")
    assert got is not None and got[2] == b"<title>x</title>"
    assert sent[0].url.host == "93.184.216.34", "连的是解析出来并判过的那个 IP(防 DNS 重绑定)"
    assert sent[0].headers["host"] == "public.test"


def test_redirect_to_private_is_refused(net):
    sent, routes = net
    routes["public.test"] = httpx.Response(302, headers={"location": "http://internal.test/admin"})
    assert fetch("http://public.test/") is None
    assert len(sent) == 1, "跳到内网地址的那一跳不许发出去"


def test_redirect_loop_stops(net):
    sent, routes = net
    routes["public.test"] = httpx.Response(302, headers={"location": "http://public.test/again"})
    assert fetch("http://public.test/") is None
    assert len(sent) == lp.MAX_HOPS + 1


def test_body_is_capped(net):
    _, routes = net
    routes["public.test"] = httpx.Response(200, headers={"content-type": "text/html"}, content=b"a" * 5000)
    got = fetch("http://public.test/", max_bytes=1000)
    assert got is not None and len(got[2]) == 1000


def test_wrong_content_type_refused(net):
    _, routes = net
    routes["public.test"] = httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"x")
    assert fetch("http://public.test/") is None
