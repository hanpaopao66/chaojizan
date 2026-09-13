"""Bot API:`/bot/<token>/<method>`(DEV-PROMPTS-40 #355,§5.13;文档 docs/BOT-API.md)。

和 Telegram Bot API 一个样子:GET 和 POST 都收,参数可以放查询串、JSON、
application/x-www-form-urlencoded、multipart/form-data(传文件用它);复杂参数(reply_markup、entities、
commands、menu_button)在表单里传 JSON 字符串。响应 `{"ok":true,"result":…}` /
`{"ok":false,"error_code":…,"description":…}`,HTTP 状态码 = error_code;429 另带 `parameters.retry_after`。

**路由里拿到的 token 是打过码的**(`前 6 位***`,见 main.BotTokenPathMiddleware);真 token 在 scope 里。
这个文件里的日志一律只写前 6 位。数据库会话按需开、用完就关:getUpdates 长轮询最多挂 50 秒,
不能一直占着连接。
"""
import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select
from starlette.datastructures import UploadFile

from ..db import SessionLocal
from ..models import Bot, BotUpdate, MediaFile, SocialProfile, User
from ..services import bots
from ..services import chat_store as store
from ..services.bots import BotError

router = APIRouter(tags=["机器人 Bot API"])
logger = logging.getLogger("superz.bots")

GET_UPDATES_MAX_LIMIT = 100
GET_UPDATES_MAX_TIMEOUT = 50
CALLBACK_TEXT_MAX = 200
_INT_MAX = 2 ** 62

#: Telegram 的 chat action → 我们实时协议里的 typing action(§5.3)
CHAT_ACTIONS = {
    "typing": "typing", "find_location": "typing",
    "upload_photo": "upload_photo",
    "record_video": "upload_video", "upload_video": "upload_video",
    "record_video_note": "upload_video", "upload_video_note": "upload_video",
    "record_voice": "record_voice", "upload_voice": "record_voice",
    "upload_document": "upload_file",
    "choose_sticker": "choose_sticker",
}


class Params:
    """一次调用的参数:查询串 + 请求体合在一起(请求体优先),文件单放。"""

    def __init__(self, data: dict, files: dict[str, UploadFile]):
        self.data = data
        self.files = files

    def has(self, key: str) -> bool:
        return self.data.get(key) not in (None, "") or key in self.files

    def required(self, key: str):
        v = self.data.get(key)
        if v is None or v == "":
            raise BotError(400, f"Bad Request: {key} is empty")
        return v

    def str(self, key: str) -> str | None:
        v = self.data.get(key)
        if v is None:
            return None
        if isinstance(v, (dict, list)):
            raise BotError(400, f"Bad Request: {key} 要是字符串")
        return str(v)

    def int(self, key: str, *, required: bool = False, default: int | None = None) -> int | None:
        v = self.data.get(key)
        if v is None or v == "":
            if required:
                raise BotError(400, f"Bad Request: {key} is empty")
            return default
        if isinstance(v, bool):
            raise BotError(400, f"Bad Request: {key} 要是整数")
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if isinstance(v, str) and re.fullmatch(r"\s*-?\d{1,19}\s*", v):
            v = int(v)
        if not isinstance(v, int) or abs(v) >= _INT_MAX:
            raise BotError(400, f"Bad Request: {key} 要是整数")
        return v

    def bool(self, key: str, default: bool = False) -> bool:
        v = self.data.get(key)
        if v is None or v == "":
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v).strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
        raise BotError(400, f"Bad Request: {key} 要是 true / false")

    def json(self, key: str):
        """复杂参数:JSON 请求体里直接是对象;表单 / 查询串里是 JSON 字符串。"""
        v = self.data.get(key)
        if isinstance(v, str):
            if not v.strip():
                return None
            try:
                return json.loads(v)
            except ValueError:
                raise BotError(400, f"Bad Request: can't parse {key} JSON object")
        return v


async def read_params(request: Request) -> Params:
    data: dict = dict(request.query_params)
    files: dict[str, UploadFile] = {}
    if request.method != "POST":
        return Params(data, files)
    ctype = request.headers.get("content-type", "").lower()
    if ctype.startswith("multipart/form-data") or \
            ctype.startswith("application/x-www-form-urlencoded"):
        try:
            form = await request.form(max_files=4, max_fields=200)
        except Exception:
            raise BotError(400, "Bad Request: can't parse request body")
        for k, v in form.multi_items():
            if isinstance(v, UploadFile):
                files[k] = v
            else:
                data[k] = v
        return Params(data, files)
    body = await request.body()
    if body.strip():
        try:
            obj = json.loads(body)
        except ValueError:
            raise BotError(400, "Bad Request: can't parse JSON body")
        if not isinstance(obj, dict):
            raise BotError(400, "Bad Request: 请求体要是 JSON 对象")
        data.update(obj)
    return Params(data, files)


def _ok(result) -> JSONResponse:
    return JSONResponse({"ok": True, "result": result})


def _fail(e: BotError) -> JSONResponse:
    body: dict = {"ok": False, "error_code": e.code, "description": e.description}
    if e.retry_after:
        body["parameters"] = {"retry_after": e.retry_after}
    return JSONResponse(body, status_code=e.code)


Handler = Callable[[Bot, Params], Awaitable[object]]
METHODS: dict[str, Handler] = {}


def method(name: str):
    def deco(fn: Handler) -> Handler:
        METHODS[name.lower()] = fn
        return fn
    return deco


@router.api_route("/bot/{token}/{method_name}", methods=["GET", "POST"], include_in_schema=False)
async def bot_api(token: str, method_name: str, request: Request):
    real = request.scope.get(bots.SCOPE_KEY) or token
    try:
        async with SessionLocal() as db:
            await bots.require_on(db)           # 拉闸时一律 503,先于认 token
            bot = await bots.authenticate(db, real)
        fn = METHODS.get(method_name.lower())
        if fn is None:
            raise BotError(404, "Not Found")
        params = await read_params(request)
        return _ok(await fn(bot, params))
    except BotError as e:
        return _fail(e)
    except HTTPException as e:
        return _fail(bots.from_http(e))
    except Exception:
        # 只写前 6 位:异常栈里不会有 token(库里查的是它的哈希),路径在中间件里就打过码了
        logger.exception("Bot API 内部错误:token %s method %s",
                         bots.mask_token(real), method_name[:40])
        return _fail(BotError(500, "Internal Server Error"))


@router.api_route("/bot/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
async def bot_api_not_found(rest: str):
    return _fail(BotError(404, "Not Found"))


def _no_parse_mode(p: Params) -> None:
    if p.has("parse_mode"):
        raise BotError(400, "Bad Request: 暂不支持 parse_mode,格式请用 entities / caption_entities 传")


def _reply_to(p: Params) -> int | None:
    seq = p.int("reply_to_message_id")
    if seq is None:
        rp = p.json("reply_parameters")
        if isinstance(rp, dict) and rp.get("message_id") is not None:
            seq = Params({"message_id": rp["message_id"]}, {}).int("message_id")
    return seq


# ---------------------------------------------------------------- 自己

@method("getMe")
async def get_me(bot: Bot, p: Params):
    async with SessionLocal() as db:
        return await bots.me_obj(db, bot)


# ---------------------------------------------------------------- 取更新

@method("getUpdates")
async def get_updates(bot: Bot, p: Params):
    """长轮询:没有更新时挂着等(≤ 50 秒),有了立刻回。offset 之前的视为已确认,删掉。设了 webhook 时 409。"""
    from ..redis_client import get_redis

    offset = p.int("offset")
    limit = max(1, min(GET_UPDATES_MAX_LIMIT, p.int("limit", default=100)))
    timeout = max(0, min(GET_UPDATES_MAX_TIMEOUT, p.int("timeout", default=0)))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    confirmed = False
    while True:
        if timeout:
            # 先清掉旧的「叫醒」再查库:查库之后才提交的更新会再推一个叫醒,不会漏
            try:
                await get_redis().delete(bots.wake_key(bot.user_id))
            except Exception:
                pass
        async with SessionLocal() as db:
            b = await db.get(Bot, bot.user_id)
            if b is None:
                raise BotError(401, "Unauthorized")
            if b.webhook_url:
                raise BotError(409, "Conflict: can't use getUpdates method while webhook is "
                                    "active; use deleteWebhook to delete the webhook first")
            start = offset
            if offset is not None and offset < 0:   # 负数 = 从最新往回数(和 Telegram 一样)
                last = await db.scalar(select(func.max(BotUpdate.update_id)).where(
                    BotUpdate.bot_id == bot.user_id))
                start = (last or 0) + offset + 1
            if start is not None and not confirmed:
                await db.execute(delete(BotUpdate).where(BotUpdate.bot_id == bot.user_id,
                                                         BotUpdate.update_id < start))
                confirmed = True
            q = select(BotUpdate.payload).where(
                BotUpdate.bot_id == bot.user_id, BotUpdate.delivered_at.is_(None),
                BotUpdate.created_at >= bots.utcnow() - bots.UPDATE_TTL)
            if start is not None:
                q = q.where(BotUpdate.update_id >= start)
            rows = list(await db.scalars(q.order_by(BotUpdate.update_id).limit(limit)))
            await db.commit()
        remaining = deadline - loop.time()
        if rows or remaining <= 0.05:
            return rows
        try:
            await bots.blpop_until(bots.wake_key(bot.user_id), remaining)
        except Exception:
            await asyncio.sleep(min(1.0, remaining))


# ---------------------------------------------------------------- webhook

@method("setWebhook")
async def set_webhook(bot: Bot, p: Params):
    url = p.str("url") or ""
    async with SessionLocal() as db:
        b = await db.get(Bot, bot.user_id)
        await bots.set_webhook(db, b, url, p.str("secret_token"), p.bool("drop_pending_updates"))
        await db.commit()
    return True


@method("deleteWebhook")
async def delete_webhook(bot: Bot, p: Params):
    async with SessionLocal() as db:
        b = await db.get(Bot, bot.user_id)
        await bots.delete_webhook(db, b, p.bool("drop_pending_updates"))
        await db.commit()
    return True


@method("getWebhookInfo")
async def get_webhook_info(bot: Bot, p: Params):
    async with SessionLocal() as db:
        return await bots.webhook_info(db, await db.get(Bot, bot.user_id))


# ---------------------------------------------------------------- 发消息

class _Staged:
    """收下来、验过类型、还没入库的上传文件(落在临时目录)。"""

    def __init__(self, path, name: str, size: int):
        self.path, self.name, self.size = path, name, size

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)


async def _receive(up: UploadFile, kind: str) -> _Staged:
    """multipart 传上来的文件:落临时文件、查大小、按魔数认类型(不信文件名和 Content-Type)。"""
    from ..services import media as media_svc

    limit = media_svc.LIMITS["photo" if kind == "photo" else "file"]
    tmp = media_svc.TMP_DIR / f"bot-{uuid.uuid4().hex}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    staged = _Staged(tmp, (up.filename or "")[:200], 0)
    try:
        with open(tmp, "wb") as f:
            while chunk := await up.read(1024 * 1024):
                staged.size += len(chunk)
                if staged.size > limit:
                    raise BotError(400, f"Bad Request: file is too big(最大 {limit // 1024 // 1024}MB)")
                f.write(chunk)
        if staged.size == 0:
            raise BotError(400, "Bad Request: file must be non-empty")
        with open(tmp, "rb") as f:
            category, _, _ = media_svc.sniff(f.read(64))
        if kind == "photo" and category != "image":
            raise BotError(400, "Bad Request: sendPhoto 只收图片(jpg / png / webp / heic),"
                                "别的文件用 sendDocument")
    except BaseException:
        staged.discard()
        raise
    return staged


async def _ingest(db, bot_user: User, staged: _Staged, kind: str) -> list[dict]:
    """走聊天媒体同一条入库路径(私密桶、图片去 EXIF、每天 2GB 配额)。"""
    from ..services import media as media_svc

    await media_svc.check_quota(bot_user.id, staged.size)
    mf = await media_svc.ingest(db, bot_user, staged.path,
                                declared="photo" if kind == "photo" else "file",
                                name=staged.name, purpose="chat")
    return [store.media_json(mf)]


async def _stage_media(db, bot_user: User, p: Params, kind: str) -> list[dict] | _Staged:
    """发之前先把附件验一遍 —— **先于扣限流额度**,传错了不白吃额度:
    file_id → 直接给出消息里的媒体;上传的文件 → 收下验过,返回待入库的(入库在扣完额度之后)。"""
    field = "photo" if kind == "photo" else "document"
    up = p.files.get(field)
    if up is not None:
        return await _receive(up, kind)
    ref = (p.str(field) or "").strip()
    if not ref:
        raise BotError(400, f"Bad Request: there is no {field} in the request")
    if re.match(r"^[a-z][a-z0-9+.-]*://", ref, re.IGNORECASE):
        # 服务端去拉一个开发者给的地址 = SSRF(拿我们的网络位置打内网),不做
        raise BotError(400, "Bad Request: 不支持传 URL 让服务端去拉文件:请用 multipart/form-data 上传,"
                            "或者传你以前上传过的 file_id")
    media_id = bots.parse_file_id(ref, bot_user.id)
    mf = await db.get(MediaFile, media_id) if media_id else None
    if mf is None or mf.owner_id != bot_user.id:
        raise BotError(400, "Bad Request: wrong file identifier/HTTP URL specified")
    if mf.status != "ready":
        raise BotError(400, "Bad Request: 这个文件还在处理中,稍后再发")
    allowed = store.MEDIA_KIND_FOR["photo" if kind == "photo" else "file"]
    if mf.kind not in allowed:
        raise BotError(400, "Bad Request: wrong file identifier/HTTP URL specified"
                            "(这个 file_id 不是图片)" if kind == "photo" else
                       "Bad Request: wrong file identifier/HTTP URL specified")
    return [store.media_json(mf)]


async def _send(bot: Bot, p: Params, *, kind: str, text: str, entities: list[dict]) -> dict:
    _no_parse_mode(p)
    if kind == "text" and len(text) > store.TEXT_MAX:
        raise BotError(400, "Bad Request: message is too long")
    if kind != "text" and len(text) > store.CAPTION_MAX:
        raise BotError(400, "Bad Request: message caption is too long")
    ref = p.required("chat_id")
    markup_raw = p.json("reply_markup")
    reply_to = _reply_to(p)
    silent = p.bool("disable_notification")
    async with SessionLocal() as db:
        chat = await bots.resolve_target(db, bot.user_id, ref, need_talked=True)
        markup = await bots.validate_markup(db, markup_raw)
        bot_user = await db.get(User, bot.user_id)
        staged = await _stage_media(db, bot_user, p, kind) if kind != "text" else None
        try:
            # 限流在参数都验过之后、真正入库之前:传错了不扣额度,刷上传的也先被限流挡住
            await bots.check_send_rate(bot.user_id, chat)
            media = await _ingest(db, bot_user, staged, kind) if isinstance(staged, _Staged) \
                else staged
            msg = await store.send_as_bot(db, chat, bot_user, kind=kind, text=text,
                                          entities=entities, media=media, reply_to_seq=reply_to,
                                          markup=markup, silent=silent)
            out = await bots.tg_message(db, chat, msg, bot_id=bot.user_id)
            await db.commit()
        finally:
            if isinstance(staged, _Staged):
                staged.discard()
    return out


@method("sendMessage")
async def send_message(bot: Bot, p: Params):
    text = p.str("text")
    if text is None or not text.strip():
        raise BotError(400, "Bad Request: message text is empty")
    return await _send(bot, p, kind="text", text=text,
                       entities=bots.entities_from_tg(p.json("entities")))


@method("sendPhoto")
async def send_photo(bot: Bot, p: Params):
    return await _send(bot, p, kind="photo", text=p.str("caption") or "",
                       entities=bots.entities_from_tg(p.json("caption_entities")))


@method("sendDocument")
async def send_document(bot: Bot, p: Params):
    return await _send(bot, p, kind="file", text=p.str("caption") or "",
                       entities=bots.entities_from_tg(p.json("caption_entities")))


# ---------------------------------------------------------------- 改、删

def _no_inline(p: Params) -> None:
    if p.has("inline_message_id"):
        raise BotError(400, "Bad Request: 不支持 inline_message_id(没有内联模式)")


async def _edit(bot: Bot, p: Params, *, text: str | None, entities: list[dict] | None) -> dict:
    ref = p.required("chat_id")
    seq = p.int("message_id", required=True)
    markup_raw = p.json("reply_markup")
    async with SessionLocal() as db:
        chat = await bots.resolve_target(db, bot.user_id, ref, need_talked=False)
        markup = await bots.validate_markup(db, markup_raw)
        bot_user = await db.get(User, bot.user_id)
        msg = await store.edit_as_bot(db, chat, bot_user, seq, text=text, entities=entities,
                                      markup=markup)
        out = await bots.tg_message(db, chat, msg, bot_id=bot.user_id)
        await db.commit()
    return out


@method("editMessageText")
async def edit_message_text(bot: Bot, p: Params):
    _no_inline(p)
    _no_parse_mode(p)
    text = p.str("text")
    if text is None or not text.strip():
        raise BotError(400, "Bad Request: message text is empty")
    return await _edit(bot, p, text=text, entities=bots.entities_from_tg(p.json("entities")))


@method("editMessageReplyMarkup")
async def edit_message_reply_markup(bot: Bot, p: Params):
    _no_inline(p)
    return await _edit(bot, p, text=None, entities=None)


@method("deleteMessage")
async def delete_message(bot: Bot, p: Params):
    ref = p.required("chat_id")
    seq = p.int("message_id", required=True)
    async with SessionLocal() as db:
        chat = await bots.resolve_target(db, bot.user_id, ref, need_talked=False)
        await store.delete_as_bot(db, chat, await db.get(User, bot.user_id), seq)
        await db.commit()
    return True


# ---------------------------------------------------------------- 回调

@method("answerCallbackQuery")
async def answer_callback_query(bot: Bot, p: Params):
    from ..services.moderation import find_banned

    qid = str(p.required("callback_query_id"))
    text = p.str("text") or ""
    if len(text) > CALLBACK_TEXT_MAX:
        raise BotError(400, f"Bad Request: MESSAGE_TOO_LONG(text 最多 {CALLBACK_TEXT_MAX} 个字)")
    url = (p.str("url") or "").strip() or None
    if url is not None:
        u = urlparse(url)
        if u.scheme.lower() not in ("http", "https") or not u.netloc or len(url) > 1024:
            raise BotError(400, "Bad Request: URL_INVALID(url 只能是 http / https 链接)")
    if text:
        async with SessionLocal() as db:
            if await find_banned(db, text):
                raise BotError(400, "Bad Request: text 包含不允许发布的内容")
    await bots.answer_callback(bot.user_id, qid, text, p.bool("show_alert"), url)
    return True


# ---------------------------------------------------------------- 命令、菜单

def _default_scope_only(p: Params) -> None:
    scope = p.json("scope")
    if scope not in (None, {}) and not (isinstance(scope, dict) and scope.get("type") == "default"):
        raise BotError(400, "Bad Request: 只支持默认范围的命令(scope 不传或 {\"type\":\"default\"})")
    if p.str("language_code"):
        raise BotError(400, "Bad Request: 不支持按语言分别设置命令(language_code 不传)")


@method("setMyCommands")
async def set_my_commands(bot: Bot, p: Params):
    _default_scope_only(p)
    raw = p.json("commands")
    if raw is None:
        raise BotError(400, "Bad Request: commands is empty")
    async with SessionLocal() as db:
        b = await db.get(Bot, bot.user_id)
        b.commands = await bots.validate_commands(db, raw)
        await db.commit()
    return True


@method("getMyCommands")
async def get_my_commands(bot: Bot, p: Params):
    _default_scope_only(p)
    async with SessionLocal() as db:
        b = await db.get(Bot, bot.user_id)
        return list(b.commands or [])


@method("setChatMenuButton")
async def set_chat_menu_button(bot: Bot, p: Params):
    if p.has("chat_id"):
        raise BotError(400, "Bad Request: 只支持设置默认菜单按钮(不传 chat_id)")
    async with SessionLocal() as db:
        b = await db.get(Bot, bot.user_id)
        await bots.set_menu(db, b, p.json("menu_button"))
        await db.commit()
    return True


@method("getChatMenuButton")
async def get_chat_menu_button(bot: Bot, p: Params):
    async with SessionLocal() as db:
        return bots.menu_obj(await db.get(Bot, bot.user_id))


# ---------------------------------------------------------------- 会话

@method("getChat")
async def get_chat(bot: Bot, p: Params):
    ref = p.required("chat_id")
    async with SessionLocal() as db:
        chat = await bots.resolve_target(db, bot.user_id, ref, need_talked=False)
        out = await bots.tg_chat(db, chat, bot.user_id)
        # 新版框架把这两个当必填字段解析,给个缺省值省得它们报错
        out.update({"accent_color_id": 0, "max_reaction_count": 3})
        if chat.type == "private":
            prof = await db.get(SocialProfile, out["id"])
            if prof is not None and prof.bio:
                out["bio"] = prof.bio
        elif chat.about:
            out["description"] = chat.about
        return out


@method("sendChatAction")
async def send_chat_action(bot: Bot, p: Params):
    """正在输入这类状态:不落库,发一个 typing 实时帧,6 秒后客户端自己消失。每个会话 3 秒最多一次。"""
    from ..realtime.hub import hub
    from ..redis_client import get_redis

    action = CHAT_ACTIONS.get((p.str("action") or "").strip())
    if action is None:
        raise BotError(400, "Bad Request: wrong parameter action in request")
    ref = p.required("chat_id")
    async with SessionLocal() as db:
        chat = await bots.resolve_target(db, bot.user_id, ref, need_talked=True)
    if chat.type == "channel":
        return True             # 频道里没有「正在输入」
    try:
        fresh = await get_redis().set(f"bot:typing:{bot.user_id}:{chat.id}", "1", nx=True, ex=3)
    except Exception:
        fresh = True
    if fresh:
        await hub.send_chat_ephemeral(chat.id, {"t": "typing", "chat_id": chat.id,
                                                "user_id": bot.user_id, "action": action},
                                      exclude=bot.user_id)
    return True
