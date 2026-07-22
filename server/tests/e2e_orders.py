"""Super-Z 全链路验证:用户下单 -> 支付 -> 商家接单/出餐 -> 骑手抢单/取餐/送达 -> 用户确认"""
import time

from tests.util import call, login

customer, merchant, rider = login("13800000001"), login("13800000002"), login("13800000003")
print("✓ 三个角色登录成功")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop0 = next(m for m in shops if m["name"] == "张记面馆")
assert shop0["monthly_sales"] > 0  # 列表现在带真实月售
print(f"✓ PostGIS 附近商家查询:找到「{shop0['name']}」(抽成 {float(shop0['commission_rate'])*100:.0f}%,月售 {shop0['monthly_sales']})")

dishes = call("GET", f"/merchants/{shop0['id']}/dishes")
print(f"✓ 菜单 {len(dishes)} 道菜:" + "、".join(d["name"] for d in dishes))

# 库存断言必须用测试专属菜品:公共菜品会被后台清扫任务回补历史订单库存,数字不可预测
tag = str(int(time.time()))
dish_a = call("POST", "/merchants/me/dishes", merchant,
              {"name": f"测试面-{tag}", "price_cents": 1800, "stock": 100})
dish_b = call("POST", "/merchants/me/dishes", merchant,
              {"name": f"测试豆浆-{tag}", "price_cents": 600, "stock": 200})

order = call("POST", "/orders", customer, {
    "merchant_id": shop0["id"],
    "items": [{"dish_id": dish_a["id"], "quantity": 2}, {"dish_id": dish_b["id"], "quantity": 1}],
    "address": "春熙路步行街 100 号 2 单元 501", "lat": 30.6612, "lng": 104.0823, "remark": "不要香菜",
})
no = order["order_no"]
print(f"✓ 下单成功 {no},合计 ¥{order['total_cents']/100}(含配送费 ¥{order['delivery_fee_cents']/100})")

paid = call("POST", f"/orders/{no}/pay/mock", customer)
assert paid["status"] == "paid" and paid["commission_cents"] == int(paid["food_cents"] * 0.05)
print(f"✓ 支付成功,平台抽成 ¥{paid['commission_cents']/100}(5%)")

paid2 = call("POST", f"/orders/{no}/pay/mock", customer)
assert paid2["status"] == "paid" and paid2["commission_cents"] == paid["commission_cents"]
print("✓ 重复支付回调幂等,未重复计费")

err = call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"}, expect_error=True)
assert err["_error"] in (403, 409), err
print(f"✓ 状态机拦截非法操作(骑手在商家接单前取餐):{err['detail']}")

call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
print("✓ 商家接单 → 出餐完成")

# 骑手视角:可抢订单必须带取餐点(商家)信息,导航全靠它
call("POST", "/riders/online", rider, {"is_online": True})
call("POST", "/riders/location", rider, {"lat": 30.6605, "lng": 104.0815})
pool = call("GET", "/riders/available-orders", rider)
assert any(o["order_no"] == no for o in pool)
pool_order = next(o for o in pool if o["order_no"] == no)
assert pool_order["merchant_name"] == "张记面馆" and pool_order["merchant_lat"], pool_order
grabbed = call("POST", f"/riders/grab/{no}", rider)
assert grabbed["merchant_lat"] and grabbed["merchant_address"], grabbed
print(f"✓ 骑手上线、抢单成功,订单带取餐点:{grabbed['merchant_name']} ({grabbed['merchant_lat']}, {grabbed['merchant_lng']})")

err = call("POST", f"/riders/grab/{no}", rider, expect_error=True)
assert err["_error"] == 409
print(f"✓ 重复抢单被拒:{err['detail']}")

loc = call("GET", f"/orders/{no}/rider-location", customer)
assert loc["lat"] == 30.6605
print(f"✓ 用户查骑手位置(Redis):({loc['lat']}, {loc['lng']})")

call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
final = call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
assert final["status"] == "completed"
print("✓ 取餐 → 送达 → 用户确认收货,订单完成")

menu = call("GET", f"/merchants/{shop0['id']}/dishes")
a_now = next(d for d in menu if d["id"] == dish_a["id"])
assert a_now["stock"] == 98, a_now
print(f"✓ 库存正确扣减:{dish_a['name']} 100 → {a_now['stock']}")

# 拒单流程:必须带原因,原因回显给用户,库存回补
order2 = call("POST", "/orders", customer, {
    "merchant_id": shop0["id"],
    "items": [{"dish_id": dish_a["id"], "quantity": 1}],
    "address": "测试地址", "lat": 30.6612, "lng": 104.0823,
})
no2 = order2["order_no"]
call("POST", f"/orders/{no2}/pay/mock", customer)
err = call("POST", f"/orders/{no2}/transition", merchant,
           {"to_status": "cancelled", "reason": ""}, expect_error=True)
assert err["_error"] == 422
print(f"✓ 商家拒单不填原因被拒:{err['detail']}")

rejected = call("POST", f"/orders/{no2}/transition", merchant,
                {"to_status": "cancelled", "reason": "牛肉卖完了,抱歉"})
assert rejected["status"] == "cancelled" and rejected["cancel_reason"] == "牛肉卖完了,抱歉"
seen = call("GET", f"/orders/{no2}", customer)
assert seen["cancel_reason"] == "牛肉卖完了,抱歉"
menu2 = call("GET", f"/merchants/{shop0['id']}/dishes")
assert next(d for d in menu2 if d["id"] == dish_a["id"])["stock"] == 98
print("✓ 拒单带原因,用户可见,库存已回补(97→98)")

# 拒掉的是已支付订单:必须全额退款,refund_cents 与退款流水一致(审计规则 5 口径)
assert rejected["refund_cents"] == rejected["total_cents"] > 0, rejected
assert "取消退款" in rejected["refund_note"]
flows = call("GET", f"/orders/{no2}/refunds", customer)
assert sum(f["amount_cents"] for f in flows) == rejected["refund_cents"], flows
print(f"✓ 拒单全额退款 ¥{rejected['refund_cents']/100},退款流水与 refund_cents 一致")

# 用户取消已支付订单同样全额退款
order3 = call("POST", "/orders", customer, {
    "merchant_id": shop0["id"],
    "items": [{"dish_id": dish_a["id"], "quantity": 1}],
    "address": "测试地址", "lat": 30.6612, "lng": 104.0823,
})
no3 = order3["order_no"]
call("POST", f"/orders/{no3}/pay/mock", customer)
cancelled = call("POST", f"/orders/{no3}/transition", customer,
                 {"to_status": "cancelled", "reason": "点错了"})
assert cancelled["status"] == "cancelled"
assert cancelled["refund_cents"] == cancelled["total_cents"] > 0, cancelled
flows = call("GET", f"/orders/{no3}/refunds", customer)
assert sum(f["amount_cents"] for f in flows) == cancelled["refund_cents"], flows
print(f"✓ 用户取消已支付订单:全额退款 ¥{cancelled['refund_cents']/100},流水一致")

# 清场:测试菜品下架,不污染菜单
for dish in (dish_a, dish_b):
    call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("✓ 测试菜品已下架(菜品编辑接口可用)")

print("\n全链路验证通过 🎉")
