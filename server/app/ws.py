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
from .config import settings
from .db import SessionLocal
from sqlalchemy import select

from .models import Order, User
from .services.staff import operable_shop

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
async def order_ws(ws: WebSocket, order_no: str, token: str = Query("")):
    """订单实时通道:**这一单的三方**都连得上,别人一律挡掉。

    这条以前是敞开的 —— 商家听单通道验了 JWT + 店铺归属,订单这条谁都能连。
    播出去的载荷是克制的(只有 type/order_no/status/rider_id,没有地址、
    手机号、金额),而且要拿到完整订单号才连得上(平台只公开尾 6 位),
    所以它不是一条能拿到数据的路;但"谁都能订阅别人订单的状态流"
    没有任何存在理由。

    **三方都要放行,不能收窄成只有顾客**:骑手端要看这单的状态推进,
    商家端也要 —— 收窄的话表现是"配送中页面不刷新",而那种故障
    没人会往鉴权上想。商家侧走 operable_shop,与所有商家端点同一套
    (连锁老板、区域经理、店员的归属判定都在那里面)。
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        uid = int(payload["sub"])
        async with SessionLocal() as db:
            order = await db.scalar(
                select(Order).where(Order.order_no == order_no))
            if order is None:
                raise ValueError
            ok = uid in (order.customer_id, order.rider_id)
            if not ok and payload.get("role") == "merchant":
                user = await db.get(User, uid)
                if user is not None:
                    shop, _ = await operable_shop(db, user, order.merchant_id)
                    ok = shop is not None and shop.id == order.merchant_id
        if not ok:
            raise ValueError
    except Exception:
        await ws.close(code=4401)
        return
    await _hold(f"order:{order_no}", ws)


@router.websocket("/ws/merchants/{merchant_id}")
async def merchant_ws(ws: WebSocket, merchant_id: int, token: str = Query("")):
    """商家听单通道:验 token + 店铺归属,防止别人偷听你的订单流水。

    归属判定走 services.staff.operable_shop —— 与所有商家端点同一套。
    老写法是 `db.scalar(owner_id == 我)` 再比对 merchant_id,不带
    ORDER BY:单店时永远只有一个候选看不出问题,**连锁老板名下三家店时
    返回哪家由数据库决定**,于是另外两家的听单通道随机连不上 ——
    而"听不到新单"这种故障商家只会以为是今天没生意。
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("role") != "merchant":
            raise ValueError
        async with SessionLocal() as db:
            user = await db.get(User, int(payload["sub"]))
            if user is None:
                raise ValueError
            shop, _ = await operable_shop(db, user, merchant_id)
        if shop is None or shop.id != merchant_id:
            raise ValueError
    except Exception:
        await ws.close(code=4401)
        return
    await _hold(f"merchant:{merchant_id}", ws)
