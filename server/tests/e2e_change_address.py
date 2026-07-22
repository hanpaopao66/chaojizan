"""订单改地址:骑手取餐前可改(每单一次/同半径),配送费按距离差重算——
变近自动退差价,变贵拦截(补价未开通),取餐后关闭,自取单无地址可改。
在 server/ 目录下运行:python -m tests.e2e_change_address
"""
import time

from tests.util import call, login

merchant = login("13800000002")
rider = login("13800000003")
customer = call("POST", "/auth/register",
                body={"phone": f"134{int(time.time()) % 100000000:08d}",
                      "password": "123456", "name": "改址测试",
                      "role": "customer"})["token"]

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"改址测试菜-{int(time.time())}", "price_cents": 2000, "stock": 50})

# 商家在 (30.6598, 104.0810):远址 ~3.3km(基础费 ¥5),近址 ~0.4km(基础费 ¥3)
FAR = {"address": "远端小区 1 栋", "lat": 30.6896, "lng": 104.0810}
NEAR = {"address": "近端小区 2 栋", "lat": 30.6630, "lng": 104.0810}


def make_order(addr, to="accepted", pickup=False):
    body = {"merchant_id": shop["id"],
            "items": [{"dish_id": dish["id"], "quantity": 1}]}
    if pickup:
        body["pickup"] = True
    else:
        body.update(addr)
    order = call("POST", "/orders", customer, body)
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    if to in ("accepted", "ready", "picked_up"):
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    if to in ("ready", "picked_up"):
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    if to == "picked_up":
        call("POST", f"/riders/grab/{no}", rider)
        call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    return call("GET", f"/orders/{no}", customer)


def change(no, addr, expect_error=False):
    return call("POST", f"/orders/{no}/change-address", customer,
                {**addr, "contact_name": "改址人", "contact_phone": "13400000000"},
                expect_error=expect_error)


# 1) 远→近:退差价,金额三处联动。
# 夜间时段(21:00-06:00)配送费含 +2 元夜间加价,改址保留加价只退基础费差价,
# 断言按「相对差」写,任何时段跑都成立
o = make_order(FAR)
night = o["delivery_fee_cents"] - 500  # 0 或 200(夜间加价部分)
assert o["delivery_fee_cents"] == 500 + night, o["delivery_fee_cents"]
after = change(o["order_no"], NEAR)
assert after["address"] == "近端小区 2 栋"
assert after["delivery_fee_cents"] == 300 + night
assert after["total_cents"] == o["total_cents"] - 200
assert after["refund_cents"] == 200
flows = call("GET", f"/orders/{o['order_no']}/refunds", customer)
assert sum(f["amount_cents"] for f in flows) == 200
assert after["contact_name"] == "改址人"
print("✓ 改近退差价 ¥2.00:配送费/实付/退款流水三处联动")

# 2) 每单一次
err = change(o["order_no"], FAR, expect_error=True)
assert err["_error"] == 409 and "一次" in err["detail"]
print("✓ 每单只能改一次")

# 3) 近→远:变贵拦截(补价未开通)
o2 = make_order(NEAR)
err = change(o2["order_no"], FAR, expect_error=True)
assert err["_error"] == 409 and "补差价" in err["detail"]
print(f"✓ 改贵拦截:{err['detail']}")

# 4) 半径外拦截
err = change(o2["order_no"], {"address": "十公里外", "lat": 30.75, "lng": 104.081},
             expect_error=True)
assert err["_error"] == 409 and "配送范围" in err["detail"]
print("✓ 超出配送半径拦截")

# 5) 取餐后关闭
o3 = make_order(NEAR, to="picked_up")
err = change(o3["order_no"], FAR, expect_error=True)
assert err["_error"] == 409 and "骑手" in err["detail"]
print(f"✓ 取餐后自助通道关闭:{err['detail']}")

# 6) 自取单没有配送地址
o4 = make_order(None, to="accepted", pickup=True)
err = change(o4["order_no"], NEAR, expect_error=True)
assert err["_error"] == 409 and "自取" in err["detail"]
print("✓ 自取单不可改配送地址")

call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\n订单改地址验证通过 🎉")
