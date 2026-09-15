"""媒体:收文件、认格式、出缩略图、判权(DEV-PROMPTS-40 #341)。

**判格式看内容不看名字**(和图片上传同一个原则):把 .exe 改名成 .jpg 发过来,
这里认出来是「文件」,按文件存、不预览、不生成缩略图。

判权(S1)按用途分流:
- chat:上传者本人;或者这个媒体出现在「我能读的某条消息」里(GIN 索引查 media 列);
- sticker / preview:公开;
- video:交给视频模块(投稿状态、可见性)。
"""
import asyncio
import hashlib
import logging
import shutil
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ACTIVE_ROLES, Chat, ChatMember, ChatMessage, MediaFile, MessageHide, User
from . import storage, transcode

logger = logging.getLogger("superz.media")

TMP_DIR = storage.PRIVATE_DIR / "_media_tmp"

#: 各类单个文件的上限(D8)
LIMITS = {
    "photo": 20 * 1024 * 1024,
    "gif": 20 * 1024 * 1024,
    "sticker": 1024 * 1024,
    "voice": 20 * 1024 * 1024,
    "video_note": 50 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
    "file": 100 * 1024 * 1024,
    "video_source": 1024 * 1024 * 1024,
    #: 音乐原始音频(DEV-PROMPTS-41 M4):单首 ≤ 200MB。无损(flac / wav)按这个上限也够二十分钟
    "audio_source": 200 * 1024 * 1024,
    "cover": 10 * 1024 * 1024,
    "chat_photo": 10 * 1024 * 1024,
}
#: 每人每天上传总量(§5.7)
DAILY_BYTES = 2 * 1024 * 1024 * 1024
THUMB_EDGE = 320
PHOTO_EDGE = 2560

_HEIF_BRANDS = {b"heic", b"heix", b"heif", b"hevc", b"mif1", b"msf1"}


def sniff(head: bytes) -> tuple[str, str, str]:
    """前 64 字节 → (大类, 扩展名, mime)。大类:image / gif / video / audio / file。"""
    if head[:3] == b"\xff\xd8\xff":
        return "image", ".jpg", "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", ".png", "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", ".webp", "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", ".gif", "image/gif"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _HEIF_BRANDS:
            return "image", ".heic", "image/heic"
        if brand in (b"M4A ", b"M4B "):
            return "audio", ".m4a", "audio/mp4"
        if brand.startswith(b"qt"):
            return "video", ".mov", "video/quicktime"
        return "video", ".mp4", "video/mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video", ".webm", "video/webm"
    if head[:4] == b"OggS":
        return "audio", ".ogg", "audio/ogg"
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio", ".mp3", "audio/mpeg"
    if head[:2] in (b"\xff\xf1", b"\xff\xf9"):
        return "audio", ".aac", "audio/aac"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio", ".wav", "audio/wav"
    # FLAC(DEV-PROMPTS-41 M4 允许上传的格式之一):魔数就是四个字母 fLaC
    if head[:4] == b"fLaC":
        return "audio", ".flac", "audio/flac"
    if head[:6] == b"#!AMR\n":
        return "audio", ".amr", "audio/amr"
    return "file", "", "application/octet-stream"


def resolve_kind(declared: str, category: str) -> str:
    """客户端说它是什么 + 内容实际是什么 → 最终类型。说是图片、实际是别的,一律按文件。"""
    if declared == "file":
        return "file"
    if declared in ("photo", "chat_photo", "cover", "sticker"):
        return declared if category == "image" else ("gif" if category == "gif" and
                                                     declared == "photo" else "file")
    if declared == "gif":
        return "gif" if category in ("gif", "video") else "file"
    if declared in ("video", "video_note", "video_source"):
        return declared if category == "video" else "file"
    if declared == "voice":
        return "voice" if category in ("audio", "video") else "file"
    # 音乐原始音频(DEV-PROMPTS-41 M4):mp3 / m4a / aac / flac / wav / ogg。
    # 带封面图的 mp3 会被认成 video(ffmpeg 把内嵌封面当一路视频流),所以 video 也放进来 ——
    # 真的是不是音频由 music_media 的 ffprobe 说了算,那里没有音轨会失败
    if declared == "audio_source":
        return "audio_source" if category in ("audio", "video") else "file"
    return {"image": "photo", "gif": "gif", "video": "video", "audio": "file"}.get(category, "file")


def new_key(kind: str, owner_id: int | None, ext: str) -> str:
    return f"media/{kind}/u{owner_id or 0}/{uuid.uuid4().hex}{ext}"


async def check_quota(user_id: int, size: int) -> None:
    """每人每天 2GB(按北京日期)。"""
    from ..redis_client import get_redis
    import time as _t
    day = _t.strftime("%Y%m%d", _t.gmtime(_t.time() + 8 * 3600))
    key = f"media:bytes:{user_id}:{day}"
    try:
        r = get_redis()
        used = int(await r.get(key) or 0)
        if used + size > DAILY_BYTES:
            raise HTTPException(413, "今天上传的文件总量超过 2GB 了,明天再传")
        await r.incrby(key, size)
        await r.expire(key, 26 * 3600)
    except HTTPException:
        raise
    except Exception:
        logger.warning("上传配额检查失败,放行", exc_info=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _image_process(src: Path, kind: str) -> tuple[bytes, bytes, int, int, str, str]:
    """图片:转方向、去 EXIF(定位)、长边限到 2560、出缩略图。返回 (主图, 缩略图, 宽, 高, 扩展名, mime)。"""
    from PIL import Image, ImageOps

    data = src.read_bytes()
    try:
        im = Image.open(BytesIO(data))
        if (im.format or "").upper() in ("HEIF", "HEIC") or data[4:8] == b"ftyp":
            import pillow_heif
            pillow_heif.register_heif_opener()
            im = Image.open(BytesIO(data))
    except Exception as e:
        raise HTTPException(422, "图片打不开,可能已损坏") from e
    # 分辨率要在**解码之前**判:open 只读文件头,尺寸是白拿的;下面的 exif_transpose 会把整张图解出来 ——
    # 一张 1.7 亿像素的小文件(纯色 PNG 压得很小)解开要半个 G 内存,几个并发就能把机器打满
    if im.width * im.height > 80_000_000:
        raise HTTPException(422, "图片分辨率太大了")
    try:
        im = ImageOps.exif_transpose(im)
    except Exception as e:
        raise HTTPException(422, "图片打不开,可能已损坏") from e
    has_alpha = im.mode in ("RGBA", "LA", "P") and kind in ("sticker",)
    edge = 512 if kind == "sticker" else PHOTO_EDGE
    if max(im.size) > edge:
        im.thumbnail((edge, edge))
    out = BytesIO()
    if has_alpha or (kind == "sticker"):
        im = im.convert("RGBA")
        im.save(out, "WEBP", quality=90)
        ext, mime = ".webp", "image/webp"
    else:
        im = im.convert("RGB")
        im.save(out, "JPEG", quality=90, optimize=True)   # 重新编码 = 丢掉 EXIF(含定位)
        ext, mime = ".jpg", "image/jpeg"
    th = im.copy()
    th.thumbnail((THUMB_EDGE, THUMB_EDGE))
    tb = BytesIO()
    th.convert("RGB").save(tb, "JPEG", quality=70)
    return out.getvalue(), tb.getvalue(), im.width, im.height, ext, mime


async def _thumb_from_video(src: Path, at: float) -> bytes | None:
    dst = src.with_suffix(".thumb.jpg")
    try:
        await transcode.run(transcode.thumb_args(str(src), str(dst), at, THUMB_EDGE * 2),
                            timeout=60)
        return dst.read_bytes() if dst.exists() else None
    except transcode.TranscodeError:
        return None
    finally:
        dst.unlink(missing_ok=True)


async def _waveform(src: Path) -> list[int]:
    try:
        pcm = await transcode.run(transcode.pcm_args(str(src)), timeout=120, capture=True)
    except transcode.TranscodeError:
        return [0] * 64
    return transcode.waveform_from_pcm(pcm)


async def ingest(db: AsyncSession, owner: User, src: Path, *, declared: str, name: str,
                 purpose: str = "chat") -> MediaFile:
    """收下一个已经落在本地的文件(整块上传或分片拼好的),按类型处理后进对象存储。

    图片、语音、短视频的处理在这里同步做完(都是秒级);需要转码的视频先进库(processing),
    转码交给队列(workers/media.py),做完发一个用户事件 `media` 告诉上传的人。
    """
    size = src.stat().st_size
    with open(src, "rb") as f:
        head = f.read(64)
    category, ext, mime = sniff(head)
    kind = resolve_kind(declared, category)
    limit = LIMITS.get(kind, LIMITS["file"])
    if size > limit:
        raise HTTPException(413, f"这类文件最大 {limit // 1024 // 1024}MB")
    if size == 0:
        raise HTTPException(422, "文件是空的")
    private = purpose not in ("sticker", "chat_photo")
    mf = MediaFile(owner_id=owner.id, purpose=purpose, private=private, kind=kind, mime=mime,
                   size=size, name=(name or "")[:200], status="ready", waveform=[], meta={},
                   created_at=datetime.now(timezone.utc))
    work = TMP_DIR / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=True)
    try:
        if kind in ("photo", "sticker", "chat_photo", "cover"):
            main, thumb, w, h, ext2, mime2 = await asyncio.to_thread(_image_process, src, kind)
            mf.w, mf.h, mf.mime, mf.size = w, h, mime2, len(main)
            mf.key = new_key(kind, owner.id, ext2)
            await asyncio.to_thread(storage.backend().put, main, mf.key, private)
            mf.thumb_key = mf.key.replace(ext2, ".thumb.jpg")
            await asyncio.to_thread(storage.backend().put, thumb, mf.thumb_key, private)
            mf.sha256 = hashlib.sha256(main).hexdigest()
        elif kind in ("voice",):
            if not transcode.have_ffmpeg():
                raise HTTPException(503, "服务器缺少 ffmpeg,暂时发不了语音")
            dst = work / "voice.m4a"
            await transcode.run(transcode.voice_args(str(src), str(dst)), timeout=120)
            p = await transcode.probe(dst)
            mf.duration_ms, mf.mime, mf.size = p.duration_ms, "audio/mp4", dst.stat().st_size
            mf.waveform = await _waveform(dst)
            mf.key = new_key(kind, owner.id, ".m4a")
            await asyncio.to_thread(storage.put_path, dst, mf.key, private, "audio/mp4")
            mf.sha256 = await asyncio.to_thread(_sha256, dst)
        elif kind == "audio_source":
            # 音乐的原始音频(DEV-PROMPTS-41 #378):原样收下、进私密桶,**这里不转码**。
            # 转 AAC 是在歌曲挂到作品上之后由队列做的(services/music_media.py),
            # 和投稿原片(video_source)同一个分工:上传只负责「收得下、认得出」
            if not transcode.have_ffmpeg():
                raise HTTPException(503, "服务器缺少 ffmpeg,暂时传不了歌曲")
            p = await transcode.probe(src)
            if not p.acodec:
                raise HTTPException(422, "这个文件里没有声音")
            mf.duration_ms = p.duration_ms
            orig_key = new_key(kind, owner.id, ext or ".bin")
            await asyncio.to_thread(storage.put_path, src, orig_key, private, mime)
            mf.key = orig_key
            mf.meta = {"source_key": orig_key, "acodec": p.acodec, "bitrate": p.bitrate}
            mf.sha256 = await asyncio.to_thread(_sha256, src)
        elif kind in ("video", "video_note", "gif", "video_source"):
            if not transcode.have_ffmpeg():
                raise HTTPException(503, "服务器缺少 ffmpeg,暂时发不了视频")
            p = await transcode.probe(src)
            if not p.has_video:
                raise HTTPException(422, "这个文件里没有视频画面")
            if transcode.video_too_large(p):
                raise HTTPException(422, "视频分辨率太大了(最高 8K)")
            mf.w, mf.h, mf.duration_ms = p.display_w, p.display_h, p.duration_ms
            if kind == "video_source" and p.duration_ms > 30 * 60 * 1000:
                raise HTTPException(422, "单个分 P 最长 30 分钟")
            thumb = await _thumb_from_video(src, min(1.0, p.duration_ms / 2000))
            orig_key = new_key(kind, owner.id, ext or ".mp4")
            await asyncio.to_thread(storage.put_path, src, orig_key, private, mime)
            mf.meta = {"source_key": orig_key, "vcodec": p.vcodec, "acodec": p.acodec,
                       "bitrate": p.bitrate}
            if thumb:
                mf.thumb_key = orig_key.rsplit(".", 1)[0] + ".thumb.jpg"
                await asyncio.to_thread(storage.backend().put, thumb, mf.thumb_key, private)
            mf.sha256 = await asyncio.to_thread(_sha256, src)
            if kind == "video_source":
                mf.key = orig_key          # 投稿原片:转码由视频模块按分 P 发起
            elif kind in ("video", "video_note") and not transcode.chat_video_needs_transcode(p) \
                    and ext in (".mp4", ".mov"):
                dst = work / "remux.mp4"
                await transcode.run(transcode.remux_args(str(src), str(dst)), timeout=300)
                mf.key = new_key(kind, owner.id, ".mp4")
                await asyncio.to_thread(storage.put_path, dst, mf.key, private, "video/mp4")
                mf.mime, mf.size = "video/mp4", dst.stat().st_size
            else:
                mf.status = "processing"
                mf.mime = "video/mp4"
        else:  # 文件
            mf.key = new_key("file", owner.id, Path(name or "").suffix[:10].lower())
            await asyncio.to_thread(storage.put_path, src, mf.key, private,
                                    mime if category != "file" else "application/octet-stream")
            mf.sha256 = await asyncio.to_thread(_sha256, src)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    db.add(mf)
    await db.flush()
    if mf.status == "processing":
        from ..workers.media import enqueue_after_commit
        enqueue_after_commit(db, {"type": "gif" if kind == "gif" else "chat_video",
                                  "media_id": mf.id})
    return mf


# ---------------- 带签名的下载地址 ----------------
#
# 网页版的 <video>、图片组件带不了 Authorization 头,所以下载地址可以带签名:
# `?u=<用户>&e=<到期>&s=<签名>`。签名**绑定用户**,下载时照样按这个用户重新判权(can_read)——
# 消息删了、人被移出会话,旧地址立刻失效(S1),不是「拿到链接就能下七天」。
# 到期取「7 天后的零点」:同一天签出来的地址一样,客户端的图片缓存能命中。

URL_TTL_DAYS = 7


def _url_key() -> bytes:
    from ..config import settings
    return hashlib.sha256(f"superz-media-url:{settings.jwt_secret}".encode()).digest()


def url_sig(media_id: int, user_id: int, exp: int, thumb: bool) -> str:
    import hmac
    msg = f"{media_id}:{user_id}:{exp}:{1 if thumb else 0}".encode()
    return hmac.new(_url_key(), msg, hashlib.sha256).hexdigest()[:32]


def url_expiry(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    day = int(now.timestamp()) // 86400
    return (day + URL_TTL_DAYS + 1) * 86400


def signed_url(media_id: int, user_id: int, thumb: bool = False, exp: int | None = None) -> str:
    exp = exp or url_expiry()
    base = f"/media/v1/files/{media_id}?u={user_id}&e={exp}&s={url_sig(media_id, user_id, exp, thumb)}"
    return base + ("&thumb=1" if thumb else "")


def check_url_sig(media_id: int, user_id: int, exp: int, sig: str, thumb: bool) -> bool:
    import hmac
    import time
    if exp < time.time():
        return False
    return hmac.compare_digest(url_sig(media_id, user_id, exp, thumb), sig or "")


# ---- 管理员按举报单看媒体(S8)----
#
# 管理员不在被举报的会话里,普通判权(can_read)给不了他;而被举报的恰恰常是图片、视频。
# 给他的是**绑定这张举报单**的地址:签名里有举报单号,1 小时失效;下载时再按那张单的
# S8 范围(被举报的几条 ± 5 条)重新判一次 —— 地址被转出去也看不到范围之外的东西。
# 签名的明文带 "r:" 前缀,和普通地址的签名不会互相冒用。

def report_url_sig(media_id: int, admin_id: int, report_id: int, exp: int, thumb: bool) -> str:
    import hmac
    msg = f"r:{report_id}:{media_id}:{admin_id}:{exp}:{1 if thumb else 0}".encode()
    return hmac.new(_url_key(), msg, hashlib.sha256).hexdigest()[:32]


def report_signed_url(media_id: int, admin_id: int, report_id: int, thumb: bool = False) -> str:
    import time
    from .chat_moderation import MEDIA_GRANT_SECONDS
    exp = int(time.time()) + MEDIA_GRANT_SECONDS
    sig = report_url_sig(media_id, admin_id, report_id, exp, thumb)
    return (f"/media/v1/files/{media_id}?u={admin_id}&r={report_id}&e={exp}&s={sig}"
            + ("&thumb=1" if thumb else ""))


def check_report_url_sig(media_id: int, admin_id: int, report_id: int, exp: int, sig: str,
                         thumb: bool) -> bool:
    import hmac
    import time
    if exp < time.time():
        return False
    return hmac.compare_digest(report_url_sig(media_id, admin_id, report_id, exp, thumb),
                               sig or "")


def media_out(mf: MediaFile, viewer_id: int | None = None) -> dict:
    return {"id": mf.id, "kind": mf.kind, "status": mf.status, "error": mf.error,
            "w": mf.w, "h": mf.h, "size": mf.size, "mime": mf.mime, "name": mf.name,
            "duration_ms": mf.duration_ms, "waveform": mf.waveform or [],
            "url": signed_url(mf.id, viewer_id) if viewer_id else f"/media/v1/files/{mf.id}",
            "thumb": (signed_url(mf.id, viewer_id, True) if viewer_id
                      else f"/media/v1/files/{mf.id}?thumb=1") if mf.thumb_key else None,
            "public_url": storage.url_for(mf.key, False) if not mf.private and mf.key else None}


async def can_read(db: AsyncSession, user: User | None, mf: MediaFile) -> bool:
    """这个人能不能下载这个媒体(S1)。"""
    if not mf.private:
        return True
    if user is None:
        return False
    if mf.owner_id == user.id:
        return True
    if mf.purpose == "chat":
        # 出现在我能读的某条消息里:我在那个会话里(或者它是公开会话),消息没删、在我清空之后、没被我隐藏
        needle = [{"id": mf.id}]
        member_ok = exists().where(and_(
            ChatMember.chat_id == ChatMessage.chat_id, ChatMember.user_id == user.id,
            ChatMember.role.in_(ACTIVE_ROLES), ChatMessage.seq > ChatMember.cleared_seq))
        # 被平台封禁的公开群 / 频道:外人的预览关了,里面的媒体也跟着关(#368「公开发现里消失」)
        from ..models import SocialSanction
        banned = exists().where(and_(
            SocialSanction.target_type == "chat", SocialSanction.target_id == Chat.id,
            SocialSanction.action == "ban_chat", SocialSanction.revoked_at.is_(None),
            or_(SocialSanction.until.is_(None), SocialSanction.until > func.now())))
        public_ok = exists().where(and_(Chat.id == ChatMessage.chat_id,
                                        Chat.username.is_not(None),
                                        Chat.type.in_(("group", "channel")),
                                        Chat.deleted_at.is_(None), ~banned))
        hidden = exists().where(and_(MessageHide.chat_id == ChatMessage.chat_id,
                                     MessageHide.seq == ChatMessage.seq,
                                     MessageHide.user_id == user.id))
        row = await db.scalar(select(ChatMessage.id).where(
            ChatMessage.media.contains(needle), ChatMessage.deleted_at.is_(None),
            member_ok | public_ok, ~hidden).limit(1))
        return row is not None
    if mf.purpose == "video":
        from .video_access import can_read_video_media  # 视频模块(#357)
        return await can_read_video_media(db, user, mf)
    if mf.purpose == "music":
        from .music_access import can_read_music_media  # 音乐模块(#378)
        return await can_read_music_media(db, user, mf)
    return False
