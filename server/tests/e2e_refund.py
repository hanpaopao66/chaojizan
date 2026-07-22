"""缺货部分退款验证:单菜退款、金额/佣金重算、库存回补、全退光=整单取消"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")

# 专属菜品:A ¥10×2 + B ¥6×1,金额可精确断言
tag = str(int(time.time()))
dish_a = call("POST", "/merchants/me/dishes", merchant,
              {"name": f"退款测试面-{tag}", "price_cents": 1000, "stock": 50})
dish_b = call("POST", "/merchants/me/dishes", merchant,
              {"name": f"退款测试汤-{tag}", "price_cents": 600, "stock": 50})

order = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish_a["id"], "quantity": 2},
              {"dish_id": dish_b["id"], "quantity": 1}],
    "address": "测试地址", "lat": 30.66, "lng": 104.08,
})
no = order["order_no"]
call("POST", f"/orders/{no}/pay/mock", customer)
fee = order["delivery_fee_cents"]

# 非商家不能退
err = call("POST", f"/orders/{no}/refund-item", rider,
           {"dish_id": dish_a["id"], "quantity": 1}, expect_error=True)
assert err["_error"] in (403, 404)
print("✓ 非本店商家不能操作退款")

# 退超量被拒
err = call("POST", f"/orders/{no}/refund-item", merchant,
           {"dish_id": dish_a["id"], "quantity": 3}, expect_error=True)
assert err["_error"] == 422
print(f"✓ 退超量被拒:{err['detail']}")

# 退 A×1:金额/佣金重算、库存回补
o = call("POST", f"/orders/{no}/refund-item", merchant,
         {"dish_id": dish_a["id"], "quantity": 1})
assert o["refund_cents"] == 1000
assert o["food_cents"] == 1600 and o["total_cents"] == 1600 + fee
assert o["commission_cents"] == int(1600 * float(shop["commission_rate"]))
assert f"退款测试面-{tag}×1" in o["refund_note"]
menu = call("GET", f"/merchants/{shop['id']}/dishes")
assert next(d for d in menu if d["id"] == dish_a["id"])["stock"] == 49  # 50-2+1
print("✓ 部分退款:金额/佣金重算正确,库存已回补")

# 用户视角可见退款明细
mine = call("GET", f"/orders/{no}", customer)
assert mine["refund_cents"] == 1000 and mine["refund_note"]
print("✓ 用户端可见退款金额与明细")

# 商家接单后仍可退(制作中)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
o = call("POST", f"/orders/{no}/refund-item", merchant,
         {"dish_id": dish_b["id"], "quantity": 1})
assert o["refund_cents"] == 1600
print("✓ 制作中仍可缺货退款")

# 出餐后不允许
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
err = call("POST", f"/orders/{no}/refund-item", merchant,
           {"dish_id": dish_a["id"], "quantity": 1}, expect_error=True)
assert err["_error"] == 409
print(f"✓ 出餐后不允许缺货退款:{err['detail']}")

# 清场这单(骑手送完)
call("POST", f"/riders/grab/{no}", rider)
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

# 全退光 = 整单取消 + 配送费一并退
order2 = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish_a["id"], "quantity": 2}],
    "address": "测试地址", "lat": 30.66, "lng": 104.08,
})
no2 = order2["order_no"]
call("POST", f"/orders/{no2}/pay/mock", customer)
o = call("POST", f"/orders/{no2}/refund-item", merchant,
         {"dish_id": dish_a["id"], "quantity": 2})
assert o["status"] == "cancelled"
assert o["refund_cents"] == 2000 + order2["delivery_fee_cents"]
assert o["cancel_reason"] == "商家缺货,整单退款"
print("✓ 全部退光 = 整单取消,配送费一并退")

# 清场:下架测试菜
for d in (dish_a, dish_b):
    call("PATCH", f"/merchants/me/dishes/{d['id']}", merchant, {"is_on_sale": False})

print("\n缺货部分退款验证通过 🎉")
