"""转码队列与 worker(DEV-PROMPTS-40 #342)。

两种跑法(`MEDIA_WORKER`):

- `inline`(缺省,开发 / CI):api 进程里起后台任务跑,同一时刻只跑一个。零配置能跑通;
- `external`(生产):任务进 Redis 队列,独立的 media-worker 容器 `python -m app.workers.media` 来取。

**任务不丢**:worker 用 BLMOVE 把任务从队列挪到「进行中」列表,做完才删;
worker 被杀掉重启时先把「进行中」的挪回队列。inline 模式下 api 重启时,
把库里还是 processing 的媒体重新排一遍(见 [recover])。

急停:平台开关 `media_transcode` 关掉时,新任务只排队不执行(发不了视频,但不会把机器压垮)。
"""
import asyncio
import json
import logging
import shutil
import uuid
from pathlib import Path

from redis.exceptions import TimeoutError as RedisTimeout

from ..config import settings
from ..redis_client import get_redis

logger = logging.getLogger("superz.media")

QUEUE = "media:jobs"
PROCESSING = "media:jobs:processing"

#: 等任务时一次最多阻塞几秒。**必须小于 Redis 客户端的读超时**(redis-py 默认 5 秒,
#: redis._defaults.DEFAULT_SOCKET_TIMEOUT):阻塞 5 秒的 BLMOVE 在第 5 秒被客户端当成读超时掐断,
#: 队列一空 worker 就崩、被 compose 拉起、再崩 —— 2026-09-13 生产上第一次起独立 worker 就是这样,
#: 聊天视频全停在「处理中」。CI 和本地测不出来:那里转码在 api 进程里跑,不走这个循环。
#: 和 services/bots.py 的 BLPOP_SLICE(4 秒一段)同一个道理
BLOCK_SECONDS = 4
_inline_sem: asyncio.Semaphore | None = None


def enqueue_after_commit(db, job: dict) -> None:
    from ..services.rt_events import after_commit
    after_commit(db, lambda: enqueue(job))


async def enqueue(job: dict) -> None:
    if settings.media_worker == "inline":
        asyncio.get_running_loop().create_task(_run_inline(job))
        return
    await get_redis().rpush(QUEUE, json.dumps(job))


async def _run_inline(job: dict) -> None:
    global _inline_sem
    if _inline_sem is None:
        _inline_sem = asyncio.Semaphore(1)
    async with _inline_sem:
        await run_job(job)


async def _transcode_enabled() -> bool:
    from ..db import SessionLocal
    from ..models import PlatformFlag
    async with SessionLocal() as db:
        row = await db.get(PlatformFlag, "media_transcode")
    return row is None or row.value != "off"


async def run_job(job: dict) -> None:
    kind = job.get("type")
    try:
        if not await _transcode_enabled():
            logger.warning("转码急停中,任务 %s 暂不执行", job)
            await asyncio.sleep(30)
            await enqueue(job)
            return
        if kind == "chat_video":
            await process_chat_video(int(job["media_id"]))
        elif kind == "gif":
            await process_gif(int(job["media_id"]))
        elif kind == "video_part":
            from ..services.video_media import process_part  # 视频模块(#358)
            await process_part(int(job["part_id"]))
        elif kind == "music_track":
            from ..services.music_media import process_track  # 音乐模块(#378)
            await process_track(int(job["track_id"]))
        else:
            logger.warning("不认识的转码任务:%s", job)
    except Exception:
        logger.exception("转码任务失败:%s", job)


async def _finish(media_id: int, *, ok: bool, error: str = "", **fields) -> None:
    from ..db import SessionLocal
    from ..models import MediaFile
    from ..services.media import media_out
    from ..services.rt_events import append_user_event

    async with SessionLocal() as db:
        mf = await db.get(MediaFile, media_id)
        if mf is None:
            return
        for k, v in fields.items():
            setattr(mf, k, v)
        mf.status = "ready" if ok else "failed"
        mf.error = error[:300]
        if mf.owner_id:
            await append_user_event(db, mf.owner_id, "media", media_out(mf))
        await db.commit()


async def _source(media_id: int, work: Path):
    from ..db import SessionLocal
    from ..models import MediaFile
    from ..services import storage

    async with SessionLocal() as db:
        mf = await db.get(MediaFile, media_id)
    if mf is None or mf.status != "processing":
        return None, None
    src_key = (mf.meta or {}).get("source_key") or mf.key
    src = work / ("src" + Path(src_key).suffix)
    await asyncio.to_thread(storage.download_to, src_key, mf.private, src)
    return mf, src


async def process_chat_video(media_id: int) -> None:
    """聊天视频:转成 720p(不超过原片)H.264/AAC,faststart。原片转完就删。"""
    from ..services import storage, transcode

    work = Path(storage.PRIVATE_DIR / "_media_tmp" / uuid.uuid4().hex)
    work.mkdir(parents=True, exist_ok=True)
    try:
        mf, src = await _source(media_id, work)
        if mf is None:
            return
        p = await transcode.probe(src)
        rungs = [r for r in transcode.ladder(p) if r[0] <= 720] or transcode.ladder(p)[-1:]
        name, w, h, kbps = rungs[0]
        dst = work / "out.mp4"
        await transcode.run(transcode.rendition_args(str(src), str(dst), w, h, kbps,
                                                     bool(p.acodec)))
        key = f"media/{mf.kind}/u{mf.owner_id or 0}/{uuid.uuid4().hex}.mp4"
        await asyncio.to_thread(storage.put_path, dst, key, mf.private, "video/mp4")
        source_key = (mf.meta or {}).get("source_key")
        await _finish(media_id, ok=True, key=key, w=w, h=h, size=dst.stat().st_size,
                      mime="video/mp4", duration_ms=p.duration_ms,
                      meta={**(mf.meta or {}), "source_key": None})
        if source_key and source_key != key:
            await asyncio.to_thread(storage.remove, source_key, mf.private)
    except Exception as e:
        logger.exception("聊天视频转码失败 media=%s", media_id)
        await _finish(media_id, ok=False, error=str(e) or "转码失败")
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def process_gif(media_id: int) -> None:
    """GIF → 无声 MP4 循环(D18)。"""
    from ..services import storage, transcode

    work = Path(storage.PRIVATE_DIR / "_media_tmp" / uuid.uuid4().hex)
    work.mkdir(parents=True, exist_ok=True)
    try:
        mf, src = await _source(media_id, work)
        if mf is None:
            return
        dst = work / "out.mp4"
        await transcode.run(transcode.gif_args(str(src), str(dst)), timeout=600)
        p = await transcode.probe(dst)
        key = f"media/gif/u{mf.owner_id or 0}/{uuid.uuid4().hex}.mp4"
        await asyncio.to_thread(storage.put_path, dst, key, mf.private, "video/mp4")
        source_key = (mf.meta or {}).get("source_key")
        await _finish(media_id, ok=True, key=key, w=p.display_w, h=p.display_h,
                      size=dst.stat().st_size, mime="video/mp4", duration_ms=p.duration_ms,
                      meta={**(mf.meta or {}), "source_key": None})
        if source_key:
            await asyncio.to_thread(storage.remove, source_key, mf.private)
    except Exception as e:
        logger.exception("GIF 转换失败 media=%s", media_id)
        await _finish(media_id, ok=False, error=str(e) or "转换失败")
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def recover() -> int:
    """inline 模式下 api 启动时调:库里还是 processing 的,重新排队。返回排了几个。"""
    from sqlalchemy import select

    from ..db import SessionLocal
    from ..models import MediaFile

    async with SessionLocal() as db:
        rows = list(await db.scalars(select(MediaFile.id).where(
            MediaFile.status == "processing", MediaFile.kind.in_(("video", "video_note", "gif")))))
    for mid in rows:
        kind_job = "chat_video"
        await enqueue({"type": kind_job, "media_id": mid})
    try:
        from ..services.video_media import recover_parts
        rows += await recover_parts()
    except ImportError:
        pass
    try:
        from ..services.music_media import recover_tracks
        rows += await recover_tracks()
    except ImportError:
        pass
    return len(rows)


async def worker_main() -> None:
    """独立 worker 进程的主循环。"""
    r = get_redis()
    # 上次没做完的挪回队列
    while await r.lmove(PROCESSING, QUEUE, "LEFT", "RIGHT"):
        pass
    logger.info("media-worker 启动,等任务")
    while True:
        try:
            raw = await r.blmove(QUEUE, PROCESSING, BLOCK_SECONDS, "LEFT", "RIGHT")
        except RedisTimeout:
            # 网络抖一下读超时:接着等,不为这个退出进程(退出就是 compose 的重启循环)
            logger.warning("等任务时 Redis 读超时,接着等")
            continue
        if raw is None:
            continue
        try:
            await run_job(json.loads(raw))
        finally:
            await r.lrem(PROCESSING, 1, raw)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(worker_main())
