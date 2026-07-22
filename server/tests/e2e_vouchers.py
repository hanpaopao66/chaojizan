"""团购券全链路验证:发券 → 抢购 → 支付 → 核销分账 → 退款 → 审计。

在 server/ 目录下运行:python -m tests.e2e_vouchers
"""
import time

from tests.util import call, login

tag = str(int(time.time()))
admin = login("13800000000")

# ---- 商家发券 ----
boss = call("POST", "/auth/register", body={
    "phone": "131" + tag[-8:], "password": "123456", "name": "团购老板",
    "role": "merchant"})["token"]
shop = call("POST", "/merchants", boss, {
    "name": f"团购测试店-{tag}", "address": "测试路 7 号",
    "lat": 30.6612, "lng": 104.0823,
    "license_no": "JY99900011177777",
    "license_image_url": "/uploads/license-demo.jpg"})
call("POST", f"/admin/merchants/{shop['id']}/approve", admin)

err = call("POST", "/vouchers", boss, {
    "title": "倒贴券", "sell_price_cents": 5000, "face_value_cents": 4000,
    "total_count": 10}, expect_error=True)
assert err["_error"] == 422
print("✓ 售价 ≥ 面值被拒(用户没有理由买)")

deal = call("POST", "/vouchers", boss, {
    "title": "50元代金券", "sell_price_cents": 4500,
    "face_value_cents": 5000, "total_count": 2, "per_user_limit": 2})
print(f"✓ 发券:{deal['title']},¥45 购 ¥50,共 2 张")

deals = call("GET", "/vouchers")
assert any(d["id"] == deal["id"] and d["merchant_name"] for d in deals)
print("✓ 在售列表可见(带商家名)")

# ---- 用户抢购 ----
customer = call("POST", "/auth/register", body={
    "phone": "130" + tag[-8:], "password": "123456", "name": "团购客",
    "role": "customer"})["token"]

t1 = call("POST", f"/vouchers/{deal['id']}/purchase", customer)
t1 = call("POST", f"/vouchers/purchases/{t1['purchase_no']}/pay/mock", customer)
assert t1["status"] == "paid" and len(t1["code"]) == 12 and t1["expires_at"]
print(f"✓ 抢购+支付成功,券码 {t1['code']},90 天有效")

t2 = call("POST", f"/vouchers/{deal['id']}/purchase", customer)
call("POST", f"/vouchers/purchases/{t2['purchase_no']}/pay/mock", customer)
err = call("POST", f"/vouchers/{deal['id']}/purchase", customer,
           expect_error=True)
assert err["_error"] == 409  # 限购 2 张(且库存也刚好售罄)
print(f"✓ 第三张被拒(限购/售罄):{err['detail']}")

# ---- 核销分账 ----
redeemed = call("POST", "/vouchers/redeem", boss, {"code": t1["code"]})
assert redeemed["status"] == "redeemed"
assert redeemed["commission_cents"] == int(4500 * 0.02)
assert redeemed["net_cents"] == 4500 - redeemed["commission_cents"]
print(f"✓ 核销成功:商家应收 {redeemed['net_cents']} 分 = 售价 4500 - 2% 服务费 {redeemed['commission_cents']}")

err = call("POST", "/vouchers/redeem", boss, {"code": t1["code"]},
           expect_error=True)
assert err["_error"] == 409 and "重复" in err["detail"]
print("✓ 重复核销被拒")

other_boss = call("POST", "/auth/register", body={
    "phone": "129" + tag[-8:], "password": "123456", "name": "别家老板",
    "role": "merchant"})["token"]
other_shop = call("POST", "/merchants", other_boss, {
    "name": f"别家店-{tag}", "address": "x", "lat": 30.66, "lng": 104.08,
    "license_no": "JY2", "license_image_url": "/uploads/x.jpg"})
call("POST", f"/admin/merchants/{other_shop['id']}/approve", admin)
err = call("POST", "/vouchers/redeem", other_boss, {"code": t2["code"]},
           expect_error=True)
assert err["_error"] == 404
print("✓ 别家店核销不了本店的券")

# ---- 退款(未使用随时退) ----
refunded = call("POST", f"/vouchers/purchases/{t2['purchase_no']}/refund",
                customer)
assert refunded["status"] == "refunded"
deals = call("GET", "/vouchers")
mine = next(d for d in deals if d["id"] == deal["id"])
assert mine["total_count"] == 1, "退款后库存应回补"
print("✓ 未使用的券全额退款,库存回补")

# ---- 券包与审计 ----
wallet = call("GET", "/vouchers/purchases/mine", customer)
statuses = sorted(t["status"] for t in wallet)
assert statuses == ["redeemed", "refunded"]
print("✓ 券包状态正确(1 张已使用 + 1 张已退款)")

problems = call("POST", "/admin/audit/run", admin)["detail"]
assert not any(p["check"] == "voucher_split_mismatch" for p in problems), problems
print("✓ 审计:团购分账恒等式全平(净额+服务费=售价)")

print("\n团购券全链路(发券/抢购/核销/退款/审计)验证通过 🎉")
