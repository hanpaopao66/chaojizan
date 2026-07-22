"""P1 商业化验证:评价标签 / 限时折扣 / 商家销量数据。

在 server/ 目录下运行:python -m tests.e2e_p1_commercial
"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

tag = str(int(time.time()))
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]

# ---- 限时折扣:设置 → 校验 → 按折扣价成交 → 过期不生效 ----
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"折扣菜-{tag}", "price_cents": 2000, "stock": 50})

err = call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
           {"flash_price_cents": 2500,
            "flash_until": "2099-01-01T00:00:00Z"}, expect_error=True)
assert err["_error"] == 422
print("✓ 折扣价高于原价被拒(不叫折扣)")

err = call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
           {"flash_price_cents": 1500}, expect_error=True)
assert err["_error"] == 422
print("✓ 只传折扣价不传截止时间被拒(必须成对)")

call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
     {"flash_price_cents": 1500, "flash_until": "2099-01-01T00:00:00Z"})
menu = call("GET", f"/merchants/{sid}/dishes")
d = next(x for x in menu if x["id"] == dish["id"])
assert d["flash_price_cents"] == 1500
print("✓ 限时折扣设置成功(¥20 → ¥15)")

order = call("POST", "/orders", customer, {
    "merchant_id": sid,
    "items": [{"dish_id": dish["id"], "quantity": 2}],
    "address": "折扣验证地址", "lat": 30.6612, "lng": 104.0823,
})
assert order["items"][0]["price_cents"] == 1500, "应按折扣价成交"
assert order["food_cents"] == 3000
print("✓ 下单按折扣价成交(2×15=30),佣金自动按折后实收计")

# 过期折扣不生效
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
     {"flash_price_cents": 1500, "flash_until": "2020-01-01T00:00:00Z"})
order2 = call("POST", "/orders", customer, {
    "merchant_id": sid,
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "address": "折扣验证地址", "lat": 30.6612, "lng": 104.0823,
})
assert order2["items"][0]["price_cents"] == 2000, "过期折扣应按原价"
print("✓ 过期折扣自动失效,按原价成交")

# ---- 评价标签:白名单校验 + 存取 ----
no = order["order_no"]
call("POST", f"/orders/{no}/pay/mock", customer)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
call("POST", "/riders/online", rider, {"is_online": True})
call("POST", "/riders/location", rider, {"lat": 30.6605, "lng": 104.0815})
call("POST", f"/riders/grab/{no}", rider)
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

err = call("POST", f"/orders/{no}/review", customer, {
    "merchant_rating": 5, "tags": ["巨好吃"]}, expect_error=True)
assert err["_error"] == 422
print("✓ 白名单外的标签被拒")

review = call("POST", f"/orders/{no}/review", customer, {
    "merchant_rating": 5, "tags": ["味道好", "配送快"], "comment": ""})
assert review["tags"] == ["味道好", "配送快"]
back = call("GET", f"/merchants/{sid}/reviews")
assert next(r for r in back if r["id"] == review["id"])["tags"] == ["味道好", "配送快"]
print("✓ 一键标签评价:提交与回读一致(零文字也能评)")

# ---- 商家菜品销量数据(经营诊断) ----
mine = call("GET", "/merchants/me/dishes", merchant)
d = next(x for x in mine if x["id"] == dish["id"])
assert d["monthly_sales"] >= 2, "商家端应能看到菜品月售"
print(f"✓ 商家端菜品带月售数据(折扣菜月售 {d['monthly_sales']})")

print("\nP1 商业化(评价标签/限时折扣/销量数据)验证通过 🎉")
