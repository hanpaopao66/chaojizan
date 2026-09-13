"""消息与视频的清扫(DEV-PROMPTS-40):跟着 auto_flow 走,只在清扫进程里跑一份。

和订单清扫分开一条循环,是因为节奏不一样:

- **定时消息**要准:用户选的是「9:00 发」,30 秒一轮的订单清扫最晚能拖到 9:00:30 —— 这里 5 秒一轮;
- **过期的分片上传**不急:10 分钟一轮。

原来 `routers/chat.send_due_scheduled` 写好了却没人调:定时消息存进去就再也没发出来。
这条循环就是它的调用方,守卫见 tests/unit/test_social_sweep.py。
"""
import asyncio
import logging
import shutil
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select

logger = logging.getLogger("superz.social_sweep")

TICK_SECONDS = 5
UPLOAD_SWEEP_EVERY = 600
#: 转码临时目录里超过这么久还在的,是进程被杀留下的残骸
STALE_WORK_DIR = timedelta(hours=6)


async def sweep_expired_uploads(now: datetime | None = None) -> int:
    """24 小时没传完的分片上传:删行、删已经收到的片;做完 / 失败超过 24 小时的行也清掉。
    顺带清转码临时目录里 6 小时前的残骸。返回清掉的上传数。"""
    from ..db import SessionLocal
    from ..models import Upload
    from .media import TMP_DIR

    now = now or datetime.now(timezone.utc)
    async with SessionLocal() as db:
        rows = list(await db.scalars(select(Upload.id).where(or_(
            Upload.expires_at <= now,
            (Upload.status != "open") & (Upload.created_at <= now - timedelta(hours=24))))))
        if rows:
            await db.execute(delete(Upload).where(Upload.id.in_(rows)))
            await db.commit()
    for uid in rows:
        shutil.rmtree(TMP_DIR / f"chunks-{uid}", ignore_errors=True)
    cutoff = time.time() - STALE_WORK_DIR.total_seconds()
    try:
        for d in TMP_DIR.iterdir():
            if d.is_dir() and not d.name.startswith("chunks-") and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
    except FileNotFoundError:
        pass
    return len(rows)


async def social_tick_loop() -> None:
    from ..routers.chat import send_due_scheduled

    logger.info("消息清扫启动:定时消息 %ss 一轮,过期上传 %ss 一轮", TICK_SECONDS, UPLOAD_SWEEP_EVERY)
    last_uploads = 0.0
    while True:
        try:
            n = await send_due_scheduled()
            if n:
                logger.info("发出 %s 条定时消息", n)
            if time.monotonic() - last_uploads >= UPLOAD_SWEEP_EVERY:
                last_uploads = time.monotonic()
                gone = await sweep_expired_uploads()
                if gone:
                    logger.info("清掉 %s 个过期的分片上传", gone)
        except Exception:  # 清扫失败不能把循环带走,下一轮重试
            logger.exception("消息清扫失败")
        await asyncio.sleep(TICK_SECONDS)
