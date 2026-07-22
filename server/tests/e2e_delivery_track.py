"""实时配送轨迹(清单#57):配送中可取骑手点、即将送达触发去重、终结后停止暴露、归属校验。"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")
other = login("13800000004")  # 无关用户(演示商家账号,借来测越权)

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
DROP = (30.6612, 104.0823)  # 收货点
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"轨迹测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})

o = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "address": "测试地址1号", "lat": DROP[0], "lng": DROP[1],
    "contact_name": "测试", "contact_phone": "13800000001"})
no = o["order_no"]

# 没骑手时取位置 404
err = call("GET", f"/orders/{no}/rider-location", customer, expect_error=True)
assert err["_error"] == 404
call("POST", f"/orders/{no}/pay/mock", customer)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
call("POST", f"/riders/grab/{no}", rider)
print("✓ 无骑手时位置 404;骑手接单后进入可追踪")

# 骑手上报位置(离收货点很远)→ 用户能取到点
FAR = {"lat": 30.70, "lng": 104.12}
r = call("POST", "/riders/location", rider, FAR)
assert r["ok"] and r["arrived"] == [], "远处不触发即将送达"
loc = call("GET", f"/orders/{no}/rider-location", customer)
assert abs(loc["lat"] - FAR["lat"]) < 1e-6 and loc["updated_at"]
print("✓ 配送中可取骑手实时点;远处不触发即将送达")

# 越权:无关用户看不到骑手位置
err = call("GET", f"/orders/{no}/rider-location", other, expect_error=True)
assert err["_error"] == 403
print("✓ 归属校验:无关用户 403")

# 取餐 → 骑手抵近(<500m)→ 触发一次即将送达,再上报不重复
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
NEAR = {"lat": DROP[0] + 0.001, "lng": DROP[1]}  # ≈111m
r1 = call("POST", "/riders/location", rider, NEAR)
assert no in r1["arrived"], f"抵近应触发即将送达,实际 {r1['arrived']}"
r2 = call("POST", "/riders/location", rider, NEAR)
assert no not in r2["arrived"], "即将送达一单只推一次(去重)"
print("✓ <500m 触发一次即将送达,重复上报不再推(去重)")

# 送达完成 → 位置接口不再暴露实时点(隐私最小化)
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
call("POST", "/riders/location", rider, NEAR)  # 骑手仍在上报
loc = call("GET", f"/orders/{no}/rider-location", customer)
assert loc["lat"] is None and loc["lng"] is None, "订单终结后不该暴露实时点"
print("✓ 订单完成后位置接口不再暴露实时点")

call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\n实时配送轨迹验证通过 🎉")
