"""M5 运营功能验证:起送价 / 打包费 / 商家满减 / 平台首单立减 / 佣金口径。

用独立新商家全程测试,不污染演示商家的运营设置。
首单立减需要服务端开启(FIRST_ORDER_DISCOUNT_CENTS>0),未开启时该段自动跳过。
在 server/ 目录下运行:python -m tests.e2e_operations
"""
import time

from tests.util import call, login

tag = str(int(time.time()))
admin = login("13800000000")
rider = login("13800000003")

# ---- 独立商家:注册 → 申请 → 过审 → 运营设置 ----
boss_phone = "137" + tag[-8:]
boss = call("POST", "/auth/register", body={
    "phone": boss_phone, "password": "123456", "name": "运营测试老板",
    "role": "merchant"})["token"]
shop = call("POST", "/merchants", boss, {
    "name": f"运营测试店-{tag}", "address": "测试路 5 号",
    "lat": 30.6612, "lng": 104.0823,
    "license_no": "JY99900011199999",
    "license_image_url": "/uploads/license-demo.jpg"})
call("POST", f"/admin/merchants/{shop['id']}/approve", admin)

shop = call("PATCH", "/merchants/me", boss, {
    "is_open": True,
    "min_order_cents": 2000,     # 起送 ¥20
    "packing_fee_cents": 200,    # 打包 ¥2
    "promo_rules": [
        {"threshold_cents": 3000, "off_cents": 500},   # 满30减5
        {"threshold_cents": 5000, "off_cents": 1000},  # 满50减10
    ],
})
assert shop["min_order_cents"] == 2000 and len(shop["promo_rules"]) == 2
print("✓ 商家运营设置:起送 ¥20 / 打包 ¥2 / 满30减5 / 满50减10")

err = call("PATCH", "/merchants/me", boss, {
    "promo_rules": [{"threshold_cents": 1000, "off_cents": 1000}]},
    expect_error=True)
assert err["_error"] == 422
print("✓ 倒贴规则被拒(减 ≥ 门槛,422)")

dish = call("POST", "/merchants/me/dishes", boss,
            {"name": f"运营菜-{tag}", "price_cents": 1500, "stock": 100})

# ---- 用独立新用户(顺便验证首单立减) ----
cust_phone = "136" + tag[-8:]
customer = call("POST", "/auth/register", body={
    "phone": cust_phone, "password": "123456", "name": "运营测试客",
    "role": "customer"})["token"]

def place(quantity, expect_error=False):
    return call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": quantity}],
        "address": "运营验证地址", "lat": 30.6612, "lng": 104.0823,
    }, expect_error=expect_error)

# 1 份 ¥15 < 起送 ¥20 → 拒
err = place(1, expect_error=True)
assert err["_error"] == 409 and "起送" in err["detail"]
print(f"✓ 未达起送价被拒:{err['detail']}")

# 3 份 ¥45:满30减5 生效;打包 ¥2;配送 ¥3
order = place(3)
assert order["food_cents"] == 4500
assert order["packing_fee_cents"] == 200
assert order["discount_cents"] == 500, order["promo_note"]
subsidy = order["subsidy_cents"]
expected_total = 4500 + 200 - 500 + order["delivery_fee_cents"] - subsidy
assert order["total_cents"] == expected_total, "实付恒等式"
print(f"✓ 满30减5 生效,实付 = 菜品+打包-满减+配送-补贴 = {expected_total} 分")

if subsidy > 0:
    print(f"✓ 首单立减 {subsidy} 分(平台承担):{order['promo_note']}")
else:
    print("- 首单立减未开启(FIRST_ORDER_DISCOUNT_CENTS=0),跳过补贴断言")

# 支付 → 佣金按实收口径(菜品+打包-满减)
no = order["order_no"]
paid = call("POST", f"/orders/{no}/pay/mock", customer)
gross = 4500 + 200 - 500
assert paid["commission_cents"] == int(gross * 0.05), \
    f"佣金 {paid['commission_cents']} ≠ 5% × 实收 {gross}"
print(f"✓ 佣金按实收口径:5% × {gross} = {paid['commission_cents']} 分(商家让利平台跟着少收)")

# 第二单:不再有首单立减
order2 = place(2)  # ¥30,满30减5
assert order2["subsidy_cents"] == 0, "首单立减只能享受一次"
assert order2["discount_cents"] == 500
call("POST", f"/orders/{order2['order_no']}/pay/mock", customer)
print("✓ 第二单无首单立减(只减一次),满减照常")

# ---- 跑完整单到结算,验证账本与审计 ----
call("POST", f"/orders/{no}/transition", boss, {"to_status": "accepted"})
call("POST", f"/orders/{no}/transition", boss, {"to_status": "ready"})
call("POST", "/riders/online", rider, {"is_online": True})
call("POST", "/riders/location", rider, {"lat": 30.6605, "lng": 104.0815})
call("POST", f"/riders/grab/{no}", rider)
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

problems = call("POST", "/admin/audit/run", admin)["detail"]
mine = [p for p in problems if no in p.get("detail", "")]
assert not mine, f"审计发现本单问题:{mine}"
bad = {p["check"] for p in problems} & {"order_total_mismatch",
                                        "merchant_earning_mismatch",
                                        "global_identity_mismatch"}
assert not bad, f"审计恒等式不平:{problems}"
print("✓ 完成结算后审计全绿(新口径恒等式全平)")

print("\nM5 运营功能(起送/打包/满减/首单立减/佣金口径)验证通过 🎉")
