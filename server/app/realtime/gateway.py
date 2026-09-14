"""`/ws/v2`:实时网关入口(DEV-PROMPTS-40 §5.3,#343)。

**token 不放 URL。** 老的 `/ws/orders/{no}?token=` 把登录凭据写进了 nginx 访问日志;
这里连上之后 5 秒内第一帧必须是 `{"t":"auth","token":…}`,否则关闭(4401)。

客户端帧:ping / state / typing / view / call(通话信令,#354)。
别的模块要接新的客户端帧,往 [HANDLERS] 里注册,不用改这里的循环。
"""
import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..db import SessionLocal
from ..models import SocialProfile, User
from ..services.social import SOCIAL_ROLES
from .hub import Conn, hub

logger = logging.getLogger("superz.realtime")
router = APIRouter()

AUTH_TIMEOUT = 5
#: 60 秒收不到任何帧就断开(客户端 25 秒一次心跳)
IDLE_TIMEOUT = 60
#: 每个会话每个连接,正在输入最多 3 秒发一次
TYPING_EVERY = 3.0
TYPING_ACTIONS = {"typing", "record_voice", "upload_photo", "upload_video",
                  "upload_file", "choose_sticker", "cancel"}

#: 客户端帧类型 → 处理函数(conn, frame)。通话、机器人等模块自己注册
HANDLERS: dict[str, Callable[[Conn, dict], Awaitable[None]]] = {}
#: 一个人的最后一条连接断开时调用(user_id)。通话用它判断「对方掉线了」
DISCONNECT_HOOKS: list[Callable[[int], Awaitable[None]]] = []


async def user_from_token(token: str) -> User | None:
    """和 security.get_current_user 同一套判据,外加:助手令牌不许连、只许用户端账号。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("scope") == "agent":
        return None
    async with SessionLocal() as db:
        # 扫码登录的网页 / 电脑:那台设备在手机上被移除了就不许再连(和 get_current_user 同一个判据)
        if payload.get("ld") is not None:
            from ..security import login_device_alive
            if not await login_device_alive(db, payload):
                return None
        user = await db.get(User, int(payload.get("sub") or 0))
    if user is None or user.deleted_at is not None or user.phone.startswith("del"):
        return None
    if user.role not in SOCIAL_ROLES:
        return None
    return user


async def _user_pts(user_id: int) -> int:
    async with SessionLocal() as db:
        p = await db.get(SocialProfile, user_id)
        return p.user_pts if p else 0


@router.websocket("/ws/v2")
async def ws_v2(ws: WebSocket):
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT)
        msg = json.loads(first)
        if not isinstance(msg, dict) or msg.get("t") != "auth":
            raise ValueError
        user = await user_from_token(str(msg.get("token") or ""))
        if user is None:
            raise ValueError
    except Exception:
        try:
            await ws.close(code=4401)
        except Exception:
            pass
        return

    conn = Conn(ws, user.id, device=str(msg.get("device") or "")[:64],
                app=str(msg.get("app") or "")[:32])
    conn.foreground = bool(msg.get("foreground", True))
    writer = asyncio.create_task(conn.writer())
    await hub.register(conn)
    conn.send({"t": "ready", "user_pts": await _user_pts(user.id),
               "server_time": datetime.now(timezone.utc).isoformat()})
    try:
        while not conn.closed:
            text = await asyncio.wait_for(ws.receive_text(), timeout=IDLE_TIMEOUT)
            try:
                frame = json.loads(text)
            except ValueError:
                continue
            if isinstance(frame, dict):
                await _handle(conn, frame)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        logger.warning("ws/v2 连接异常断开", exc_info=True)
    finally:
        writer.cancel()
        await hub.unregister(conn)
        if not hub.is_connected(user.id):
            for hook in DISCONNECT_HOOKS:
                try:
                    await hook(user.id)
                except Exception:
                    logger.warning("断线回调失败", exc_info=True)
        try:
            await ws.close()
        except Exception:
            pass


async def _handle(conn: Conn, frame: dict) -> None:
    t = frame.get("t")
    if t == "ping":
        conn.send({"t": "pong"})
        if conn.foreground:
            await hub.refresh_online(conn.user_id)
    elif t == "state":
        conn.foreground = bool(frame.get("foreground"))
        if not conn.foreground:
            conn.viewing = None
        await hub.refresh_online(conn.user_id)
    elif t == "view":
        chat_id = frame.get("chat_id")
        conn.viewing = int(chat_id) if isinstance(chat_id, int) and \
            chat_id in hub.user_chats.get(conn.user_id, ()) else None
    elif t == "typing":
        await _typing(conn, frame)
    elif isinstance(t, str) and t in HANDLERS:
        await HANDLERS[t](conn, frame)


async def _typing(conn: Conn, frame: dict) -> None:
    chat_id = frame.get("chat_id")
    action = frame.get("action")
    if not isinstance(chat_id, int) or action not in TYPING_ACTIONS:
        return
    # 只有在这个会话里的人才能发「正在输入」;频道里订阅者不说话,不转发
    if chat_id not in hub.user_chats.get(conn.user_id, ()):
        return
    if hub.chat_types.get(chat_id) == "channel":
        return
    now = time.monotonic()
    if action != "cancel" and now - conn.last_typing.get(chat_id, 0) < TYPING_EVERY:
        return
    conn.last_typing[chat_id] = now
    await hub.send_chat_ephemeral(
        chat_id, {"t": "typing", "chat_id": chat_id, "user_id": conn.user_id,
                  "action": action}, exclude=conn.user_id)
