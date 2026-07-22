"""商家自建店铺券(清单#60):发券/领取/下单抵扣走 discount 商家承担、佣金按券后实收、
与满减取最优不叠加、超限领拒、跨店拒、审计口径与满减一致。"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
addr = {"address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "测试", "contact_phone": "13800000001"}
ts = int(time.time())
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"店铺券测试菜-{ts}", "price_cents": 5000, "stock": 200})

# 清掉满减,避免干扰
call("PATCH", "/merchants/me", merchant, {"promo_rules": []})

# 商家建店铺券:满 40 减 8,限量 3,每人限领 1
batch = call("POST", "/merchants/me/coupon-batches", merchant, {
    "name": f"满40减8-{ts}", "threshold_cents": 4000, "off_cents": 800,
    "total": 3, "per_user_limit": 1, "valid_days": 7})
assert batch["off_cents"] == 800 and batch["threshold_cents"] == 4000
# 倒贴校验
err = call("POST", "/merchants/me/coupon-batches", merchant, {
    "name": "倒贴", "threshold_cents": 1000, "off_cents": 1000, "total": 1},
    expect_error=True)
assert err["_error"] == 422
print("✓ 商家建店铺券(满40减8),倒贴被拒")

# 用户可领列表
avail = call("GET", f"/merchants/{shop['id']}/coupons", customer)
mine_batch = next(b for b in avail if b["batch_id"] == batch["id"])
assert mine_batch["can_claim"] and mine_batch["remaining"] == 3

# 领取
claim = call("POST", f"/merchants/{shop['id']}/coupons/{batch['id']}/claim",
             customer)
cid = claim["coupon_id"]
# 每人限领 1:再领被拒
err = call("POST", f"/merchants/{shop['id']}/coupons/{batch['id']}/claim",
           customer, expect_error=True)
assert err["_error"] == 409
print("✓ 领取成功,每人限领 1 张再领被拒")

# 下单用券:菜品 50 元,满 40 减 8 → discount=800(商家承担),佣金按券后实收
o = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "coupon_id": cid, **addr})
assert o["discount_cents"] == 800, f"店铺券应走 discount 口径,实际 {o['discount_cents']}"
assert o["subsidy_cents"] == 0, "店铺券是商家承担,不进平台补贴"
assert "店铺券" in o["promo_note"]
paid = call("POST", f"/orders/{o['order_no']}/pay/mock", customer)
# 佣金 = (food+packing-discount) * 5% = (5000-800)*0.05 = 210(支付时才算)
assert paid["commission_cents"] == 210, \
    f"佣金应按券后实收,实际 {paid['commission_cents']}"
print(f"✓ 下单抵扣走 discount(商家承担),佣金按券后实收 = {paid['commission_cents']} 分")

# 用过的券不能再用
o2 = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "coupon_id": cid, **addr}, expect_error=True)
assert o2["_error"] == 409
print("✓ 已用的券不可再用")

# 跨店拒:另一家店用这张券
others = [m for m in shops if m["id"] != shop["id"]]
if others:
    err = call("POST", "/orders", customer, {
        "merchant_id": others[0]["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "coupon_id": cid, **addr}, expect_error=True)
    assert err["_error"] in (409, 422)
    print("✓ 店铺券跨店使用被拒")

# 与满减取最优:配满40减20(优于券的减8),用券下单应被拒(满减更优)
call("PATCH", "/merchants/me", merchant,
     {"promo_rules": [{"threshold_cents": 4000, "off_cents": 2000}]})
# 换新用户领并测取最优(演示用户已领满限额)
from tests.util import register_fresh_customer
fresh = register_fresh_customer()
claim3 = call("POST", f"/merchants/{shop['id']}/coupons/{batch['id']}/claim",
              fresh)
err = call("POST", "/orders", fresh, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "coupon_id": claim3["coupon_id"], **addr}, expect_error=True)
assert err["_error"] == 409 and "满减" in err["detail"], err
print("✓ 满减(减20)优于店铺券(减8)时,用券被拒(二选一取最优,不叠加)")

# 不用券时满减正常走
o3 = call("POST", "/orders", fresh, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}], **addr})
assert o3["discount_cents"] == 2000
print("✓ 不用券时满减(减20)正常")

# 收尾
call("PATCH", "/merchants/me", merchant, {"promo_rules": []})
call("POST", f"/merchants/me/coupon-batches/{batch['id']}/toggle", merchant)
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\n商家店铺券验证通过 🎉")
