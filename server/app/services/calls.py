"""1 对 1 语音 / 视频通话的信令(DEV-PROMPTS-40 §5.12,#354,D4)。

媒体走 WebRTC 点对点(打不通时走 coturn 中继),服务端只转信令、记状态:

    主叫 invite(call_id, video, sdp) ──▶ 被叫所有设备 incoming
    被叫设备 ringing                  ──▶ 主叫 ringing
    被叫 accept(sdp)                  ──▶ 主叫 accept;被叫的其他设备 taken(别响了)
    被叫 decline                      ──▶ 主叫 declined
    任一方 ice(candidate)            ──▶ 对方
    任一方 hangup                     ──▶ 对方 hangup
    45 秒没人接                        ──▶ 双方 missed
    对方正在通话 / 拉黑                ──▶ 主叫 busy
    对方隐私不让我打                   ──▶ 主叫 error(reason=privacy)

帧都在 `/ws/v2` 上:`{"t":"call","a":<动作>,"call_id":…}`。一个人的所有设备都收得到,
客户端按 call_id 认自己手上的那一通,不认识的忽略。

每一通都在 calls 表留一行;结束时在两人的私聊里写一条 kind=call 的消息
(类型、结果、时长),会话列表和聊天记录里都看得到「未接来电」。
"""
import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timezone

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import Call, SocialProfile, User
from ..realtime.gateway import DISCONNECT_HOOKS, HANDLERS
from ..realtime.hub import Conn, hub
from .social import SOCIAL_ROLES, allowed, blocked_between, display_name

logger = logging.getLogger("superz.calls")

#: 响铃多久没人接算未接(§5.12)。生产 45 秒;放在配置里是为了 CI 调短(settings.call_ring_seconds)
RING_SECONDS = settings.call_ring_seconds
#: 一方掉线后等多久再判断「通话中断」(给网络切换、重连留时间)。生产 20 秒(settings.call_drop_grace_seconds)
DROP_GRACE_SECONDS = settings.call_drop_grace_seconds
#: 正在通话的人:call:busy:{user_id} = call_id
_BUSY_TTL = 4 * 3600
#: 信令里 sdp / candidate 的上限(正常 sdp 几 KB)
_MAX_BLOB = 20_000

#: 响铃超时的计时器(本进程发起的通话)
_timers: dict[str, asyncio.Task] = {}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- ICE 服务器(TURN 用 coturn 的 REST 共享密钥方案)----------------

def ice_servers(user_id: int) -> dict:
    """临时的 TURN 用户名密码:用户名 = 「到期时间:用户」,密码 = HMAC-SHA1(共享密钥, 用户名)。
    coturn 配 `use-auth-secret` + `static-auth-secret` 就认。有效 1 小时,泄露了也只能用 1 小时。"""
    ttl = 3600
    servers = []
    stun = [u.strip() for u in (settings.stun_urls or "").split(",") if u.strip()]
    if stun:
        servers.append({"urls": stun})
    turn = [u.strip() for u in (settings.turn_urls or "").split(",") if u.strip()]
    if turn and settings.turn_secret:
        username = f"{int(time.time()) + ttl}:{user_id}"
        cred = base64.b64encode(hmac.new(settings.turn_secret.encode(), username.encode(),
                                         hashlib.sha1).digest()).decode()
        servers.append({"urls": turn, "username": username, "credential": cred})
    return {"ice_servers": servers, "ttl": ttl}


# ---------------- 状态 ----------------

async def _redis():
    from ..redis_client import get_redis
    return get_redis()


async def _busy_with(user_id: int) -> str | None:
    try:
        v = await (await _redis()).get(f"call:busy:{user_id}")
        return v.decode() if isinstance(v, bytes) else v
    except Exception:
        return None


async def _set_busy(user_id: int, call_id: str) -> None:
    try:
        await (await _redis()).set(f"call:busy:{user_id}", call_id, ex=_BUSY_TTL)
    except Exception:
        pass


async def _clear_busy(user_id: int, call_id: str) -> None:
    try:
        r = await _redis()
        v = await r.get(f"call:busy:{user_id}")
        v = v.decode() if isinstance(v, bytes) else v
        if v == call_id:
            await r.delete(f"call:busy:{user_id}")
    except Exception:
        pass


async def _send(user_id: int, frame: dict) -> None:
    await hub.send_user(user_id, {"t": "call", **frame})


def _peer(call: Call, me: int) -> int:
    return call.callee_id if call.caller_id == me else call.caller_id


# ---------------- 结束:写记录 + 聊天里一条 kind=call ----------------

async def _finish(call_id: str, state: str, reason: str = "", *,
                  notify: list[tuple[int, dict]] | tuple = ()) -> None:
    """把一通电话结束掉(幂等:已经结束的不再动)。"""
    t = _timers.pop(call_id, None)
    if t is not None and t is not asyncio.current_task():
        t.cancel()
    async with SessionLocal() as db:
        call = await db.scalar(select(Call).where(Call.call_id == call_id).with_for_update()
                               .execution_options(populate_existing=True))
        if call is None or call.state not in ("ringing", "active"):
            return
        answered = call.answered_at is not None
        call.state = state
        call.reason = reason[:24]
        call.ended_at = now_utc()
        duration = int((call.ended_at - call.answered_at).total_seconds()) if answered else 0
        caller = await db.get(User, call.caller_id)
        await _write_call_message(db, call, caller, state, duration)
        await db.commit()
        caller_id, callee_id = call.caller_id, call.callee_id
    await _clear_busy(caller_id, call_id)
    await _clear_busy(callee_id, call_id)
    for uid, frame in notify:
        await _send(uid, frame)


async def _write_call_message(db, call: Call, caller: User | None, state: str, duration: int) -> None:
    from . import chat_store
    if caller is None:
        return
    try:
        chat, _ = await chat_store.private_chat(db, caller, call.callee_id)
        chat = await chat_store.lock_chat(db, chat.id)
        call.chat_id = chat.id
        await chat_store.insert_message(
            db, chat, sender_id=call.caller_id, kind="call",
            extra={"call": {"call_id": call.call_id, "video": call.video, "state": state,
                            "duration": duration}},
            # 未接来电要提醒,其他结果(打通了、主叫取消)静音
            silent=state != "missed")
        if state == "missed":
            from .chat_push import notify_message
            seq = chat.last_seq
            chat_id = chat.id
            from .rt_events import after_commit
            after_commit(db, lambda: notify_message(chat_id, seq))
    except Exception:
        # 聊天记录写不进去不能影响通话本身结束
        logger.warning("通话记录消息没写进去 call=%s", call.call_id, exc_info=True)


async def _ring_timeout(call_id: str, caller_id: int, callee_id: int) -> None:
    try:
        await asyncio.sleep(RING_SECONDS)
    except asyncio.CancelledError:
        return
    await _finish(call_id, "missed", "timeout",
                  notify=[(caller_id, {"a": "missed", "call_id": call_id}),
                          (callee_id, {"a": "missed", "call_id": call_id})])


# ---------------- 信令 ----------------

async def handle(conn: Conn, frame: dict) -> None:
    a = frame.get("a")
    call_id = str(frame.get("call_id") or "")[:24]
    if not call_id or not call_id.replace("-", "").isalnum():
        return
    try:
        if a == "invite":
            await _invite(conn, call_id, frame)
        elif a in ("ringing", "accept", "decline", "hangup", "ice", "media"):
            await _relay(conn, call_id, a, frame)
    except Exception:
        logger.warning("通话信令处理失败 a=%s call=%s", a, call_id, exc_info=True)


async def _invite(conn: Conn, call_id: str, frame: dict) -> None:
    me = conn.user_id
    to = frame.get("to")
    sdp = frame.get("sdp")
    if not isinstance(to, int) or to == me or not isinstance(sdp, str) or len(sdp) > _MAX_BLOB:
        conn.send({"t": "call", "a": "error", "call_id": call_id, "reason": "bad_request",
                   "message": "呼叫参数不对"})
        return
    video = bool(frame.get("video"))
    async with SessionLocal() as db:
        from .flags import social_flag_on
        if not await social_flag_on(db, "calls_enabled"):
            conn.send({"t": "call", "a": "error", "call_id": call_id, "reason": "disabled",
                       "message": "通话功能暂未开放"})
            return
        callee = await db.get(User, to)
        if callee is None or callee.role not in SOCIAL_ROLES or callee.deleted_at is not None:
            conn.send({"t": "call", "a": "error", "call_id": call_id, "reason": "not_found",
                       "message": "没有这个用户"})
            return
        if await db.scalar(select(Call.id).where(Call.call_id == call_id)):
            return   # 同一个 call_id 重发:当作重复,不处理
        # 封号期间不能发起通话(#368)。信令走 WebSocket,没有 HTTP 403,把同一份说明放进错误帧
        from fastapi import HTTPException

        from .sanctions import check_user
        try:
            await check_user(db, me, "call")
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
            conn.send({"t": "call", "a": "error", "call_id": call_id, "reason": "sanctioned",
                       "message": detail.get("message", ""), "sanction": detail})
            return
        blocked = await blocked_between(db, me, to)
        prof = await db.get(SocialProfile, to)
        privacy_ok = blocked or await allowed(db, prof, to, me, "calls")
        caller = await db.get(User, me)
        busy = blocked or await _busy_with(to) is not None or await _busy_with(me) is not None
        state = "busy" if busy else ("failed" if not privacy_ok else "ringing")
        call = Call(call_id=call_id, caller_id=me, callee_id=to, video=video, state=state,
                    started_at=now_utc(), reason="privacy" if state == "failed" else "")
        db.add(call)
        if state == "busy":
            # 对方忙线也留一条记录(和 Telegram 一样,聊天里看得到「对方忙线」)
            await _write_call_message(db, call, caller, "busy", 0)
        await db.commit()
        caller_card = {"id": me, "name": display_name(caller) if caller else ""}
        if caller is not None and caller.avatar_url:
            caller_card["avatar"] = caller.avatar_url
    if state == "busy":
        conn.send({"t": "call", "a": "busy", "call_id": call_id})
        return
    if state == "failed":
        conn.send({"t": "call", "a": "error", "call_id": call_id, "reason": "privacy",
                   "message": "对方的隐私设置不接受你的来电"})
        return
    await _set_busy(me, call_id)
    await _set_busy(to, call_id)
    await _send(to, {"a": "incoming", "call_id": call_id, "from": caller_card, "video": video,
                     "sdp": sdp})
    _timers[call_id] = asyncio.get_running_loop().create_task(_ring_timeout(call_id, me, to))
    # 被叫不在前台:推一条(App 在后台 / 没开也知道有人打电话)
    if not hub.is_foreground(to):
        from . import push
        name = caller_card["name"] or "有人"
        asyncio.get_running_loop().create_task(push.push_to_user(
            to, name, f"邀请你{'视频' if video else '语音'}通话",
            {"type": "call", "call_id": call_id}, record_skip=True))


async def _relay(conn: Conn, call_id: str, a: str, frame: dict) -> None:
    me = conn.user_id
    async with SessionLocal() as db:
        call = await db.scalar(select(Call).where(Call.call_id == call_id))
        if call is None or me not in (call.caller_id, call.callee_id):
            return
        state = call.state
        peer = _peer(call, me)
        is_callee = me == call.callee_id
        if a == "accept":
            if not is_callee or state != "ringing":
                conn.send({"t": "call", "a": "gone", "call_id": call_id})
                return
            sdp = frame.get("sdp")
            if not isinstance(sdp, str) or len(sdp) > _MAX_BLOB:
                return
            call.state = "active"
            call.answered_at = now_utc()
            await db.commit()
    if a == "ringing":
        if is_callee and state == "ringing":
            await _send(peer, {"a": "ringing", "call_id": call_id})
    elif a == "accept":
        t = _timers.pop(call_id, None)
        if t is not None:
            t.cancel()
        await _send(peer, {"a": "accept", "call_id": call_id, "sdp": frame.get("sdp")})
        # 被叫的其他设备别再响了(接的那台自己知道是自己接的,会忽略这一帧)
        await _send(me, {"a": "taken", "call_id": call_id, "device": conn.device})
    elif a == "media":
        # 开关摄像头 / 静音:告诉对方,好在他那边显示「对方关了摄像头」
        if state == "active":
            await _send(peer, {"a": "media", "call_id": call_id,
                               "video": bool(frame.get("video")), "muted": bool(frame.get("muted"))})
    elif a == "ice":
        cand = frame.get("candidate")
        if state in ("ringing", "active") and isinstance(cand, dict) and len(str(cand)) <= _MAX_BLOB:
            await _send(peer, {"a": "ice", "call_id": call_id, "candidate": cand})
    elif a == "decline":
        if is_callee and state == "ringing":
            await _finish(call_id, "declined", "declined",
                          notify=[(peer, {"a": "declined", "call_id": call_id}),
                                  (me, {"a": "taken", "call_id": call_id, "device": conn.device})])
    elif a == "hangup":
        if state == "ringing":
            # 还没接就挂:主叫挂是取消,被叫挂等于拒接
            final = "canceled" if not is_callee else "declined"
        elif state == "active":
            final = "ended"
        else:
            return
        await _finish(call_id, final, "hangup",
                      notify=[(peer, {"a": "hangup", "call_id": call_id}),
                              (me, {"a": "taken", "call_id": call_id, "device": conn.device})])


async def on_disconnect(user_id: int) -> None:
    """这个人最后一条连接断了:他要是正在通话,给一点重连时间,还没回来就判通话中断。"""
    call_id = await _busy_with(user_id)
    if not call_id:
        return

    async def later():
        await asyncio.sleep(DROP_GRACE_SECONDS)
        if hub.is_connected(user_id):
            return
        async with SessionLocal() as db:
            call = await db.scalar(select(Call).where(Call.call_id == call_id))
            if call is None or call.state not in ("ringing", "active"):
                return
            peer = _peer(call, user_id)
            final = "ended" if call.state == "active" else (
                "canceled" if call.caller_id == user_id else "missed")
        await _finish(call_id, final, "dropped", notify=[(peer, {"a": "hangup", "call_id": call_id})])

    asyncio.get_running_loop().create_task(later())


def new_call_id() -> str:
    return secrets.token_hex(8)


HANDLERS["call"] = handle
DISCONNECT_HOOKS.append(on_disconnect)
