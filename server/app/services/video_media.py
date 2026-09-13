"""视频投稿的转码(DEV-PROMPTS-40 #358,§5.8、D9)。

每个分 P 单独一个任务(`{"type": "video_part", "part_id": …}`,见 workers/media.py):

1. ffprobe 读时长、宽高(竖屏按宽算档位,旋转按显示方向);
2. 按源分辨率出 360 / 480 / 720 / 1080 里**不超过原片**的档位(transcode.ladder),
   H.264 High + AAC 的 MP4,`+faststart`,关键帧 2 秒(拖进度条落点准);
3. 雪碧图:整秒间隔、总共不超过 400 格,160 宽、10×10 一张,连同每格的尺寸和间隔写进 sprite,
   客户端拖进度条时按 `index = floor(t / interval)` 算第几张、第几行第几列;
4. 自动封面候选三帧(10% / 50% / 90% 处),没选封面时用第一帧(10% 处,#342);
5. 全部分 P 就绪 → 稿件进 reviewing;某 P 失败 → 稿件 failed,带原因。

转码失败重试 2 次(共 3 次),还不行才标 failed。原片转完就删(部署机存储有限,各档位就是存档),
媒体行留着作记录。转码途中 UP 主删了这一 P / 删了稿件:做完发现行没了,把刚传上去的产物删掉。

锁的顺序固定是**先稿件、后分 P**(和接口那边一致),两边同时动同一个稿件时不会互相等死。
"""
import asyncio
import logging
import math
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select

from . import storage, transcode

logger = logging.getLogger("superz.video")

#: 自动封面候选的位置(时长的百分比)
COVER_POINTS = (0.1, 0.5, 0.9)
COVER_WIDTH = 1280
ATTEMPTS = 3


def sprite_meta(duration_ms: int, interval_ms: int, sheets: int, frame_w: int,
                frame_h: int) -> dict:
    """雪碧图的元数据(纯函数,单测锁住):总格数 = ceil(时长 / 间隔),不超过实际张数能装下的。"""
    per = transcode.SPRITE_COLS * transcode.SPRITE_ROWS
    count = min(max(1, math.ceil(duration_ms / interval_ms)), sheets * per) if sheets else 0
    return {"interval_ms": interval_ms, "cols": transcode.SPRITE_COLS,
            "rows": transcode.SPRITE_ROWS, "w": frame_w, "h": frame_h, "count": count}


def sprite_cell(position_ms: int, meta: dict) -> tuple[int, int, int]:
    """进度 → (第几张, 行, 列)。客户端照这个算(单测锁住,文档里也写了)。"""
    per = meta["cols"] * meta["rows"]
    i = min(max(0, position_ms // meta["interval_ms"]), max(0, meta["count"] - 1))
    sheet, cell = divmod(i, per)
    return sheet, cell // meta["cols"], cell % meta["cols"]


async def _transcode(mf, video_id: int, part_id: int, uploader_id: int, work: Path,
                     uploaded: list[tuple[str, bool]]) -> dict:
    from PIL import Image

    src_key = (mf.meta or {}).get("source_key") or mf.key
    src = work / ("src" + (Path(src_key).suffix or ".mp4"))
    await asyncio.to_thread(storage.download_to, src_key, mf.private, src)
    p = await transcode.probe(src)
    if not p.has_video:
        raise transcode.TranscodeError("这个文件里没有视频画面")
    rungs = transcode.ladder(p)
    if not rungs:
        raise transcode.TranscodeError("读不出画面尺寸")
    long_timeout = max(600.0, p.duration_ms / 1000 * 8)
    prefix = f"video/v{video_id}/p{part_id}/{uuid.uuid4().hex}"
    renditions = []
    for name, w, h, kbps in rungs:
        dst = work / f"{name}.mp4"
        await transcode.run(transcode.rendition_args(str(src), str(dst), w, h, kbps,
                                                     bool(p.acodec)), timeout=long_timeout)
        key = f"{prefix}/{name}.mp4"
        await asyncio.to_thread(storage.put_path, dst, key, True, "video/mp4")
        uploaded.append((key, True))
        size = dst.stat().st_size
        renditions.append({"q": name, "key": key, "w": w, "h": h, "size": size,
                           "bitrate": int(size * 8 * 1000 / max(1, p.duration_ms))})
        dst.unlink(missing_ok=True)
    # 雪碧图
    interval = transcode.sprite_interval_ms(p.duration_ms)
    await transcode.run(transcode.sprite_args(str(src), str(work / "sprite_%03d.jpg"), interval),
                        timeout=long_timeout)
    sheets = sorted(work.glob("sprite_*.jpg"))
    keys: list[str] = []
    frame_w = frame_h = 0
    for i, sh in enumerate(sheets):
        if i == 0:
            with Image.open(sh) as im:
                frame_w = im.width // transcode.SPRITE_COLS
                frame_h = im.height // transcode.SPRITE_ROWS
        key = f"{prefix}/sprite_{i}.jpg"
        await asyncio.to_thread(storage.put_path, sh, key, True, "image/jpeg")
        uploaded.append((key, True))
        keys.append(key)
    sprite = {**sprite_meta(p.duration_ms, interval, len(keys), frame_w, frame_h), "keys": keys}
    # 封面候选三帧
    covers = []
    for frac in COVER_POINTS:
        dst = work / f"cover_{int(frac * 100)}.jpg"
        at = max(0.0, p.duration_ms * frac / 1000)
        try:
            await transcode.run(transcode.thumb_args(str(src), str(dst), at, COVER_WIDTH),
                                timeout=120)
        except transcode.TranscodeError:
            continue
        if not dst.exists() or dst.stat().st_size == 0:
            continue
        with Image.open(dst) as im:
            cw, ch = im.width, im.height
        key = f"media/cover/u{uploader_id}/{uuid.uuid4().hex}.jpg"
        await asyncio.to_thread(storage.put_path, dst, key, True, "image/jpeg")
        uploaded.append((key, True))
        covers.append({"key": key, "size": dst.stat().st_size, "w": cw, "h": ch})
    return {"duration_ms": p.duration_ms, "w": p.display_w, "h": p.display_h,
            "renditions": renditions, "sprite": sprite, "covers": covers}


async def _locked(db, part_id: int):
    """先锁稿件、再锁分 P(和接口里的顺序一致)。FOR UPDATE 一律配 populate_existing。"""
    from ..models import Video, VideoPart

    vid_id = await db.scalar(select(VideoPart.video_id).where(VideoPart.id == part_id))
    if vid_id is None:
        return None, None
    video = await db.scalar(select(Video).where(Video.id == vid_id).with_for_update()
                            .execution_options(populate_existing=True))
    part = await db.scalar(select(VideoPart).where(VideoPart.id == part_id).with_for_update()
                           .execution_options(populate_existing=True))
    return video, part


async def _finish_ok(part_id: int, result: dict, source_media_id: int) -> bool:
    from datetime import datetime, timezone

    from ..db import SessionLocal
    from ..models import MediaFile
    from . import video as vsvc

    async with SessionLocal() as db:
        video, part = await _locked(db, part_id)
        if (video is None or part is None or part.status != "processing"
                or video.deleted_at is not None):
            return False
        now = datetime.now(timezone.utc)
        cover_ids = []
        for c in result["covers"]:
            mf = MediaFile(owner_id=video.uploader_id, purpose="video", private=True, key=c["key"],
                           kind="cover", mime="image/jpeg", size=c["size"], w=c["w"], h=c["h"],
                           status="ready", name="", waveform=[], meta={"auto": True},
                           created_at=now)
            db.add(mf)
            await db.flush()
            cover_ids.append(mf.id)
        part.status = "ready"
        part.error = ""
        part.duration_ms = result["duration_ms"]
        part.w, part.h = result["w"], result["h"]
        part.renditions = sorted(result["renditions"], key=lambda r: -r["q"])
        part.sprite = result["sprite"]
        part.cover_media_ids = cover_ids
        # 原片转完就删:各档位就是存档,部署机的存储要省着用
        src = await db.get(MediaFile, source_media_id)
        if src is not None:
            vsvc.remove_objects_after_commit(db, vsvc._media_objects(src))
            src.key, src.thumb_key = "", ""
            src.meta = {**(src.meta or {}), "source_key": None, "transcoded": True}
        await vsvc.after_part_change(db, video)
        await vsvc.emit_video_event(db, video)
        await db.commit()
    return True


async def _finish_failed(part_id: int, error: str) -> None:
    from ..db import SessionLocal
    from . import video as vsvc

    async with SessionLocal() as db:
        video, part = await _locked(db, part_id)
        if video is None or part is None or part.status != "processing":
            return
        part.status = "failed"
        part.error = (error or "转码失败")[:300]
        await vsvc.after_part_change(db, video)
        await vsvc.emit_video_event(db, video)
        await db.commit()


async def _remove(objs: list[tuple[str, bool]]) -> None:
    for key, private in objs:
        try:
            await asyncio.to_thread(storage.remove, key, private)
        except Exception:
            logger.warning("清理转码产物失败 %s", key, exc_info=True)


async def process_part(part_id: int) -> None:
    """转一个分 P。worker(或 inline 模式下 api 的后台任务)调。"""
    from ..db import SessionLocal
    from ..models import MediaFile, Video, VideoPart

    async with SessionLocal() as db:
        part = await db.get(VideoPart, part_id)
        if part is None or part.status != "processing":
            return
        video = await db.get(Video, part.video_id)
        mf = await db.get(MediaFile, part.source_media_id) if part.source_media_id else None
        if video is None:
            return
        video_id, uploader_id = video.id, video.uploader_id
    if mf is None or not (mf.key or (mf.meta or {}).get("source_key")):
        await _finish_failed(part_id, "原片不见了,重新上传一次")
        return
    if not transcode.have_ffmpeg():
        await _finish_failed(part_id, "服务器缺少 ffmpeg")
        return
    last_error = ""
    for attempt in range(ATTEMPTS):
        work = Path(storage.PRIVATE_DIR / "_media_tmp" / uuid.uuid4().hex)
        work.mkdir(parents=True, exist_ok=True)
        uploaded: list[tuple[str, bool]] = []
        try:
            result = await _transcode(mf, video_id, part_id, uploader_id, work, uploaded)
            if not await _finish_ok(part_id, result, mf.id):
                # 转码途中这一 P / 稿件被删了:刚传上去的产物没人要了
                await _remove(uploaded)
            return
        except Exception as e:
            await _remove(uploaded)
            last_error = str(e) or type(e).__name__
            logger.warning("分 P %s 第 %s 次转码失败:%s", part_id, attempt + 1, last_error)
            if "没有视频画面" in last_error or "读不出" in last_error:
                break   # 内容本身的问题,重试也一样
        finally:
            shutil.rmtree(work, ignore_errors=True)
    await _finish_failed(part_id, last_error)


async def recover_parts() -> list[int]:
    """api 启动时(inline 模式)调:还在 processing 的分 P 重新排队。返回排了哪些。"""
    from ..db import SessionLocal
    from ..models import VideoPart
    from ..workers.media import enqueue

    async with SessionLocal() as db:
        ids = list(await db.scalars(select(VideoPart.id).where(VideoPart.status == "processing")
                                    .order_by(VideoPart.id)))
    for pid in ids:
        await enqueue({"type": "video_part", "part_id": pid})
    return ids
