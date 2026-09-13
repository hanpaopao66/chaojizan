"""视频 e2e 的公共件(DEV-PROMPTS-40 #357–#368):UP 主(已实名)、现场生成测试片、上传原片、
直接往库里放「已发布」的视频(排序、弹幕、评论这些用例不需要真的转码)、第二名审核员、清限流。

测试素材全部现场生成(ffmpeg 出测试片、Pillow 画封面),不带任何二进制文件进仓库。
跑法同其它 e2e:先起服务,再
`SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_video_xxx`
(直连库 / Redis 的助手读 DATABASE_URL / REDIS_URL,要和服务端指向同一个库)。
"""
import io
import json
import os
import random
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

from tests.chat_util import Person, person, sql
from tests.miniapp_util import admin_token, id_number
from tests.util import BASE, DEMO_PASSWORD, call, fresh_phone, login

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def realname(p: Person, name: str = "测试UP主") -> None:
    """实名认证(D11)。开发环境没配二要素核验时,校验位对的证号直接算过 —— 走的是真接口,不是后门。"""
    call("POST", "/auth/verify-identity", p.token, {"real_name": name, "id_no": id_number()})


def uploader(prefix: str = "139") -> Person:
    p = person(prefix)
    realname(p)
    return p


def ffmpeg_clip(w: int, h: int, secs: float = 4, *, audio: bool = True) -> bytes:
    """现场生成一段 H.264(+AAC)测试片。"""
    args = ["-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=25:duration={secs}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}", "-c:a", "aac",
                 "-shortest"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "clip.mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, out],
                       check=True, timeout=120)
        return open(out, "rb").read()


def png_bytes(w: int = 640, h: int = 360, color=(30, 120, 200)) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def raw(token: str | None, path: str, *, method: str = "GET", data: bytes | None = None,
        headers: dict | None = None) -> tuple[int, dict, bytes]:
    """不解析 JSON 的请求:下载视频、Range、封面。"""
    req = urllib.request.Request(path if path.startswith("http") else BASE + path, data=data,
                                 method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def media_upload(p: Person, data: bytes, name: str, kind: str, purpose: str = "video",
                 expect_error: bool = False) -> dict:
    """整块上传(≤ 20MB)。"""
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("kind", kind), ("purpose", purpose)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                     .encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                 f'filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                 + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    code, _, body = raw(p.token, "/media/v1/upload", method="POST", data=b"".join(parts),
                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    out = json.loads(body or b"{}")
    if code != 200:
        if expect_error:
            return {"_error": code, "detail": out.get("detail")}
        raise SystemExit(f"FAIL 上传 {name}: {code} {out}")
    return out


def chunked_upload(p: Person, data: bytes, name: str, kind: str = "video_source",
                   purpose: str = "video") -> dict:
    """分片上传(投稿的大文件走这条),片乱序传。"""
    up = p.post("/media/v1/uploads", {"size": len(data), "name": name, "kind": kind,
                                      "purpose": purpose})
    cs = up["chunk_size"]
    for n in reversed(range(up["chunks"])):
        code, _, body = raw(p.token, f"/media/v1/uploads/{up['id']}/chunks/{n}", method="PUT",
                            data=data[n * cs:(n + 1) * cs])
        assert code == 200, (code, body)
    return p.post(f"/media/v1/uploads/{up['id']}/complete", {"kind": kind})


def new_video(p: Person, **fields) -> dict:
    body = {"title": "测试视频", "zone": "tech", "tags": ["测试"], "description": "e2e 测试用"}
    body.update(fields)
    return p.post("/video/v1/uploads/videos", body)


def add_part(p: Person, vid: str, media_id: int, title: str = "") -> dict:
    return p.post(f"/video/v1/videos/{vid}/parts", {"media_id": media_id, "title": title})


def creator(p: Person, vid: str) -> dict:
    return p.get(f"/video/v1/creator/videos/{vid}")


def wait_video(p: Person, vid: str, pred, timeout: float = 240, what: str = "") -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = creator(p, vid)
        if pred(last):
            return last
        time.sleep(1)
    raise AssertionError(f"{timeout}s 内稿件 {vid} 没到期望的状态 {what}:"
                         f"status={last and last['status']} pending={last and last['pending']}")


_ADMIN2 = None


def admin2_token() -> str:
    """第二名审核员(直连库建;演示库只有一个管理员)。申诉必须换人处理(S6)。"""
    global _ADMIN2
    if _ADMIN2 is None:
        from app.security import hash_password
        phone = fresh_phone("135")
        sql("INSERT INTO users (phone, name, role, password_hash, is_online, avatar_url) "
            "VALUES (:p, '审核员乙', 'admin', :h, false, '')",
            {"p": phone, "h": hash_password(DEMO_PASSWORD)})
        _ADMIN2 = login(phone)
    return _ADMIN2


def new_vid() -> str:
    return "sv" + "".join(secrets.choice(_B58) for _ in range(10))


def fixture_video(uploader_id: int, *, title: str = "测试视频", zone: str = "life",
                  vertical: bool = False, duration_ms: int = 60_000, hours_ago: float = 1,
                  tags: list[str] | None = None, description: str = "",
                  allow_danmaku: bool = True, allow_comments: bool = True,
                  copyright: str = "original") -> dict:
    """直接往库里放一个「已发布」的视频(带一个就绪的分 P)。
    排序、弹幕、评论这些用例测的是转码之后的事,不必每次真的转码;投稿到发布的全流程在 e2e_video_upload。"""
    vid = new_vid()
    vid_id = sql(
        "INSERT INTO videos (vid, uploader_id, title, description, zone, tags, status, visibility, "
        "is_vertical, duration_ms, allow_danmaku, allow_comments, copyright, published_at, "
        "submitted_at) VALUES (:vid, :u, :t, :d, :z, :tags, 'published', 'public', :vert, :dur, "
        ":ad, :ac, :cr, now() - make_interval(secs => :secs), now()) RETURNING id",
        {"vid": vid, "u": uploader_id, "t": title, "d": description, "z": zone,
         "tags": tags or [], "vert": vertical, "dur": duration_ms, "ad": allow_danmaku,
         "ac": allow_comments, "cr": copyright, "secs": hours_ago * 3600}, fetch="scalar")
    w, h = (720, 1280) if vertical else (1280, 720)
    part_id = sql(
        "INSERT INTO video_parts (video_id, idx, title, status, duration_ms, w, h, live) "
        "VALUES (:v, 0, 'P1', 'ready', :dur, :w, :h, true) RETURNING id",
        {"v": vid_id, "dur": duration_ms, "w": w, "h": h}, fetch="scalar")
    return {"vid": vid, "id": vid_id, "part_id": part_id}


def clear_rate_limits(scope: str, user_id: int) -> None:
    """清掉某人在某个限流桶里的计数(测限流以外的用例不该被自家限流卡住,也不该为此真等 5 秒)。"""
    import redis

    from app.config import settings
    r = redis.Redis.from_url(settings.redis_url)
    try:
        for pat in (f"rls:{scope}:{user_id}:*", f"rld:{scope}:{user_id}:*", f"rl:{scope}:{user_id}:*"):
            for k in r.scan_iter(match=pat):
                r.delete(k)
    finally:
        r.close()


def set_coins(user_id: int, coins: int) -> None:
    """测试夹具:给某人放几枚硬币(真实来源只有每日首次和投稿过审,S4;这里只是省得等明天)。"""
    sql("INSERT INTO social_profiles (user_id, public_id, privacy, notify, bio, "
        "personalize_video, coins, user_pts) VALUES (:u, :pid, '{}', '{}', '', true, :c, 0) "
        "ON CONFLICT (user_id) DO UPDATE SET coins = :c",
        {"u": user_id, "pid": "t" + uuid.uuid4().hex[:11], "c": coins})


def set_flag(key: str, value: str | None) -> None:
    """平台开关:走管理员接口拨;value=None 表示删掉这一行(回到缺省值,开发环境是开)。"""
    if value is None:
        sql("DELETE FROM platform_flags WHERE key = :k", {"k": key})
    else:
        call("POST", f"/admin/flags/{key}", admin_token(), {"value": value, "reason": "e2e"})


def rand_name(base: str) -> str:
    return f"{base}{random.randint(10000, 99999)}"


__all__ = ["Person", "person", "sql", "call", "admin_token", "admin2_token", "realname",
           "uploader", "ffmpeg_clip", "png_bytes", "raw", "media_upload", "chunked_upload",
           "new_video", "add_part", "creator", "wait_video", "fixture_video",
           "clear_rate_limits", "set_coins", "set_flag", "rand_name", "BASE"]
