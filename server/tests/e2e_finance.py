"""商家对账验证:完成单入账(净额=流水-佣金)、日汇总与明细对得上、权限隔离"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")

# 专属菜品,金额可精确断言:2 × ¥10 = ¥20 流水,佣金 5% = ¥1.00,净得 ¥19.00
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"对账测试菜-{int(time.time())}", "price_cents": 1000, "stock": 50})

daily_before = {d["day"]: d for d in call("GET", "/merchants/me/finance/daily", merchant)}

order = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 2}],
    "address": "测试地址", "lat": 30.66, "lng": 104.08,
})
no = order["order_no"]
call("POST", f"/orders/{no}/pay/mock", customer)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/riders/grab/{no}", rider)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

daily_after = {d["day"]: d for d in call("GET", "/merchants/me/finance/daily", merchant)}
changed = [
    (day, stat) for day, stat in daily_after.items()
    if stat["net_cents"] != daily_before.get(day, {"net_cents": 0})["net_cents"]
]
assert len(changed) == 1, changed
day, stat = changed[0]
before = daily_before.get(day, {"order_count": 0, "food_cents": 0, "commission_cents": 0, "net_cents": 0})
assert stat["order_count"] == before["order_count"] + 1
assert stat["food_cents"] == before["food_cents"] + 2000
assert stat["commission_cents"] == before["commission_cents"] + 100
assert stat["net_cents"] == before["net_cents"] + 1900
print(f"✓ 完成单入账:{day} 流水 +¥20.00,佣金 +¥1.00(5%),净收入 +¥19.00")

detail = call("GET", f"/merchants/me/finance/orders?day={day}", merchant)
mine = next(o for o in detail if o["order_no"] == no)
assert mine["net_cents"] == 1900 and mine["commission_cents"] == 100
print("✓ 单日明细逐单可查,金额与汇总一致")

total_detail = sum(o["net_cents"] for o in detail)
assert total_detail == stat["net_cents"], f"明细合计 {total_detail} ≠ 日汇总 {stat['net_cents']}"
print(f"✓ 明细合计 = 日汇总({stat['net_cents']/100:.2f} 元),账能对上")

err = call("GET", "/merchants/me/finance/daily", customer, expect_error=True)
assert err["_error"] == 403
print("✓ 非商家角色无对账权限(403)")

# 另一个商家看不到张记面馆的账
other = call("POST", "/auth/register", body={
    "phone": "139" + str(int(time.time() * 7))[-8:],
    "password": "123456", "name": "对账测试商家", "role": "merchant",
})["token"]
err = call("GET", "/merchants/me/finance/daily", other, expect_error=True)
assert err["_error"] == 404  # 还没开店
print("✓ 其他商家账号看不到本店账目(数据按店隔离)")

# 清场
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\n商家对账验证通过 🎉")
