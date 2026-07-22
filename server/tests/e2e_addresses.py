"""地址簿 + POI 提示 + 订单联系人透传验证"""
from urllib.parse import quote

from tests.util import orderable_dish, call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

# 清掉历史地址,保证可重复运行
for addr in call("GET", "/addresses", customer):
    call("DELETE", f"/addresses/{addr['id']}", customer)

tips = call("GET", f"/geo/tips?keywords={quote('春熙路')}", customer)
assert len(tips) >= 1 and tips[0]["lat"] and tips[0]["name"]
print(f"✓ POI 输入提示返回 {len(tips)} 条(演示模式):{tips[0]['name']}")

err = call("POST", "/addresses", customer, {
    "contact_name": "小明", "contact_phone": "123", "address": tips[0]["name"],
    "lat": tips[0]["lat"], "lng": tips[0]["lng"],
}, expect_error=True)
assert err["_error"] == 422
print("✓ 非法手机号被拒(422)")

a1 = call("POST", "/addresses", customer, {
    "contact_name": "小明", "contact_phone": "13511112222",
    "address": tips[0]["name"], "detail": "2 单元 501",
    "lat": tips[0]["lat"], "lng": tips[0]["lng"],
})
assert a1["is_default"] is True
print("✓ 第一个地址自动设为默认")

a2 = call("POST", "/addresses", customer, {
    "contact_name": "小红", "contact_phone": "13533334444",
    "address": "公司前台", "lat": 30.662, "lng": 104.083, "is_default": True,
})
addresses = call("GET", "/addresses", customer)
defaults = [a for a in addresses if a["is_default"]]
assert len(addresses) == 2 and len(defaults) == 1 and defaults[0]["id"] == a2["id"]
print("✓ 新默认地址生效,旧默认自动取消,默认排在最前")

err = call("GET", "/addresses", merchant, expect_error=True)
assert err["_error"] == 403
print("✓ 非用户角色无地址簿权限(403)")

# 下单带联系人,骑手视角能看到
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop0 = next(m for m in shops if m["name"] == "张记面馆")
dishes = call("GET", f"/merchants/{shop0['id']}/dishes")
main_dish = orderable_dish(dishes)
order = call("POST", "/orders", customer, {
    "merchant_id": shop0["id"],
    "items": [{"dish_id": main_dish["id"], "quantity": 1}],
    "address": f"{a1['address']} {a1['detail']}", "lat": a1["lat"], "lng": a1["lng"],
    "contact_name": a1["contact_name"], "contact_phone": a1["contact_phone"],
})
no = order["order_no"]
call("POST", f"/orders/{no}/pay/mock", customer)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
grabbed = call("POST", f"/riders/grab/{no}", rider)
# 电话脱敏(清单#13):骑手视角 contact_phone 打码,可拨号码走 privacy_phone
assert grabbed["contact_name"] == "小明" and grabbed["contact_phone"] == "135****2222"
assert grabbed["privacy_phone"] == "13511112222"  # 过渡期(未接 AXB)可拨真号
print("✓ 骑手抢单后能看到联系人和电话")

# 清场:把订单走完,避免影响后续测试
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

print("\n地址簿验证通过 🎉")
