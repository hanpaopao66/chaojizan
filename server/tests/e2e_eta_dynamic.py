"""ETA 动态刷新(清单#59):骑手接单/取餐按位置重估、出餐超时顺延、克制(<5分钟不刷)。

**只往后放宽,不往前收紧。** 透明中心公开承诺「预计送达时间只会因路况、天气变宽,
不会因为你跑得快而变紧」,而刷新后的 eta_at 是超时赔付的新基准 —— 所以骑手接单快、
离得近时照旧用原来的时限(以前这里会把 +90 分钟收紧到二十来分钟,和那条承诺对不上)。
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from tests.util import demo_shop, call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = demo_shop()
DROP = (30.6612, 104.0823)
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"ETA测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def new_order():
    o = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址1号", "lat": DROP[0], "lng": DROP[1],
        "contact_name": "测试", "contact_phone": "13800000001"})
    call("POST", f"/orders/{o['order_no']}/pay/mock", customer)
    return o["order_no"]


def db_set(order_no, **fields):
    """直连 DB 改订单字段(backdate accepted_at / 强设 eta_at 等)。"""
    async def _run():
        from sqlalchemy import update
        from app.db import SessionLocal, engine
        from app.models import Order
        async with SessionLocal() as db:
            await db.execute(update(Order).where(Order.order_no == order_no)
                             .values(**fields))
            await db.commit()
        await engine.dispose()
    asyncio.run(_run())


def get_eta(order_no):
    o = call("GET", f"/orders/{order_no}", customer)
    return datetime.fromisoformat(o["eta_at"]) if o.get("eta_at") else None


def sweep():
    """每次 sweep 都独立起一个事件循环,收尾必须把**数据库和 Redis**
    的连接池都释放掉 —— 只 dispose 引擎的话,Redis 池里的连接还绑在
    上一个已关闭的 loop 上,第二次 sweep 就炸在 read_response。
    (同类问题在 e2e_upload_privacy 也踩过)"""
    async def _run():
        from app.db import engine
        from app.redis_client import pool
        from app.services.auto_flow import sweep_once
        try:
            await sweep_once()
        finally:
            await engine.dispose()
            await pool.disconnect()
    asyncio.run(_run())


now = datetime.now(timezone.utc)

# ---- 骑手接单按位置重估:只放宽不收紧 —— eta 设得很远,骑手在店附近接单,照旧用原来的时限 ----
no = new_order()
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
far = now + timedelta(minutes=90)
db_set(no, eta_at=far)
call("POST", "/riders/location", rider, {"lat": 30.6598, "lng": 104.0810})  # 店附近
call("POST", f"/riders/grab/{no}", rider)
eta_after_grab = get_eta(no)
assert abs((eta_after_grab - far).total_seconds()) < 2, \
    f"骑手接单快、离得近,时限不许往前收:从 {far} 变成了 {eta_after_grab}"
print("✓ 骑手接单按位置重估:离得近也不收紧(公开承诺:不会因为你跑得快而变紧)")

# ---- 取餐节点重估:原来的时限已经来不及了 → 往后放宽 ----
db_set(no, eta_at=now + timedelta(minutes=1))  # 设成一分钟后,骑手还在 3 公里外
call("POST", "/riders/location", rider, {"lat": DROP[0] + 0.03, "lng": DROP[1]})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
eta_after_pickup = get_eta(no)
assert eta_after_pickup > now + timedelta(minutes=5), \
    f"取餐时离收货点还远,ETA 应往后放宽,实际 {eta_after_pickup}"
print(f"✓ 取餐节点按位置重估:来不及就往后放宽到 {eta_after_pickup.astimezone():%H:%M}")

# ---- 克制:偏差<5分钟不刷新 ----
no2 = new_order()
call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "ready"})
# 骑手就在店里(rider→店≈0),READY 状态自然重估≈now+2min;
# 把 eta 设成 now+4min(与自然值差<5分钟),接单应"克制不刷新"
target = now + timedelta(minutes=4)
db_set(no2, eta_at=target)
call("POST", "/riders/location", rider, {"lat": shop["lat"], "lng": shop["lng"]})
call("POST", f"/riders/grab/{no2}", rider)
eta2 = get_eta(no2)
assert abs((eta2 - target).total_seconds()) < 300, \
    f"偏差<5分钟不该刷新,却从 {target} 变到 {eta2}"
print("✓ 克制:偏差<5分钟不刷新 ETA")

# ---- 出餐超时顺延:backdate + 强设近过期 eta,两趟 sweep 到二档,eta 顺延到未来 ----
no3 = new_order()
call("PATCH", "/merchants/me", merchant, {"promise_ready_minutes": 5})
call("POST", f"/orders/{no3}/transition", merchant, {"to_status": "accepted"})
db_set(no3, accepted_at=now - timedelta(minutes=30),
       eta_at=now - timedelta(minutes=5))  # 已"过期"
sweep()  # 一档
sweep()  # 二档 → 顺延
eta3 = get_eta(no3)
assert eta3 is not None and eta3 > now, \
    f"出餐严重超时应把 ETA 顺延到未来,实际 {eta3}"
print(f"✓ 出餐超时顺延:ETA 从过期顺延到 {eta3.astimezone():%H:%M}")

call("PATCH", "/merchants/me", merchant, {"promise_ready_minutes": 15})
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\nETA 动态刷新验证通过 🎉")
