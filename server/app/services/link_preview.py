"""链接预览:服务端代取网页的标题、摘要、配图(DEV-PROMPTS-40 #352)。

**为什么服务端取、而不是客户端自己取**:客户端直连第三方网页,等于把每个收到这条消息的人的
IP 交给那个网站 —— 一张 1×1 的图就能统计「这条消息被谁看了」。服务端取一次、配图存成
平台自己的图片,收消息的人一个都不用碰第三方。

**SSRF 防护**(安全审计会逐项验):
- 只许 http / https;
- DNS 解析后**每个 IP** 都必须是公网地址(拒回环、私网、链路本地、组播、保留段);
- 解析完**钉住 IP 去连**(Host 头和 TLS SNI 用原域名),防 DNS 重绑定;
- 不自动跟随跳转,每一跳重新做上面三步,最多 3 跳;
- 网页 ≤ 1MB、图片 ≤ 2MB,整体 5 秒。
"""
import asyncio
import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Chat, ChatMessage
from .entities import urls
from .rt_events import append_chat_event

logger = logging.getLogger("superz.chat")

PAGE_MAX = 1024 * 1024
IMAGE_MAX = 2 * 1024 * 1024
TIMEOUT = 5.0
MAX_HOPS = 3
UA = "SuperZ-LinkPreview/1.0 (+https://chaojizan.cc)"


def is_public_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast and not a.is_reserved


async def _resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return list(dict.fromkeys(i[4][0] for i in infos))


async def safe_fetch(url: str, *, max_bytes: int, accept: tuple[str, ...]) \
        -> tuple[str, str, bytes] | None:
    """按上面的规则取一个地址。任何一步不合规都返回 None(不抛)。"""
    for _ in range(MAX_HOPS + 1):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        ips = await _resolve(host, port)
        if not ips or not all(is_public_ip(ip) for ip in ips):
            return None
        ip = ips[0]
        netloc = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
        pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
        host_header = host if parts.port is None else f"{host}:{port}"
        headers = {"Host": host_header, "User-Agent": UA,
                   "Accept": "text/html,application/xhtml+xml,image/*;q=0.8"}
        ext = {"sni_hostname": host} if parts.scheme == "https" else {}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as c:
                req = c.build_request("GET", pinned, headers=headers, extensions=ext)
                resp = await c.send(req, stream=True)
                try:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location", "")
                        if not loc:
                            return None
                        url = urljoin(url, loc)
                        continue
                    if resp.status_code != 200:
                        return None
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    if not any(ctype.startswith(a) for a in accept):
                        return None
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                        if len(body) > max_bytes:
                            break
                    return url, resp.headers.get("content-type", ""), bytes(body[:max_bytes])
                finally:
                    await resp.aclose()
        except (httpx.HTTPError, OSError, ValueError):
            return None
    return None


class _Meta(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and "content" in a and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and len(self.title) < 300:
            self.title += data


def _decode(body: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype, re.I) or \
        re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', body[:4096], re.I)
    enc = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try:
        return body.decode(enc, errors="ignore")
    except LookupError:
        return body.decode("utf-8", errors="ignore")


def parse_preview(html: str, url: str) -> dict:
    p = _Meta()
    try:
        p.feed(html[:PAGE_MAX])
    except Exception:
        pass
    g = p.meta.get
    title = (g("og:title") or g("twitter:title") or p.title or "").strip()
    desc = (g("og:description") or g("twitter:description") or g("description") or "").strip()
    image = g("og:image") or g("twitter:image") or ""
    site = (g("og:site_name") or urlsplit(url).hostname or "").strip()
    return {"url": url, "site": site[:60], "title": re.sub(r"\s+", " ", title)[:120],
            "description": re.sub(r"\s+", " ", desc)[:300],
            "image_src": urljoin(url, image) if image else ""}


async def _store_image(src: str) -> dict | None:
    got = await safe_fetch(src, max_bytes=IMAGE_MAX, accept=("image/",))
    if got is None:
        return None
    _, _, data = got
    try:
        from PIL import Image
        im = Image.open(BytesIO(data))
        im.verify()
        im = Image.open(BytesIO(data))
        w, h = im.size
        fmt = (im.format or "").lower()
    except Exception:
        return None
    if w < 50 or h < 50 or w * h > 40_000_000:
        return None
    ext = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif"}.get(fmt)
    if ext is None:
        return None
    from . import storage
    stored = await asyncio.to_thread(storage.save, data, ext, "link_preview")
    return {"image": stored.url, "image_w": w, "image_h": h}


async def build_preview(url: str) -> dict | None:
    got = await safe_fetch(url, max_bytes=PAGE_MAX, accept=("text/html", "application/xhtml"))
    if got is None:
        return None
    final, ctype, body = got
    info = parse_preview(_decode(body, ctype), final)
    if not info["title"] and not info["description"]:
        return None
    src = info.pop("image_src")
    if src:
        img = await _store_image(src)
        if img:
            info.update(img)
    return info


async def attach_preview(chat_id: int, seq: int) -> None:
    """发完消息之后取第一个链接的预览,写回消息并发一个 edit 事件(不标「已编辑」)。"""
    async with SessionLocal() as db:
        msg = await db.scalar(select(ChatMessage).where(ChatMessage.chat_id == chat_id,
                                                        ChatMessage.seq == seq))
        if msg is None or msg.deleted_at is not None:
            return
        found = urls(msg.text or "", msg.entities or [])
        if not found:
            return
        url = found[0]
    try:
        info = await build_preview(url)
    except Exception:
        logger.info("链接预览失败:%s", url, exc_info=True)
        return
    if info is None:
        return
    from .chat_view import message_payload

    async with SessionLocal() as db:
        chat = await db.get(Chat, chat_id)
        msg = await db.scalar(select(ChatMessage).where(ChatMessage.chat_id == chat_id,
                                                        ChatMessage.seq == seq)
                              .with_for_update().execution_options(populate_existing=True))
        if chat is None or msg is None or msg.deleted_at is not None:
            return
        if url not in urls(msg.text or "", msg.entities or []):
            return          # 这期间消息被改了,链接没了
        msg.extra = {**(msg.extra or {}), "preview": info}
        await db.flush()
        await append_chat_event(db, chat_id, "edit", await message_payload(db, chat, msg))
        await db.commit()
