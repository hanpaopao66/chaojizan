"""接口限流(Redis 固定窗口)。

目标是拦爆破和刷子,不是限制正常用户,所以阈值宽松(见 config.py)。
Redis 不可用时放行——限流是防护,不能反过来变成单点故障。
"""
import logging
import time

from fastapi import HTTPException, Request

from .config import settings
from .redis_client import get_redis

logger = logging.getLogger("superz.ratelimit")


def client_ip(request: Request) -> str:
    """真实来源 IP。**所有按 IP 限流的地方都必须走这里。**

    生产上 api 跑在 nginx 后面,而 nginx 是**另一个容器** ——
    直接读 `request.client.host` 拿到的是 nginx 的容器地址(172.x),
    对所有请求都是同一个值。后果不是"限流不准",是"限流对象错了":
    /screen 和 /transparency 全站共用一个 120/分钟的桶,
    几台店内电视轮询就能把额度刷光,然后所有人一起 429。

    两道保险,缺一不可:
      1. uvicorn 起时带 `--forwarded-allow-ips`(见 server/Dockerfile),
         它会用可信代理送来的 X-Forwarded-For 改写 request.client;
      2. 这里再读一次 XFF 首值 —— 万一忘了配启动参数,至少还有这一层。

    注意 XFF 是客户端可伪造的头,只有经过步骤 1 的可信代理链才有意义。
    所以这个值只配用来做限流分桶,**不要拿它做鉴权判断**。
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd.strip():
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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
