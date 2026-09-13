"""接口限流(Redis 固定窗口;「N 秒一次」的按冷却算,见 check_rate_limit_seconds)。

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


async def check_daily_limit(scope: str, key: str, per_day: int,
                            message: str = "今天的次数用完了,明天再试") -> None:
    """同一 (scope, key) 每个**北京自然日**最多 per_day 次,超出抛 429(DEV-PROMPTS-40 §5.7)。

    按北京日期切窗,不按 UTC:用户说的「今天」是北京的今天,UTC 切的话
    每天早上 8 点额度莫名其妙地重置一次。Redis 不可用时放行(同上)。
    """
    if not settings.rate_limit_enabled:
        return
    day = time.strftime("%Y%m%d", time.gmtime(time.time() + 8 * 3600))
    redis_key = f"rld:{scope}:{key}:{day}"
    try:
        r = get_redis()
        count = await r.incr(redis_key)
        if count == 1:
            await r.expire(redis_key, 26 * 3600)
    except Exception as exc:
        logger.warning("限流检查失败,放行: %s", exc)
        return
    if count > per_day:
        raise HTTPException(429, message)


async def check_rate_limit_seconds(scope: str, key: str, limit: int, seconds: int = 1,
                                   message: str = "发得太快了,歇一下再发") -> None:
    """同一 (scope, key) 每 seconds 秒最多 limit 次(聊天的「每秒 5 条」用它,§5.7)。

    limit == 1(弹幕 3 秒一条、评论 5 秒一条、群里 1 秒一条)按冷却算:放过一次之后满 seconds 秒才放下一次。
    固定窗口在这里不对 —— 两条只隔 0.1 秒,正好跨过窗口边界就都放过去了,和「3 秒一条」说的不一样
    (e2e_danmaku 在全量回归里偶发失败就是这个)。limit > 1 仍是固定窗口,边界上最多多放一倍,够用。
    """
    if not settings.rate_limit_enabled:
        return
    try:
        r = get_redis()
        if limit == 1:
            passed = bool(await r.set(f"rls:{scope}:{key}:{seconds}:cd", 1, nx=True, px=seconds * 1000))
        else:
            window = int(time.time() // seconds)
            redis_key = f"rls:{scope}:{key}:{seconds}:{window}"
            count = await r.incr(redis_key)
            if count == 1:
                await r.expire(redis_key, seconds + 5)
            passed = count <= limit
    except Exception as exc:
        logger.warning("限流检查失败,放行: %s", exc)
        return
    if not passed:
        raise HTTPException(429, message)
