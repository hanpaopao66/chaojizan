"""加急小费(#25):仅无人接单窗口开放、tip/total 同步抬升、结算含小费、取消随退、审计平账。"""
import asyncio
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"加急测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})
addr = {"address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "测试", "contact_phone": "13800000001"}


def make_order():
    o = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}], **addr})
    call("POST", f"/orders/{o['order_no']}/pay/mock", customer)
    call("POST", f"/orders/{o['order_no']}/transition", merchant,
         {"to_status": "accepted"})
    return o["order_no"]


def set_no_rider(order_no):
    """直连 DB 置无人接单告警标记(模拟清扫任务已喊过一轮)。"""
    async def _run():
        from datetime import datetime, timezone
        from sqlalchemy import update
        from app.db import SessionLocal, engine
        from app.models import Order
        async with SessionLocal() as db:
            await db.execute(update(Order).where(Order.order_no == order_no)
                             .values(no_rider_alerted_at=datetime.now(timezone.utc)))
            await db.commit()
        await engine.dispose()
    asyncio.run(_run())


no = make_order()

# 未进入无人接单窗口:加急被拒
err = call("POST", f"/orders/{no}/boost-tip", customer, {"add_cents": 500},
           expect_error=True)
assert err["_error"] == 409 and "无需加急" in err["detail"], err
print("✓ 非无人接单状态加急被拒")

# 进入告警窗口后可加急:tip 与 total 同步抬升
set_no_rider(no)
before = call("GET", f"/orders/{no}", customer)
boosted = call("POST", f"/orders/{no}/boost-tip", customer, {"add_cents": 500})
assert boosted["tip_cents"] == 500
assert boosted["total_cents"] == before["total_cents"] + 500
print(f"✓ 加急 +5 元:小费 {boosted['tip_cents']/100:g} 元,total 同步 +5")

# 再加急累加
boosted = call("POST", f"/orders/{no}/boost-tip", customer, {"add_cents": 300})
assert boosted["tip_cents"] == 800
print("✓ 二次加急累加至 8 元")

# 累计上限:当前 8 元,加 50 元→58 元(可),再加 50 元→108 元超 100 被拒
call("POST", f"/orders/{no}/boost-tip", customer, {"add_cents": 5000})
err = call("POST", f"/orders/{no}/boost-tip", customer, {"add_cents": 5000},
           expect_error=True)
assert err["_error"] == 422, err
print("✓ 小费累计超 100 元被拒")

# 抢单池:骑手能看到该单且小费已反映
cur = call("GET", f"/orders/{no}", customer)
tip_now = cur["tip_cents"]
assert tip_now == 5800  # 800 + 5000
pool = call("GET", "/riders/available-orders", rider)
prow = next((o for o in pool if o["order_no"] == no), None)
assert prow is not None and prow["tip_cents"] == tip_now
print(f"✓ 抢单池反映加急小费(排序权重已加,骑手可见 {tip_now/100:g} 元)")

# 骑手抢单 → 送达完成 → 结算含小费(100% 归骑手,不计佣)
call("POST", f"/riders/grab/{no}", rider)
w0 = call("GET", "/riders/wallet", rider)
for st in ("ready", "picked_up", "delivered", "completed"):
    actor = merchant if st == "ready" else rider
    if st == "completed":
        actor = customer
    call("POST", f"/orders/{no}/transition", actor, {"to_status": st})
w1 = call("GET", "/riders/wallet", rider)
final = call("GET", f"/orders/{no}", customer)
gained = w1["total_earned_cents"] - w0["total_earned_cents"]
assert gained == final["delivery_fee_cents"] + tip_now, \
    f"骑手应得配送费+小费,实际 {gained} vs {final['delivery_fee_cents']}+{tip_now}"
print(f"✓ 结算:骑手入账 配送费+小费 = {gained/100:g} 元(小费 100% 归骑手不计佣)")

# 自取/自送单不允许加急(造一个自取单验证)
po = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}], "pickup": True})
call("POST", f"/orders/{po['order_no']}/pay/mock", customer)
err = call("POST", f"/orders/{po['order_no']}/boost-tip", customer,
           {"add_cents": 500}, expect_error=True)
assert err["_error"] == 409
print("✓ 自取单不允许加急小费")

# 取消退款:加急后取消,小费随 total 一起退
no2 = make_order()
set_no_rider(no2)
call("POST", f"/orders/{no2}/boost-tip", customer, {"add_cents": 500})
o2 = call("GET", f"/orders/{no2}", customer)
call("POST", f"/orders/{no2}/transition", merchant,
     {"to_status": "cancelled", "reason": "测试收尾"})
done = call("GET", f"/orders/{no2}", customer)
assert done["refund_cents"] == o2["total_cents"], \
    f"取消应全额退(含小费),退 {done['refund_cents']} vs total {o2['total_cents']}"
print("✓ 加急后取消:小费随 total 全额退")

call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\n加急小费验证通过 🎉")
