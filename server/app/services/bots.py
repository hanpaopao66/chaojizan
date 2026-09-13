"""机器人平台(DEV-PROMPTS-40 #355,§5.13):token、给机器人的更新、Telegram 形状的对象、
内联键盘、菜单按钮、限流、建 / 删机器人。接口在 routers/bot_api.py(Bot API)、routers/dev_bots.py
(开发者后台)、routers/chat_bots.py(客户端);webhook 投递在 services/bot_webhook.py。

## 形状对齐 Telegram Bot API

开发者手上的机器人框架(python-telegram-bot、aiogram、telegraf……)把 base url 换成
`https://chaojizan.cc/bot/` 就能用:方法名、参数名、Update / Message / User / Chat 的字段名都照 Telegram。
标识的对应关系:

- 用户 `id` = users.id;
- 私聊的 `chat.id` = 对面那个人的 id(和 Telegram 一样,私聊 id 就是人的 id);
- 群 / 频道的 `chat.id` = -(10¹² + chats.id),和 Telegram 超级群、频道的 `-100…` 一个样子,看正负就分得出私聊和群;
- `message_id` = 会话里的 seq(§5.1)。

## 机器人不能主动找人

私聊只能发给「和它说过话」的人(私聊存在、对方在里面发过消息);被拉黑 403;群里只能发到它是成员的群。
这条和 Telegram 一样,是防骚扰的地基 —— 不然建一个机器人就能按 id 挨个给全站发广告。

## 更新的编号

每个机器人一条 update_id 序列(bots.next_update_id)。**编号在事务提交的前一刻才分配**(见 [_allocate]):
按机器人 id 排好序锁行、分号、插行,然后提交。这样两件事同时成立 ——
提交顺序就是编号顺序(getUpdates 用 offset 确认时不会把一个晚提交的小编号当成「已确认」删掉,那样就丢了);
锁永远在事务最后按同一个顺序拿,两个事务不会各拿一个机器人的锁互相等(死锁)。

## token

`<机器人 user id>:<35 位随机>`,库里只存 sha256。日志、异常、后台只出现前 6 位:路径里的 token 在进应用的
第一层(main.BotTokenPathMiddleware)就换成 `前 6 位***`,之后谁打日志(包括 uvicorn 的访问日志)拿到的
都是打过码的路径。
"""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import socket
import string
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import and_, delete, event, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (ACTIVE_ROLES, Bot, BotUpdate, Chat, ChatMember, ChatMessage, Developer,
                      MiniApp, SocialProfile, User, UserRole, Username)
from .entities import FORMAT_TYPES, mentioned_user_ids, mentioned_usernames, utf16_offsets
from .flags import bots_on
from .rt_events import after_commit
from .social import blocked_between, display_name, ensure_profile, validate_username

logger = logging.getLogger("superz.bots")

BOTS_OFF = "机器人功能暂未开放"
#: 每个开发者最多几个机器人
MAX_BOTS_PER_DEVELOPER = 20
#: 更新最多留多久(没投成 / 没取走的,满 24 小时丢掉;和 Telegram 一样)
UPDATE_TTL = timedelta(hours=24)

# ---- 限流(§5.7,写进 docs/BOT-API.md)----
#: 每个机器人全局每秒最多发几条
SEND_PER_SECOND = 30
#: 同一会话:每秒补 1 条、桶里最多攒 3 条(允许突发 3)
CHAT_BURST = 3
CHAT_PER_SECOND = 1
#: 同一群每分钟最多几条
GROUP_PER_MINUTE = 20

CALLBACK_WAIT_SECONDS = 10
#: 回调查询在 Redis 里留多久(机器人 15 分钟内都能 answer,之后就是「查询太旧」)
CALLBACK_TTL = 900


class BotError(Exception):
    """Bot API 的错误:error_code 就是 HTTP 状态码,description 照 Telegram 的写法
    (「Bad Request: …」「Forbidden: …」),框架按这个前缀抛各自的异常类。"""

    def __init__(self, code: int, description: str, *, retry_after: int | None = None):
        super().__init__(description)
        self.code = code
        self.description = description
        self.retry_after = retry_after


def from_http(e: HTTPException) -> BotError:
    """聊天模块共用的代码抛的是 HTTPException(中文),换成 Bot API 的写法。"""
    code, detail = e.status_code, str(e.detail)
    if code in (404, 410, 413, 422):
        code = 400
    if detail.startswith(("Bad Request", "Forbidden", "Conflict", "Unauthorized",
                          "Too Many Requests", "Not Found")):
        return BotError(code, detail)
    prefix = {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 409: "Conflict",
              429: "Too Many Requests"}.get(code)
    return BotError(code, f"{prefix}: {detail}" if prefix else detail)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =====================================================================
# token
# =====================================================================

TOKEN_SECRET_LEN = 35
_TOKEN_ALPHABET = string.ascii_letters + string.digits + "_-"
TOKEN_RE = re.compile(r"^(\d{1,12}):([A-Za-z0-9_-]{35})$")
#: 一段文字里长得像 token 的部分(路径、异常文案、第三方库的日志……哪里都可能带出来)
_TOKEN_ANYWHERE = re.compile(r"(?<![0-9])\d{1,12}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")
#: ASGI scope 里放真 token 的键:路径里已经换成打码的样子(main.BotTokenPathMiddleware)
SCOPE_KEY = "superz.bot_token"


def new_token(bot_id: int) -> str:
    return f"{bot_id}:" + "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(TOKEN_SECRET_LEN))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_prefix(token: str) -> str:
    """认 token 用的前 6 位 —— 日志、后台里只出现这么多。"""
    return (token or "")[:6]


def mask_token(token: str) -> str:
    return f"{token_prefix(token)}***"


def mask_tokens(text: str) -> str:
    """把一段文字里所有像 token 的部分换成 `前 6 位***`。"""
    return _TOKEN_ANYWHERE.sub(lambda m: mask_token(m.group(0)), text or "")


def mask_path(path: str) -> tuple[str, str | None]:
    """`/bot/<token>/<method>` → (`/bot/<前 6 位>***/<method>`, token)。不是 Bot API 的路径原样返回。"""
    if not path.startswith("/bot/"):
        return path, None
    token, sep, rest = path[5:].partition("/")
    if not token:
        return path, None
    return f"/bot/{mask_token(token)}{sep}{rest}", token


async def authenticate(db: AsyncSession, token: str) -> Bot:
    """token → 机器人。格式不对、查不到、机器人删了一律 401(不区分,不给人试探)。"""
    m = TOKEN_RE.match(token or "")
    if m is None:
        raise BotError(401, "Unauthorized")
    bot = await db.scalar(select(Bot).where(Bot.token_hash == token_hash(token)))
    if bot is None or bot.user_id != int(m.group(1)):
        raise BotError(401, "Unauthorized")
    user = await db.get(User, bot.user_id)
    if user is None or user.deleted_at is not None or user.role != UserRole.bot:
        raise BotError(401, "Unauthorized")
    return bot


async def require_on(db: AsyncSession) -> None:
    if not await bots_on(db):
        raise BotError(503, BOTS_OFF)


# =====================================================================
# 标识:chat_id、file_id
# =====================================================================

#: 群 / 频道对外的 chat_id = -(GROUP_ID_BASE + chats.id)
GROUP_ID_BASE = 10 ** 12
_INT32 = 2 ** 31


def tg_group_id(chat_id: int) -> int:
    return -(GROUP_ID_BASE + chat_id)


def parse_chat_ref(value) -> tuple[str, int | str]:
    """chat_id 参数 → ("user", 用户 id) / ("chat", chats.id) / ("username", 小写用户名)。认不出 400。"""
    bad = BotError(400, "Bad Request: chat not found")
    if isinstance(value, bool) or value is None:
        raise bad
    if isinstance(value, str):
        v = value.strip()
        if v.startswith("@"):
            name = v[1:]
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", name):
                raise bad
            return "username", name.lower()
        if not re.fullmatch(r"-?\d{1,19}", v):
            raise bad
        value = int(v)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        raise bad
    if 0 < value < _INT32:
        return "user", value
    inner = -value - GROUP_ID_BASE
    if value < 0 and 0 < inner < _INT32:
        return "chat", inner
    raise bad


def _file_key() -> bytes:
    return hashlib.sha256(f"superz-bot-file:{settings.jwt_secret}".encode()).digest()


def file_id_for(media_id: int, bot_id: int) -> str:
    """给机器人看的 file_id:按机器人签名,**别的机器人拿去用不了**(防止拿着别人文件的 id 转发)。"""
    sig = hmac.new(_file_key(), f"{bot_id}:{media_id}".encode(), hashlib.sha256).hexdigest()[:24]
    return f"{media_id}-{sig}"


def file_unique_id(media_id: int) -> str:
    """同一个文件对所有机器人都一样的 id(Telegram 的 file_unique_id:只用来认「是不是同一个文件」)。"""
    return hmac.new(_file_key(), f"u:{media_id}".encode(), hashlib.sha256).hexdigest()[:16]


def parse_file_id(file_id: str, bot_id: int) -> int | None:
    m = re.fullmatch(r"(\d{1,12})-([0-9a-f]{24})", file_id or "")
    if m is None:
        return None
    media_id = int(m.group(1))
    return media_id if hmac.compare_digest(file_id_for(media_id, bot_id), file_id) else None


# =====================================================================
# Telegram 形状的对象
# =====================================================================

def tg_user(user: User, profile: SocialProfile | None) -> dict:
    d = {"id": user.id, "is_bot": user.role == UserRole.bot, "first_name": display_name(user)}
    if profile is not None and profile.username:
        d["username"] = profile.username
    return d


async def user_obj(db: AsyncSession, user_id: int | None) -> dict | None:
    if not user_id:
        return None
    u = await db.get(User, user_id)
    if u is None:
        return None
    return tg_user(u, await db.get(SocialProfile, user_id))


def _peer_of(chat: Chat, bot_id: int) -> int | None:
    if chat.type != "private" or not chat.pair_key or ":" not in chat.pair_key:
        return None
    a, b = (int(x) for x in chat.pair_key.split(":"))
    return b if a == bot_id else a


async def tg_chat(db: AsyncSession, chat: Chat, bot_id: int) -> dict:
    """机器人眼里的会话:私聊是对面那个人(id 就是他的 user id),群 / 频道是 -(10¹² + chats.id)。"""
    if chat.type == "private":
        peer = _peer_of(chat, bot_id) or 0
        u = await db.get(User, peer) if peer else None
        prof = await db.get(SocialProfile, peer) if peer else None
        d = {"id": peer, "type": "private", "first_name": display_name(u) if u else ""}
        if prof is not None and prof.username:
            d["username"] = prof.username
        return d
    d = {"id": tg_group_id(chat.id), "type": "channel" if chat.type == "channel" else "group",
         "title": chat.title}
    if chat.username:
        d["username"] = chat.username
    return d


#: 我们的实体类型 → Telegram 的(只有删除线名字不一样)
_TO_TG = {"strike": "strikethrough"}
_FROM_TG = {"strikethrough": "strike"}
#: `/命令` 或 `/命令@机器人用户名`,前面是开头或空白
_COMMAND_RE = re.compile(
    r"(?<!\S)/([A-Za-z0-9_]{1,32})(?:@([A-Za-z][A-Za-z0-9_]{3,31}))?(?![A-Za-z0-9_@/])")


def leading_command(text: str) -> tuple[str, str | None] | None:
    """消息以 `/命令` 或 `/命令@用户名` 开头时返回 (小写命令, 小写的 @用户名 或 None)。"""
    m = _COMMAND_RE.match(text or "")
    if m is None:
        return None
    return m.group(1).lower(), (m.group(2).lower() if m.group(2) else None)


def command_entities(text: str, taken: list[tuple[int, int]]) -> list[dict]:
    """文字里的 `/命令` 标成 bot_command 实体(Telegram 会标,框架的命令路由靠它)。代码块、链接里的不算。"""
    if not text or "/" not in text:
        return []
    offs = utf16_offsets(text)
    out = []
    for m in _COMMAND_RE.finditer(text):
        a, b = offs[m.start()], offs[m.end()]
        if any(a < te and b > ts for ts, te in taken):
            continue
        out.append({"type": "bot_command", "offset": a, "length": b - a})
    return out


async def tg_entities(db: AsyncSession, text: str, entities: list | None) -> list[dict]:
    out, taken = [], []
    for e in entities or []:
        t = e.get("type")
        d = {"type": _TO_TG.get(t, t), "offset": e["offset"], "length": e["length"]}
        if t == "text_link":
            d["url"] = e.get("url") or ""
        elif t == "pre" and e.get("language"):
            d["language"] = e["language"]
        elif t == "text_mention":
            uid = int(e.get("user_id") or 0)
            d["user"] = await user_obj(db, uid) or {"id": uid, "is_bot": False, "first_name": ""}
        out.append(d)
        if t in ("url", "text_link", "code", "pre", "mention"):
            taken.append((e["offset"], e["offset"] + e["length"]))
    out += command_entities(text, taken)
    out.sort(key=lambda x: (x["offset"], -x["length"]))
    return out


def entities_from_tg(raw) -> list[dict]:
    """机器人传来的 entities(Telegram 的写法)→ 我们的格式实体(之后照常走 validate_entities)。

    mention / hashtag / url / bot_command 这几种服务端自己会认,传了丢掉;
    我们没有的格式(blockquote、custom_emoji……)也丢掉、不报错 —— 字照发,只是少一层格式。
    """
    if raw in (None, "", []):
        return []
    if not isinstance(raw, list):
        raise BotError(400, "Bad Request: can't parse entities: 要是 JSON 数组")
    out = []
    for e in raw:
        if not isinstance(e, dict):
            raise BotError(400, "Bad Request: can't parse entities")
        t = _FROM_TG.get(e.get("type"), e.get("type"))
        if t not in FORMAT_TYPES:
            continue
        d = {"type": t, "offset": e.get("offset"), "length": e.get("length")}
        if t == "text_link":
            d["url"] = e.get("url")
        elif t == "text_mention":
            u = e.get("user")
            d["user_id"] = u.get("id") if isinstance(u, dict) else e.get("user_id")
        elif t == "pre" and e.get("language"):
            d["language"] = e.get("language")
        out.append(d)
    return out


def tg_media(kind: str, items: list | None, extra: dict, bot_id: int) -> dict:
    """消息里的附件 → Telegram 的 photo / document / video / voice / … 字段。"""
    if not items:
        return {}
    it = items[0]
    mid = int(it.get("id") or 0)
    base: dict = {"file_id": file_id_for(mid, bot_id), "file_unique_id": file_unique_id(mid)}
    if it.get("size"):
        base["file_size"] = it["size"]
    w, h = int(it.get("w") or 0), int(it.get("h") or 0)
    dur = int(round((it.get("duration_ms") or 0) / 1000))
    mime = it.get("mime") or ""
    if kind == "photo":
        return {"photo": [{**base, "width": w, "height": h}]}
    if kind == "video":
        return {"video": {**base, "width": w, "height": h, "duration": dur, "mime_type": mime}}
    if kind == "gif":
        return {"animation": {**base, "width": w, "height": h, "duration": dur, "mime_type": mime}}
    if kind == "voice":
        return {"voice": {**base, "duration": dur, "mime_type": mime}}
    if kind == "video_note":
        return {"video_note": {**base, "length": min(w, h) or w, "duration": dur}}
    if kind == "sticker":
        st = extra.get("sticker") or {}
        return {"sticker": {**base, "width": w, "height": h, "type": "regular", "is_animated": False,
                            "is_video": False, "emoji": st.get("emoji") or ""}}
    if kind == "file":
        return {"document": {**base, "file_name": it.get("name") or "", "mime_type": mime}}
    return {}


async def tg_message(db: AsyncSession, chat: Chat, msg: ChatMessage, *, bot_id: int,
                     with_reply: bool = True) -> dict:
    """一条消息在机器人眼里的样子(Telegram 的 Message)。"""
    out: dict = {"message_id": msg.seq}
    if msg.as_chat:
        out["sender_chat"] = await tg_chat(db, chat, bot_id)
    elif msg.sender_id:
        sender = await user_obj(db, msg.sender_id)
        if sender is not None:
            out["from"] = sender
    out["chat"] = await tg_chat(db, chat, bot_id)
    out["date"] = int((msg.created_at or utcnow()).timestamp())
    extra = msg.extra or {}
    text = msg.text or ""
    ents = await tg_entities(db, text, msg.entities) if text else []
    if msg.kind == "text":
        out["text"] = text
        if ents:
            out["entities"] = ents
    elif text:
        out["caption"] = text
        if ents:
            out["caption_entities"] = ents
    out.update(tg_media(msg.kind, msg.media, extra, bot_id))
    if msg.kind == "location" and extra.get("location"):
        loc = extra["location"]
        out["location"] = {"latitude": loc.get("lat"), "longitude": loc.get("lng")}
    elif msg.kind == "contact" and extra.get("contact"):
        c = extra["contact"]
        # 名片不带手机号(S2):Telegram 这个字段必填,给空串
        out["contact"] = {"phone_number": "", "first_name": c.get("name") or "",
                          "user_id": c.get("user_id")}
    elif msg.kind == "dice" and extra.get("dice"):
        out["dice"] = {"emoji": extra["dice"].get("emoji"), "value": extra["dice"].get("value")}
    if with_reply and msg.reply_to_seq:
        r = await db.scalar(select(ChatMessage).where(ChatMessage.chat_id == chat.id,
                                                      ChatMessage.seq == msg.reply_to_seq,
                                                      ChatMessage.deleted_at.is_(None)))
        if r is not None:
            out["reply_to_message"] = await tg_message(db, chat, r, bot_id=bot_id,
                                                       with_reply=False)
    if msg.edited_at:
        out["edit_date"] = int(msg.edited_at.timestamp())
    if msg.markup:
        out["reply_markup"] = msg.markup
    return out


async def me_obj(db: AsyncSession, bot: Bot) -> dict:
    """getMe。"""
    u = await db.get(User, bot.user_id)
    d = tg_user(u, await db.get(SocialProfile, bot.user_id))
    d.update({"can_join_groups": True, "can_read_all_group_messages": not bot.privacy_mode,
              "supports_inline_queries": False})
    return d


# =====================================================================
# 给机器人的更新:谁能收到什么
# =====================================================================

def should_deliver(*, chat_type: str, privacy_mode: bool, bot_id: int, bot_username: str | None,
                   text: str, mentioned_names: set[str], mentioned_ids: set[int],
                   reply_to_sender: int | None) -> bool:
    """这条消息该不该给这个机器人(纯函数,单测锁真值表)。

    - 私聊:对面发的都给;
    - 群、隐私模式关:全给;
    - 群、隐私模式开(缺省):`/命令`(没 @ 谁,群里每个机器人都收)、`/命令@我`、@我、回复我的消息;
      `/命令@别的机器人` 不给我;
    - 频道:不给(机器人在频道里只能发帖)。
    """
    if chat_type == "private":
        return True
    if chat_type != "group":
        return False
    if not privacy_mode:
        return True
    uname = (bot_username or "").lower()
    cmd = leading_command(text)
    if cmd is not None and (cmd[1] is None or (uname and cmd[1] == uname)):
        return True
    if uname and uname in mentioned_names:
        return True
    if bot_id in mentioned_ids:
        return True
    return reply_to_sender == bot_id


async def bots_in(db: AsyncSession, chat: Chat) -> list[tuple[int, bool, str | None]]:
    """会话里的机器人成员:[(user id, 隐私模式, 用户名)],按 id 排好。私聊只查两个人,不扫成员表。"""
    if chat.type == "private":
        if not chat.pair_key or ":" not in chat.pair_key:
            return []
        ids = [int(x) for x in chat.pair_key.split(":")]
        q = (select(Bot.user_id, Bot.privacy_mode, SocialProfile.username)
             .outerjoin(SocialProfile, SocialProfile.user_id == Bot.user_id)
             .where(Bot.user_id.in_(ids)))
    elif chat.type in ("group", "channel"):
        q = (select(Bot.user_id, Bot.privacy_mode, SocialProfile.username)
             .join(ChatMember, and_(ChatMember.user_id == Bot.user_id,
                                    ChatMember.chat_id == chat.id))
             .outerjoin(SocialProfile, SocialProfile.user_id == Bot.user_id)
             .where(ChatMember.role.in_(ACTIVE_ROLES)))
    else:
        return []
    rows = (await db.execute(q.order_by(Bot.user_id))).all()
    return [(int(r[0]), bool(r[1]), r[2]) for r in rows]


_PENDING = "bot_updates_pending"


def enqueue(db: AsyncSession, bot_id: int, kind: str, obj: dict) -> None:
    """登记一条给机器人的更新。编号和落库在提交前一刻统一做(见 [_allocate]),回滚就当没发生过。"""
    db.info.setdefault(_PENDING, []).append((bot_id, kind, obj))
    after_commit(db, lambda: _wake(bot_id))


@event.listens_for(Session, "before_commit")
def _allocate(session: Session) -> None:
    """提交前:按机器人 id 排序锁行、分 update_id、插 bot_updates。

    **锁永远在事务最后、按同一个顺序拿**:不同事务不会一个先锁 A 再等 B、另一个先锁 B 再等 A。
    行锁一直握到提交,所以同一个机器人的更新「编号小的一定先提交」—— getUpdates 拿 offset 确认时
    不会有一个编号更小、却还没提交的更新被当成「已确认」删掉。
    """
    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    now = utcnow()
    by_bot: dict[int, list[tuple[str, dict]]] = {}
    for bot_id, kind, obj in pending:
        by_bot.setdefault(bot_id, []).append((kind, obj))
    for bot_id in sorted(by_bot):
        items = by_bot[bot_id]
        last = session.execute(
            update(Bot).where(Bot.user_id == bot_id)
            .values(next_update_id=Bot.next_update_id + len(items))
            .returning(Bot.next_update_id)
            .execution_options(synchronize_session=False)).scalar()
        if last is None:        # 机器人在这期间被删了
            continue
        first = last - len(items)
        for i, (kind, obj) in enumerate(items):
            uid = first + i
            session.add(BotUpdate(bot_id=bot_id, update_id=uid,
                                  payload={"update_id": uid, kind: obj}, attempts=0,
                                  next_try_at=now, created_at=now))


@event.listens_for(Session, "after_rollback")
def _drop_pending(session: Session) -> None:
    session.info.pop(_PENDING, None)


def wake_key(bot_id: int) -> str:
    return f"bot:wake:{bot_id}"


async def _wake(bot_id: int) -> None:
    """提交之后:叫醒正在长轮询的 getUpdates,并让本进程的 webhook 循环马上看一眼。"""
    from ..redis_client import get_redis
    try:
        r = get_redis()
        async with r.pipeline(transaction=False) as p:
            p.rpush(wake_key(bot_id), "1")
            p.ltrim(wake_key(bot_id), -5, -1)
            p.expire(wake_key(bot_id), 60)
            await p.execute()
    except Exception:
        logger.warning("叫醒机器人 %s 的长轮询失败(它会在超时后自己再来取)", bot_id, exc_info=True)
    from .bot_webhook import poke
    poke()


async def _fan_out(db: AsyncSession, chat: Chat, msg: ChatMessage,
                   bots: list[tuple[int, bool, str | None]], kind: str) -> None:
    text = msg.text or ""
    ents = msg.entities or []
    names = mentioned_usernames(text, ents)
    ids = mentioned_user_ids(ents)
    reply_sender = None
    if msg.reply_to_seq:
        reply_sender = await db.scalar(select(ChatMessage.sender_id).where(
            ChatMessage.chat_id == chat.id, ChatMessage.seq == msg.reply_to_seq))
    for bot_id, privacy, uname in bots:
        if not should_deliver(chat_type=chat.type, privacy_mode=privacy, bot_id=bot_id,
                              bot_username=uname, text=text, mentioned_names=names,
                              mentioned_ids=ids, reply_to_sender=reply_sender):
            continue
        enqueue(db, bot_id, kind, await tg_message(db, chat, msg, bot_id=bot_id))


async def _deliverable(db: AsyncSession, chat: Chat, msg: ChatMessage):
    if msg.kind == "service" or chat.type not in ("private", "group"):
        return None
    bots = await bots_in(db, chat)
    if not bots:
        return None
    if msg.sender_id:
        sender = await db.get(User, msg.sender_id)
        # 机器人互相看不见(和 Telegram 一样),自己发的也不回给自己
        if sender is not None and sender.role == UserRole.bot:
            return None
    if not await bots_on(db):
        return None
    return bots


async def on_message(db: AsyncSession, chat: Chat, msg: ChatMessage) -> None:
    """chat_store.insert_message 的尾巴:新消息该给哪些机器人。和消息同一个事务,一起提交、一起回滚。"""
    bots = await _deliverable(db, chat, msg)
    if bots:
        await _fan_out(db, chat, msg, bots, "message")


async def on_edit(db: AsyncSession, chat: Chat, msg: ChatMessage) -> None:
    """chat_store.edit 的尾巴:改过的消息按同样的规则给 edited_message。"""
    bots = await _deliverable(db, chat, msg)
    if bots:
        await _fan_out(db, chat, msg, bots, "edited_message")


_STATUS = {"owner": "creator", "admin": "administrator", "member": "member",
           "restricted": "restricted", "left": "left", "banned": "kicked"}


def tg_member(role: str | None, user: dict, rights: dict | None = None) -> dict:
    status = _STATUS.get(role or "left", "left")
    d: dict = {"status": status, "user": user}
    if status == "administrator":
        r = rights or {}
        d.update({"can_be_edited": False, "can_manage_chat": True,
                  "can_change_info": bool(r.get("change_info")),
                  "can_delete_messages": bool(r.get("delete_messages")),
                  "can_restrict_members": bool(r.get("ban_users")),
                  "can_invite_users": bool(r.get("invite_users")),
                  "can_pin_messages": bool(r.get("pin_messages")),
                  "can_promote_members": bool(r.get("add_admins")),
                  "can_post_messages": bool(r.get("post_messages")),
                  "can_edit_messages": bool(r.get("edit_messages")),
                  "is_anonymous": bool(r.get("anonymous"))})
    return d


async def on_member_changed(db: AsyncSession, chat: Chat, user_id: int, old_role: str | None,
                            new_role: str, actor_id: int | None, rights: dict | None = None) -> None:
    """群 / 频道里机器人自己的成员身份变了(被拉进来、移出、封禁、任免管理员)→ my_chat_member。"""
    if chat.type not in ("group", "channel") or old_role == new_role:
        return
    if await db.scalar(select(Bot.user_id).where(Bot.user_id == user_id)) is None:
        return
    if not await bots_on(db):
        return
    me = await user_obj(db, user_id)
    if me is None:
        return
    enqueue(db, user_id, "my_chat_member", {
        "chat": await tg_chat(db, chat, user_id),
        "from": await user_obj(db, actor_id) or me,
        "date": int(utcnow().timestamp()),
        "old_chat_member": tg_member(old_role, me),
        "new_chat_member": tg_member(new_role, me, rights),
    })


def pair_key(a: int, b: int) -> str:
    x, y = sorted((a, b))
    return f"{x}:{y}"


async def on_block_changed(user_id: int, other_id: int, blocked: bool) -> None:
    """用户拉黑 / 解除拉黑机器人:私聊里给它一条 my_chat_member(kicked / member),和 Telegram 一样。"""
    from ..db import SessionLocal

    async with SessionLocal() as db:
        if await db.scalar(select(Bot.user_id).where(Bot.user_id == other_id)) is None:
            return
        if not await bots_on(db):
            return
        chat = await db.scalar(select(Chat).where(Chat.pair_key == pair_key(user_id, other_id),
                                                  Chat.deleted_at.is_(None)))
        me = await user_obj(db, other_id)
        if chat is None or me is None:
            return
        old, new = ("member", "banned") if blocked else ("banned", "member")
        enqueue(db, other_id, "my_chat_member", {
            "chat": await tg_chat(db, chat, other_id),
            "from": await user_obj(db, user_id),
            "date": int(utcnow().timestamp()),
            "old_chat_member": tg_member(old, me),
            "new_chat_member": tg_member(new, me),
        })
        await db.commit()


# =====================================================================
# 机器人往哪发:chat_id → 会话(机器人不能主动找人)
# =====================================================================

async def user_talked(db: AsyncSession, chat_id: int, user_id: int) -> bool:
    """这个人在这个私聊里发过消息没有(删掉的也算:话说过了)。"""
    return await db.scalar(select(ChatMessage.id).where(
        ChatMessage.chat_id == chat_id, ChatMessage.sender_id == user_id,
        ChatMessage.kind != "service").limit(1)) is not None


async def resolve_target(db: AsyncSession, bot_id: int, ref, *, need_talked: bool) -> Chat:
    """chat_id 参数 → 机器人能用的会话。

    私聊:会话得存在(用户打开过和它的私聊)、没被拉黑;need_talked 时还要对方在里面说过话 ——
    发消息、正在输入都要,改 / 删自己发过的消息不要。群 / 频道:机器人得是成员。
    """
    from .chat_view import is_active, member_of

    kind, v = parse_chat_ref(ref)
    if kind == "username":
        row = await db.get(Username, v)
        if row is None:
            raise BotError(400, "Bad Request: chat not found")
        if row.owner_type == "user":
            kind, v = "user", row.owner_id
        else:
            kind, v = "chat", row.owner_id
    if kind == "user":
        if v == bot_id:
            raise BotError(400, "Bad Request: chat not found")
        chat = await db.scalar(select(Chat).where(Chat.pair_key == pair_key(bot_id, int(v)),
                                                  Chat.deleted_at.is_(None)))
        # 不区分「没这个人」和「他没打开过和你的私聊」:都是你不能主动找他
        if chat is None:
            raise BotError(403, "Forbidden: bot can't initiate conversation with a user")
        user = await db.get(User, int(v))
        if user is None or user.deleted_at is not None:
            raise BotError(403, "Forbidden: user is deactivated")
        if await blocked_between(db, bot_id, int(v)):
            raise BotError(403, "Forbidden: bot was blocked by the user")
        if need_talked and not await user_talked(db, chat.id, int(v)):
            raise BotError(403, "Forbidden: bot can't initiate conversation with a user")
        return chat
    chat = await db.get(Chat, int(v))
    if chat is None or chat.deleted_at is not None or chat.type not in ("group", "channel"):
        raise BotError(400, "Bad Request: chat not found")
    m = await member_of(db, chat.id, bot_id)
    if not is_active(m):
        kind_word = "channel" if chat.type == "channel" else "group"
        raise BotError(403, f"Forbidden: bot is not a member of the {kind_word} chat")
    return chat


# =====================================================================
# 限流(§5.7):全局每秒 30、同一会话每秒 1(突发 3)、同一群每分钟 20
# =====================================================================

#: 三道一起判、全过才扣 —— 不能前一道扣了、后一道拦下,白白吃掉额度
_RATE_LUA = """
local now = tonumber(ARGV[1])
local glimit = tonumber(ARGV[2])
local cap = tonumber(ARGV[3])
local rate = tonumber(ARGV[4])
local grp = tonumber(ARGV[5])
local g = tonumber(redis.call('GET', KEYS[1]) or '0')
if g >= glimit then
  return {1, 1000 - (now % 1000)}
end
local b = redis.call('HMGET', KEYS[2], 'tokens', 'ts')
local tokens = tonumber(b[1])
local ts = tonumber(b[2])
if tokens == nil or ts == nil then
  tokens = cap
  ts = now
end
tokens = math.min(cap, tokens + math.max(0, now - ts) * rate)
if tokens < 1 then
  return {2, math.ceil((1 - tokens) / rate)}
end
if grp > 0 then
  local c = tonumber(redis.call('GET', KEYS[3]) or '0')
  if c >= grp then
    return {3, 60000 - (now % 60000)}
  end
end
redis.call('INCR', KEYS[1])
redis.call('PEXPIRE', KEYS[1], 2000)
redis.call('HSET', KEYS[2], 'tokens', tostring(tokens - 1), 'ts', tostring(now))
redis.call('PEXPIRE', KEYS[2], 60000)
if grp > 0 then
  redis.call('INCR', KEYS[3])
  redis.call('PEXPIRE', KEYS[3], 120000)
end
return {0, 0}
"""


async def check_send_rate(bot_id: int, chat: Chat) -> None:
    """发消息前判三道限流,超了 429 + retry_after(秒)。Redis 不可用时放行(和 ratelimit.py 一样)。"""
    if not settings.rate_limit_enabled:
        return
    from ..redis_client import get_redis

    now = int(time.time() * 1000)
    keys = [f"bot:rl:g:{bot_id}:{now // 1000}", f"bot:rl:c:{bot_id}:{chat.id}",
            f"bot:rl:m:{bot_id}:{chat.id}:{now // 60000}"]
    try:
        res = await get_redis().eval(_RATE_LUA, 3, *keys, now, SEND_PER_SECOND, CHAT_BURST,
                                     CHAT_PER_SECOND / 1000,
                                     GROUP_PER_MINUTE if chat.type == "group" else 0)
    except Exception:
        logger.warning("机器人限流检查失败,放行", exc_info=True)
        return
    code, wait_ms = int(res[0]), int(res[1])
    if code:
        wait = max(1, -(-wait_ms // 1000))
        raise BotError(429, f"Too Many Requests: retry after {wait}", retry_after=wait)


# =====================================================================
# 内联键盘(4.a):校验和规整
# =====================================================================

MAX_BUTTONS = 100
MAX_ROW_BUTTONS = 8
CALLBACK_DATA_MAX_BYTES = 64
BUTTON_TEXT_MAX = 64
BUTTON_URL_MAX = 1024
_BUTTON_KEYS = ("text", "callback_data", "url", "web_app")


def parse_markup(raw) -> tuple[dict | None, list[str], set[str]]:
    """reply_markup → (规整后的 {"inline_keyboard": [[…]]} 或 None, 按钮文字, 用到的小程序 appid)。纯函数。

    每个按钮恰好一个动作:callback_data(1–64 字节)/ url(http、https)/ web_app({"app_id"})。
    最多 100 个按钮、每行最多 8 个。回复键盘(keyboard / remove_keyboard / force_reply)不做,传了 400。
    """
    if raw is None or raw == "":
        return None, [], set()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise BotError(400, "Bad Request: can't parse reply keyboard markup JSON object")
    if not isinstance(raw, dict):
        raise BotError(400, "Bad Request: can't parse reply keyboard markup JSON object")
    if any(k in raw for k in ("keyboard", "remove_keyboard", "force_reply")):
        raise BotError(400, "Bad Request: 回复键盘(ReplyKeyboardMarkup / ReplyKeyboardRemove / "
                            "ForceReply)不支持,只支持 inline_keyboard")
    rows = raw.get("inline_keyboard")
    if not isinstance(rows, list):
        raise BotError(400, "Bad Request: reply_markup 要是 {\"inline_keyboard\": [[按钮, …], …]}")
    out_rows: list[list[dict]] = []
    texts: list[str] = []
    apps: set[str] = set()
    total = 0
    for row in rows:
        if not isinstance(row, list) or not row:
            raise BotError(400, "Bad Request: inline_keyboard 的每一行至少一个按钮")
        if len(row) > MAX_ROW_BUTTONS:
            raise BotError(400, f"Bad Request: 每行最多 {MAX_ROW_BUTTONS} 个按钮")
        out_row = []
        for b in row:
            total += 1
            if total > MAX_BUTTONS:
                raise BotError(400, f"Bad Request: 最多 {MAX_BUTTONS} 个按钮")
            if not isinstance(b, dict):
                raise BotError(400, "Bad Request: 按钮要是 JSON 对象")
            extra_keys = [k for k in b if k not in _BUTTON_KEYS]
            if extra_keys:
                raise BotError(400, f"Bad Request: 不支持的按钮类型 {extra_keys[0]}"
                                    "(只支持 callback_data / url / web_app)")
            text = b.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > BUTTON_TEXT_MAX:
                raise BotError(400, f"Bad Request: 按钮文字 1–{BUTTON_TEXT_MAX} 个字")
            actions = [k for k in ("callback_data", "url", "web_app") if b.get(k) not in (None, "")]
            if len(actions) != 1:
                raise BotError(400, "Bad Request: 每个按钮要有且只有一个动作"
                                    "(callback_data / url / web_app 三选一)")
            act = actions[0]
            btn: dict = {"text": text}
            if act == "callback_data":
                data = b["callback_data"]
                if not isinstance(data, str) or not 1 <= len(data.encode()) <= CALLBACK_DATA_MAX_BYTES:
                    raise BotError(400, "Bad Request: BUTTON_DATA_INVALID(callback_data 要 1–64 字节)")
                btn["callback_data"] = data
            elif act == "url":
                url = b["url"]
                p = urlparse(url) if isinstance(url, str) else None
                if p is None or p.scheme.lower() not in ("http", "https") or not p.netloc \
                        or len(url) > BUTTON_URL_MAX:
                    raise BotError(400, "Bad Request: BUTTON_URL_INVALID(url 只能是 http / https 链接)")
                btn["url"] = url
            else:
                wa = b["web_app"]
                app_id = wa.get("app_id") if isinstance(wa, dict) else None
                if not isinstance(app_id, str) or not re.fullmatch(r"[0-9A-Za-z]{2,24}", app_id):
                    raise BotError(400, "Bad Request: web_app 按钮要写 {\"app_id\": \"已上架的小程序 id\"}"
                                        "(不支持任意网址)")
                btn["web_app"] = {"app_id": app_id}
                apps.add(app_id)
            texts.append(text)
            out_row.append(btn)
        out_rows.append(out_row)
    if not out_rows:
        return None, [], set()
    return {"inline_keyboard": out_rows}, texts, apps


async def online_app_ids(db: AsyncSession, app_ids: set[str]) -> set[str]:
    if not app_ids:
        return set()
    return set(await db.scalars(select(MiniApp.appid).where(MiniApp.appid.in_(app_ids),
                                                            MiniApp.status == "online")))


async def validate_markup(db: AsyncSession, raw) -> dict | None:
    """parse_markup + 屏蔽词 + web_app 的小程序必须已上架。"""
    from .moderation import find_banned

    markup, texts, apps = parse_markup(raw)
    if markup is None:
        return None
    if await find_banned(db, "\n".join(texts)):
        raise BotError(400, "Bad Request: 按钮文字包含不允许发布的内容")
    missing = apps - await online_app_ids(db, apps)
    if missing:
        raise BotError(400, f"Bad Request: web_app 按钮的 app_id 必须是已上架的小程序:{sorted(missing)[0]}")
    return markup


def markup_has_callback(markup: dict | None, data: str) -> bool:
    for row in (markup or {}).get("inline_keyboard") or []:
        for b in row or []:
            if isinstance(b, dict) and b.get("callback_data") == data:
                return True
    return False


# =====================================================================
# 回调查询(4.b)
# =====================================================================

def _cbq_key(qid: str) -> str:
    return f"bot:cbq:{qid}"


def _cbq_answer_key(qid: str) -> str:
    return f"bot:cbq:ans:{qid}"


def chat_instance(bot_id: int, chat_id: int) -> str:
    """Telegram 的 chat_instance:同一个机器人、同一个会话永远一样,别的会话不一样。不暴露 chats.id。"""
    h = hmac.new(_file_key(), f"ci:{bot_id}:{chat_id}".encode(), hashlib.sha256).hexdigest()
    return str(int(h[:15], 16))


async def create_callback_query(db: AsyncSession, chat: Chat, me: User, member: ChatMember,
                                seq: int, data: str) -> tuple[str, int]:
    """用户点了机器人消息上的回调按钮 → 给那个机器人一条 callback_query。返回 (查询 id, 机器人 id)。

    调用方已判过:会话成员、限流、开关。这里判:消息在(没删、在我能看到的范围里)、是机器人发的、
    markup 里真有这个 callback_data —— 伪造的数据一律 400,机器人收不到。
    """
    from .chat_view import visible_floor

    msg = await db.scalar(select(ChatMessage).where(ChatMessage.chat_id == chat.id,
                                                    ChatMessage.seq == seq,
                                                    ChatMessage.deleted_at.is_(None)))
    if msg is None or seq <= visible_floor(chat, member):
        raise HTTPException(404, "消息不存在或已删除")
    bot_id = msg.sender_id if msg.sender_id and not msg.as_chat else None
    bot = await db.get(Bot, bot_id) if bot_id else None
    if bot is None:
        raise HTTPException(400, "这条消息不是机器人发的,没有可以点的按钮")
    if not markup_has_callback(msg.markup, data):
        raise HTTPException(400, "按钮数据对不上(按钮可能已经被机器人换掉了)")
    qid = str(secrets.randbits(62) | (1 << 62))
    enqueue(db, bot.user_id, "callback_query", {
        "id": qid,
        "from": tg_user(me, await db.get(SocialProfile, me.id)),
        "message": await tg_message(db, chat, msg, bot_id=bot.user_id),
        "chat_instance": chat_instance(bot.user_id, chat.id),
        "data": data,
    })
    return qid, bot.user_id


async def remember_query(qid: str, bot_id: int, user_id: int) -> None:
    """提交之前先记下「这个查询是谁的」:机器人收到更新时 answer 一定对得上。"""
    from ..redis_client import get_redis
    try:
        await get_redis().set(_cbq_key(qid), json.dumps({"bot": bot_id, "user": user_id}),
                              ex=CALLBACK_TTL)
    except Exception:
        logger.warning("回调查询记不进 Redis,机器人的回话等不到了", exc_info=True)


#: 一次 BLPOP 最多挂多久。redis-py 的连接缺省 socket_timeout 是 5 秒:一次挂满 10 秒会在第 5 秒
#: 被客户端当成超时掐断(实测:回调 5 秒就回了 answered=false)。所以长等待切成 ≤4 秒一段
BLPOP_SLICE = 4.0


async def blpop_until(key: str, timeout: float) -> str | None:
    """在 key 上等一个元素,最多 timeout 秒;等到了返回它,超时返回 None。Redis 出错抛异常。"""
    from ..redis_client import get_redis

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    r = get_redis()
    while True:
        left = deadline - loop.time()
        if left <= 0.05:
            return None
        got = await r.blpop([key], timeout=min(BLPOP_SLICE, left))
        if got:
            return got[1]


async def wait_answer(qid: str, timeout: float = CALLBACK_WAIT_SECONDS) -> dict | None:
    """最多等 timeout 秒机器人的 answerCallbackQuery(Redis BLPOP,不占数据库连接)。"""
    try:
        got = await blpop_until(_cbq_answer_key(qid), timeout)
    except Exception:
        logger.warning("等机器人回话时 Redis 出错", exc_info=True)
        return None
    if not got:
        return None
    try:
        return json.loads(got)
    except (TypeError, ValueError):
        return None


async def answer_callback(bot_id: int, qid: str, text: str, show_alert: bool,
                          url: str | None) -> None:
    """answerCallbackQuery:把回话交给正在等的那个请求。每个查询只能回一次。"""
    from ..redis_client import get_redis

    stale = BotError(400, "Bad Request: query is too old and response timeout expired "
                          "or query ID is invalid")
    try:
        r = get_redis()
        raw = await r.get(_cbq_key(qid))
        info = json.loads(raw) if raw else None
        if not info or info.get("bot") != bot_id:
            raise stale
        if not await r.delete(_cbq_key(qid)):
            raise stale     # 两个请求同时回同一个查询:晚到的那个当它已经回过了
        async with r.pipeline(transaction=False) as p:
            p.rpush(_cbq_answer_key(qid), json.dumps({"text": text, "show_alert": show_alert,
                                                      "url": url}, ensure_ascii=False))
            p.expire(_cbq_answer_key(qid), 60)
            await p.execute()
    except BotError:
        raise
    except Exception:
        logger.warning("answerCallbackQuery 写 Redis 失败", exc_info=True)
        raise stale


# =====================================================================
# webhook 地址、命令、菜单按钮(Bot API 和开发者后台共用一套校验)
# =====================================================================

#: 和 Telegram 一样只许这几个端口(非默认端口多半是内网服务)
WEBHOOK_PORTS = (443, 80, 88, 8443)
WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def _ip_ok(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    # 用 is_global 而不是只看 is_private:169.254.169.254(云厂商元数据)、100.64/10(运营商 NAT)
    # 都不在 is_private 里,而它们恰恰是最该拦的
    return addr.is_global and not addr.is_multicast


def dev_local_url(url: str) -> bool:
    """开发环境允许 http(s)://127.0.0.1 / localhost(e2e 在本机起一个服务收 webhook)。生产永远 False。"""
    if not settings.is_dev:
        return False
    p = urlparse(url)
    return p.scheme in ("http", "https") and (p.hostname or "").lower() in (
        "127.0.0.1", "localhost", "::1")


def check_webhook_url_shape(url: str) -> None:
    """不查 DNS 的那部分:https、端口、不带账号密码、长度。纯函数。"""
    bad = "Bad Request: bad webhook: "
    if not url or len(url) > 300:
        raise BotError(400, bad + "地址 1–300 个字符")
    if dev_local_url(url):
        return
    p = urlparse(url)
    if p.scheme != "https":
        raise BotError(400, bad + "HTTPS url must be provided for webhook")
    if not p.hostname:
        raise BotError(400, bad + "地址里缺少域名")
    if p.username or p.password:
        raise BotError(400, bad + "地址里不能带用户名和密码")
    try:
        port = p.port
    except ValueError:
        raise BotError(400, bad + "端口不对")
    if port not in (None, *WEBHOOK_PORTS):
        raise BotError(400, bad + "Webhook can be set up only on ports 80, 88, 443 or 8443")


async def check_webhook_url(url: str) -> None:
    """webhook 地址校验:形状 + **解析出 IP 再判**(拒绝内网 / 回环 / 链路本地)。

    设置时判一次,每次投递前再判一次:域名今天指向公网、明天改指 127.0.0.1 是最经典的绕法。
    """
    check_webhook_url_shape(url)
    if dev_local_url(url):
        return
    host = urlparse(url).hostname or ""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise BotError(400, "Bad Request: bad webhook: Failed to resolve host: "
                            "Name or service not known")
    for info in infos:
        ip = info[4][0]
        if not _ip_ok(ip):
            raise BotError(400, f"Bad Request: bad webhook: 地址解析到内网或回环地址({ip}),"
                                "出于安全不能投递")


def webhook_secret_plain(bot: Bot) -> str:
    from .crypto import decrypt
    return decrypt(bot.webhook_secret) if bot.webhook_secret else ""


async def set_webhook(db: AsyncSession, bot: Bot, url: str, secret: str | None,
                      drop_pending: bool) -> None:
    """设 webhook(调用方提交)。url 传空串 = 删掉。"""
    from .crypto import encrypt

    url = (url or "").strip()
    if not url:
        await delete_webhook(db, bot, drop_pending)
        return
    await check_webhook_url(url)
    if secret not in (None, "") and not WEBHOOK_SECRET_RE.fullmatch(str(secret)):
        raise BotError(400, "Bad Request: secret_token 只能是 1–256 位的 A-Z a-z 0-9 _ -")
    if bot.webhook_url != url:
        bot.webhook_error_at = None
        bot.webhook_error = ""
    bot.webhook_url = url
    bot.webhook_secret = encrypt(str(secret)) if secret else ""
    if drop_pending:
        await drop_pending_updates(db, bot.user_id)


async def delete_webhook(db: AsyncSession, bot: Bot, drop_pending: bool) -> None:
    bot.webhook_url = ""
    bot.webhook_secret = ""
    bot.webhook_error_at = None
    bot.webhook_error = ""
    if drop_pending:
        await drop_pending_updates(db, bot.user_id)


async def drop_pending_updates(db: AsyncSession, bot_id: int) -> None:
    await db.execute(delete(BotUpdate).where(BotUpdate.bot_id == bot_id,
                                             BotUpdate.delivered_at.is_(None)))


async def pending_count(db: AsyncSession, bot_id: int) -> int:
    return int(await db.scalar(select(func.count()).select_from(BotUpdate).where(
        BotUpdate.bot_id == bot_id, BotUpdate.delivered_at.is_(None),
        BotUpdate.created_at >= utcnow() - UPDATE_TTL)) or 0)


async def webhook_info(db: AsyncSession, bot: Bot) -> dict:
    """getWebhookInfo。没出过错时不带 last_error_*(和 Telegram 一样)。"""
    d = {"url": bot.webhook_url or "", "has_custom_certificate": False,
         "pending_update_count": await pending_count(db, bot.user_id)}
    if bot.webhook_url:
        d["max_connections"] = 1
    if bot.webhook_error_at is not None:
        d["last_error_date"] = int(bot.webhook_error_at.timestamp())
        d["last_error_message"] = bot.webhook_error or ""
    return d


COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")
MAX_COMMANDS = 100


async def validate_commands(db: AsyncSession, raw) -> list[dict]:
    """setMyCommands 的 commands:command 1–32 位 [a-z0-9_](前面的 / 可带可不带),description 1–256 字,
    最多 100 条,不许重复,说明过屏蔽词。"""
    from .moderation import find_banned

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise BotError(400, "Bad Request: can't parse commands JSON object")
    if not isinstance(raw, list):
        raise BotError(400, "Bad Request: commands 要是 JSON 数组")
    if len(raw) > MAX_COMMANDS:
        raise BotError(400, f"Bad Request: 最多 {MAX_COMMANDS} 条命令")
    out, seen = [], set()
    for c in raw:
        if not isinstance(c, dict):
            raise BotError(400, "Bad Request: 每条命令要是 {\"command\", \"description\"}")
        cmd = c.get("command")
        desc = c.get("description")
        cmd = cmd.strip().removeprefix("/") if isinstance(cmd, str) else ""
        if not COMMAND_RE.fullmatch(cmd):
            raise BotError(400, "Bad Request: BOT_COMMAND_INVALID(命令只能是 1–32 位小写字母、数字、下划线)")
        if not isinstance(desc, str) or not 1 <= len(desc.strip()) <= 256:
            raise BotError(400, "Bad Request: BOT_COMMAND_DESCRIPTION_INVALID(说明 1–256 个字)")
        if cmd in seen:
            raise BotError(400, f"Bad Request: 命令重复:/{cmd}")
        seen.add(cmd)
        out.append({"command": cmd, "description": desc.strip()})
    if out and await find_banned(db, "\n".join(c["description"] for c in out)):
        raise BotError(400, "Bad Request: 命令说明包含不允许发布的内容")
    return out


MENU_TEXT_MAX = 64


async def set_menu(db: AsyncSession, bot: Bot, raw) -> None:
    """菜单按钮:{"type":"commands"} / {"type":"default"}(= 没有)/
    {"type":"web_app","text":…,"web_app":{"app_id":…}}。web_app 只能是**机器人主人自己名下已上架**的小程序。"""
    from .moderation import find_banned

    if raw in (None, "", {}):
        raw = {"type": "default"}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise BotError(400, "Bad Request: can't parse menu_button JSON object")
    if not isinstance(raw, dict):
        raise BotError(400, "Bad Request: menu_button 要是 JSON 对象")
    t = raw.get("type")
    if t == "default":
        bot.menu_type, bot.menu_text, bot.menu_app_id = "", "", ""
        return
    if t == "commands":
        bot.menu_type, bot.menu_text, bot.menu_app_id = "commands", "", ""
        return
    if t != "web_app":
        raise BotError(400, "Bad Request: menu_button.type 只能是 commands / default / web_app")
    text = raw.get("text")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= MENU_TEXT_MAX:
        raise BotError(400, f"Bad Request: 菜单按钮文字 1–{MENU_TEXT_MAX} 个字")
    wa = raw.get("web_app")
    app_id = wa.get("app_id") if isinstance(wa, dict) else None
    if not isinstance(app_id, str) or not app_id:
        raise BotError(400, "Bad Request: web_app 菜单要写 {\"app_id\": \"已上架的小程序 id\"}"
                            "(不支持任意网址)")
    app = await db.scalar(select(MiniApp).where(MiniApp.appid == app_id))
    if app is None or app.status != "online":
        raise BotError(400, "Bad Request: web_app 的 app_id 必须是已上架的小程序")
    dev_id = await db.scalar(select(Developer.id).where(Developer.user_id == bot.owner_id))
    if dev_id is None or app.developer_id != dev_id:
        raise BotError(400, "Bad Request: 菜单按钮只能打开你自己名下已上架的小程序")
    if await find_banned(db, text):
        raise BotError(400, "Bad Request: 菜单按钮文字包含不允许发布的内容")
    bot.menu_type, bot.menu_text, bot.menu_app_id = "web_app", text.strip(), app.appid


def menu_obj(bot: Bot) -> dict:
    """getChatMenuButton:机器人自己设的是什么(不管小程序现在还在不在线)。"""
    if bot.menu_type == "commands":
        return {"type": "commands"}
    if bot.menu_type == "web_app":
        return {"type": "web_app", "text": bot.menu_text, "web_app": {"app_id": bot.menu_app_id}}
    return {"type": "default"}


async def menu_for_client(db: AsyncSession, bot: Bot) -> dict | None:
    """客户端输入栏左边的菜单按钮(4.c)。小程序下架了就不出按钮 —— 不给用户一个点了打不开的按钮。"""
    if bot.menu_type == "commands":
        return {"type": "commands"}
    if bot.menu_type == "web_app" and bot.menu_app_id:
        app = await db.scalar(select(MiniApp).where(MiniApp.appid == bot.menu_app_id))
        if app is None or app.status != "online":
            return None
        return {"type": "web_app", "text": bot.menu_text, "app_id": app.appid,
                "app": {"name": app.name, "icon": app.icon}}
    return None


async def bot_infos(db: AsyncSession, chat: Chat) -> list[dict]:
    """GET /chat/v1/chats/{id}/bot-info:私聊里是对面那个机器人,群 / 频道里是所有机器人成员。"""
    out = []
    for bot_id, _, _ in await bots_in(db, chat):
        bot = await db.get(Bot, bot_id)
        u = await db.get(User, bot_id)
        if bot is None or u is None or u.deleted_at is not None:
            continue
        prof = await db.get(SocialProfile, bot_id)
        out.append({
            "id": u.id,
            "name": display_name(u),
            "username": prof.username if prof else None,
            "avatar": u.avatar_url or "",
            "about": bot.about or "",
            "description": bot.description or "",
            "commands": [{"command": c.get("command", ""), "description": c.get("description", "")}
                         for c in (bot.commands or [])],
            "menu_button": await menu_for_client(db, bot),
            "privacy_mode": bool(bot.privacy_mode),
        })
    return out


# =====================================================================
# 开发者后台:建、改、重置 token、删
# =====================================================================

BOT_NAME_MAX = 32


async def check_bot_name(db: AsyncSession, name: str) -> str:
    from .moderation import find_banned

    name = (name or "").strip()
    if not 1 <= len(name) <= BOT_NAME_MAX:
        raise HTTPException(422, f"名字 1–{BOT_NAME_MAX} 个字")
    if await find_banned(db, name):
        raise HTTPException(422, "名字包含不允许使用的内容")
    return name


async def create_bot(db: AsyncSession, owner: User, name: str, username: str) -> tuple[Bot, str]:
    """建机器人:users 里一行 role=bot(没有手机号、没有能用的密码,登不了)+ bots 一行。返回 (机器人, token)。

    用户名和 @用户名 共用一个命名空间(usernames 表的主键兜并发),必须以 bot 结尾。调用方提交。
    """
    from ..security import hash_password
    from .moderation import find_banned

    name = await check_bot_name(db, name)
    uname = (username or "").strip().lstrip("@")
    problem = validate_username(uname, is_bot=True)
    if problem:
        raise HTTPException(422, problem)
    if await find_banned(db, uname):
        raise HTTPException(422, "这个用户名包含不允许使用的内容")
    n = await db.scalar(select(func.count()).select_from(Bot).where(Bot.owner_id == owner.id))
    if (n or 0) >= MAX_BOTS_PER_DEVELOPER:
        raise HTTPException(409, f"每个开发者最多 {MAX_BOTS_PER_DEVELOPER} 个机器人")
    if await db.get(Username, uname.lower()) is not None:
        raise HTTPException(409, "这个用户名已经被占用了")
    # 一个谁都不知道的密码:机器人只能用 token 说话,不能登录。bcrypt 要算两百多毫秒,放线程里别卡住事件循环
    pw = await asyncio.to_thread(hash_password, secrets.token_urlsafe(32))
    user = User(phone=f"bot{secrets.token_hex(7)}", role=UserRole.bot, name=name, password_hash=pw)
    db.add(user)
    await db.flush()
    res = await db.execute(insert(Username).values(
        username_lc=uname.lower(), owner_type="user", owner_id=user.id
    ).on_conflict_do_nothing(index_elements=["username_lc"]))
    if res.rowcount != 1:
        raise HTTPException(409, "这个用户名已经被占用了")
    prof = await ensure_profile(db, user.id)
    prof.username = uname
    token = new_token(user.id)
    bot = Bot(user_id=user.id, owner_id=owner.id, token_hash=token_hash(token),
              token_prefix=token_prefix(token), about="", description="", commands=[],
              webhook_url="", webhook_secret="", webhook_error="", menu_type="", menu_text="",
              menu_app_id="", privacy_mode=True, next_update_id=1)
    db.add(bot)
    await db.flush()
    logger.info("建了机器人 %s(@%s),主人 %s,token %s***", user.id, uname, owner.id,
                token_prefix(token))
    return bot, token


async def reset_token(db: AsyncSession, bot: Bot) -> str:
    """换一个新 token,旧的当场失效。新 token 只在这次响应里完整出现一次。调用方提交。"""
    token = new_token(bot.user_id)
    bot.token_hash = token_hash(token)
    bot.token_prefix = token_prefix(token)
    logger.info("机器人 %s 重置了 token,新的是 %s***", bot.user_id, token_prefix(token))
    return token


async def delete_bot(db: AsyncSession, bot: Bot) -> dict:
    """删机器人:**按注销账号同样的级联**(services/chat_purge.purge_user,S5)——
    它发的消息正文、媒体、按钮清空(seq 占位,在线的人当场看到消失)、它上传的文件删掉、退出所有群和频道、
    @用户名释放;然后删 bots 行和更新队列(token 当场失效),users 那行和注销一样留墓碑(外键,不硬删)。
    调用方提交。"""
    from ..security import hash_password
    from .chat_purge import purge_user

    bot_id = bot.user_id
    out = await purge_user(db, bot_id)
    await db.execute(delete(BotUpdate).where(BotUpdate.bot_id == bot_id))
    await db.delete(bot)
    user = await db.get(User, bot_id)
    if user is not None:
        user.deleted_at = utcnow()
        user.phone = f"del{bot_id}_{secrets.token_hex(3)}"
        user.name = "已删除的机器人"
        user.avatar_url = ""
        user.password_hash = await asyncio.to_thread(hash_password, secrets.token_hex(16))
    logger.info("删了机器人 %s:%s", bot_id, out)
    return out
