"""加菜(追加单):免配送费免起送价、地址/骑手随原单、不进抢单池、
独立支付独立佣金、原单出餐后拒绝、原单取消级联退款。
在 server/ 目录下运行:python -m tests.e2e_append_order
"""
import asyncio
import time

from app.services.auto_flow import sweep_once
from tests.util import call, login

merchant = login("13800000002")
rider = login("13800000003")
customer = call("POST", "/auth/register",
                body={"phone": f"133{int(time.time()) % 100000000:08d}",
                      "password": "123456", "name": "加菜测试",
                      "role": "customer"})["token"]

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
main_dish = call("POST", "/merchants/me/dishes", merchant,
                 {"name": f"加菜主菜-{int(time.time())}", "price_cents": 2000, "stock": 50})
cola = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"加菜可乐-{int(time.time())}", "price_cents": 300, "stock": 50})


def make_parent(pay=True, accept=False, pickup=False):
    body = {"merchant_id": shop["id"],
            "items": [{"dish_id": main_dish["id"], "quantity": 1}]}
    if pickup:
        body["pickup"] = True
    else:
        body.update({"address": "测试小区 3 栋", "lat": 30.66, "lng": 104.08})
    order = call("POST", "/orders", customer, body)
    no = order["order_no"]
    if pay:
        call("POST", f"/orders/{no}/pay/mock", customer)
    if accept:
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    return no


def append(parent_no, expect_error=False):
    return call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": cola["id"], "quantity": 1}],
        "append_to": parent_no,
    }, expect_error=expect_error)


# 1) 免配送费免起送价,地址/备注/关联字段正确
p1 = make_parent(accept=True)
a1 = append(p1)
assert a1["delivery_fee_cents"] == 0
assert a1["food_cents"] == 300  # 低于起送价 ¥15 也能下
assert a1["parent_order_no"] == p1
assert a1["address"] == "测试小区 3 栋"
assert p1[-6:] in a1["remark"]
paid1 = call("POST", f"/orders/{a1['order_no']}/pay/mock", customer)
assert paid1["commission_cents"] == 15  # 独立计佣 5%
assert paid1["total_cents"] == 300
print("✓ 追加单免配送费免起送价,地址随原单,独立计佣 5%")

# 2) 不进抢单池,不能被单独抢
pool = call("GET", "/riders/available-orders", rider)
assert all(o["order_no"] != a1["order_no"] for o in pool)
err = call("POST", f"/riders/grab/{a1['order_no']}", rider, expect_error=True)
assert err["_error"] == 409
print("✓ 追加单不进抢单池,单独抢单被拒")

# 3) 抢原单,追加单骑手跟随
call("POST", f"/riders/grab/{p1}", rider)
a1_now = call("GET", f"/orders/{a1['order_no']}", customer)
p1_now = call("GET", f"/orders/{p1}", customer)
assert a1_now["rider_id"] == p1_now["rider_id"] is not None
print("✓ 原单被抢,追加单骑手自动跟随")

# 4) 原单已有骑手后再加菜,直接继承
a2 = append(p1)
assert a2["rider_id"] == p1_now["rider_id"]
call("POST", f"/orders/{a2['order_no']}/pay/mock", customer)
print("✓ 原单已有骑手时,新追加单直接继承")

# 5) 追加单不能再追加
err = append(a1["order_no"], expect_error=True)
assert err["_error"] == 409 and "不能再追加" in err["detail"]

# 6) 原单出餐后不能加
call("POST", f"/orders/{p1}/transition", merchant, {"to_status": "ready"})
err = append(p1, expect_error=True)
assert err["_error"] == 409 and "出餐" in err["detail"]
print("✓ 套娃追加与出餐后追加都被拒")

# 7) 自取单不支持加菜
p2 = make_parent(pickup=True, accept=False)
err = append(p2, expect_error=True)
assert err["_error"] == 409 and "自取" in err["detail"]
print("✓ 自取单不支持追加(再下一单即可)")

# 8) 原单取消 → 追加单级联取消退款
p3 = make_parent(pay=True, accept=False)
a3 = append(p3)
call("POST", f"/orders/{a3['order_no']}/pay/mock", customer)
call("POST", f"/orders/{p3}/transition", customer,
     {"to_status": "cancelled", "reason": "不想要了"})
asyncio.run(sweep_once())
a3_now = call("GET", f"/orders/{a3['order_no']}", customer)
assert a3_now["status"] == "cancelled"
assert "原订单已取消" in a3_now["cancel_reason"]
assert a3_now["refund_cents"] == a3_now["total_cents"]
flows = call("GET", f"/orders/{a3['order_no']}/refunds", customer)
assert sum(f["amount_cents"] for f in flows) == a3_now["refund_cents"]
print("✓ 原单取消,追加单级联取消并全额退款")

for d in (main_dish, cola):
    call("PATCH", f"/merchants/me/dishes/{d['id']}", merchant, {"is_on_sale": False})
print("\n加菜(追加单)验证通过 🎉")
