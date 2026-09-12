"""实时网关的连接表与分发(DEV-PROMPTS-40 §5.3,#343)。

两张表:

- `conns`:用户 → 他此刻连着的所有设备;
- `chat_online`:会话 → 此刻在线的成员。用户连上来时从库里读一次他在哪些会话里,
  之后靠事件(进群 / 退群 / 被移出)增量维护。

发一个会话事件 = 取这个会话的在线成员,逐个塞进他们各个连接的发送队列。
**不按全部成员查库** —— 频道十万订阅者、在线三百人,就只碰三百个连接。

每个连接有自己的发送队列和写协程:某台手机网络卡住,只堵它自己,
不会拖住给别人的分发(队列满了直接断开这台,让它重连后走断线补齐)。
"""
import asyncio
import json
import logging
import os
import secrets
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, update

logger = logging.getLogger("superz.realtime")

#: 本进程的标识:Redis 上转一圈回来的帧,是自己发出去的就不再分发一遍
PROCESS_ID = f"{os.getpid()}-{secrets.token_hex(4)}"
#: 在线键的 TTL。客户端 25 秒一次心跳,每次心跳续一次
ONLINE_TTL = 90
#: 单个连接的发送队列上限。满了说明这台设备收不动了,断开让它重连补齐
QUEUE_MAX = 2000


class Conn:
    """一条 WebSocket 连接。"""

    def __init__(self, ws, user_id: int, device: str = "", app: str = ""):
        self.ws = ws
        self.user_id = user_id
        self.device = device
        self.app = app
        self.foreground = True
        self.viewing: int | None = None
        self.last_typing: dict[int, float] = {}
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        self.closed = False

    def send(self, frame: dict) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            logger.warning("用户 %s 的连接发送队列满了,断开让它重连", self.user_id)
            self.closed = True
            asyncio.get_running_loop().create_task(self._close(4409))

    async def _close(self, code: int) -> None:
        try:
            await self.ws.close(code=code)
        except Exception:
            pass

    async def writer(self) -> None:
        """把队列里的帧写到 socket。一个连接一个写协程。"""
        while True:
            frame = await self.queue.get()
            try:
                await self.ws.send_text(json.dumps(frame, ensure_ascii=False, default=str))
            except Exception:
                self.closed = True
                return


class Hub:
    def __init__(self) -> None:
        self.conns: dict[int, set[Conn]] = defaultdict(set)
        self.chat_online: dict[int, set[int]] = defaultdict(set)
        self.user_chats: dict[int, set[int]] = {}
        self.chat_types: dict[int, str] = {}

    # ---------------- 连接 ----------------

    async def register(self, conn: Conn) -> None:
        first = not self.conns.get(conn.user_id)
        self.conns[conn.user_id].add(conn)
        if first:
            await self._load_membership(conn.user_id)
        await self.refresh_online(conn.user_id)

    async def unregister(self, conn: Conn) -> None:
        conn.closed = True
        s = self.conns.get(conn.user_id)
        if s is not None:
            s.discard(conn)
            if not s:
                del self.conns[conn.user_id]
                for chat_id in self.user_chats.pop(conn.user_id, set()):
                    members = self.chat_online.get(chat_id)
                    if members is not None:
                        members.discard(conn.user_id)
                        if not members:
                            self.chat_online.pop(chat_id, None)
                            self.chat_types.pop(chat_id, None)
        await self.refresh_online(conn.user_id)

    def is_connected(self, user_id: int) -> bool:
        return bool(self.conns.get(user_id))

    def is_foreground(self, user_id: int) -> bool:
        """这个人此刻有前台连接(App 开着、在前台)。推送据此决定发不发(#353)。"""
        return any(c.foreground and not c.closed for c in self.conns.get(user_id, ()))

    def is_viewing(self, user_id: int, chat_id: int) -> bool:
        return any(c.foreground and c.viewing == chat_id for c in self.conns.get(user_id, ()))

    async def _load_membership(self, user_id: int) -> None:
        from ..db import SessionLocal
        from ..models import ACTIVE_ROLES, Chat, ChatMember

        async with SessionLocal() as db:
            rows = (await db.execute(
                select(ChatMember.chat_id, Chat.type)
                .join(Chat, Chat.id == ChatMember.chat_id)
                .where(ChatMember.user_id == user_id,
                       ChatMember.role.in_(ACTIVE_ROLES),
                       Chat.deleted_at.is_(None)))).all()
        chats = self.user_chats.setdefault(user_id, set())
        for chat_id, type_ in rows:
            chats.add(chat_id)
            self.chat_online[chat_id].add(user_id)
            self.chat_types[chat_id] = type_

    def join(self, user_id: int, chat_id: int, type_: str | None = None) -> None:
        """user 进了 chat(只对在线的人有意义;不在线的人下次连上时从库里读)。"""
        if user_id not in self.conns:
            return
        self.user_chats.setdefault(user_id, set()).add(chat_id)
        self.chat_online[chat_id].add(user_id)
        if type_:
            self.chat_types[chat_id] = type_

    def leave(self, user_id: int, chat_id: int) -> None:
        chats = self.user_chats.get(user_id)
        if chats is not None:
            chats.discard(chat_id)
        members = self.chat_online.get(chat_id)
        if members is not None:
            members.discard(user_id)
            if not members:
                self.chat_online.pop(chat_id, None)
                self.chat_types.pop(chat_id, None)

    # ---------------- 分发 ----------------

    async def dispatch(self, frames: list[dict], *, from_bus: bool = False) -> None:
        """事件帧(已落库、已提交)分给在线连接,并转发给其他进程。"""
        for f in frames:
            try:
                if f.get("t") == "ev":
                    self._deliver_chat(f)
                elif f.get("t") == "uev":
                    self._apply_user_event(f)
                    self.send_user_local(int(f["user_id"]), f)
            except Exception:
                logger.exception("分发事件失败:%s", f.get("type"))
        if not from_bus:
            from . import bus
            await bus.publish(frames=frames)

    def _deliver_chat(self, f: dict) -> None:
        chat_id = int(f["chat_id"])
        for uid in list(self.chat_online.get(chat_id, ())):
            self.send_user_local(uid, f)
        # 被移出 / 封禁 / 退出的人:这一条(告诉他自己出去了)照发,之后就不再发给他
        if f.get("type") == "member":
            d = f.get("data") or {}
            if d.get("role") in ("left", "banned") and d.get("user_id"):
                self.leave(int(d["user_id"]), chat_id)

    def _apply_user_event(self, f: dict) -> None:
        uid = int(f["user_id"])
        d = f.get("data") or {}
        chat = d.get("chat") or {}
        if f.get("type") == "chat_join" and chat.get("id"):
            self.join(uid, int(chat["id"]), chat.get("type"))
        elif f.get("type") == "chat_leave" and d.get("chat_id") and d.get("role") != "hidden":
            # 「删除私聊」只是从列表里拿掉(role=hidden),人还在会话里:
            # 对方再发消息要能实时收到,所以不从分发表里摘掉
            self.leave(uid, int(d["chat_id"]))

    def send_user_local(self, user_id: int, frame: dict) -> None:
        for c in list(self.conns.get(user_id, ())):
            c.send(frame)

    async def send_user(self, user_id: int, frame: dict) -> None:
        """不落库的帧(正在输入、在线状态、通话信令):本进程发 + 转给其他进程。"""
        self.send_user_local(user_id, frame)
        from . import bus
        await bus.publish(direct=[[user_id, frame]])

    async def send_chat_ephemeral(self, chat_id: int, frame: dict,
                                  exclude: int | None = None) -> None:
        targets = [u for u in self.chat_online.get(chat_id, ()) if u != exclude]
        for uid in targets:
            self.send_user_local(uid, frame)
        from . import bus
        await bus.publish(chat_direct=[[chat_id, frame, exclude]])

    def deliver_direct(self, direct: list, chat_direct: list) -> None:
        """其他进程转过来的不落库帧。"""
        for uid, frame in direct or ():
            self.send_user_local(int(uid), frame)
        for chat_id, frame, exclude in chat_direct or ():
            for uid in list(self.chat_online.get(int(chat_id), ())):
                if uid != exclude:
                    self.send_user_local(uid, frame)

    # ---------------- 在线状态 ----------------

    async def refresh_online(self, user_id: int) -> None:
        """有前台连接 → 续在线键;没有 → 删键、记最后上线时间、告诉私聊对方。"""
        from ..redis_client import get_redis
        from ..services.social import ONLINE_KEY

        online = self.is_foreground(user_id)
        key = ONLINE_KEY.format(user_id)
        try:
            r = get_redis()
            was = bool(await r.exists(key))
            if online:
                await r.set(key, "1", ex=ONLINE_TTL)
            else:
                await r.delete(key)
        except Exception:
            logger.warning("在线状态写 Redis 失败", exc_info=True)
            return
        if online == was:
            return
        at = datetime.now(timezone.utc)
        if not online:
            await self._save_last_seen(user_id, at)
        await self._broadcast_presence(user_id, online, at)
        # 私聊对方可能连在别的进程上:让每个进程各自给自己的连接发一遍
        from . import bus
        await bus.publish(presence=[[user_id, online]])

    async def _save_last_seen(self, user_id: int, at: datetime) -> None:
        from ..db import SessionLocal
        from ..models import SocialProfile

        try:
            async with SessionLocal() as db:
                await db.execute(update(SocialProfile).where(SocialProfile.user_id == user_id)
                                 .values(last_seen_at=at))
                await db.commit()
        except Exception:
            logger.warning("记最后上线时间失败", exc_info=True)

    async def _broadcast_presence(self, user_id: int, online: bool,
                                  at: datetime | None = None) -> None:
        """只发给「和他有私聊、此刻在线、隐私允许看」的人。"""
        peers: set[int] = set()
        for chat_id in self.user_chats.get(user_id, ()):
            if self.chat_types.get(chat_id) == "private":
                peers |= {u for u in self.chat_online.get(chat_id, ()) if u != user_id}
        if not peers:
            return
        from ..db import SessionLocal
        from ..services.social import user_cards

        async with SessionLocal() as db:
            for peer in peers:
                card = (await user_cards(db, peer, [user_id])).get(user_id)
                if card is None:
                    continue
                self.send_user_local(peer, {"t": "presence", "user_id": user_id,
                                            **card["last_seen"]})


hub = Hub()
