"""接口限流(Redis 固定窗口)。

目标是拦爆破和刷子,不是限制正常用户,所以阈值宽松(见 config.py)。
Redis 不可用时放行——限流是防护,不能反过来变成单点故障。
"""
import logging
import time

from fastapi import HTTPException

from .config import settings
from .redis_client import get_redis

logger = logging.getLogger("superz.ratelimit")


async def check_rate_limit(scope: str, key: str, per_minute: int) -> None:
    """同一 (scope, key) 每分钟最多 per_minute 次,超出抛 429。"""
    if not settings.rate_limit_enabled:
        return
    window = int(time.time() // 60)
    redis_key = f"rl:{scope}:{key}:{window}"
    try:
        r = get_redis()
        count = await r.incr(redis_key)
        if count == 1:
            await r.expire(redis_key, 90)  # 窗口结束后自动清理
    except Exception as exc:
        logger.warning("限流检查失败,放行: %s", exc)
        return
    if count > per_minute:
        raise HTTPException(429, "操作太频繁,请稍后再试")
