"""后台清扫进程入口(生产:独立容器,与 api 同一个镜像不同 command)。

## 为什么要拎出来单独一个进程

`auto_flow_loop` 原先挂在 api 的 lifespan 里,而 api 是 `--workers 4`,
于是**每个 worker 各起一份**,同一批订单被四个循环同时扫。
它们抢的是同一批行:超时退款、自动确认、发安抚券、生成账本锚点 ——
靠 Redis 防重键和行锁挡住了大部分重复,但那是"没出事",不是"设计上不会出事"。
账本锚点这类一天一条、按哈希链串起来的东西,重复执行的代价尤其难收拾。

现在:api 容器 `AUTO_FLOW_ENABLED=false`,清扫只在本进程里跑,天然单份。

## 它不是 web 进程

不监听端口、不注册路由。要看它活没活着看容器日志或 `docker compose ps`。
崩了由 `restart: unless-stopped` 拉起来,循环内部本来也每轮 try/except。

本地开发不需要它:`uvicorn app.main:app` 默认 AUTO_FLOW_ENABLED=true,
lifespan 照旧自己起一份(单进程,没有重复问题)。
"""
import asyncio
import logging

from .config import settings
from .db import engine
from .services.auto_flow import auto_flow_loop

logger = logging.getLogger("superz.sweeper")


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.auto_flow_enabled:
        # 明确说清楚再退出。静默空转会让人对着"容器明明在跑"查半天
        logger.warning("AUTO_FLOW_ENABLED=false,清扫进程不做事,退出")
        return
    logger.info("清扫进程启动,间隔 %ss", settings.sweep_interval_seconds)
    try:
        await auto_flow_loop()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
