"""音乐 e2e 的公共件(DEV-PROMPTS-41 #378):音乐人、现场生成测试音频、上传、转码等待、
一条龙发布(开通 → 建作品 → 加歌 → 提交 → 过审)。

测试素材全部现场生成(ffmpeg 出正弦波、Pillow 画封面),**不带任何二进制文件进仓库**。
跑法同其它 e2e:先起服务,再
`SUPERZ_API=http://127.0.0.1:8110 DATABASE_URL=… REDIS_URL=… python -m tests.e2e_music_xxx`。
"""
import json
import os
import subprocess
import tempfile
import time
import uuid

from tests.chat_util import Person, person, sql
from tests.util import BASE, call
from tests.video_util import (admin2_token, admin_token, clear_rate_limits, png_bytes, raw,
                              rand_name, set_flag)

__all__ = ["Person", "person", "sql", "call", "BASE", "admin_token", "admin2_token",
           "clear_rate_limits", "png_bytes", "raw", "rand_name", "set_flag",
           "tone", "upload_audio", "upload_cover", "artist", "new_release", "add_track",
           "wait_ready", "publish_release", "studio_release", "approve", "TRACK_SECONDS"]

#: 测试音频的长度:要过 §5.4 的门槛(min(30 秒, 时长一半)),6 秒的歌听 3 秒就算一次收听
TRACK_SECONDS = 6


def tone(seconds: float = TRACK_SECONDS, hz: int = 440, fmt: str = "wav") -> bytes:
    """现场生成一段正弦波。fmt: wav(默认)/ flac(顺带测 sniff 认不认 fLaC)/ mp3。"""
    codec = {"wav": ["-c:a", "pcm_s16le"], "flac": ["-c:a", "flac"],
             "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"]}[fmt]
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, f"clip.{fmt}")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}",
                        *codec, out], check=True, timeout=120)
        return open(out, "rb").read()


def _multipart(p: Person, data: bytes, name: str, kind: str, purpose: str,
               expect_error: bool = False) -> dict:
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


def upload_audio(p: Person, data: bytes | None = None, name: str = "demo.wav",
                 expect_error: bool = False) -> dict:
    """整块上传一段音频(用途 music、类型 audio_source)。"""
    return _multipart(p, data if data is not None else tone(), name, "audio_source", "music",
                      expect_error)


def upload_cover(p: Person, expect_error: bool = False) -> dict:
    return _multipart(p, png_bytes(600, 600, (200, 80, 40)), "cover.png", "cover", "music",
                      expect_error)


def chunked_audio(p: Person, data: bytes, name: str = "big.wav") -> dict:
    """分片上传(音频走这条,片乱序传)。"""
    up = p.post("/media/v1/uploads", {"size": len(data), "name": name, "kind": "audio_source",
                                      "purpose": "music"})
    cs = up["chunk_size"]
    for n in reversed(range(up["chunks"])):
        code, _, body = raw(p.token, f"/media/v1/uploads/{up['id']}/chunks/{n}", method="PUT",
                            data=data[n * cs:(n + 1) * cs])
        assert code == 200, (code, body)
    return p.post(f"/media/v1/uploads/{up['id']}/complete", {"kind": "audio_source"})


def artist(p: Person | None = None, name: str | None = None, **fields) -> tuple[Person, dict]:
    """开通音乐人(不要求实名,M2)。返回 (人, artist)。"""
    p = p or person()
    body = {"name": name or rand_name("测试音乐人"), "bio": "e2e 测试用", "genres": ["pop"]}
    body.update(fields)
    out = p.post("/music/v1/studio/artist", body)
    assert out["artist"]["aid"].startswith("ma"), out
    return p, out["artist"]


def new_release(p: Person, **fields) -> dict:
    body = {"title": rand_name("测试专辑"), "kind": "single", "genre": "pop",
            "language": "mandarin", "description": "e2e 测试用"}
    body.update(fields)
    return p.post("/music/v1/studio/releases", body)


def add_track(p: Person, rid: str, media_id: int, **fields) -> dict:
    body = {"title": rand_name("测试歌曲"), "media_id": media_id, "declaration": "original"}
    body.update(fields)
    return p.post(f"/music/v1/studio/releases/{rid}/tracks", body)


def studio_release(p: Person, rid: str) -> dict:
    items = p.get("/music/v1/studio/releases")["items"]
    hit = next((x for x in items if x["rid"] == rid), None)
    assert hit is not None, f"作品 {rid} 不在音乐人中心里"
    return hit


def wait_ready(p: Person, rid: str, timeout: float = 180) -> dict:
    """等这个作品里的歌全部转完码。失败(failed)也返回,由调用方断言。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = studio_release(p, rid)
        states = {t["transcode_status"] for t in last["tracks"]}
        if states and states <= {"ready", "failed"}:
            return last
        time.sleep(1)
    raise AssertionError(f"{timeout}s 内作品 {rid} 的歌没转完:"
                         f"{[(t['title'], t['transcode_status']) for t in (last or {}).get('tracks', [])]}")


def approve(rid: str, token: str | None = None, note: str = "e2e 通过") -> dict:
    return call("POST", f"/admin/music/releases/{rid}/decide", token or admin_token(),
                {"action": "approve", "note": note})


def publish_release(p: Person, *, tracks: int = 1, **fields) -> dict:
    """一条龙:建作品 → 传封面 → 加歌 → 等转码 → 提交 → 过审。返回音乐人中心里的作品。"""
    cover = upload_cover(p)
    r = new_release(p, cover_media_id=cover["id"], **fields)
    rid = r["rid"]
    for i in range(tracks):
        src = upload_audio(p, tone(hz=440 + i * 30), f"t{i}.wav")
        add_track(p, rid, src["id"], title=rand_name(f"第{i + 1}首"))
    wait_ready(p, rid)
    p.post(f"/music/v1/studio/releases/{rid}/submit")
    approve(rid)
    return studio_release(p, rid)
