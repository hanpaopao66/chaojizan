"""媒体 e2e(DEV-PROMPTS-40 #341 #342 #347,不变量 S1)。

测试素材全部现场生成(Pillow 画图、wave 写正弦波、ffmpeg 出测试片),不带任何二进制文件进仓库。
需要本机有 ffmpeg(服务端镜像里有;CI 的 ubuntu 自带)。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_media
"""
import hashlib
import io
import json
import math
import os
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import wave

from tests.chat_util import WS, person
from tests.util import BASE


def upload(p, data: bytes, name: str, kind: str, purpose: str = "chat",
           expect_error: bool = False):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("kind", kind), ("purpose", purpose)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                     .encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                 f'filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                 + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(BASE + "/media/v1/upload", data=b"".join(parts), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {p.token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read() or b"{}")
        if expect_error:
            return {"_error": e.code, "detail": body.get("detail")}
        raise SystemExit(f"FAIL 上传 {name}: {e.code} {body}")


def raw(p, path: str, *, method="GET", data: bytes | None = None, headers=None):
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if p is not None:
        req.add_header("Authorization", f"Bearer {p.token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def png_bytes(w=640, h=480) -> bytes:
    from PIL import Image
    im = Image.new("RGB", (w, h), (200, 80, 40))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def jpeg_with_gps() -> bytes:
    from PIL import Image
    im = Image.new("RGB", (800, 600), (40, 120, 200))
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (34.0, 16.0, 0.0), 3: "E", 4: (108.0, 57.0, 0.0)}  # GPSInfo
    b = io.BytesIO()
    im.save(b, "JPEG", exif=exif)
    return b.getvalue()


def wav_bytes(seconds=2.0) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        frames = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / 16000)
                                                 * (i / (16000 * seconds))))
                          for i in range(int(16000 * seconds)))
        w.writeframes(frames)
    return b.getvalue()


def ffmpeg_clip(args: list[str], suffix: str) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "clip" + suffix)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, out],
                       check=True, timeout=120)
        return open(out, "rb").read()


def gif_bytes() -> bytes:
    from PIL import Image
    frames = [Image.new("RGB", (120, 90), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    b = io.BytesIO()
    frames[0].save(b, "GIF", save_all=True, append_images=frames[1:], duration=200, loop=0)
    return b.getvalue()


def wait_ready(p, mid: int, timeout=120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        m = p.get(f"/media/v1/media/{mid}")
        if m["status"] != "processing":
            return m
        time.sleep(1)
    raise AssertionError(f"媒体 {mid} {timeout}s 还没处理完")


def main():
    a, b, c = person(), person(), person()
    chat = a.private_with(b)
    cid = chat["id"]

    # ---- 图片:去定位、出缩略图 ----
    ph = upload(a, png_bytes(), "a.png", "photo")
    assert ph["kind"] == "photo" and ph["status"] == "ready" and (ph["w"], ph["h"]) == (640, 480), ph
    code, hdr, body = raw(a, ph["thumb"])
    assert code == 200 and hdr["content-type"].startswith("image/jpeg"), (code, hdr)
    gps = upload(a, jpeg_with_gps(), "gps.jpg", "photo")
    code, _, body = raw(a, gps["url"])
    from PIL import Image
    assert 0x8825 not in Image.open(io.BytesIO(body)).getexif(), "照片里的定位信息必须去掉"
    print("  ✓ 图片:宽高、缩略图;EXIF 定位去掉了")

    # ---- 伪装成图片的文件 ----
    fake = upload(a, b"MZ\x90\x00" + os.urandom(2000), "cute.jpg", "photo")
    assert fake["kind"] == "file" and fake["thumb"] is None, fake
    code, hdr, _ = raw(a, fake["url"])
    assert hdr["content-type"] == "application/octet-stream" and "attachment" in \
        hdr.get("content-disposition", ""), hdr
    print("  ✓ 改名成 .jpg 的可执行文件按「文件」处理:不预览、强制下载")

    # ---- 语音 ----
    vo = upload(a, wav_bytes(2.0), "rec.wav", "voice")
    assert vo["kind"] == "voice" and vo["mime"] == "audio/mp4", vo
    assert 1800 <= vo["duration_ms"] <= 2300 and len(vo["waveform"]) == 64, vo
    assert max(vo["waveform"]) == 31 and vo["waveform"][0] < vo["waveform"][-1], \
        "渐强的正弦波,波形应该前低后高"
    print(f"  ✓ 语音:转成 AAC m4a,时长 {vo['duration_ms']}ms,64 格波形")

    # ---- 视频:免转码 / 要转码 ----
    mp4 = ffmpeg_clip(["-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=2",
                       "-f", "lavfi", "-i", "sine=frequency=500:duration=2",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"], ".mp4")
    v1 = upload(a, mp4, "ok.mp4", "video")
    assert v1["status"] == "ready" and v1["mime"] == "video/mp4" and (v1["w"], v1["h"]) == (640, 360), v1
    webm = ffmpeg_clip(["-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=25:duration=2",
                        "-c:v", "libvpx-vp9", "-b:v", "1M", "-an"], ".webm")
    wa = WS(a.token)
    wa.wait_for(lambda f: f.get("t") == "ready")
    v2 = upload(a, webm, "big.webm", "video")
    assert v2["status"] == "processing", v2
    r = a.send(cid, "", kind="video", media_ids=[v2["id"]], expect_error=True)
    assert r.get("_error") == 409 and "处理中" in r["detail"], r
    done = wa.wait_for(lambda f: f.get("t") == "uev" and f.get("type") == "media"
                       and f["data"]["id"] == v2["id"], timeout=180)
    assert done["data"]["status"] == "ready" and done["data"]["h"] == 720, done["data"]
    print("  ✓ 视频:H.264/AAC 直接可用;1080p VP9 进队列转成 720p,做完推 media 事件;处理中不能发")

    # ---- GIF ----
    g = upload(a, gif_bytes(), "a.gif", "gif")
    g = wait_ready(a, g["id"])
    assert g["kind"] == "gif" and g["mime"] == "video/mp4" and g["status"] == "ready", g
    print("  ✓ GIF 转成无声 MP4")

    # ---- 分片续传 + Range ----
    blob = os.urandom(9 * 1024 * 1024 + 123)
    up = a.post("/media/v1/uploads", {"size": len(blob), "name": "数据包.bin", "kind": "file"})
    cs = up["chunk_size"]
    assert up["chunks"] == 3, up
    for n in (2, 0):
        code, _, _ = raw(a, f"/media/v1/uploads/{up['id']}/chunks/{n}", method="PUT",
                         data=blob[n * cs:(n + 1) * cs])
        assert code == 200, code
    st = a.get(f"/media/v1/uploads/{up['id']}")
    assert st["received"] == [0, 2], st
    r = a.post(f"/media/v1/uploads/{up['id']}/complete", {"kind": "file"}, expect_error=True)
    assert r.get("_error") == 409, "还有片没传完时不能完成"
    code, _, _ = raw(a, f"/media/v1/uploads/{up['id']}/chunks/1", method="PUT",
                     data=blob[cs:2 * cs][:-1])
    assert code == 422, "片的大小不对要拒"
    raw(a, f"/media/v1/uploads/{up['id']}/chunks/1", method="PUT", data=blob[cs:2 * cs])
    f = a.post(f"/media/v1/uploads/{up['id']}/complete", {"kind": "file"})
    assert f["size"] == len(blob) and f["name"] == "数据包.bin", f
    code, hdr, part = raw(a, f["url"], headers={"Range": "bytes=100-199"})
    assert code == 206 and part == blob[100:200] and hdr["content-range"] == \
        f"bytes 100-199/{len(blob)}", (code, hdr)
    code, _, whole = raw(a, f["url"])
    assert hashlib.sha256(whole).hexdigest() == hashlib.sha256(blob).hexdigest()
    code, _, _ = raw(a, f["url"], headers={"Range": f"bytes={len(blob) + 5}-"})
    assert code == 416
    print("  ✓ 分片续传:乱序传、查进度、缺片不能完成、片大小校验;下载支持 Range,整份 SHA-256 一致")

    # ---- 判权(S1)----
    for who in (b, c):
        code, _, _ = raw(who, ph["url"])
        assert code == 404, f"没发出来之前,别人拿不到:{code}"
    plain = f"/media/v1/files/{ph['id']}"
    assert raw(None, plain)[0] == 404, "没登录、不带签名拿不到"
    forged = ph["url"].replace(f"u={a.id}", f"u={c.id}")
    assert raw(None, forged)[0] == 404, "把签名地址里的用户换成别人:签名对不上"
    m = a.send(cid, "", kind="photo", media_ids=[ph["id"]])
    assert m["media"][0]["id"] == ph["id"] and m["media"][0]["thumb"], m
    assert raw(b, plain)[0] == 200, "发到私聊之后,对方能下载"
    assert raw(c, plain)[0] == 404, "S1:会话外的人还是拿不到"
    b_url = next(x for x in b.get(f"/chat/v1/chats/{cid}/messages")["messages"]
                 if x["seq"] == m["seq"])["media"][0]["url"]
    assert f"u={b.id}" in b_url and raw(None, b_url)[0] == 200, "B 的签名地址不带头也能下(网页版 <video> 用)"
    signed = b.post("/media/v1/sign", {"ids": [ph["id"]]})["items"]
    assert f"u={b.id}" in signed[str(ph["id"])]["url"]
    assert c.post("/media/v1/sign", {"ids": [ph["id"]]})["items"] == {}, "看不了的不给签"
    a.post(f"/chat/v1/chats/{cid}/messages/delete", {"seqs": [m["seq"]], "revoke": True})
    assert raw(b, plain)[0] == 404, "为双方删除之后,对方再也拿不到这个文件"
    assert raw(None, b_url)[0] == 404, "签名地址也跟着失效:签名绑人,下载时照样判权"
    cm = upload(c, png_bytes(100, 100), "c.png", "photo")
    r = a.send(cid, "", kind="photo", media_ids=[cm["id"]], expect_error=True)
    assert r.get("_error") == 404, "不能拿别人上传的文件发消息"
    print("  ✓ S1:发出来之前只有自己能下;签名绑人不能改;会话里的人能下、外人不能;删了连签名地址一起失效;不能盗用别人的文件")

    # ---- 各类媒体消息 ----
    for kind, media in (("voice", vo), ("video", v1), ("file", f), ("gif", g)):
        mm = a.send(cid, "说明文字" if kind == "video" else "", kind=kind, media_ids=[media["id"]])
        assert mm["kind"] == kind and mm["media"][0]["id"] == media["id"], mm
        if kind == "voice":
            assert len(mm["media"][0]["waveform"]) == 64
    got = [x["kind"] for x in b.get(f"/chat/v1/chats/{cid}/messages")["messages"]][-4:]
    assert got == ["voice", "video", "file", "gif"], got
    shared = b.get(f"/chat/v1/chats/{cid}/search?kind=photo")["items"]
    assert [x["kind"] for x in shared] == ["gif", "video"], [x["kind"] for x in shared]
    print("  ✓ 语音 / 视频(带说明)/ 文件 / GIF 消息;共享媒体页按类型筛")

    # ---- 配额 ----
    day = time.strftime("%Y%m%d", time.gmtime(time.time() + 8 * 3600))
    import redis
    from app.config import settings
    rc = redis.Redis.from_url(settings.redis_url)
    rc.set(f"media:bytes:{c.id}:{day}", 2 * 1024 ** 3 - 10)
    r = upload(c, png_bytes(), "big.png", "photo", expect_error=True)
    assert r.get("_error") == 413 and "2GB" in r["detail"], r
    rc.delete(f"media:bytes:{c.id}:{day}")
    print("  ✓ 每人每天 2GB 上传配额")

    wa.close()
    print("e2e_media 全部通过 ✅")


if __name__ == "__main__":
    main()
