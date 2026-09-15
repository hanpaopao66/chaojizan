"""歌曲转码(DEV-PROMPTS-41 #378,§5.3 末尾、M4)。

每首歌一个任务(`{"type": "music_track", "track_id": …}`,见 workers/media.py):

1. ffprobe 读时长:**5 秒–20 分钟**(M4)。超出范围直接判失败并写原因 —— 20 秒的白噪声和
   两小时的整轨都不是「一首歌」,让它们进库只会把榜单和存储一起搞乱;
2. 出 std(128k)和 hq(256k,源码率低于 192k 不出)两档,AAC-LC / 44.1kHz / 立体声,
   响度统一 −14 LUFS,`+faststart`;
3. 产物进私密桶 `music/t{track_id}/{uuid}/{q}.m4a`,写进 tracks.renditions;
4. **ready 之后删源文件**:200MB 的无损留着没用,各档位就是存档;媒体行留着作记录。

转码失败重试 3 次(内容本身的问题不重试),还不行才标 failed、写 fail_reason,
音乐人可以删了重传。转码途中歌 / 作品被删了:做完发现行没了,把刚传上去的产物删掉。
"""
import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select

from . import storage, transcode

logger = logging.getLogger("superz.music")

#: 一首歌的时长范围(M4)
MIN_DURATION_MS = 5 * 1000
MAX_DURATION_MS = 20 * 60 * 1000
ATTEMPTS = 3
#: 这几句是内容本身的问题,重试三次结果一样
_FATAL = ("时长", "没有声音", "读不出")


def duration_ok(duration_ms: int) -> bool:
    """时长在允许范围内没有(M4,纯函数,单测锁住)。"""
    return MIN_DURATION_MS <= duration_ms <= MAX_DURATION_MS


def duration_error(duration_ms: int) -> str:
    """给音乐人看的失败原因。"""
    secs = duration_ms / 1000
    if duration_ms < MIN_DURATION_MS:
        return f"这首歌只有 {secs:.1f} 秒,太短了(最短 5 秒)"
    return f"这首歌有 {secs / 60:.1f} 分钟,太长了(最长 20 分钟)"


def track_key(track_id: int, batch: str, quality: str) -> str:
    """转码产物的对象名。每次转码换一个 batch(uuid):重传 / 重试不会覆盖还在被播放的旧文件。"""
    return f"music/t{track_id}/{batch}/{quality}.m4a"


async def _transcode(mf, track_id: int, work: Path,
                     uploaded: list[tuple[str, bool]]) -> dict:
    src_key = (mf.meta or {}).get("source_key") or mf.key
    src = work / ("src" + (Path(src_key).suffix or ".bin"))
    await asyncio.to_thread(storage.download_to, src_key, mf.private, src)
    p = await transcode.probe(src)
    if not p.acodec:
        raise transcode.TranscodeError("这个文件里没有声音")
    if not duration_ok(p.duration_ms):
        raise transcode.TranscodeError(duration_error(p.duration_ms))
    # loudnorm 要把整首歌过一遍,长歌慢;给够时间,别让 20 分钟的整轨卡在超时上
    timeout = max(600.0, p.duration_ms / 1000 * 4)
    batch = uuid.uuid4().hex
    renditions = []
    for quality, kbps in transcode.audio_qualities(p.bitrate):
        dst = work / f"{quality}.m4a"
        await transcode.run(transcode.audio_rendition_args(str(src), str(dst), kbps),
                            timeout=timeout)
        key = track_key(track_id, batch, quality)
        await asyncio.to_thread(storage.put_path, dst, key, True, "audio/mp4")
        uploaded.append((key, True))
        size = dst.stat().st_size
        renditions.append({"q": quality, "key": key, "size": size,
                           "bitrate": int(size * 8 * 1000 / max(1, p.duration_ms))})
        dst.unlink(missing_ok=True)
    return {"duration_ms": p.duration_ms, "renditions": renditions}


async def _locked(db, track_id: int):
    """FOR UPDATE 一律配 populate_existing:会话里有旧快照时,不加它锁到了数据还是旧的。"""
    from ..models import MusicTrack

    return await db.scalar(select(MusicTrack).where(MusicTrack.id == track_id)
                           .with_for_update().execution_options(populate_existing=True))


async def _finish_ok(track_id: int, result: dict, source_media_id: int | None) -> bool:
    from ..db import SessionLocal
    from ..models import MediaFile
    from . import music as msvc

    async with SessionLocal() as db:
        track = await _locked(db, track_id)
        if track is None or track.transcode_status not in ("pending", "processing"):
            return False
        track.transcode_status = "ready"
        track.fail_reason = ""
        track.duration_ms = result["duration_ms"]
        track.renditions = result["renditions"]
        # 原文件转完就删:各档位就是存档,部署机的存储要省着用(M4「转完删源文件」)
        src = await db.get(MediaFile, source_media_id) if source_media_id else None
        if src is not None:
            msvc.remove_objects_after_commit(db, msvc.media_objects(src))
            src.key, src.thumb_key = "", ""
            src.meta = {**(src.meta or {}), "source_key": None, "transcoded": True}
        await db.commit()
    return True


async def _finish_failed(track_id: int, error: str) -> None:
    from ..db import SessionLocal

    async with SessionLocal() as db:
        track = await _locked(db, track_id)
        if track is None or track.transcode_status not in ("pending", "processing"):
            return
        track.transcode_status = "failed"
        track.fail_reason = (error or "转码失败")[:300]
        await db.commit()


async def _mark_processing(track_id: int) -> bool:
    from ..db import SessionLocal

    async with SessionLocal() as db:
        track = await _locked(db, track_id)
        if track is None or track.transcode_status not in ("pending", "processing"):
            return False
        track.transcode_status = "processing"
        await db.commit()
    return True


async def _remove(objs: list[tuple[str, bool]]) -> None:
    for key, private in objs:
        try:
            await asyncio.to_thread(storage.remove, key, private)
        except Exception:
            logger.warning("清理转码产物失败 %s", key, exc_info=True)


async def process_track(track_id: int) -> None:
    """转一首歌。worker(或 inline 模式下 api 的后台任务)调。"""
    from ..db import SessionLocal
    from ..models import MediaFile, MusicTrack

    async with SessionLocal() as db:
        track = await db.get(MusicTrack, track_id)
        if track is None or track.transcode_status not in ("pending", "processing"):
            return
        mf = await db.get(MediaFile, track.source_media_id) if track.source_media_id else None
    if mf is None or not (mf.key or (mf.meta or {}).get("source_key")):
        await _finish_failed(track_id, "音频文件不见了,删掉这首重新上传一次")
        return
    if not transcode.have_ffmpeg():
        await _finish_failed(track_id, "服务器缺少 ffmpeg")
        return
    if not await _mark_processing(track_id):
        return
    last_error = ""
    for attempt in range(ATTEMPTS):
        work = Path(storage.PRIVATE_DIR / "_media_tmp" / uuid.uuid4().hex)
        work.mkdir(parents=True, exist_ok=True)
        uploaded: list[tuple[str, bool]] = []
        try:
            result = await _transcode(mf, track_id, work, uploaded)
            if not await _finish_ok(track_id, result, mf.id):
                # 转码途中这首歌 / 这个作品被删了:刚传上去的产物没人要了
                await _remove(uploaded)
            return
        except Exception as e:
            await _remove(uploaded)
            last_error = str(e) or type(e).__name__
            logger.warning("歌曲 %s 第 %s 次转码失败:%s", track_id, attempt + 1, last_error)
            if any(k in last_error for k in _FATAL):
                break   # 内容本身的问题,重试也一样
        finally:
            shutil.rmtree(work, ignore_errors=True)
    await _finish_failed(track_id, last_error)


async def recover_tracks() -> list[int]:
    """api 启动时(inline 模式)调:还没转完的歌重新排队。返回排了哪些。"""
    from ..db import SessionLocal
    from ..models import MusicTrack
    from ..workers.media import enqueue

    async with SessionLocal() as db:
        ids = list(await db.scalars(select(MusicTrack.id).where(
            MusicTrack.transcode_status.in_(("pending", "processing"))).order_by(MusicTrack.id)))
    for tid in ids:
        await enqueue({"type": "music_track", "track_id": tid})
    return ids
