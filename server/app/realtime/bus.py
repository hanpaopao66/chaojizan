"""跨进程分发:一个 Redis 频道,所有 api 进程都订阅(DEV-PROMPTS-40 §6)。

现在 api 是单进程,这一层等于自己发给自己再丢掉(带进程标识去重)。
照多进程的方式写,是为了以后加 worker 时协议不用改 —— 真到那时才补,
最可能的结果是「多开了几个进程,一半人收不到消息」,而且不报错。

`REALTIME_BUS=false` 可以关掉(只在明确单进程、又不想要这点开销时)。
"""
import asyncio
import json
import logging

from ..config import settings
from ..redis_client import get_redis

logger = logging.getLogger("superz.realtime")
CHANNEL = "rt:frames"


async def publish(*, frames: list | None = None, direct: list | None = None,
                  chat_direct: list | None = None, presence: list | None = None) -> None:
    if not settings.realtime_bus:
        return
    from .hub import PROCESS_ID

    payload = {"origin": PROCESS_ID}
    if frames:
        payload["frames"] = frames
    if direct:
        payload["direct"] = direct
    if chat_direct:
        payload["chat_direct"] = chat_direct
    if presence:
        payload["presence"] = presence
    try:
        await get_redis().publish(CHANNEL, json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        # Redis 挂了:本进程的连接照样收到(dispatch 先本地发、再转发),只是跨进程的丢了
        logger.warning("实时事件转发到 Redis 失败", exc_info=True)


async def listen_forever() -> None:
    """启动时起一个后台任务跑它;断了自动重连。"""
    from .hub import PROCESS_ID, hub

    while True:
        pubsub = None
        try:
            pubsub = get_redis().pubsub()
            await pubsub.subscribe(CHANNEL)
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    payload = json.loads(msg["data"])
                except (TypeError, ValueError):
                    continue
                if payload.get("origin") == PROCESS_ID:
                    continue
                if payload.get("frames"):
                    await hub.dispatch(payload["frames"], from_bus=True)
                if payload.get("direct") or payload.get("chat_direct"):
                    hub.deliver_direct(payload.get("direct") or [],
                                       payload.get("chat_direct") or [])
                for uid, online in payload.get("presence") or ():
                    await hub._broadcast_presence(int(uid), bool(online))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("实时事件订阅断了,2 秒后重连", exc_info=True)
            await asyncio.sleep(2)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
