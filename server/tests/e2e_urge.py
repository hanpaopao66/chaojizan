"""用户催单:对象自动判定(商家/骑手)、3 分钟间隔、每单 3 次上限、
商家一键回复、事件型 OrderEvent 不影响状态机。
在 server/ 目录下运行:python -m tests.e2e_urge
"""
import asyncio
import time

import redis.asyncio as aioredis

from app.config import settings
from tests.util import call, login

merchant = login("13800000002")
rider = login("13800000003")
customer = call("POST", "/auth/register",
                body={"phone": f"135{int(time.time()) % 100000000:08d}",
                      "password": "123456", "name": "催单测试",
                      "role": "customer"})["token"]

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"催单测试菜-{int(time.time())}", "price_cents": 2000, "stock": 50})


def make_order(to="paid", pickup=False):
    body = {"merchant_id": shop["id"],
            "items": [{"dish_id": dish["id"], "quantity": 1}]}
    if pickup:
        body["pickup"] = True
    else:
        body.update({"address": "测试地址", "lat": 30.66, "lng": 104.08})
    order = call("POST", "/orders", customer, body)
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    if to in ("accepted", "ready", "picked_up"):
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    if to in ("ready", "picked_up"):
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    if to == "picked_up" and not pickup:
        call("POST", f"/riders/grab/{no}", rider)
        call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    return no


async def clear_cooldown(no):
    r = aioredis.from_url(settings.redis_url)
    await r.delete(f"urge:cd:{no}")
    await r.aclose()


# 1) 未出餐催商家;间隔限制;3 次上限
no1 = make_order("accepted")
r1 = call("POST", f"/orders/{no1}/urge", customer)
assert r1["target"] == "merchant" and r1["times_left"] == 2
err = call("POST", f"/orders/{no1}/urge", customer, expect_error=True)
assert err["_error"] == 429 and "3 分钟" in err["detail"]
print("✓ 催商家成功;连催被 3 分钟间隔拦下")

asyncio.run(clear_cooldown(no1))
r2 = call("POST", f"/orders/{no1}/urge", customer)
assert r2["times_left"] == 1
asyncio.run(clear_cooldown(no1))
r3 = call("POST", f"/orders/{no1}/urge", customer)
assert r3["times_left"] == 0
asyncio.run(clear_cooldown(no1))
err = call("POST", f"/orders/{no1}/urge", customer, expect_error=True)
assert err["_error"] == 429 and "3 次" in err["detail"]
print("✓ 每单 3 次上限生效")

# 2) 催单事件落 OrderEvent(不影响状态);商家一键回复
events = call("GET", f"/orders/{no1}/events", customer)
assert sum(1 for e in events if e["to_status"] == "urged") == 3
o1 = call("GET", f"/orders/{no1}", customer)
assert o1["status"] == "accepted", "催单不改变订单状态"
call("POST", f"/orders/{no1}/urge-reply", merchant, {"text": "马上好,正在加急制作!"})
events = call("GET", f"/orders/{no1}/events", customer)
assert any(e["to_status"] == "urge_reply" for e in events)
print("✓ 催单/回复写事件流水,订单状态不受影响")

# 3) 没催过的订单不能回复
no2 = make_order("accepted")
err = call("POST", f"/orders/{no2}/urge-reply", merchant,
           {"text": "马上好"}, expect_error=True)
assert err["_error"] == 409
print("✓ 无催单记录不能回复")

# 4) 配送中催骑手
no3 = make_order("picked_up")
r = call("POST", f"/orders/{no3}/urge", customer)
assert r["target"] == "rider"
print("✓ 配送中催单对象自动切到骑手")

# 5) 自取单出餐后不给催(自己去取);已取消订单 409
no4 = make_order("ready", pickup=True)
err = call("POST", f"/orders/{no4}/urge", customer, expect_error=True)
assert err["_error"] == 409 and "取餐码" in err["detail"]
no5 = make_order("paid")
call("POST", f"/orders/{no5}/transition", customer,
     {"to_status": "cancelled", "reason": "不想要了"})
err = call("POST", f"/orders/{no5}/urge", customer, expect_error=True)
assert err["_error"] == 409
print("✓ 自取已出餐/已取消订单不能催")

call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\n用户催单验证通过 🎉")
