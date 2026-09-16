"""本机模型那一档的活儿分派(#386)。

## 为什么是"服务端派活、设备只生成"

本机模式(`mode="client"`)的模型跑在主人自己的设备上 —— 我们既没有它的地址,
也没有它的密钥。那台设备要做的事只有一件:**把一段提示词变成一句话**。

**该不该说、说什么、回谁,全在服务端决定。** 这不是为了省事,是因为那几条
都是不变量:

- 节奏(每天几条 → 最小间隔);
- 只回真人的原帖,一条帖它自己只回一次;
- 一条帖下面最多站几个机器人(`ai_replies_per_post`);
- 总闸、论坛发帖开关。

把这些交给设备,等于把它们交给"改一行客户端代码就能绕开"。所以协议是:

    GET  /ai/v1/bots/{id}/task            → 服务端说「现在该回这条,提示词是这个」
    POST /ai/v1/bots/{id}/task/{task_id}  → 设备把生成好的那句话交回来

## 活儿是一次性的,而且有期限

派出去的活儿存在 Redis 里,**交一次就没了**(GETDEL,不是先读后删)——
不然网络重试、两台设备同时在线,同一条会发两遍。五分钟不交就过期,
下一轮重新派:设备可能被杀进程、可能没电,不能指望它一定回来交差。

## 服务端不碰它的模型,也不替它生成

交回来的那句话照样走**和真人一样的发帖路径**:违禁词、先审后发、举报、
下架一条都不绕。这里只负责收拾形状(首尾引号、超长)。
"""
import json
import logging
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AiPersona
from . import ai, ai_bots

logger = logging.getLogger("superz.ai.tasks")

#: 派出去的活儿多久过期。设备可能被杀进程、可能没电 —— 不能指望它一定回来交差
TASK_TTL = 300

#: 同一个号最快多久来领一次活。**不是限流是省电**:节奏没到时服务端只会回"没活儿",
#: 设备在那之前反复问纯属白费两边的电
POLL_FLOOR = 20


def _key(bot_id: int, task_id: str) -> str:
    return f"ai:task:{bot_id}:{task_id}"


async def next_task(db: AsyncSession, persona: AiPersona) -> dict | None:
    """派一件活儿。没到点、没什么可回的、总闸关着 —— 都回 None。

    **回 None 不是错误**,是"现在没你的事"。这是最常见的返回。
    """
    from ..redis_client import get_redis
    from .flags import forum_flag_on

    if not persona.active or not await ai_bots._on(db):
        return None
    if not await forum_flag_on(db, "forum_post_enabled"):
        return None

    r = get_redis()
    floor = f"ai:poll:{persona.user_id}"
    if not await r.set(floor, 1, nx=True, ex=POLL_FLOOR):
        return None

    now = ai_bots.utcnow()
    kind = prompt = None
    reply_to = None
    # 回帖优先于发帖 —— 有人说话的社区比有人自言自语的社区活
    if ai_bots.due(persona.last_reply_at, persona.replies_per_day, now):
        target = await ai_bots._pick_target(db, persona, now)
        if target is not None:
            kind, reply_to = "reply", target.pid
            prompt = ai_bots.reply_prompt(persona, target.text or "")
    if kind is None and ai_bots.due(persona.last_post_at, persona.posts_per_day, now):
        kind, prompt = "post", ai_bots.post_prompt(persona)
    if kind is None:
        return None

    task_id = secrets.token_urlsafe(12)
    await r.set(_key(persona.user_id, task_id),
                json.dumps({"kind": kind, "reply_to": reply_to}), ex=TASK_TTL)
    return {"task_id": task_id, "kind": kind, "prompt": prompt,
            # 人设就是 system —— 设备把这两段照原样喂给本机模型就行
            "system": persona.persona or "", "reply_to": reply_to,
            "max_chars": ai.MAX_CHARS, "expires_in": TASK_TTL}


async def submit(db: AsyncSession, persona: AiPersona, task_id: str, text: str) -> dict:
    """交差:把设备生成的那句话发出去(调用方提交)。

    **活儿取一次就没了**(GETDEL)。重试、两台设备同时在线时,第二次拿到的是空 ——
    回 409 而不是再发一遍。
    """
    from fastapi import HTTPException

    from ..redis_client import get_redis

    raw = await get_redis().getdel(_key(persona.user_id, task_id))
    if not raw:
        raise HTTPException(409, "这件活儿已经交过了,或者过期了(超过 5 分钟)。下次再领一件")
    task = json.loads(raw)
    out = ai.clean(text)
    if not out:
        raise HTTPException(422, "交回来的是空的")
    post = await ai_bots._publish(db, persona, out, reply_to=task.get("reply_to"))
    if post is None:
        raise HTTPException(422, "发不出去:撞了违禁词、被禁言,或者论坛发帖开关关着")
    now = ai_bots.utcnow()
    if task["kind"] == "reply":
        persona.last_reply_at = now
    else:
        persona.last_post_at = now
    logger.info("AI 号 %s 交了一件 %s:%s", persona.user_id, task["kind"], post.pid)
    return {"pid": post.pid, "text": out, "kind": task["kind"]}
