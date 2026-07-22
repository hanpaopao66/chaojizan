"""WebSocket 实时推送(多主题)。

主题:
  order:{order_no}     订单状态变更(用户/骑手端订阅,无鉴权,order_no 即凭证)
  merchant:{id}        商家新单提醒(需要 token,校验店铺归属)

推送内容示例:
  {"type": "order_status", "order_no": "...", "status": "picked_up"}
  {"type": "new_order", "order_no": "...", "summary": "红烧牛肉面×2", "total_cents": 4500}
"""
from collections import defaultdict

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Merchant

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)

    async def subscribe(self, topic: str, ws: WebSocket):
        await ws.accept()
        self._subscribers[topic].add(ws)

    def unsubscribe(self, topic: str, ws: WebSocket):
        self._subscribers[topic].discard(ws)
        if not self._subscribers[topic]:
            del self._subscribers[topic]

    async def broadcast(self, topic: str, payload: dict):
        dead = []
        for ws in self._subscribers.get(topic, ()):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unsubscribe(topic, ws)


manager = ConnectionManager()


async def _hold(topic: str, ws: WebSocket):
    await manager.subscribe(topic, ws)
    try:
        while True:
            await ws.receive_text()  # 心跳/保活,内容忽略
    except WebSocketDisconnect:
        manager.unsubscribe(topic, ws)


@router.websocket("/ws/orders/{order_no}")
async def order_ws(ws: WebSocket, order_no: str):
    await _hold(f"order:{order_no}", ws)


@router.websocket("/ws/merchants/{merchant_id}")
async def merchant_ws(ws: WebSocket, merchant_id: int, token: str = Query("")):
    """商家听单通道:验 token + 店铺归属,防止别人偷听你的订单流水。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("role") != "merchant":
            raise ValueError
        async with SessionLocal() as db:
            shop = await db.scalar(
                select(Merchant).where(Merchant.owner_id == int(payload["sub"]))
            )
        if shop is None or shop.id != merchant_id:
            raise ValueError
    except Exception:
        await ws.close(code=4401)
        return
    await _hold(f"merchant:{merchant_id}", ws)
