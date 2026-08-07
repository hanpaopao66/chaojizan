"""电话脱敏全链路:商家/骑手看打码号、拨打走 privacy_phone;用户本人看真号;
小票不落真号;严格模式(PRIVACY_PHONE_STRICT=true 的服务实例)连真号都不下发。

严格模式断言由 e2e_privacy_phone_strict 在独立实例上跑;本文件测默认(过渡期)行为。
"""
import time
from types import SimpleNamespace
from datetime import datetime, timezone

from tests.util import demo_shop, call, fake_order, login

REAL = "13800000001"
MASKED = "138****0001"

# ---- 纯函数层:打码与小票 ----
from app.services.privacy_phone import mask_phone

assert mask_phone(REAL) == MASKED
assert mask_phone("123") == "****"
assert mask_phone("") == ""
print("✓ mask_phone:标准打码,短号全遮,空号不炸")

from app.services.cloud_print import build_ticket

# 共用 util.fake_order:三个用例各写一份的话,订单加个字段就断一片
fake = fake_order(order_no="x" * 20, contact_phone=REAL)
ticket = build_ticket(fake, "测试店")
assert REAL not in ticket and MASKED in ticket, "小票不得出现真号"
fake.privacy_phone = "17000000000"  # 绑定了 X 号则印 X 号
assert "17000000000" in build_ticket(fake, "测试店")
print("✓ 小票:未绑定印打码号,绑定后印 X 号,真号永不落纸")

# ---- 接口层(默认过渡模式) ----
customer = login(REAL)
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = demo_shop()
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"脱敏测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})

order = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
    "contact_name": "张三", "contact_phone": REAL,
})
no = order["order_no"]
assert order["contact_phone"] == REAL, "用户本人下单响应看真号"
call("POST", f"/orders/{no}/pay/mock", customer)
mine = call("GET", f"/orders/{no}", customer)
assert mine["contact_phone"] == REAL
print("✓ 用户本人:下单/详情都是真号")

m_view = call("GET", f"/orders/{no}", merchant)
assert m_view["contact_phone"] == MASKED, f"商家应看打码,实际 {m_view['contact_phone']}"
assert m_view["privacy_phone"] == REAL, "过渡期商家可拨真号(privacy_phone)"
m_list = call("GET", "/orders", merchant)
row = next(o for o in m_list if o["order_no"] == no)
assert row["contact_phone"] == MASKED
print("✓ 商家:详情与列表 contact_phone 全打码,拨打走 privacy_phone")

call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
pool = call("GET", "/riders/available-orders", rider)
p_row = next(o for o in pool if o["order_no"] == no)
assert p_row["contact_phone"] == MASKED, "抢单池也不给真号"
grabbed = call("POST", f"/riders/grab/{no}", rider)
assert grabbed["contact_phone"] == MASKED
assert grabbed["privacy_phone"] == REAL
r_view = call("GET", f"/orders/{no}", rider)
assert r_view["contact_phone"] == MASKED
print("✓ 骑手:抢单池/抢单响应/详情全打码")

# 收尾:取消订单退款,下架测试菜
call("POST", f"/orders/{no}/transition", merchant,
     {"to_status": "cancelled", "reason": "测试收尾"})
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
     {"is_on_sale": False})
print("\n电话脱敏(默认过渡模式)验证通过 🎉")
