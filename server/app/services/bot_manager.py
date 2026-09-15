"""机器人管家 @guanjia_bot:在对话里建机器人、改命令、重置 token……(对标 Telegram 的 @BotFather)。

它是官方开发者名下一个普通的机器人,只是 webhook 地址是 `internal:guanjia` —— 投递循环
(bot_webhook.deliver_bot)认出这个前缀,就不发 HTTP、直接在进程里调 [handle]。所以排队、按 update_id 顺序、
同一时刻只有一个进程在处理(Redis 锁)这些都和别的机器人一样,不另起一套。`internal:` 开头的地址只能由服务端写
(setWebhook 和开发者后台都只收 https),开发者设不出来。建它、把设置对齐:scripts/seed_bot_manager.py。

能做的和开发者后台「机器人」页一样,**用的也是同一批函数**(services/bots 的 create_bot、check_bot_name、
validate_commands、reset_token、delete_bot),规则、上限、屏蔽词一处改两处生效。

## 谁能用

聊天用的是顾客账号,机器人挂在开发者账号名下(账号按「手机号 + 角色」分立)—— 管家按**同一个手机号**找开发者账号。
没有开发者账号的,告诉他先去开发者后台注册;开发者账号暂停的不许建新机器人(和后台一样),注销的什么都不能做。
每一步都按这次更新里的 `from.id` 重新找一遍开发者、再按 owner_id 查机器人:按钮上的机器人 id 只是个选择,不是凭据。

## token 不进聊天记录

开发者后台的承诺是「token 只显示一次,库里只存它的 sha256,平台看不到原文」。管家要是像 Telegram 那样把 token
发成一条消息,原文就进了消息表(和每天的备份),承诺就破了。所以建好 / 重置之后发的是一个「查看 token」按钮:
token 加密后放 Redis、[REVEAL_TTL] 秒内有效、只能取一次;点按钮时用回调应答(弹窗)给出去 —— 回调应答本来就不入库。
取过或者过期了按钮就收掉,想要新的发 /token 重置。

## 出错

处理函数自己兜住所有异常、回一句「没办成」,**不让投递循环重试**:重试会把「建机器人」这种事做两遍。
"""
from __future__ import annotations

import contextlib
import json
import logging
import re
import secrets

from fastapi import HTTPException
from sqlalchemy import func, select

from ..config import settings
from ..db import SessionLocal
from ..models import Bot, Developer, SocialProfile, User, UserRole
from ..redis_client import get_redis
from . import bots
from . import chat_store as store
from .bots import BotError
from .crypto import decrypt, encrypt
from .social import display_name

logger = logging.getLogger("superz.bots")

USERNAME = "guanjia_bot"
NAME = "机器人管家"
WEBHOOK = bots.INTERNAL_WEBHOOK_PREFIX + "guanjia"
ABOUT = "官方机器人:在对话里建机器人、改命令、重置 token。"
DESCRIPTION = "我帮你建和管理机器人,和开发者后台的「机器人」页做同样的事。发 /newbot 建第一个,/help 看看还能做什么。"
COMMANDS = [
    {"command": "newbot", "description": "建一个新机器人"},
    {"command": "mybots", "description": "我的机器人"},
    {"command": "setcommands", "description": "改命令列表"},
    {"command": "setdescription", "description": "改描述(空会话里显示的那段)"},
    {"command": "setabout", "description": "改简介(资料卡上的一句话)"},
    {"command": "setprivacy", "description": "群里的隐私模式"},
    {"command": "token", "description": "重置 token"},
    {"command": "deletebot", "description": "删除机器人"},
    {"command": "cancel", "description": "取消正在做的事"},
    {"command": "help", "description": "看看能做什么"},
]

#: 多步操作(起名 → 起用户名、发命令列表……)记在 Redis 里,这么久没下文就忘掉
STATE_TTL = 900
#: 「查看 token」按钮的有效期
REVEAL_TTL = 600
ABOUT_MAX = 120
DESCRIPTION_MAX = 512
CLEAR_WORDS = {"清空", "空", "无", "-"}


def _base() -> str:
    return settings.public_base_url.rstrip("/")


def _dev_url() -> str:
    return f"{_base()}/dev"


HELP = """我是机器人管家,帮你建和管理机器人(和开发者后台的「机器人」页做同样的事)。

/newbot 建一个新机器人
/mybots 我的机器人
/setcommands 改命令列表(用户输入 / 时看到的)
/setdescription 改描述(空会话中间那段)
/setabout 改简介(资料卡上的一句话)
/setprivacy 群里的隐私模式
/token 重置 token
/deletebot 删除机器人
/cancel 取消正在做的事

建机器人要先有开发者账号:用这个手机号登录开发者后台注册一个。"""


class _Stop(Exception):
    """中途要回一句话就结束(找不到开发者、机器人不是你的……)。"""

    def __init__(self, text: str, markup: dict | None = None):
        super().__init__(text)
        self.text = text
        self.markup = markup


def parse_commands_text(text: str) -> list[dict]:
    """「命令 - 说明」一行一条 → [{command, description}](和 BotFather 的写法一样)。

    命令前面的 / 可带可不带、大写的转小写;分隔可以是 - 或 —。格式不对抛 ValueError(话能直接给人看)。
    长度、字符、重复、屏蔽词这些交给 bots.validate_commands,和 setMyCommands 同一套。
    """
    out = []
    for i, line in enumerate((text or "").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^/?([^\s\-—–]+)\s*[-—–]+\s*(.+)$", line)
        if m is None:
            raise ValueError(f"第 {i} 行没看懂:命令和说明之间用「-」隔开,比如「start - 开始」")
        out.append({"command": m.group(1).lower(), "description": m.group(2).strip()})
    return out


def _kb(*rows: list[dict]) -> dict:
    return {"inline_keyboard": [list(r) for r in rows]}


def _btn(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def _link(text: str, url: str) -> dict:
    return {"text": text, "url": url}


def _no_dev_markup() -> dict:
    return _kb([_link("打开开发者后台", _dev_url())])


def _bot_error_text(e: BotError) -> str:
    # Bot API 的报错带「Bad Request:」前缀和英文代号,给人看的只留中文那半句
    s = re.sub(r"^(Bad Request|Forbidden|Conflict)(: )?", "", e.description).strip()
    m = re.search(r"[((](.+)[))]$", s)
    return (m.group(1) if m else s) or e.description


# ---------------------------------------------------------------------------- 状态

def _st_key(uid: int) -> str:
    return f"bot:mgr:st:{uid}"


async def _state(uid: int) -> dict | None:
    raw = await get_redis().get(_st_key(uid))
    return json.loads(raw) if raw else None


async def _set_state(uid: int, st: dict) -> None:
    await get_redis().set(_st_key(uid), json.dumps(st, ensure_ascii=False), ex=STATE_TTL)


async def _clear_state(uid: int) -> None:
    await get_redis().delete(_st_key(uid))


async def _stash_token(bot_id: int, uid: int, token: str) -> str:
    """token 加密放 Redis,返回按钮上用的一次性编号。"""
    nonce = secrets.token_urlsafe(18)
    await get_redis().set(f"bot:mgr:tok:{nonce}",
                          encrypt(json.dumps({"bot": bot_id, "user": uid, "token": token})),
                          ex=REVEAL_TTL)
    return nonce


def _reveal_markup(nonce: str) -> dict:
    return _kb([_btn("查看 token(只能看一次)", f"tok:{nonce}")], [_link("在开发者后台打开", _dev_url())])


# ---------------------------------------------------------------------------- 发、改、回

async def _reply(me_id: int, uid: int, text: str, markup: dict | None = None) -> None:
    async with SessionLocal() as db:
        chat = await bots.resolve_target(db, me_id, uid, need_talked=True)
        bot_user = await db.get(User, me_id)
        await store.send_as_bot(db, chat, bot_user, kind="text", text=text, entities=[],
                                markup=await bots.validate_markup(db, markup) if markup else None)
        await db.commit()


async def _set_markup(me_id: int, uid: int, seq: int, markup: dict | None) -> None:
    """换掉 / 收掉管家自己那条消息上的按钮(点过的「查看 token」、确认过的「确定重置」)。"""
    with contextlib.suppress(BotError, HTTPException):
        async with SessionLocal() as db:
            chat = await bots.resolve_target(db, me_id, uid, need_talked=False)
            bot_user = await db.get(User, me_id)
            await store.edit_as_bot(db, chat, bot_user, seq, text=None, entities=None,
                                    markup=await bots.validate_markup(db, markup) if markup else None)
            await db.commit()


async def _answer(me_id: int, qid: str, text: str = "", alert: bool = False) -> None:
    # 每个回调都要回:不回的话用户那边的按钮要转 10 秒
    with contextlib.suppress(BotError):
        await bots.answer_callback(me_id, qid, text, alert, None)


# ---------------------------------------------------------------------------- 开发者、机器人

async def _developer(db, uid: int, *, creating: bool = False) -> User:
    """这个聊天账号(顾客)对应的开发者账号:同一个手机号、role=developer。"""
    me = await db.get(User, uid)
    if me is None or me.deleted_at is not None:
        raise _Stop("找不到你的账号。")
    dev_user = await db.scalar(select(User).where(
        User.phone == me.phone, User.role == UserRole.developer, User.deleted_at.is_(None)))
    dev = await db.scalar(select(Developer).where(Developer.user_id == dev_user.id)) \
        if dev_user is not None else None
    if dev_user is None or dev is None:
        raise _Stop("你还没有开发者账号。先用这个手机号登录开发者后台,注册成开发者,再回来找我。",
                    _no_dev_markup())
    if dev.status == "closed":
        raise _Stop("你的开发者账号已经注销了。")
    if creating and dev.status == "suspended":
        raise _Stop("你的开发者账号已暂停,不能建新机器人。")
    return dev_user


async def _own_bot(db, uid: int, bot_id: int, *, lock: bool = True) -> Bot:
    dev_user = await _developer(db, uid)
    q = select(Bot).where(Bot.user_id == bot_id, Bot.owner_id == dev_user.id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    bot = await db.scalar(q)
    if bot is None:
        raise _Stop("这个机器人不在你名下(可能已经删了)。发 /mybots 看看现在有哪些。")
    return bot


async def _label(db, bot: Bot) -> tuple[str, str]:
    """(名字, 用户名)"""
    u = await db.get(User, bot.user_id)
    prof = await db.get(SocialProfile, bot.user_id)
    return (display_name(u) if u else ""), (prof.username if prof and prof.username else "")


# ---------------------------------------------------------------------------- 入口

async def handle(me_id: int, update: dict) -> None:
    """投递循环调这里(bot_webhook.internal_post)。见文件头「出错」。"""
    uid = None
    try:
        if "message" in update:
            m = update["message"]
            if (m.get("chat") or {}).get("type") != "private":
                return      # 只在私聊里干活;被拉进群里就不吭声
            uid = (m.get("from") or {}).get("id")
            if uid:
                await _on_message(me_id, int(uid), m)
        elif "callback_query" in update:
            q = update["callback_query"]
            uid = (q.get("from") or {}).get("id")
            if uid:
                await _on_callback(me_id, int(uid), q)
    except Exception:
        logger.exception("机器人管家处理更新 %s 出错", update.get("update_id"))
        if uid:
            with contextlib.suppress(Exception):
                await _reply(me_id, int(uid), "出了点问题,没办成。稍后再试一次;一直不行的话到开发者后台操作。")


async def _on_message(me_id: int, uid: int, m: dict) -> None:
    text = (m.get("text") or "").strip()
    cmd = bots.leading_command(text)
    try:
        if cmd is not None:
            await _clear_state(uid)     # 新命令打断正在做的事(和 BotFather 一样)
            name = cmd[0]
            fn = _COMMANDS.get(name)
            if fn is None:
                raise _Stop("没有这个命令。发 /help 看看我能做什么。")
            await fn(me_id, uid)
            return
        st = await _state(uid)
        if st is None:
            raise _Stop("发 /help 看看我能做什么,或者直接 /newbot 建一个机器人。")
        step = _STEPS.get(st.get("step", ""))
        if step is None:
            await _clear_state(uid)
            raise _Stop("刚才在做的事过期了,重新发一次命令吧。")
        await step(me_id, uid, st, text)
    except _Stop as s:
        await _reply(me_id, uid, s.text, s.markup)


# ---------------------------------------------------------------------------- 命令

async def cmd_help(me_id: int, uid: int) -> None:
    await _reply(me_id, uid, HELP, _kb([_link("打开开发者后台", _dev_url())]))


async def cmd_cancel(me_id: int, uid: int) -> None:
    await _reply(me_id, uid, "好,已取消。")


async def cmd_newbot(me_id: int, uid: int) -> None:
    async with SessionLocal() as db:
        dev_user = await _developer(db, uid, creating=True)
        n = await db.scalar(select(func.count()).select_from(Bot).where(Bot.owner_id == dev_user.id))
    if (n or 0) >= bots.MAX_BOTS_PER_DEVELOPER:
        raise _Stop(f"每个开发者最多 {bots.MAX_BOTS_PER_DEVELOPER} 个机器人,先删掉一个(/deletebot)再建。")
    await _set_state(uid, {"step": "newbot_name"})
    await _reply(me_id, uid, f"好,给新机器人起个名字 —— 聊天里显示的就是它,1–{bots.BOT_NAME_MAX} 个字。\n"
                             "随时发 /cancel 取消。")


async def _pick(me_id: int, uid: int, action: str, prompt: str) -> None:
    """先选一个机器人:按钮上带动作和机器人 id(回调里还会再核一遍是不是你的)。"""
    async with SessionLocal() as db:
        dev_user = await _developer(db, uid)
        rows = list(await db.scalars(select(Bot).where(Bot.owner_id == dev_user.id)
                                     .order_by(Bot.created_at, Bot.user_id)))
        if not rows:
            raise _Stop("你还没有机器人,发 /newbot 建一个。")
        buttons = []
        for b in rows:
            name, uname = await _label(db, b)
            buttons.append([_btn(f"{name} @{uname}" if uname else name, f"pick:{action}:{b.user_id}")])
    await _reply(me_id, uid, prompt, {"inline_keyboard": buttons})


async def cmd_mybots(me_id: int, uid: int) -> None:
    await _pick(me_id, uid, "info", "你的机器人,点一个看看:")


async def cmd_setcommands(me_id: int, uid: int) -> None:
    await _pick(me_id, uid, "cmds", "给哪个机器人改命令?")


async def cmd_setdescription(me_id: int, uid: int) -> None:
    await _pick(me_id, uid, "desc", "给哪个机器人改描述?")


async def cmd_setabout(me_id: int, uid: int) -> None:
    await _pick(me_id, uid, "about", "给哪个机器人改简介?")


async def cmd_setprivacy(me_id: int, uid: int) -> None:
    await _pick(me_id, uid, "priv", "改哪个机器人的隐私模式?")


async def cmd_token(me_id: int, uid: int) -> None:
    await _pick(me_id, uid, "token", "重置哪个机器人的 token?")


async def cmd_deletebot(me_id: int, uid: int) -> None:
    await _pick(me_id, uid, "del", "删除哪个机器人?")


_COMMANDS = {
    "start": cmd_help, "help": cmd_help, "cancel": cmd_cancel, "newbot": cmd_newbot,
    "mybots": cmd_mybots, "setcommands": cmd_setcommands, "setdescription": cmd_setdescription,
    "setabout": cmd_setabout, "setabouttext": cmd_setabout, "setprivacy": cmd_setprivacy,
    "token": cmd_token, "revoke": cmd_token, "deletebot": cmd_deletebot,
}


# ---------------------------------------------------------------------------- 多步操作

async def step_newbot_name(me_id: int, uid: int, st: dict, text: str) -> None:
    async with SessionLocal() as db:
        try:
            name = await bots.check_bot_name(db, text)
        except HTTPException as e:
            raise _Stop(f"{e.detail},再发一个名字。")
    await _set_state(uid, {"step": "newbot_username", "name": name})
    await _reply(me_id, uid, f"「{name}」,好。再起个用户名:5–32 位字母、数字、下划线,必须以 bot 结尾,"
                             "比如 diancan_bot。别人用 @用户名 找到它。")


async def step_newbot_username(me_id: int, uid: int, st: dict, text: str) -> None:
    async with SessionLocal() as db:
        dev_user = await _developer(db, uid, creating=True)
        try:
            bot, token = await bots.create_bot(db, dev_user, st.get("name", ""), text.strip().lstrip("@"))
            await db.commit()
        except HTTPException as e:
            await db.rollback()
            raise _Stop(f"{e.detail}。换一个用户名再发,或者 /cancel。")
        name, uname = await _label(db, bot)
        bot_id = bot.user_id
    await _clear_state(uid)
    nonce = await _stash_token(bot_id, uid, token)
    await _reply(me_id, uid,
                 f"建好了:「{name}」@{uname}\n\n"
                 "token 只给你看一次:点下面「查看 token」,复制后存到你服务端的配置里。"
                 f"平台只存 token 的指纹、不存原文,丢了只能发 /token 重置。按钮 {REVEAL_TTL // 60} 分钟内有效。\n\n"
                 "接下来可以:\n/setcommands 给它设命令(用户输入 / 时看到的列表)\n/setdescription 写一段介绍\n\n"
                 f"接口文档:{_base()}/developers",
                 _reveal_markup(nonce))


async def step_commands(me_id: int, uid: int, st: dict, text: str) -> None:
    try:
        raw = [] if text in CLEAR_WORDS else parse_commands_text(text)
    except ValueError as e:
        raise _Stop(f"{e}。改好了再发一次,或者 /cancel。")
    async with SessionLocal() as db:
        bot = await _own_bot(db, uid, int(st["bot"]))
        try:
            cmds = await bots.validate_commands(db, raw)
        except BotError as e:
            raise _Stop(f"{_bot_error_text(e)}。改好了再发一次,或者 /cancel。")
        bot.commands = cmds
        await db.commit()
        _, uname = await _label(db, bot)
    await _clear_state(uid)
    if not cmds:
        await _reply(me_id, uid, f"✓ @{uname} 的命令清空了。")
    else:
        await _reply(me_id, uid, f"✓ @{uname} 的命令更新了,{len(cmds)} 条。用户在和它的对话里输入 / 就能看到。")


async def _step_text_field(me_id: int, uid: int, st: dict, text: str, field: str, limit: int,
                           noun: str) -> None:
    from .moderation import find_banned

    value = "" if text in CLEAR_WORDS else text.strip()
    if len(value) > limit:
        raise _Stop(f"{noun}最多 {limit} 个字,这段有 {len(value)} 个。改短一点再发。")
    async with SessionLocal() as db:
        bot = await _own_bot(db, uid, int(st["bot"]))
        if value and await find_banned(db, value):
            raise _Stop(f"{noun}里有不允许发布的内容,换个说法再发。")
        setattr(bot, field, value)
        await db.commit()
        _, uname = await _label(db, bot)
    await _clear_state(uid)
    await _reply(me_id, uid, f"✓ @{uname} 的{noun}{'清空了' if not value else '更新了'}。")


async def step_description(me_id: int, uid: int, st: dict, text: str) -> None:
    await _step_text_field(me_id, uid, st, text, "description", DESCRIPTION_MAX, "描述")


async def step_about(me_id: int, uid: int, st: dict, text: str) -> None:
    await _step_text_field(me_id, uid, st, text, "about", ABOUT_MAX, "简介")


async def step_delete(me_id: int, uid: int, st: dict, text: str) -> None:
    await _clear_state(uid)
    async with SessionLocal() as db:
        bot = await _own_bot(db, uid, int(st["bot"]))
        name, uname = await _label(db, bot)
        if text.strip().lstrip("@").lower() != uname.lower():
            raise _Stop("没对上,没删。要删就再发一次 /deletebot。")
        await bots.delete_bot(db, bot)
        await db.commit()
    await _reply(me_id, uid, f"✓ 删掉了「{name}」@{uname}。它发过的消息对所有人都没了,token 失效,用户名放出来了。")


_STEPS = {
    "newbot_name": step_newbot_name, "newbot_username": step_newbot_username,
    "cmds": step_commands, "desc": step_description, "about": step_about, "del": step_delete,
}


# ---------------------------------------------------------------------------- 按钮

async def _on_callback(me_id: int, uid: int, q: dict) -> None:
    qid = str(q.get("id") or "")
    data = str(q.get("data") or "")
    seq = int((q.get("message") or {}).get("message_id") or 0)
    kind, _, rest = data.partition(":")
    try:
        if kind == "tok":
            await _reveal(me_id, uid, qid, seq, rest)
            return
        if kind == "pick":
            action, _, bid = rest.partition(":")
            await _answer(me_id, qid)
            await _picked(me_id, uid, action, int(bid))
            return
        if kind == "priv":
            bid, _, on = rest.partition(":")
            async with SessionLocal() as db:
                bot = await _own_bot(db, uid, int(bid))
                bot.privacy_mode = on == "1"
                await db.commit()
                _, uname = await _label(db, bot)
            await _answer(me_id, qid, f"@{uname} 的隐私模式{'开了' if on == '1' else '关了'}")
            await _set_markup(me_id, uid, seq, None)
            return
        if kind == "reset":
            async with SessionLocal() as db:
                bot = await _own_bot(db, uid, int(rest))
                token = await bots.reset_token(db, bot)
                await db.commit()
                _, uname = await _label(db, bot)
                bot_id = bot.user_id
            await _answer(me_id, qid)
            await _set_markup(me_id, uid, seq, None)
            nonce = await _stash_token(bot_id, uid, token)
            await _reply(me_id, uid, f"✓ @{uname} 的 token 重置了,旧的已经失效。点下面「查看 token」拿新的"
                                     f"({REVEAL_TTL // 60} 分钟内有效,只能看一次)。", _reveal_markup(nonce))
            return
        await _answer(me_id, qid, "这个按钮过期了")
    except _Stop as s:
        await _answer(me_id, qid)
        await _reply(me_id, uid, s.text, s.markup)


async def _reveal(me_id: int, uid: int, qid: str, seq: int, nonce: str) -> None:
    """「查看 token」:取一次就删。取过、过期了、不是给你的,都当它没有。"""
    r = get_redis()
    key = f"bot:mgr:tok:{nonce}"
    raw = await r.get(key)
    plain = decrypt(raw) if raw else ""     # 解不开(换了密钥)返回空串,当它没有
    info = json.loads(plain) if plain else None
    if not info or info.get("user") != uid or not await r.delete(key):
        await _answer(me_id, qid, "这个 token 已经看过或者过期了。要新的就发 /token 重置(旧的会失效)。", alert=True)
        await _set_markup(me_id, uid, seq, _kb([_link("在开发者后台打开", _dev_url())]))
        return
    # 弹窗里只放 token 本身:客户端「复制」按钮复制的就是弹窗里的字
    await _answer(me_id, qid, info["token"], alert=True)
    await _set_markup(me_id, uid, seq, _kb([_link("在开发者后台打开", _dev_url())]))


async def _picked(me_id: int, uid: int, action: str, bot_id: int) -> None:
    async with SessionLocal() as db:
        bot = await _own_bot(db, uid, bot_id, lock=False)
        name, uname = await _label(db, bot)
        cmds = list(bot.commands or [])
        about, desc, privacy, hook = bot.about or "", bot.description or "", bool(bot.privacy_mode), \
            bot.webhook_url or ""
    who = f"「{name}」@{uname}"
    if action == "info":
        lines = [who, f"简介:{about or '(没设)'}", f"命令:{len(cmds)} 条"]
        lines += [f"  /{c['command']} {c['description']}" for c in cmds[:8]]
        if len(cmds) > 8:
            lines.append(f"  ……还有 {len(cmds) - 8} 条")
        lines.append("隐私模式:" + ("开(群里只收 /命令、@它、回复它的)" if privacy else "关(群里的消息都收)"))
        lines.append("收消息:" + ("webhook" if hook else "getUpdates(没设 webhook)"))
        await _reply(me_id, uid, "\n".join(lines), _kb(
            [_btn("改命令", f"pick:cmds:{bot_id}"), _btn("改描述", f"pick:desc:{bot_id}")],
            [_btn("改简介", f"pick:about:{bot_id}"), _btn("隐私模式", f"pick:priv:{bot_id}")],
            [_btn("重置 token", f"pick:token:{bot_id}"), _btn("删除", f"pick:del:{bot_id}")]))
    elif action == "cmds":
        await _set_state(uid, {"step": "cmds", "bot": bot_id})
        now = "\n".join(f"{c['command']} - {c['description']}" for c in cmds) or "(还没有命令)"
        await _reply(me_id, uid, f"发来 {who} 的新命令列表,一行一条,「命令 - 说明」:\n\n"
                                 "start - 开始\nmenu - 看今天的菜\n\n"
                                 f"现在的是:\n{now}\n\n发「清空」去掉所有命令,/cancel 取消。")
    elif action == "desc":
        await _set_state(uid, {"step": "desc", "bot": bot_id})
        await _reply(me_id, uid, f"发来 {who} 的新描述:用户第一次打开和它的对话时,空白处显示的那段,"
                                 f"{DESCRIPTION_MAX} 字以内。\n现在的是:{desc or '(没设)'}\n\n发「清空」去掉,/cancel 取消。")
    elif action == "about":
        await _set_state(uid, {"step": "about", "bot": bot_id})
        await _reply(me_id, uid, f"发来 {who} 的新简介:资料卡上的一句话,{ABOUT_MAX} 字以内。\n"
                                 f"现在的是:{about or '(没设)'}\n\n发「清空」去掉,/cancel 取消。")
    elif action == "priv":
        await _reply(me_id, uid, f"{who} 的隐私模式现在是{'开' if privacy else '关'}的。\n"
                                 "开:群里只收 /命令、@它、回复它的消息;关:群里的消息全都收(群资料里对所有人可见)。",
                     _kb([_btn("开", f"priv:{bot_id}:1"), _btn("关", f"priv:{bot_id}:0")]))
    elif action == "token":
        await _reply(me_id, uid, f"重置 {who} 的 token?旧的会立刻失效,正在用它的服务马上就连不上了。",
                     _kb([_btn("确定重置", f"reset:{bot_id}")]))
    elif action == "del":
        await _set_state(uid, {"step": "del", "bot": bot_id})
        await _reply(me_id, uid, f"要删掉 {who} 吗?它发过的消息对所有人消失、token 立刻失效、用户名放出来,不能恢复。\n"
                                 f"确定的话,原样发它的用户名:@{uname}\n不删就 /cancel。")
