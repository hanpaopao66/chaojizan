"""机器人 webhook 投递(DEV-PROMPTS-40 #355,§5.13)。

- 每个 api 进程各跑一个循环([webhook_loop],挂在 main.lifespan 上):每秒看一眼「有 webhook、队头到点了」
  的机器人,新更新提交后本进程还会被 [poke] 立刻叫醒,不用等满一秒;
- **同一个机器人同一时刻只有一个进程在投**:Redis 锁 `bot:wh:lock:<机器人>`(拿不到就跳过这一轮,
  Redis 挂了这一轮谁都不投 —— 宁可晚到,不能重复);
- **按 update_id 顺序投**:只投队头那一条,成功了删掉再投下一条;失败了队头按 1 / 2 / 4 / 8 … 分钟退避,
  后面的全部等着(和 Telegram 一样,开发者不会先收到新消息、后收到旧消息);
- 非 2xx 或 10 秒没回都算失败,记下 last_error(getWebhookInfo 里给开发者看);
- 创建满 24 小时还没投成的丢掉(清理顺手做,取 getUpdates 时也过滤);
- 每次投之前**重新解析地址判一次内网**:设置时指向公网、之后改指 127.0.0.1 是最经典的绕法。
  不跟随重定向,不走环境变量里的代理。

请求:`POST <webhook_url>`,`Content-Type: application/json`,正文就是 Update 对象;
设了 secret_token 的带 `X-Superz-Bot-Api-Secret-Token: <secret_token>` 头,开发者据此认出是我们发的。
"""
import asyncio
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, select, text

from ..db import SessionLocal
from ..models import Bot, BotUpdate
from . import bots

logger = logging.getLogger("superz.bots")

SECRET_HEADER = "X-Superz-Bot-Api-Secret-Token"
TIMEOUT_SECONDS = 10
#: 没有新更新时多久看一眼(退避到点的重试、别的进程提交的更新靠它)
LOOP_INTERVAL = 1.0
#: 过期清理多久做一次
PURGE_EVERY = 10.0
#: 同时投几个机器人(一个机器人的 webhook 慢,不能拖住别的机器人)
CONCURRENCY = 8
#: 一个机器人一轮最多连着投几条、最多投多久,到了让给别人,下一轮接着投。
#: 时间上限要明显小于锁的 TTL:锁先过期的话别的进程会同时投同一个机器人,顺序就乱了
PER_ROUND = 50
ROUND_SECONDS = 30
LOCK_TTL = 60

_event: asyncio.Event | None = None


def poke() -> None:
    """有新更新提交了:叫醒本进程的循环,不用等下一秒。"""
    if _event is not None:
        _event.set()


def retry_delay(attempts: int) -> timedelta:
    """第 attempts 次失败之后多久再试:1、2、4、8 …… 分钟(24 小时后丢弃,自然就停了)。"""
    return timedelta(minutes=2 ** max(0, attempts - 1))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def webhook_loop() -> None:
    global _event
    _event = asyncio.Event()
    logger.info("机器人 webhook 投递循环启动")
    last_purge = 0.0
    loop = asyncio.get_running_loop()
    while True:
        try:
            if loop.time() - last_purge >= PURGE_EVERY:
                await purge_expired()
                last_purge = loop.time()
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("机器人 webhook 投递这一轮出错(下一轮接着来)")
        try:
            await asyncio.wait_for(_event.wait(), timeout=LOOP_INTERVAL)
        except asyncio.TimeoutError:
            pass
        _event.clear()


async def purge_expired(now: datetime | None = None) -> int:
    """丢掉创建满 24 小时的更新(不管是在等 webhook 还是等 getUpdates)。"""
    cutoff = (now or _utcnow()) - bots.UPDATE_TTL
    async with SessionLocal() as db:
        res = await db.execute(delete(BotUpdate).where(BotUpdate.created_at < cutoff))
        await db.commit()
    n = res.rowcount or 0
    if n:
        logger.info("丢掉了 %s 条满 24 小时没送出去的机器人更新", n)
    return n


# 每个设了 webhook 的机器人看一眼它的队头(按 update_id 最小的那条)到点没有:
# 一个机器人一次主键索引探查,不随积压的更新数增长
_DUE_SQL = text("""
SELECT b.user_id
  FROM bots b
  CROSS JOIN LATERAL (
        SELECT u.next_try_at FROM bot_updates u
         WHERE u.bot_id = b.user_id AND u.delivered_at IS NULL
         ORDER BY u.update_id LIMIT 1) head
 WHERE b.webhook_url <> '' AND (head.next_try_at IS NULL OR head.next_try_at <= :now)
 ORDER BY head.next_try_at NULLS FIRST
 LIMIT 200
""")


async def run_once() -> int:
    """投一轮。返回这一轮碰了几个机器人。"""
    async with SessionLocal() as db:
        if not await bots.bots_on(db):
            return 0          # 拉闸:webhook 暂停,更新留着(24 小时内开闸还能送到)
        ids = [int(r[0]) for r in (await db.execute(_DUE_SQL, {"now": _utcnow()})).all()]
    if not ids:
        return 0
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(bot_id: int) -> None:
        async with sem:
            try:
                await deliver_bot(bot_id)
            except Exception:
                logger.exception("给机器人 %s 投 webhook 出错", bot_id)

    await asyncio.gather(*(one(i) for i in ids))
    return len(ids)


async def _lock(bot_id: int) -> str | None:
    from ..redis_client import get_redis
    token = secrets.token_hex(8)
    try:
        ok = await get_redis().set(f"bot:wh:lock:{bot_id}", token, nx=True, ex=LOCK_TTL)
    except Exception:
        logger.warning("webhook 锁拿不到(Redis 不可用),这一轮不投", exc_info=True)
        return None
    return token if ok else None


_UNLOCK_LUA = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"


async def _unlock(bot_id: int, token: str) -> None:
    from ..redis_client import get_redis
    try:
        await get_redis().eval(_UNLOCK_LUA, 1, f"bot:wh:lock:{bot_id}", token)
    except Exception:
        pass


async def deliver_bot(bot_id: int) -> int:
    """按顺序投这个机器人的更新,直到队空、队头在退避、或者投满一轮。返回投成了几条。

    **投的时候不占数据库连接**:读出队头 → 关掉会话 → 发 HTTP(最长 10 秒)→ 新会话记结果。
    """
    lock = await _lock(bot_id)
    if lock is None:
        return 0
    sent = 0
    started = asyncio.get_running_loop().time()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                                     trust_env=False) as client:
            for _ in range(PER_ROUND):
                if asyncio.get_running_loop().time() - started > ROUND_SECONDS:
                    return sent
                now = _utcnow()
                async with SessionLocal() as db:
                    bot = await db.get(Bot, bot_id)
                    if bot is None or not bot.webhook_url:
                        return sent
                    head = await db.scalar(select(BotUpdate).where(
                        BotUpdate.bot_id == bot_id, BotUpdate.delivered_at.is_(None))
                        .order_by(BotUpdate.update_id).limit(1))
                    if head is None:
                        return sent
                    if head.created_at is not None and head.created_at < now - bots.UPDATE_TTL:
                        # 满 24 小时没投成:丢掉,接着投下一条
                        await db.execute(delete(BotUpdate).where(
                            BotUpdate.bot_id == bot_id, BotUpdate.update_id == head.update_id))
                        await db.commit()
                        continue
                    if head.next_try_at is not None and head.next_try_at > now:
                        return sent     # 队头在退避:后面的也等着(按顺序投)
                    url, secret = bot.webhook_url, bots.webhook_secret_plain(bot)
                    update_id, payload, attempts = head.update_id, head.payload, head.attempts
                if url.startswith(bots.INTERNAL_WEBHOOK_PREFIX):
                    ok, err = await internal_post(bot_id, url, payload)
                else:
                    ok, err = await post(client, url, secret, payload)
                async with SessionLocal() as db:
                    if ok:
                        await db.execute(delete(BotUpdate).where(
                            BotUpdate.bot_id == bot_id, BotUpdate.update_id == update_id))
                        await db.commit()
                        sent += 1
                        continue
                    n = attempts + 1
                    row = await db.get(BotUpdate, (bot_id, update_id))
                    if row is not None:
                        row.attempts = n
                        row.next_try_at = _utcnow() + retry_delay(n)
                    b = await db.get(Bot, bot_id)
                    if b is not None:
                        b.webhook_error_at = _utcnow()
                        b.webhook_error = err[:300]
                    await db.commit()
                    logger.info("机器人 %s 的 webhook 投递失败(第 %s 次):%s", bot_id, n, err[:120])
                    return sent
    finally:
        await _unlock(bot_id, lock)
    return sent


async def post(client: httpx.AsyncClient, url: str, secret: str, payload: dict) -> tuple[bool, str]:
    """投一次。返回 (成功没有, 失败原因)。失败原因的写法照 Telegram 的 last_error_message。"""
    try:
        await bots.check_webhook_url(url)
    except bots.BotError as e:
        return False, e.description.removeprefix("Bad Request: bad webhook: ")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers[SECRET_HEADER] = secret
    body = json.dumps(payload, ensure_ascii=False).encode()
    try:
        resp = await client.post(url, content=body, headers=headers)
    except httpx.TimeoutException:
        return False, "Read timeout expired"
    except httpx.HTTPError as e:
        return False, f"Connection failed: {type(e).__name__}"
    if 200 <= resp.status_code < 300:
        return True, ""
    return False, f"Wrong response from the webhook: {resp.status_code} {resp.reason_phrase}"


async def internal_post(bot_id: int, url: str, payload: dict) -> tuple[bool, str]:
    """平台自己的机器人(webhook 地址 `internal:…`,见 bots.INTERNAL_WEBHOOK_PREFIX):在进程里调处理函数。

    排队、按顺序、锁、24 小时过期都和 HTTP 的一样,只是「投」这一步换成函数调用。处理函数自己兜住异常
    (机器人管家出错会回用户一句话),这里再兜一层:真抛出来就按投递失败退避,和对方服务器 500 一样。
    """
    from . import bot_manager

    handlers = {bot_manager.WEBHOOK: bot_manager.handle}
    handler = handlers.get(url)
    if handler is None:
        return False, f"没有这个内部处理:{url}"
    try:
        await handler(bot_id, payload)
    except Exception as e:
        logger.exception("内部机器人 %s 处理更新出错", bot_id)
        return False, f"Internal handler failed: {type(e).__name__}"
    return True, ""
