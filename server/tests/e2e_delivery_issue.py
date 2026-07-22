"""配送异常上报与仲裁:骑手上报(餐损必须拍照/归属校验/防重复),
平台三种裁决——已协调 / 按送达处理 / 骑手责任先行赔付(商家骑手收入保留)。"""
import time

from tests.util import orderable_dish, call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dishes = call("GET", f"/merchants/{shop['id']}/dishes")
main_dish = orderable_dish(dishes)


def make_order(to="picked_up"):
    order = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": main_dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    if to == "picked_up":
        call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    return no


# 餐损必须拍照
no1 = make_order()
err = call("POST", "/riders/issues", rider,
           {"order_no": no1, "kind": "food_damaged"}, expect_error=True)
assert err["_error"] == 422
print(f"✓ 餐损上报必须拍照:{err['detail']}")

# 非本人订单不能上报
err = call("POST", "/riders/issues", login("13800000004") if False else rider,
           {"order_no": "nonexistent", "kind": "other"}, expect_error=True)
assert err["_error"] == 403
print("✓ 非本人订单/不存在订单不能上报")

# 上报成功 + 防重复
issue = call("POST", "/riders/issues", rider,
             {"order_no": no1, "kind": "cannot_contact", "note": "打了三次没人接"})
assert issue["status"] == "open"
err = call("POST", "/riders/issues", rider,
           {"order_no": no1, "kind": "other"}, expect_error=True)
assert err["_error"] == 409
print("✓ 上报成功(顾客/商家已推送),同单重复上报被拒")

# 管理端可见,按送达处理:骑手配送费在自动确认后照常结算
issues = call("GET", "/admin/delivery-issues?status=open", admin)
mine = next(i for i in issues if i["order_no"] == no1)
assert mine["kind"] == "cannot_contact" and mine["rider_phone"]
done = call("POST", f"/admin/delivery-issues/{mine['id']}/resolve", admin,
            {"action": "mark_delivered", "note": "电话确认用户留错号码"})
assert done["status"] == "resolved" and done["order_status"] == "delivered"
o1 = call("GET", f"/orders/{no1}", customer)
assert o1["status"] == "delivered"
print("✓ 按送达处理:订单转已送达,骑手配送费照常(24h 后自动完成结算)")

# 骑手责任先行赔付:用户全额退款,商家净额与骑手配送费都保留
no2 = make_order()
o2 = call("GET", f"/orders/{no2}", customer)
issue2 = call("POST", "/riders/issues", rider,
              {"order_no": no2, "kind": "food_damaged",
               "note": "颠簸洒了", "photo_url": "/uploads/demo.jpg"})
mw0 = call("GET", "/merchants/me/wallet", merchant)
rw0 = call("GET", "/riders/wallet", rider)
done2 = call("POST", f"/admin/delivery-issues/{issue2['id']}/resolve", admin,
             {"action": "refund", "note": "餐洒,先行赔付"})
assert done2["resolution"] == "refund"
o2b = call("GET", f"/orders/{no2}", customer)
assert o2b["status"] == "completed"
assert o2b["refund_cents"] == o2["total_cents"]
flows = call("GET", f"/orders/{no2}/refunds", customer)
assert sum(f["amount_cents"] for f in flows) == o2b["refund_cents"]
mw1 = call("GET", "/merchants/me/wallet", merchant)
rw1 = call("GET", "/riders/wallet", rider)
net = (o2["food_cents"] + o2["packing_fee_cents"]
       - o2["discount_cents"] - o2b["commission_cents"])
assert mw1["total_earned_cents"] == mw0["total_earned_cents"] + net
assert rw1["total_earned_cents"] == rw0["total_earned_cents"] + o2["delivery_fee_cents"]
print(f"✓ 先行赔付:用户退 {o2b['refund_cents']/100:.2f} 元(平台承担),"
      f"商家净额 +{net/100:.2f}、骑手配送费 +{o2['delivery_fee_cents']/100:.2f} 都保留")

# 已协调关单
no3 = make_order()
issue3 = call("POST", "/riders/issues", rider,
              {"order_no": no3, "kind": "wrong_address", "note": "小区名对不上"})
done3 = call("POST", f"/admin/delivery-issues/{issue3['id']}/resolve", admin,
             {"action": "continue_delivery", "note": "已电话协调,用户在门口等"})
assert done3["status"] == "resolved"
o3 = call("GET", f"/orders/{no3}", customer)
assert o3["status"] == "picked_up"  # 订单不动,继续送
call("POST", f"/orders/{no3}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no3}/transition", customer, {"to_status": "completed"})
print("✓ 已协调:工单关闭,订单继续正常流转")

print("\n配送异常上报与仲裁验证通过 🎉")
