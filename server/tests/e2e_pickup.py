"""到店自取全链路:免配送费下单 → 不进骑手抢单池 → 出餐 → 取餐码核销完成结算。"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
# 专属菜品(价格盖过起送价):不受演示菜库存/价格变化影响
main_dish = call("POST", "/merchants/me/dishes", merchant,
                 {"name": f"自取测试菜-{int(time.time())}",
                  "price_cents": 2000, "stock": 50})

# 配送单不带地址 → 422
err = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": main_dish["id"], "quantity": 1}],
}, expect_error=True)
assert err["_error"] == 422
print(f"✓ 配送单没有地址被拒:{err['detail']}")

# 自取单:不传地址,免配送费,取餐码随单生成
order = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": main_dish["id"], "quantity": 1}],
    "pickup": True,
})
no = order["order_no"]
assert order["pickup"] is True
assert order["delivery_fee_cents"] == 0
assert order["address"] == "到店自取"
assert len(order["pickup_code"]) == 4 and order["pickup_code"].isdigit()
assert order["total_cents"] == (order["food_cents"] + order["packing_fee_cents"]
                                - order["discount_cents"] - order["subsidy_cents"])
print(f"✓ 自取单免配送费,取餐码 {order['pickup_code']} 随单生成")

call("POST", f"/orders/{no}/pay/mock", customer)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})

# 不进骑手抢单池,抢也抢不到
pool = call("GET", "/riders/available-orders", rider)
assert all(o["order_no"] != no for o in pool)
err = call("POST", f"/riders/grab/{no}", rider, expect_error=True)
assert err["_error"] == 409
print("✓ 自取单不进骑手抢单池,抢单被拒")

# 出餐前不能核销
err = call("POST", f"/orders/{no}/pickup-verify", merchant,
           {"code": order["pickup_code"]}, expect_error=True)
assert err["_error"] == 409
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})

# 错码被拒
err = call("POST", f"/orders/{no}/pickup-verify", merchant,
           {"code": "0000" if order["pickup_code"] != "0000" else "1111"},
           expect_error=True)
assert err["_error"] == 422
print("✓ 未出餐不能核销;取餐码错误被拒")

# 正确核销 → 完成 + 商家结算(无骑手行)
w0 = call("GET", "/merchants/me/wallet", merchant)
done = call("POST", f"/orders/{no}/pickup-verify", merchant,
            {"code": order["pickup_code"]})
assert done["status"] == "completed"
w1 = call("GET", "/merchants/me/wallet", merchant)
net = (order["food_cents"] + order["packing_fee_cents"]
       - order["discount_cents"] - done["commission_cents"])
assert w1["total_earned_cents"] == w0["total_earned_cents"] + net
print(f"✓ 取餐码核销完成,商家入账 +{net / 100:.2f} 元(5% 佣金照常,无骑手行)")

# 重复核销被拒(状态已终结)
err = call("POST", f"/orders/{no}/pickup-verify", merchant,
           {"code": order["pickup_code"]}, expect_error=True)
assert err["_error"] == 409
print("✓ 重复核销被拒")

call("PATCH", f"/merchants/me/dishes/{main_dish['id']}", merchant, {"is_on_sale": False})
print("\n到店自取全链路验证通过 🎉")
