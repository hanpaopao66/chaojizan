"""我自己的 AI 机器人 `/ai/v1/…`(#386)。

## 平台只搭台子

**平台不做大模型级别的机器人,所有接入都是用户级别的。** 每个人自己带模型:

- **本机模型**(`client`,缺省):模型跑在你自己的手机 / 电脑上。
  服务端派活儿、你的设备生成、再交回来。**地址和密钥从不离开那台设备。**
- **公网地址**(`server`):你填一个 OpenAI 兼容的地址,平台按节奏去调。
  地址要过内网守卫,密钥加密存、读不回来。

## 只能管自己的

别人的机器人一律 404,不回 403 —— 别人有没有这个号,也不该从这里探出来。

## 说话的规矩和真人一样

名片上挂「机器人」和「AI」两个标(《标识办法》要的显式标识);发帖走和真人
一样的路(违禁词、先审后发、举报、下架);**它的互动不进任何公开榜单和推荐权重**。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import AiPersona, Developer, User
from ..ratelimit import check_rate_limit_seconds
from ..security import get_current_user
from ..services import ai, ai_bots, ai_tasks

router = APIRouter(prefix="/ai/v1", tags=["我的 AI 机器人"])


async def _mine(db: AsyncSession, me: User, bot_id: int, *, lock: bool = False) -> AiPersona:
    """我的那个号;别人的、不存在的一律 404。"""
    q = select(AiPersona).where(AiPersona.user_id == bot_id, AiPersona.owner_id == me.id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(q)
    if row is None:
        raise HTTPException(404, "没有这个机器人")
    return row


async def _out(db: AsyncSession, row: AiPersona) -> dict:
    from sqlalchemy import func

    from ..models import ForumPost, Username

    u = await db.get(User, row.user_id)
    name_row = await db.scalar(select(Username).where(
        Username.owner_type == "user", Username.owner_id == row.user_id))
    posts = await db.scalar(select(func.count()).select_from(ForumPost)
                            .where(ForumPost.author_id == row.user_id)) or 0
    return {"user_id": row.user_id, "name": u.name if u else "",
            "username": name_row.username_lc if name_row else "",
            "mode": row.mode, "endpoint": row.endpoint, "model": row.model,
            # **密钥只说设没设**,任何时候都不回明文
            "has_key": bool(row.api_key_enc), "timeout_seconds": row.timeout_seconds,
            "persona": row.persona, "topics": row.topics,
            "posts_per_day": row.posts_per_day, "replies_per_day": row.replies_per_day,
            "active": row.active, "posts": int(posts),
            "last_post_at": row.last_post_at.isoformat() if row.last_post_at else None,
            "last_reply_at": row.last_reply_at.isoformat() if row.last_reply_at else None}


class BotIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    #: 必须以 bot 结尾 —— 别人一眼看得出这是机器人
    username: str = Field(min_length=5, max_length=32)
    persona: str = Field(min_length=1, max_length=2000)
    topics: str = Field(default="", max_length=300)
    posts_per_day: int = Field(default=2, ge=0, le=288)
    replies_per_day: int = Field(default=5, ge=0, le=576)
    #: 缺省本机模型 —— 那一档我们连地址都不持有,是默认最稳的那个
    mode: str = Field(default="client", pattern="^(client|server)$")


class BotPatch(BaseModel):
    persona: str | None = Field(default=None, min_length=1, max_length=2000)
    topics: str | None = Field(default=None, max_length=300)
    posts_per_day: int | None = Field(default=None, ge=0, le=288)
    replies_per_day: int | None = Field(default=None, ge=0, le=576)
    active: bool | None = None
    mode: str | None = Field(default=None, pattern="^(client|server)$")
    endpoint: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=80)
    #: 传了才改;传空串 = 清掉。**存密文,读不回来**
    api_key: str | None = Field(default=None, max_length=300)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)


@router.get("/limits")
async def my_limits(me: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """这个人现在能建几个、每天最多发几条。**页面上要先告诉人规矩再让他填表** ——
    填完一长串再被拒是最烦人的。"""
    from sqlalchemy import func

    cap = await ai_bots.limit(db, "ai_bots_per_user")
    mine = await db.scalar(select(func.count()).select_from(AiPersona)
                           .where(AiPersona.owner_id == me.id)) or 0
    return {"enabled": await ai_bots._on(db), "per_user": cap, "mine": int(mine),
            "posts_per_day_max": await ai_bots.limit(db, "ai_posts_per_day_max"),
            "replies_per_day_max": await ai_bots.limit(db, "ai_replies_per_day_max"),
            "replies_per_post": await ai_bots.limit(db, "ai_replies_per_post")}


@router.get("/bots")
async def my_bots(me: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = list(await db.scalars(select(AiPersona).where(AiPersona.owner_id == me.id)
                                 .order_by(AiPersona.user_id)))
    return {"items": [await _out(db, r) for r in rows]}


@router.post("/bots")
async def create_my_bot(body: BotIn, me: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """建一个自己的 AI 号。名额和总闸都是后台可调的。"""
    if not await ai_bots._on(db):
        raise HTTPException(503, "AI 机器人还没开放")
    await check_rate_limit_seconds("ai_new", str(me.id), 5, 3600,
                                   "建得太快了,过一会儿再试")
    # FK 上挂在官方开发者名下(机器人账号体系要求主人是开发者),
    # 但**它是你的** —— ai_personas.owner_id 才是"谁的"
    dev = await db.scalar(select(Developer)
                          .where(Developer.is_official.is_(True),
                                 Developer.user_id.is_not(None))
                          .order_by(Developer.id).limit(1))
    owner = await db.get(User, dev.user_id) if dev else None
    if owner is None:
        raise HTTPException(503, "AI 机器人还没准备好,稍后再试")
    row = await ai_bots.create(db, owner, holder=me, name=body.name, username=body.username,
                               persona=body.persona, topics=body.topics,
                               posts_per_day=body.posts_per_day,
                               replies_per_day=body.replies_per_day, mode=body.mode)
    row.posts_per_day = min(row.posts_per_day,
                            await ai_bots.limit(db, "ai_posts_per_day_max"))
    row.replies_per_day = min(row.replies_per_day,
                              await ai_bots.limit(db, "ai_replies_per_day_max"))
    await db.commit()
    return await _out(db, row)


@router.patch("/bots/{bot_id}")
async def patch_my_bot(bot_id: int, body: BotPatch, me: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    row = await _mine(db, me, bot_id, lock=True)
    patch = body.model_dump(exclude_unset=True)
    key = patch.pop("api_key", None)
    if key is not None:
        from ..services import crypto
        row.api_key_enc = crypto.encrypt(key) if key else ""
    if patch.get("endpoint"):
        # 这个地址是用户填的,请求由**我们的服务器**发 —— 所以要过内网守卫
        await ai_bots.check_endpoint(patch["endpoint"])
    for k, v in patch.items():
        setattr(row, k, v)
    row.posts_per_day = min(row.posts_per_day,
                            await ai_bots.limit(db, "ai_posts_per_day_max"))
    row.replies_per_day = min(row.replies_per_day,
                              await ai_bots.limit(db, "ai_replies_per_day_max"))
    await db.commit()
    return await _out(db, row)


@router.delete("/bots/{bot_id}")
async def delete_my_bot(bot_id: int, me: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """删掉。**它发过的帖还在**(作者显示成已删除),和真人注销账号之后一样 ——
    不然别人回过它的那些串会断掉。用户名会释放。"""
    row = await _mine(db, me, bot_id, lock=True)
    await ai_bots.remove(db, row)
    await db.commit()
    return {"ok": True}


# ---------------- 本机模型那一档:服务端派活儿,设备只生成 ----------------

@router.get("/bots/{bot_id}/task")
async def pull_task(bot_id: int, me: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    """领一件活儿。**没到点就回 `{"task": null}`,那不是错误**,是最常见的返回。

    该不该说、回谁、一条帖下面站几个 —— 全是服务端定的。设备只负责把提示词
    变成一句话。这几条是不变量,交给设备等于交给"改一行客户端代码就能绕开"。
    """
    row = await _mine(db, me, bot_id)
    if row.mode != "client":
        raise HTTPException(409, "这个号是公网地址模式:平台自己按节奏去调,不用你的设备生成")
    task = await ai_tasks.next_task(db, row)
    await db.commit()
    return {"task": task}


class SubmitIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/bots/{bot_id}/task/{task_id}")
async def submit_task(bot_id: int, task_id: str, body: SubmitIn,
                      me: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """交差。走**和真人一样的**发帖路径:违禁词、先审后发、举报、下架一条都不绕。"""
    row = await _mine(db, me, bot_id, lock=True)
    if row.mode != "client":
        raise HTTPException(409, "这个号是公网地址模式,不收设备交回来的内容")
    out = await ai_tasks.submit(db, row, task_id, body.text)
    await db.commit()
    return out


@router.post("/bots/{bot_id}/probe")
async def probe_my_bot(bot_id: int, payload: dict | None = None,
                       me: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """让你填的那个地址现答一句,看配对了没有。

    地址错一个字、模型名写错 —— 表现都是**这个号一个字都不发**,而页面上看着是好的。
    """
    row = await _mine(db, me, bot_id)
    if row.mode != "client":
        await check_rate_limit_seconds("ai_probe", str(me.id), 20, 3600,
                                       "试得太频繁了,过一会儿再试")
        cfg = ai.config_of(row)
        if not cfg.ok:
            return {"ok": False, "error": "地址和模型名都要填",
                    "endpoint": row.endpoint, "model": row.model}
        prompt = str((payload or {}).get("prompt") or "").strip() or "用一句话说说今天天气"
        r = await ai.complete(cfg, prompt[:200])
        return {"ok": r.ok, "reply": r.text, "error": r.error,
                "endpoint": row.endpoint, "model": row.model, "has_key": bool(row.api_key_enc)}
    raise HTTPException(409, "本机模型在你自己的设备上,服务端探不了 —— 在设备上直接试")
