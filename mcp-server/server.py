#!/usr/bin/env python3
"""超级赞 MCP 服务:让 AI 助手替你点餐、发视频、发布小程序和小游戏。

## 它做不到什么(这一点写在最前面)

**付不了款。** 点餐只能把单创建到「待支付」为止,付款那一下在用户自己的
App 里由人按。即使令牌泄露,对方能替你创建一张 15 分钟后自动关闭的
待付单,**但花不掉一分钱**。

**过不了审。** 发视频停在「审核中」,小程序没过审的版本发布不了 ——
审核永远是平台的人做。助手能替你投稿、替你提审,不能替你过审。

**删不掉东西。** 删稿、删应用、改密钥和域名、实名认证、签协议,一项都没有。

这些不是没做完。服务端那一侧也不是靠自觉:助手令牌签发时勾了哪几项权限
(点餐 / 发视频 / 发布小程序),就只放行 `server/app/security.py` 里那几张
白名单(AGENT_SCOPES),**默认拒绝**。所以这里少写一个工具不是"漏了",
是**就算写了也调不通**。

## 本机文件

发视频、传小程序包要读你电脑上的文件(MCP 服务跑在你本机)。为了不被诱导着把
别的文件传出去,只认视频、封面图片、zip 包这几类,先看扩展名再看文件头;
给一个文件夹打包时,只装小程序包允许的那些扩展名,点开头的文件和目录一律跳过
(`.env`、`.git` 进不了包)。

## 为什么不用 MCP SDK

这是开源项目,少一个依赖少一份供应链风险 —— 而 MCP 在 stdio 上就是
一行一个 JSON-RPC 消息,标准库够了。

## 干跑

    SUPERZ_API=... SUPERZ_AGENT_TOKEN=... python3 server.py --selftest

不进 stdio 循环,直接把这个令牌能用的只读工具打一遍,让人在接进客户端**之前**
就知道通不通。
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "superz", "version": "2.0.0"}

API = os.environ.get("SUPERZ_API", "http://127.0.0.1:8010").rstrip("/")
TOKEN = os.environ.get("SUPERZ_AGENT_TOKEN", "")
TIMEOUT = float(os.environ.get("SUPERZ_TIMEOUT", "20"))
#: 传大文件时每一片的超时(秒)。一片 4MB,慢网络上 20 秒不够
UPLOAD_TIMEOUT = float(os.environ.get("SUPERZ_UPLOAD_TIMEOUT", "120"))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class ApiError(Exception):
    """服务端的业务错误。**原样把中文说明带回给模型** ——
    它比任何我在这里编的英文短语都准确,而且是给人看过的话。"""

    def __init__(self, status: int, detail: str):
        super().__init__(f"[{status}] {detail}")
        self.status = status
        self.detail = detail


class ToolError(ApiError):
    """没发请求就拦下的:文件不对、参数不对。"""

    def __init__(self, detail: str):
        super().__init__(0, detail)


def api(method: str, path: str, *, query: dict | None = None, body: dict | None = None,
        data: bytes | None = None, content_type: str | None = None,
        timeout: float | None = None):
    url = API + path
    if query:
        clean = {k: v for k, v in query.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    if body is not None:
        data = json.dumps(body).encode()
        content_type = "application/json"
    req = urllib.request.Request(url, data=data, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw).get("detail")
        except Exception:
            detail = raw[:200].decode("utf-8", "replace")
        if isinstance(detail, dict):
            # 小程序包没过校验时 detail 是 {message, report}:整个带回去,模型才知道改哪一条
            detail = json.dumps(detail, ensure_ascii=False)
        if e.code == 403:
            # 助手令牌撞到能力边界。**把边界说清楚**,否则模型会一直重试
            detail = (f"{detail} —— 这是 AI 助手令牌的能力边界,"
                      f"不是临时故障,重试没有用。")
        raise ApiError(e.code, str(detail))
    except urllib.error.URLError as e:
        raise ApiError(0, f"连不上 {API}:{e.reason}")


def multipart(fields: dict[str, str], name: str, filename: str, payload: bytes,
              ctype: str) -> tuple[bytes, str]:
    boundary = "----superz" + os.urandom(12).hex()
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'
                  f"{v}\r\n".encode())
    safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
    out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
              f'filename="{safe}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
    out.write(payload)
    out.write(f"\r\n--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------------------
# 这个令牌能做什么
# ---------------------------------------------------------------------------

SCOPE_LABELS = {"order": "点餐", "video": "发视频", "miniapp": "发布小程序和小游戏"}
_scopes: set[str] | None = None
_scopes_known = False


def current_scopes() -> set[str] | None:
    """问服务端这个令牌勾了哪几项权限,问一次记住。问不到(没配令牌、老服务端、连不上)回 None,
    那就把工具全列出来 —— 调不通的服务端会用中文说清原因。"""
    global _scopes, _scopes_known
    if not _scopes_known:
        _scopes_known = True
        try:
            _scopes = set((api("GET", "/auth/agent-tokens/current", timeout=5) or {})
                          .get("scopes") or [])
        except ApiError:
            _scopes = None
    return _scopes


# ---------------------------------------------------------------------------
# 本机文件:只认这几类,先看扩展名再看文件头
# ---------------------------------------------------------------------------

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
#: 小程序包里允许的扩展名(和 server/app/services/miniapp_package.py 的 CONTENT_TYPES 一致)
PACKAGE_EXTS = {"css", "gif", "html", "ico", "jpeg", "jpg", "js", "json", "m4a", "map", "mjs",
                "mp3", "mp4", "ogg", "otf", "png", "svg", "ttf", "txt", "wasm", "wav", "webm",
                "webp", "woff", "woff2"}
MAX_VIDEO = 1024 * 1024 * 1024        # 原片 1GB、最长 30 分钟(服务端再核一遍时长)
MAX_COVER = 20 * 1024 * 1024
MAX_PACKAGE = 30 * 1024 * 1024        # 小游戏 30MB、应用 10MB(服务端按应用类型再核)


def _looks_like(head: bytes, kind: str) -> bool:
    if kind == "video":
        return head[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip") \
            or head[:4] == b"\x1a\x45\xdf\xa3"           # mp4 / mov / m4v;webm / mkv
    if kind == "image":
        return head[:8] == b"\x89PNG\r\n\x1a\n" or head[:3] == b"\xff\xd8\xff" \
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
    if kind == "zip":
        return head[:4] == b"PK\x03\x04"
    return False


def local_file(path: str, kind: str) -> Path:
    """验一个要上传的本机文件。不对就在**发请求之前**拦下,说清为什么。"""
    exts, limit, what = {"video": (VIDEO_EXTS, MAX_VIDEO, "视频"),
                         "image": (IMAGE_EXTS, MAX_COVER, "封面图片"),
                         "zip": ({".zip"}, MAX_PACKAGE, "小程序包")}[kind]
    p = Path(os.path.expanduser(str(path))).resolve()
    if not p.is_file():
        raise ToolError(f"找不到这个文件:{path}")
    if p.suffix.lower() not in exts:
        raise ToolError(f"{what}只收 {'、'.join(sorted(exts))} 文件,{p.name} 不是。"
                        "为了不把你电脑上别的文件传出去,其他类型一律不传。")
    size = p.stat().st_size
    if size == 0:
        raise ToolError(f"{p.name} 是空文件")
    if size > limit:
        raise ToolError(f"{p.name} 有 {size / 1024 / 1024:.0f}MB,{what}最大 {limit // 1024 // 1024}MB")
    with p.open("rb") as f:
        head = f.read(16)
    if not _looks_like(head, kind):
        raise ToolError(f"{p.name} 的文件头看着不像{what},没传。扩展名可能被改过。")
    return p


def zip_dir(path: str) -> tuple[bytes, list[str]]:
    """把一个小程序项目文件夹打成 zip。只装包里允许的扩展名;点开头的文件和目录、
    node_modules、符号链接一律跳过,跳过了哪些原样告诉调用方。"""
    root = Path(os.path.expanduser(str(path))).resolve()
    if not root.is_dir():
        raise ToolError(f"找不到这个文件夹:{path}")
    for must in ("index.html", "superz.json"):
        if not (root / must).is_file():
            raise ToolError(f"文件夹根目录要有 index.html 和 superz.json,缺了 {must}"
                            "(包的格式见官网 /developers/quickstart)。"
                            "如果这是源码目录,先构建,再把构建产物那个文件夹给我。")
    buf = io.BytesIO()
    skipped: list[str] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            rel_dir = Path(dirpath).relative_to(root)
            for d in list(dirnames):
                if d.startswith(".") or d in ("node_modules", "__MACOSX"):
                    skipped.append((rel_dir / d).as_posix() + "/")
                    dirnames.remove(d)
            for name in sorted(filenames):
                f = Path(dirpath) / name
                rel = (rel_dir / name).as_posix()
                if name.startswith(".") or f.is_symlink() \
                        or f.suffix.lower().lstrip(".") not in PACKAGE_EXTS:
                    skipped.append(rel)
                    continue
                z.write(f, rel)
    data = buf.getvalue()
    if len(data) > MAX_PACKAGE:
        raise ToolError(f"打包后 {len(data) / 1024 / 1024:.1f}MB,超过 30MB")
    return data, sorted(skipped)


# ---------------------------------------------------------------------------
# 工具:通用
# ---------------------------------------------------------------------------

def t_whoami():
    """这个令牌是谁的、能做哪几件事、什么时候过期。"""
    return api("GET", "/auth/agent-tokens/current")


# ---------------------------------------------------------------------------
# 工具:点餐(权限 order)
# ---------------------------------------------------------------------------

def t_search_merchants(q: str, lat: float, lng: float,
                       sort: str = "comprehensive"):
    return api("GET", "/merchants/search",
               query={"q": q, "lat": lat, "lng": lng, "sort": sort})


def t_get_menu(merchant_id: int):
    return api("GET", f"/merchants/{merchant_id}/dishes")


def t_quote_order(merchant_id: int, lat: float, lng: float,
                  items: list | None = None, to_door: bool = True):
    """算价,**不下单**。

    助手最常做的事是比价,所以这一步单独拆出来 ——
    让它能算清楚再决定,而不是先下一串单再取消。
    """
    fee = api("GET", "/orders/delivery-fee",
              query={"merchant_id": merchant_id, "lat": lat, "lng": lng,
                     "to_door": str(to_door).lower()})
    out = {"delivery": fee}
    if items:
        menu = {d["id"]: d for d in (t_get_menu(merchant_id) or [])}
        food = 0
        missing = []
        for it in items:
            d = menu.get(it.get("dish_id"))
            if d is None:
                missing.append(it.get("dish_id"))
                continue
            food += int(d.get("price_cents", 0)) * int(it.get("quantity", 1))
        out["food_cents"] = food
        if missing:
            out["missing_dish_ids"] = missing
        out["note"] = ("餐费按菜单原价估算,**不含满减/优惠券,也不含规格加价** —— "
                       "真实应付以创建订单后返回的 total_cents 为准。")
    return out


def t_create_pending_order(merchant_id: int, items: list, address: str,
                           lat: float, lng: float, remark: str = "",
                           contact_phone: str = ""):
    """创建**待支付**订单。到此为止 —— 付款要用户在 App 里自己点。"""
    order = api("POST", "/orders", body={
        "merchant_id": merchant_id, "items": items, "address": address,
        "lat": lat, "lng": lng, "remark": remark,
        "contact_phone": contact_phone,
    })
    return {
        "order": order,
        "next_step": ("订单已创建,**还没付钱**。请让用户打开超级赞 App "
                      "的「我的订单」确认并支付 —— 助手没有支付能力。"
                      "15 分钟内不付款会自动关闭,不扣任何费用。"),
    }


def t_get_order_status(order_no: str):
    return api("GET", f"/orders/{order_no}")


def t_list_my_orders(limit: int = 10):
    return api("GET", "/orders", query={"limit": limit})


def t_get_transparency(topic: str = "liability"):
    """平台的公开口径。topic: liability 判责分摊 / dispatch 派单算法 /
    queue 排队规则 / fairness 分账公平 / funds 资金流向。"""
    return api("GET", f"/transparency/{topic}")


# ---------------------------------------------------------------------------
# 工具:发视频(权限 video)
# ---------------------------------------------------------------------------

def _upload_video_source(p: Path) -> dict:
    """分片传原片(每片 4MB,和 App 同一条路)。一片失败重试两次,不从头来。"""
    size = p.stat().st_size
    up = api("POST", "/media/v1/uploads", body={
        "size": size, "name": p.name[:200], "mime": "", "purpose": "video", "kind": "video_source"})
    cs = int(up["chunk_size"])
    with p.open("rb") as f:
        for n in range(int(up["chunks"])):
            f.seek(n * cs)
            piece = f.read(cs)
            for attempt in range(3):
                try:
                    api("PUT", f"/media/v1/uploads/{up['id']}/chunks/{n}", data=piece,
                        content_type="application/octet-stream", timeout=UPLOAD_TIMEOUT)
                    break
                except ApiError as e:
                    if attempt == 2 or (400 <= e.status < 500 and e.status != 429):
                        raise
                    time.sleep(2 * (attempt + 1))
    return api("POST", f"/media/v1/uploads/{up['id']}/complete", body={"kind": "video_source"},
               timeout=UPLOAD_TIMEOUT)


def t_list_video_zones():
    return api("GET", "/video/v1/zones")


def t_publish_video(file_path: str, title: str, zone: str, description: str = "",
                    tags: list | None = None, cover_path: str = "", copyright: str = "original",
                    source_url: str = "", part_title: str = "", submit: bool = True):
    """一条龙:建稿 →(传封面)→ 分片传原片 → 挂上 → 提交审核。提交后是「审核中」,由平台的人审。"""
    video = local_file(file_path, "video")
    cover = local_file(cover_path, "image") if cover_path else None
    body = {"title": title, "zone": zone, "description": description,
            "tags": list(tags or []), "copyright": copyright}
    if source_url:
        body["source_url"] = source_url
    draft = api("POST", "/video/v1/uploads/videos", body=body)
    vid = draft["vid"]
    if cover is not None:
        payload, ctype = multipart({"kind": "cover", "purpose": "video"}, "file", cover.name,
                                   cover.read_bytes(), "application/octet-stream")
        m = api("POST", "/media/v1/upload", data=payload, content_type=ctype,
                timeout=UPLOAD_TIMEOUT)
        api("PATCH", f"/video/v1/videos/{vid}", body={"cover_media_id": m["id"]})
    media = _upload_video_source(video)
    api("POST", f"/video/v1/videos/{vid}/parts", body={"media_id": media["id"],
                                                       "title": part_title[:200]})
    if not submit:
        return {"vid": vid, "status": "draft",
                "next_step": ("草稿建好了,原片在转码,**还没提交审核**。用户确认之后调 submit_video;"
                              "用 get_video_status 看转码进度。")}
    out = api("POST", f"/video/v1/videos/{vid}/submit")
    return {"vid": vid, "status": out.get("status"),
            "next_step": ("已提交审核。转码没完的会先显示「处理中」,转完自动进「审核中」;"
                          "审核由平台的人做,通过后才公开。用 get_video_status 看进度和驳回原因。")}


def t_submit_video(vid: str):
    return api("POST", f"/video/v1/videos/{vid}/submit")


def t_update_video_info(vid: str, title: str | None = None, description: str | None = None,
                        zone: str | None = None, tags: list | None = None):
    body = {k: v for k, v in (("title", title), ("description", description), ("zone", zone),
                              ("tags", tags)) if v is not None}
    if not body:
        raise ToolError("没有要改的:title、description、zone、tags 至少给一个")
    return api("PATCH", f"/video/v1/videos/{vid}", body=body)


def t_get_video_status(vid: str):
    return api("GET", f"/video/v1/creator/videos/{vid}")


def t_list_my_videos():
    return api("GET", "/video/v1/creator/videos")


# ---------------------------------------------------------------------------
# 工具:发布小程序和小游戏(权限 miniapp,开发者账号)
# ---------------------------------------------------------------------------

def t_get_developer_account():
    return api("GET", "/dev/v1/me")


def t_list_developer_messages():
    return api("GET", "/dev/v1/messages")


def t_list_my_miniapps():
    return api("GET", "/dev/v1/apps")


def t_create_miniapp(name: str, kind: str, category: str = "tools", tagline: str = ""):
    return api("POST", "/dev/v1/apps", body={"name": name, "kind": kind, "category": category,
                                             "tagline": tagline})


def t_update_miniapp_listing(appid: str, name: str | None = None, tagline: str | None = None,
                             description: str | None = None, category: str | None = None,
                             icon: str | None = None, privacy_policy: str | None = None):
    body = {k: v for k, v in (("name", name), ("tagline", tagline), ("description", description),
                              ("category", category), ("icon", icon),
                              ("privacy_policy", privacy_policy)) if v is not None}
    if not body:
        raise ToolError("没有要改的:name、tagline、description、category、icon、privacy_policy 至少给一个")
    return api("PUT", f"/dev/v1/apps/{appid}", body=body)


def t_get_miniapp(appid: str):
    return api("GET", f"/dev/v1/apps/{appid}")


def t_upload_miniapp_version(appid: str, path: str, version: str = "", changelog: str = ""):
    """传一个新版本。path 是 zip,或者构建好的那个文件夹(我来打包)。平台逐条校验,
    过了存成不可变版本;没过把校验报告原样带回来。"""
    p = Path(os.path.expanduser(str(path)))
    skipped: list[str] = []
    if p.is_dir():
        data, skipped = zip_dir(str(p))
        fname = "package.zip"
    else:
        f = local_file(str(p), "zip")
        data, fname = f.read_bytes(), f.name
    payload, ctype = multipart({"version": version, "changelog": changelog}, "file", fname, data,
                               "application/zip")
    out = api("POST", f"/dev/v1/apps/{appid}/versions", data=payload, content_type=ctype,
              timeout=UPLOAD_TIMEOUT)
    if skipped:
        out["skipped_files"] = skipped
        out["skipped_note"] = ("打包时跳过了这些(点开头的、node_modules、符号链接、包里不允许的扩展名)。"
                               "如果里面有页面要用的文件,换成允许的格式再传。")
    out["next_step"] = ("版本已存好,还没提交审核。可以先 set_trial_version 设成体验版自己试,"
                        "确认后 submit_miniapp_review;审核通过后才能 release_miniapp_version。")
    return out


def t_list_miniapp_versions(appid: str):
    return api("GET", f"/dev/v1/apps/{appid}/versions")


def t_set_trial_version(appid: str, version_id: int):
    return api("POST", f"/dev/v1/apps/{appid}/versions/{int(version_id)}/trial")


def t_submit_miniapp_review(appid: str, version_id: int, review_note: str = ""):
    return api("POST", f"/dev/v1/apps/{appid}/versions/{int(version_id)}/submit",
               body={"review_note": review_note})


def t_cancel_miniapp_review(appid: str, version_id: int):
    return api("POST", f"/dev/v1/apps/{appid}/versions/{int(version_id)}/withdraw")


def t_release_miniapp_version(appid: str, version_id: int):
    return api("POST", f"/dev/v1/apps/{appid}/versions/{int(version_id)}/release")


def t_rollback_miniapp(appid: str, version_id: int):
    return api("POST", f"/dev/v1/apps/{appid}/rollback", body={"version_id": int(version_id)})


def t_get_review_decisions(appid: str):
    return api("GET", f"/dev/v1/apps/{appid}/decisions")


# ---------------------------------------------------------------------------
# 工具清单
# ---------------------------------------------------------------------------

def _obj(props: dict, required: list | None = None) -> dict:
    s = {"type": "object", "properties": props}
    if required:
        s["required"] = required
    return s


_ITEMS = {"type": "array", "items": {"type": "object"}, "description":
          "[{dish_id, quantity, choices}];choices 是选中的规格/加料名,如 [\"大份\",\"加蛋\"],"
          "菜单里带必选规格的菜不给就下不了单"}
_APPID = {"type": "string", "description": "应用的 AppID,sz 开头,见 list_my_miniapps"}
_VID = {"type": "string", "description": "稿件号,sv 开头"}
_VERSION_ID = {"type": "integer", "description": "版本 id,见 list_miniapp_versions"}

TOOLS = [
    {
        "name": "whoami", "scope": None, "fn": t_whoami,
        "description": "这个 AI 助手令牌是谁的、能做哪几件事(点餐 / 发视频 / 发布小程序和小游戏)、"
                       "什么时候过期。不确定能不能帮用户做某件事时先查它。",
        "inputSchema": _obj({}),
    },
    # ---- 点餐 ----
    {
        "name": "search_merchants", "scope": "order", "fn": t_search_merchants,
        "description": "按位置和关键词找外卖商家。返回评分、距离、起送价。"
                       "排序只用真实评分/销量/距离——平台不做竞价排名。",
        "inputSchema": _obj({
            "q": {"type": "string", "description": "店名或菜名关键词"},
            "lat": {"type": "number", "description": "用户纬度"},
            "lng": {"type": "number", "description": "用户经度"},
            "sort": {"type": "string", "enum": ["comprehensive", "distance", "rating", "sales"]},
        }, ["q", "lat", "lng"]),
    },
    {
        "name": "get_menu", "scope": "order", "fn": t_get_menu,
        "description": "看一家店的菜单:价格、规格(必选的要在下单时带上)、库存、是否已估清。",
        "inputSchema": _obj({"merchant_id": {"type": "integer"}}, ["merchant_id"]),
    },
    {
        "name": "quote_order", "scope": "order", "fn": t_quote_order,
        "description": "算价,**不下单**。返回配送费明细(距离/夜间/天气/上门难度)"
                       "和餐费估算。比价用这个,不要靠反复下单取消。"
                       "注意:餐费按原价估,不含满减、优惠券和规格加价。",
        "inputSchema": _obj({
            "merchant_id": {"type": "integer"},
            "lat": {"type": "number"},
            "lng": {"type": "number"},
            "items": _ITEMS,
            "to_door": {"type": "boolean", "description": "送上门(true)还是送到楼下(false)"},
        }, ["merchant_id", "lat", "lng"]),
    },
    {
        "name": "create_pending_order", "scope": "order", "fn": t_create_pending_order,
        "description": "创建一张**待支付**订单。"
                       "⚠️ 这个工具**不会付款**,也付不了 —— 助手令牌没有支付能力。"
                       "创建完要让用户在超级赞 App 里自己确认支付;"
                       "15 分钟内不付会自动关闭,不扣费。",
        "inputSchema": _obj({
            "merchant_id": {"type": "integer"},
            "items": _ITEMS,
            "address": {"type": "string", "description": "收货地址"},
            "lat": {"type": "number"},
            "lng": {"type": "number"},
            "remark": {"type": "string", "description": "备注,如忌口"},
            "contact_phone": {"type": "string", "description": "联系电话;不传用账号手机号"},
        }, ["merchant_id", "items", "address", "lat", "lng"]),
    },
    {
        "name": "get_order_status", "scope": "order", "fn": t_get_order_status,
        "description": "查一单到哪一步了:待支付/待接单/制作中/待取餐/配送中/"
                       "已送达/已完成,以及预计送达时间。",
        "inputSchema": _obj({"order_no": {"type": "string"}}, ["order_no"]),
    },
    {
        "name": "list_my_orders", "scope": "order", "fn": t_list_my_orders,
        "description": "我最近的订单。",
        "inputSchema": _obj({"limit": {"type": "integer", "description": "默认 10"}}),
    },
    {
        "name": "get_transparency", "scope": "order", "fn": t_get_transparency,
        "description": "平台的公开口径:判责分摊怎么算、派单算法的权重、"
                       "排队规则、分账去向。这些是对所有人公开的承诺,"
                       "用户问「为什么这么收费」时查它。",
        "inputSchema": _obj({"topic": {"type": "string", "enum": [
            "liability", "dispatch", "queue", "fairness", "funds"]}}),
    },
    # ---- 发视频 ----
    {
        "name": "list_video_zones", "scope": "video", "fn": t_list_video_zones,
        "description": "视频分区列表(投稿要选一个分区,用它的 key)。",
        "inputSchema": _obj({}),
    },
    {
        "name": "publish_video", "scope": "video", "fn": t_publish_video,
        "description": "把用户电脑上的一个视频文件投成稿件:建稿 → 传封面(可选)→ 分片传原片 → "
                       "提交审核,一次做完。提交后是「审核中」,**由平台的人审,通过后才公开** —— "
                       "助手能替用户投稿,不能替用户过审。**只在用户明确要求发布时调用**;"
                       "拿不准就传 submit=false 先建草稿,让用户确认后再 submit_video。"
                       "要先在 App 里完成实名认证。视频只收 mp4/mov/m4v/webm/mkv,最大 1GB、30 分钟。",
        "inputSchema": _obj({
            "file_path": {"type": "string", "description": "视频文件在本机的路径"},
            "title": {"type": "string", "description": "标题,200 字以内"},
            "zone": {"type": "string", "description": "分区 key,见 list_video_zones"},
            "description": {"type": "string", "description": "简介"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
            "cover_path": {"type": "string", "description": "封面图片路径(jpg/png/webp);不给用第一帧"},
            "copyright": {"type": "string", "enum": ["original", "repost"],
                          "description": "原创还是转载;转载要给 source_url"},
            "source_url": {"type": "string", "description": "转载的原始出处"},
            "part_title": {"type": "string", "description": "这一 P 的标题,可不填"},
            "submit": {"type": "boolean", "description": "传完直接提交审核(默认 true)"},
        }, ["file_path", "title", "zone"]),
    },
    {
        "name": "submit_video", "scope": "video", "fn": t_submit_video,
        "description": "把草稿提交审核。转码没完的先是「处理中」,转完自动进「审核中」。"
                       "只在用户确认要发布时调用。",
        "inputSchema": _obj({"vid": _VID}, ["vid"]),
    },
    {
        "name": "update_video_info", "scope": "video", "fn": t_update_video_info,
        "description": "改稿件的标题、简介、分区、标签。已发布的稿件改动会进待审,线上仍是原来那一版。",
        "inputSchema": _obj({
            "vid": _VID, "title": {"type": "string"}, "description": {"type": "string"},
            "zone": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}},
        }, ["vid"]),
    },
    {
        "name": "get_video_status", "scope": "video", "fn": t_get_video_status,
        "description": "一个稿件到哪一步了:草稿 / 处理中 / 审核中 / 已发布 / 被驳回(带驳回原因)。",
        "inputSchema": _obj({"vid": _VID}, ["vid"]),
    },
    {
        "name": "list_my_videos", "scope": "video", "fn": t_list_my_videos,
        "description": "我投过的稿件和各自的状态。",
        "inputSchema": _obj({}),
    },
    # ---- 发布小程序和小游戏 ----
    {
        "name": "get_developer_account", "scope": "miniapp", "fn": t_get_developer_account,
        "description": "开发者账号的状态:认证了没有、开发者规则签了没有。没认证、没签规则的"
                       "提交不了审核 —— 那两件要开发者自己在开发者后台做,助手做不了。",
        "inputSchema": _obj({}),
    },
    {
        "name": "list_developer_messages", "scope": "miniapp", "fn": t_list_developer_messages,
        "description": "平台发给开发者的通知(审核结果、处罚、规则更新)。",
        "inputSchema": _obj({}),
    },
    {
        "name": "list_my_miniapps", "scope": "miniapp", "fn": t_list_my_miniapps,
        "description": "我的小程序和小游戏,带 AppID 和状态。",
        "inputSchema": _obj({}),
    },
    {
        "name": "create_miniapp", "scope": "miniapp", "fn": t_create_miniapp,
        "description": "新建一个小程序(kind=app)或小游戏(kind=game)。"
                       "分类:tools 工具 / productivity 效率 / life 生活 / learning 学习 / "
                       "casual 休闲益智 / puzzle 益智解谜。名称 2–20 字,不能用「超级赞」「官方」等字样。",
        "inputSchema": _obj({
            "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["app", "game"]},
            "category": {"type": "string", "enum": ["tools", "productivity", "life", "learning",
                                                    "casual", "puzzle"]},
            "tagline": {"type": "string", "description": "一句话介绍,30 字以内"},
        }, ["name", "kind"]),
    },
    {
        "name": "update_miniapp_listing", "scope": "miniapp", "fn": t_update_miniapp_listing,
        "description": "改上架信息:名称、一句话介绍、详细介绍、分类、图标(一个汉字)、隐私政策。"
                       "提交审核前要把介绍和隐私政策填好。",
        "inputSchema": _obj({
            "appid": _APPID, "name": {"type": "string"}, "tagline": {"type": "string"},
            "description": {"type": "string"}, "category": {"type": "string"},
            "icon": {"type": "string", "description": "一个汉字"},
            "privacy_policy": {"type": "string"},
        }, ["appid"]),
    },
    {
        "name": "get_miniapp", "scope": "miniapp", "fn": t_get_miniapp,
        "description": "一个应用的详情:状态、线上版本、体验版、正在审核的版本、体验链接。",
        "inputSchema": _obj({"appid": _APPID}, ["appid"]),
    },
    {
        "name": "upload_miniapp_version", "scope": "miniapp", "fn": t_upload_miniapp_version,
        "description": "传一个新版本。path 给 zip 文件,或者**构建好的**那个文件夹(根目录要有 index.html "
                       "和 superz.json,我来打包;点开头的文件、node_modules、包里不允许的扩展名会跳过并告诉你)。"
                       "平台逐条校验,没过会把校验报告带回来。传完不会自动提审。",
        "inputSchema": _obj({
            "appid": _APPID,
            "path": {"type": "string", "description": "zip 文件或构建产物文件夹在本机的路径"},
            "version": {"type": "string", "description": "版本号,如 1.2.0"},
            "changelog": {"type": "string", "description": "这一版改了什么"},
        }, ["appid", "path"]),
    },
    {
        "name": "list_miniapp_versions", "scope": "miniapp", "fn": t_list_miniapp_versions,
        "description": "一个应用的全部版本和各自的状态(开发版 / 审核中 / 审核通过 / 被驳回 / 线上)。",
        "inputSchema": _obj({"appid": _APPID}, ["appid"]),
    },
    {
        "name": "set_trial_version", "scope": "miniapp", "fn": t_set_trial_version,
        "description": "把一个版本设成体验版:开发者和体验者能先用,不公开。",
        "inputSchema": _obj({"appid": _APPID, "version_id": _VERSION_ID}, ["appid", "version_id"]),
    },
    {
        "name": "submit_miniapp_review", "scope": "miniapp", "fn": t_submit_miniapp_review,
        "description": "提交审核。审核由平台的人做,结果在 list_developer_messages 和 get_review_decisions 里。"
                       "review_note 写给审核员:怎么打开、要不要测试账号。",
        "inputSchema": _obj({"appid": _APPID, "version_id": _VERSION_ID,
                             "review_note": {"type": "string"}}, ["appid", "version_id"]),
    },
    {
        "name": "cancel_miniapp_review", "scope": "miniapp", "fn": t_cancel_miniapp_review,
        "description": "撤回还在审核中的版本(比如发现包有问题要重传)。",
        "inputSchema": _obj({"appid": _APPID, "version_id": _VERSION_ID}, ["appid", "version_id"]),
    },
    {
        "name": "release_miniapp_version", "scope": "miniapp", "fn": t_release_miniapp_version,
        "description": "把**审核通过**的版本发布上线,所有用户马上用到这一版。没过审的发布不了。"
                       "**只在开发者明确要求上线时调用。**",
        "inputSchema": _obj({"appid": _APPID, "version_id": _VERSION_ID}, ["appid", "version_id"]),
    },
    {
        "name": "rollback_miniapp", "scope": "miniapp", "fn": t_rollback_miniapp,
        "description": "线上版本出问题时,回到之前发布过的某个版本。",
        "inputSchema": _obj({"appid": _APPID, "version_id": _VERSION_ID}, ["appid", "version_id"]),
    },
    {
        "name": "get_review_decisions", "scope": "miniapp", "fn": t_get_review_decisions,
        "description": "一个应用的审核结论和处罚记录,驳回的带原因代码和说明。",
        "inputSchema": _obj({"appid": _APPID}, ["appid"]),
    },
]

BY_NAME = {t["name"]: t for t in TOOLS}


def visible_tools() -> list[dict]:
    """这个令牌能用的工具。不知道令牌能做什么时全列 —— 调不通的服务端会说清原因。"""
    scopes = current_scopes()
    return [t for t in TOOLS if t["scope"] is None or scopes is None or t["scope"] in scopes]


# ---------------------------------------------------------------------------
# JSON-RPC over stdio
# ---------------------------------------------------------------------------

def handle(msg: dict) -> dict | None:
    """处理一条请求。返回 None 表示这是通知(notification),不该回。"""
    method = msg.get("method")
    mid = msg.get("id")

    if method == "initialize":
        return ok(mid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return ok(mid, {})
    if method == "tools/list":
        return ok(mid, {"tools": [
            {k: t[k] for k in ("name", "description", "inputSchema")}
            for t in visible_tools()
        ]})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        tool = BY_NAME.get(name)
        if tool is None:
            return err(mid, -32602, f"没有这个工具:{name}")
        scopes = current_scopes()
        if tool["scope"] is not None and scopes is not None and tool["scope"] not in scopes:
            return ok(mid, {"isError": True, "content": [{"type": "text", "text": (
                f"这个 AI 助手令牌没有「{SCOPE_LABELS[tool['scope']]}」权限。要让助手做这件事,"
                "请用户在超级赞 App「设置 → AI 助手」(开发者在开发者后台「账号」)签一个勾了这一项的令牌。"
            )}]})
        try:
            result = tool["fn"](**(params.get("arguments") or {}))
        except ApiError as e:
            # 业务错误走 isError 而不是协议错误 —— 模型要看到那句中文,
            # 才知道是「余额不够」还是「这家店打烊了」
            return ok(mid, {"isError": True, "content": [
                {"type": "text", "text": e.detail}]})
        except TypeError as e:
            return ok(mid, {"isError": True, "content": [
                {"type": "text", "text": f"参数不对:{e}"}]})
        return ok(mid, {"content": [
            {"type": "text",
             "text": json.dumps(result, ensure_ascii=False, indent=2)}]})

    return err(mid, -32601, f"不支持的方法:{method}")


def ok(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def err(mid, code, message) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code,
                                                   "message": message}}


def serve(stdin=sys.stdin, stdout=sys.stdout) -> None:
    """一行一条 JSON。**读到坏行不能退出** —— 一个格式错的消息
    不该让整个助手连接断掉,那表现是「用着用着突然没反应了」。"""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle(msg)
        except Exception as e:                      # noqa: BLE001
            resp = err(msg.get("id"), -32603, f"内部错误:{e}")
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()


def selftest() -> int:
    """干跑:这个令牌能用的只读工具各打一遍。**不创建订单、不投稿、不传包** ——
    自检不该产生真实的东西。"""
    print(f"API   = {API}")
    print(f"TOKEN = {'已设置' if TOKEN else '(空)'}")
    scopes = current_scopes()
    if scopes is None:
        print("权限  = 问不到(令牌不对,或者服务端还没升级到分权限的版本)")
    else:
        print(f"权限  = {'、'.join(SCOPE_LABELS.get(s, s) for s in sorted(scopes)) or '(没有)'}")
    print()
    checks = [("whoami", t_whoami)]
    if scopes is None or "order" in scopes:
        checks += [("get_transparency", lambda: t_get_transparency("liability")),
                   ("list_my_orders", lambda: t_list_my_orders(3)),
                   ("search_merchants", lambda: t_search_merchants("饭", 30.66, 104.08))]
    if scopes is None or "video" in scopes:
        checks += [("list_video_zones", t_list_video_zones), ("list_my_videos", t_list_my_videos)]
    if scopes is None or "miniapp" in scopes:
        checks += [("get_developer_account", t_get_developer_account),
                   ("list_my_miniapps", t_list_my_miniapps)]
    bad = 0
    for name, fn in checks:
        try:
            r = fn()
            n = len(r) if isinstance(r, (list, dict)) else 0
            print(f"  ✓ {name:24} 通(返回 {n} 项)")
        except ApiError as e:
            print(f"  ✗ {name:24} {e}")
            bad += 1
    print()
    print("  · 下单、投稿、传包、提审、发布不在自检里:它们会产生真实的东西。")
    print("  · 付款工具不存在 —— 助手令牌没有支付能力,这是有意的。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else (serve() or 0))
