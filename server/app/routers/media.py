"""媒体接口 `/media/v1`(DEV-PROMPTS-40 #341):上传(整块 / 分片续传)、状态、判权下载(Range)。

下载地址只有一种:`/media/v1/files/<id>`,**每次都判权**(S1)。
不给「长期有效的直链」—— 直链一旦被转出去就收不回来。
"""
import asyncio
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import MediaFile, Upload, User
from ..ratelimit import check_rate_limit
from ..security import get_current_user_optional
from ..services import storage
from ..services.media import LIMITS, TMP_DIR, can_read, check_quota, ingest, media_out
from .social import social_user

router = APIRouter(prefix="/media/v1", tags=["媒体"])

CHUNK_SIZE = 4 * 1024 * 1024
#: 整块上传的上限;更大的走分片
SINGLE_MAX = 20 * 1024 * 1024
UPLOAD_TTL = timedelta(hours=24)
#: 客户端能声明的用途 → 允许的类型
PURPOSES = {
    "chat": {"auto", "photo", "video", "file", "voice", "video_note", "gif"},
    "sticker": {"sticker"},
    "chat_photo": {"chat_photo"},
    "video": {"video_source", "cover"},
}


def _check_purpose(purpose: str, kind: str) -> None:
    allowed = PURPOSES.get(purpose)
    if allowed is None or kind not in allowed:
        raise HTTPException(422, "上传用途和类型对不上")


async def _save_upload_file(f: UploadFile, dst, cap: int) -> int:
    size = 0
    with open(dst, "wb") as out:
        while True:
            chunk = await f.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > cap:
                raise HTTPException(413, f"单次上传最大 {cap // 1024 // 1024}MB,大文件请用分片上传")
            out.write(chunk)
    return size


@router.post("/upload")
async def upload(file: UploadFile = File(...), kind: str = Form("auto"),
                 purpose: str = Form("chat"), me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    """整块上传(≤ 20MB)。返回媒体对象;视频要转码的 status=processing,做完推 `media` 用户事件。"""
    await check_rate_limit("media_upload", str(me.id), 60)
    _check_purpose(purpose, kind)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TMP_DIR / f"up-{uuid.uuid4().hex}"
    try:
        size = await _save_upload_file(file, tmp, SINGLE_MAX)
        await check_quota(me.id, size)
        mf = await ingest(db, me, tmp, declared="photo" if kind == "auto" and
                          (file.content_type or "").startswith("image/") else kind,
                          name=file.filename or "", purpose=purpose)
        await db.commit()
        return media_out(mf)
    finally:
        tmp.unlink(missing_ok=True)


class UploadIn(BaseModel):
    size: int = Field(gt=0)
    name: str = Field(default="", max_length=200)
    mime: str = Field(default="", max_length=80)
    purpose: str = "chat"
    kind: str = "file"


def _upload_out(u: Upload) -> dict:
    return {"id": u.id, "size": u.size, "chunk_size": u.chunk_size,
            "chunks": -(-u.size // u.chunk_size), "received": sorted(u.received or []),
            "status": u.status, "media_id": u.media_id,
            "expires_at": u.expires_at.isoformat()}


@router.post("/uploads")
async def create_upload(body: UploadIn, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    """建分片上传。每片 4MB,`PUT …/chunks/<n>` 传原始字节,断了之后 GET 看收到了哪些片接着传。"""
    await check_rate_limit("media_upload", str(me.id), 60)
    _check_purpose(body.purpose, body.kind)
    cap = LIMITS.get(body.kind, LIMITS["file"])
    if body.size > cap:
        raise HTTPException(413, f"这类文件最大 {cap // 1024 // 1024}MB")
    await check_quota(me.id, body.size)
    u = Upload(id=uuid.uuid4().hex, owner_id=me.id, purpose=body.purpose, size=body.size,
               chunk_size=CHUNK_SIZE, received=[], mime=body.mime, name=body.name,
               status="open", expires_at=datetime.now(timezone.utc) + UPLOAD_TTL,
               created_at=datetime.now(timezone.utc))
    db.add(u)
    await db.commit()
    (TMP_DIR / f"chunks-{u.id}").mkdir(parents=True, exist_ok=True)
    return _upload_out(u)


async def _own_upload(db: AsyncSession, upload_id: str, me: User) -> Upload:
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise HTTPException(404, "没有这个上传")
    u = await db.get(Upload, upload_id)
    if u is None or u.owner_id != me.id:
        raise HTTPException(404, "没有这个上传")
    if u.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(410, "上传已过期(24 小时),请重新上传")
    return u


@router.get("/uploads/{upload_id}")
async def get_upload(upload_id: str, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    return _upload_out(await _own_upload(db, upload_id, me))


@router.put("/uploads/{upload_id}/chunks/{n}")
async def put_chunk(upload_id: str, n: int, request: Request, me: User = Depends(social_user),
                    db: AsyncSession = Depends(get_db)):
    u = await _own_upload(db, upload_id, me)
    if u.status != "open":
        raise HTTPException(409, "这个上传已经完成了")
    total = -(-u.size // u.chunk_size)
    if not 0 <= n < total:
        raise HTTPException(422, "片号超出范围")
    expect = u.chunk_size if n < total - 1 else u.size - u.chunk_size * (total - 1)
    d = TMP_DIR / f"chunks-{u.id}"
    d.mkdir(parents=True, exist_ok=True)
    part = d / f"{n:06d}.part"
    got = 0
    with open(part, "wb") as out:
        async for chunk in request.stream():
            got += len(chunk)
            if got > expect:
                break
            out.write(chunk)
    if got != expect:
        part.unlink(missing_ok=True)
        raise HTTPException(422, f"这一片应该是 {expect} 字节,收到 {got} 字节")
    u = await db.get(Upload, upload_id, with_for_update=True, populate_existing=True)
    if n not in (u.received or []):
        u.received = sorted({*(u.received or []), n})
    await db.commit()
    return {"received": len(u.received), "chunks": total}


class CompleteIn(BaseModel):
    kind: str = "file"


@router.post("/uploads/{upload_id}/complete")
async def complete_upload(upload_id: str, body: CompleteIn, me: User = Depends(social_user),
                          db: AsyncSession = Depends(get_db)):
    u = await _own_upload(db, upload_id, me)
    if u.status == "done" and u.media_id:
        mf = await db.get(MediaFile, u.media_id)
        return media_out(mf)
    _check_purpose(u.purpose, body.kind)
    total = -(-u.size // u.chunk_size)
    missing = sorted(set(range(total)) - set(u.received or []))
    if missing:
        raise HTTPException(409, f"还有 {len(missing)} 片没传完")
    d = TMP_DIR / f"chunks-{u.id}"
    whole = TMP_DIR / f"whole-{u.id}"

    def assemble():
        with open(whole, "wb") as out:
            for i in range(total):
                with open(d / f"{i:06d}.part", "rb") as f:
                    shutil.copyfileobj(f, out, 1024 * 1024)

    try:
        await asyncio.to_thread(assemble)
        if whole.stat().st_size != u.size:
            raise HTTPException(422, "拼起来的大小和声明的不一样")
        mf = await ingest(db, me, whole, declared=body.kind, name=u.name, purpose=u.purpose)
        u.status, u.media_id = "done", mf.id
        await db.commit()
        return media_out(mf)
    finally:
        whole.unlink(missing_ok=True)
        shutil.rmtree(d, ignore_errors=True)


@router.get("/media/{media_id}")
async def get_media(media_id: int, me: User = Depends(social_user),
                    db: AsyncSession = Depends(get_db)):
    mf = await db.get(MediaFile, media_id)
    if mf is None or not await can_read(db, me, mf):
        raise HTTPException(404, "没有这个文件")
    return media_out(mf)


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """`bytes=a-b` → (起, 止)(含止)。不合法或多段 → None(按整份返回)。纯函数。"""
    if not header:
        return None
    m = _RANGE_RE.match(header.strip())
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    if a == "" and b == "":
        return None
    if a == "":
        n = int(b)
        if n == 0:
            return None
        return max(0, size - n), size - 1
    start = int(a)
    end = int(b) if b else size - 1
    if start >= size or end < start:
        return (-1, -1)
    return start, min(end, size - 1)


async def _stream(key: str, private: bool, start: int, end: int):
    pos = start
    while pos <= end:
        n = min(storage.CHUNK, end - pos + 1)
        data = await asyncio.to_thread(storage.read_range, key, private, pos, n)
        if not data:
            break
        yield data
        pos += len(data)


def file_response(request: Request, key: str, private: bool, size: int, mime: str,
                  *, filename: str = "", cache: str = "private, max-age=86400") -> Response:
    """带 Range 的文件响应。生产开了 MEDIA_ACCEL 时交给 nginx 直出(见上线手册)。"""
    headers = {"Accept-Ranges": "bytes", "Cache-Control": cache,
               "X-Content-Type-Options": "nosniff"}
    if filename:
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    if settings.media_accel:
        url = storage.presigned_get(key, private)
        if url:
            u = urlsplit(url)
            headers["X-Accel-Redirect"] = f"/_minio_internal{u.path}?{u.query}"
            return Response(status_code=200, headers=headers, media_type=mime)
    rng = parse_range(request.headers.get("range"), size)
    if rng == (-1, -1):
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    if rng is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(_stream(key, private, 0, size - 1), media_type=mime,
                                 headers=headers)
    start, end = rng
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(_stream(key, private, start, end), status_code=206,
                             media_type=mime, headers=headers)


@router.get("/files/{media_id}")
async def get_file(media_id: int, request: Request, thumb: int = 0, download: int = 0,
                   me: User | None = Depends(get_current_user_optional),
                   db: AsyncSession = Depends(get_db)):
    mf = await db.get(MediaFile, media_id)
    # 没有、没权限、还没转完 —— 一律 404,不告诉你「有这个文件但你看不了」
    if mf is None or not await can_read(db, me, mf):
        raise HTTPException(404, "没有这个文件")
    if thumb:
        if not mf.thumb_key:
            raise HTTPException(404, "这个文件没有缩略图")
        key, mime = mf.thumb_key, "image/jpeg"
    else:
        if mf.status != "ready" or not mf.key:
            raise HTTPException(409, "文件还在处理中")
        key, mime = mf.key, mf.mime or "application/octet-stream"
    size = await asyncio.to_thread(storage.stat_size, key, mf.private)
    if size is None:
        raise HTTPException(404, "文件不见了")
    name = mf.name if (download or mf.kind == "file") and not thumb else ""
    # 文件类不让浏览器按内容猜类型渲染(防上传的 HTML 在我们的域下执行)
    if mf.kind == "file" and not thumb:
        mime = "application/octet-stream"
    return file_response(request, key, mf.private, size, mime, filename=name)
