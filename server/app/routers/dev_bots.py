"""开发者后台的机器人 `/dev/v1/bots…`(DEV-PROMPTS-40 #355)。

和小程序同一个开发者身份(developer 角色,dev_miniapps.ctx)。**只能管自己的机器人**:
别人的机器人一律 404,不回 403 —— 别人的机器人存不存在,也不该从这里探出来。

token 只在「建机器人」和「重置 token」那一次响应里完整出现,之后后台只显示前 6 位。
开关 bots_enabled 关着时不能建新机器人(503);已有的照样能看、能改、能删。
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Bot, MiniApp, SocialProfile, User
from ..services import bots
from ..services.bots import BotError
from ..services.flags import bots_on
from ..services.social import display_name
from .dev_miniapps import Ctx, ctx
from .social import PUBLIC_BASE

router = APIRouter(prefix="/dev/v1", tags=["机器人开发者"])

TOKEN_NOTICE = "token 只显示这一次,请立即保存到你的服务端配置里;丢了只能重置"


def _http(e: BotError) -> HTTPException:
    """Bot API 共用的校验抛的是 BotError(「Bad Request: …」),后台给人看的去掉前缀。"""
    detail = re.sub(r"^(Bad Request|Forbidden|Conflict)(: (bad webhook: )?)?", "", e.description)
    return HTTPException(422 if e.code == 400 else e.code, detail.strip() or e.description)


async def own_bot(db: AsyncSession, c: Ctx, bot_id: int, *, lock: bool = True) -> Bot:
    """我的机器人;别人的、不存在的一律 404。改动类的接口锁行(和 Bot API 同时改同一个机器人时不互相覆盖)。"""
    q = select(Bot).where(Bot.user_id == bot_id, Bot.owner_id == c.user.id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    bot = await db.scalar(q)
    if bot is None:
        raise HTTPException(404, "机器人不存在")
    return bot


async def bot_dev(db: AsyncSession, bot: Bot) -> dict:
    """后台看到的机器人:**不含 token**,只有前 6 位。"""
    u = await db.get(User, bot.user_id)
    prof = await db.get(SocialProfile, bot.user_id)
    menu: dict = bots.menu_obj(bot)
    if bot.menu_type == "web_app":
        app = await db.scalar(select(MiniApp).where(MiniApp.appid == bot.menu_app_id))
        menu = {"type": "web_app", "text": bot.menu_text, "app_id": bot.menu_app_id,
                "app": {"name": app.name, "icon": app.icon, "status": app.status} if app else None,
                # 小程序下架了按钮就不出:后台要让开发者看得出来为什么用户那边没有菜单
                "available": bool(app and app.status == "online")}
    info = await bots.webhook_info(db, bot)
    username = prof.username if prof else None
    return {
        "id": bot.user_id,
        "name": display_name(u) if u else "",
        "username": username,
        "link": f"{PUBLIC_BASE}/@{username}" if username else None,
        "avatar": (u.avatar_url or "") if u else "",
        "about": bot.about or "",
        "description": bot.description or "",
        "commands": list(bot.commands or []),
        "menu_button": menu,
        "privacy_mode": bool(bot.privacy_mode),
        "token_prefix": bot.token_prefix,
        "created_at": bot.created_at.isoformat() if bot.created_at else None,
        "webhook": {
            "url": bot.webhook_url or "",
            "has_secret": bool(bot.webhook_secret),
            "pending_update_count": info["pending_update_count"],
            "last_error_date": bot.webhook_error_at.isoformat() if bot.webhook_error_at else None,
            "last_error_message": bot.webhook_error or "",
        },
    }


@router.get("/bots")
async def list_bots(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    rows = list(await db.scalars(select(Bot).where(Bot.owner_id == c.user.id)
                                 .order_by(Bot.created_at.desc(), Bot.user_id.desc())))
    return {"items": [await bot_dev(db, b) for b in rows], "max": bots.MAX_BOTS_PER_DEVELOPER,
            "enabled": await bots_on(db)}


class BotCreateIn(BaseModel):
    name: str = Field(max_length=64)
    username: str = Field(max_length=33)


@router.post("/bots")
async def create_bot(body: BotCreateIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    if not await bots_on(db):
        raise HTTPException(503, bots.BOTS_OFF)
    if c.dev.status == "suspended":
        raise HTTPException(403, "开发者账号已暂停,不能创建机器人")
    bot, token = await bots.create_bot(db, c.user, body.name, body.username)
    await db.commit()
    return {"bot": await bot_dev(db, bot), "token": token, "notice": TOKEN_NOTICE}


@router.get("/bots/{bot_id}")
async def get_bot(bot_id: int, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    return await bot_dev(db, await own_bot(db, c, bot_id, lock=False))


class BotPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    about: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=512)
    avatar: str | None = Field(default=None, max_length=300)
    privacy_mode: bool | None = None


@router.put("/bots/{bot_id}")
async def update_bot(bot_id: int, body: BotPatchIn, c: Ctx = Depends(ctx),
                     db: AsyncSession = Depends(get_db)):
    """改名字、简介(资料卡上的一句话)、描述(空会话中间那段)、头像、隐私模式。"""
    from ..services.moderation import find_banned, submit_images

    bot = await own_bot(db, c, bot_id)
    u = await db.get(User, bot.user_id)
    if body.name is not None:
        u.name = await bots.check_bot_name(db, body.name)
    for field in ("about", "description"):
        v = getattr(body, field)
        if v is not None:
            v = v.strip()
            if v and await find_banned(db, v):
                raise HTTPException(422, "简介或描述包含不允许发布的内容")
            setattr(bot, field, v)
    if body.avatar is not None:
        url = body.avatar.strip()
        # 头像走现有的图片上传(POST /upload,purpose=avatar),只认这个开发者自己传的那张
        if url and not re.fullmatch(rf"/img/avatar/u{c.user.id}-[0-9a-f]{{32}}\.(jpg|jpeg|png|webp)",
                                    url):
            raise HTTPException(422, "头像要先用 /upload(purpose=avatar)上传")
        if url and url != u.avatar_url:
            await submit_images(db, "avatar", u.id, [url])     # 和用户头像一样进图片审核队列
        u.avatar_url = url
    if body.privacy_mode is not None:
        bot.privacy_mode = body.privacy_mode
    await db.commit()
    return await bot_dev(db, bot)


class CommandsIn(BaseModel):
    commands: list = Field(default_factory=list, max_length=100)


@router.put("/bots/{bot_id}/commands")
async def set_commands(bot_id: int, body: CommandsIn, c: Ctx = Depends(ctx),
                       db: AsyncSession = Depends(get_db)):
    bot = await own_bot(db, c, bot_id)
    try:
        bot.commands = await bots.validate_commands(db, body.commands)
    except BotError as e:
        raise _http(e) from e
    await db.commit()
    return await bot_dev(db, bot)


class MenuIn(BaseModel):
    type: str = Field(pattern="^(commands|default|web_app)$")
    text: str = Field(default="", max_length=64)
    app_id: str = Field(default="", max_length=24)


@router.put("/bots/{bot_id}/menu-button")
async def set_menu_button(bot_id: int, body: MenuIn, c: Ctx = Depends(ctx),
                          db: AsyncSession = Depends(get_db)):
    """菜单按钮:命令列表 / 打开自己名下一个已上架的小程序 / 没有。"""
    bot = await own_bot(db, c, bot_id)
    raw: dict = {"type": body.type}
    if body.type == "web_app":
        raw.update({"text": body.text, "web_app": {"app_id": body.app_id}})
    try:
        await bots.set_menu(db, bot, raw)
    except BotError as e:
        raise _http(e) from e
    await db.commit()
    return await bot_dev(db, bot)


class WebhookIn(BaseModel):
    url: str = Field(max_length=300)
    secret_token: str | None = Field(default=None, max_length=256)
    drop_pending_updates: bool = False


@router.put("/bots/{bot_id}/webhook")
async def set_webhook(bot_id: int, body: WebhookIn, c: Ctx = Depends(ctx),
                      db: AsyncSession = Depends(get_db)):
    bot = await own_bot(db, c, bot_id)
    try:
        await bots.set_webhook(db, bot, body.url, body.secret_token, body.drop_pending_updates)
    except BotError as e:
        raise _http(e) from e
    await db.commit()
    return await bot_dev(db, bot)


@router.delete("/bots/{bot_id}/webhook")
async def delete_webhook(bot_id: int, drop_pending_updates: bool = False, c: Ctx = Depends(ctx),
                         db: AsyncSession = Depends(get_db)):
    bot = await own_bot(db, c, bot_id)
    await bots.delete_webhook(db, bot, drop_pending_updates)
    await db.commit()
    return await bot_dev(db, bot)


@router.post("/bots/{bot_id}/token")
async def reset_token(bot_id: int, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """重置 token:旧的当场失效,新的只在这次响应里完整出现一次。"""
    bot = await own_bot(db, c, bot_id)
    token = await bots.reset_token(db, bot)
    await db.commit()
    return {"bot": await bot_dev(db, bot), "token": token, "notice": TOKEN_NOTICE}


@router.delete("/bots/{bot_id}")
async def delete_bot(bot_id: int, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """删机器人:它发的消息和注销账号一样清掉(正文、媒体、按钮),退出所有群,用户名释放,token 失效。不可恢复。"""
    bot = await own_bot(db, c, bot_id)
    out = await bots.delete_bot(db, bot)
    await db.commit()
    return {"deleted": True, **{k: v for k, v in out.items() if k in ("messages", "chats_left")}}
