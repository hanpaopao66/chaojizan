"""严格模式:未绑定中间号时不向商家/骑手下发真号。

需对着 PRIVACY_PHONE_STRICT=true 启动的服务实例跑
(SUPERZ_API 指向该实例;runner 见 e2e 脚本编排)。
"""
import time

from tests.util import call, login

REAL = "13800000001"
MASKED = "138****0001"

customer = login(REAL)
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"严格脱敏-{int(time.time())}", "price_cents": 2000,
             "stock": 50})

order = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
    "contact_name": "张三", "contact_phone": REAL,
})
no = order["order_no"]
assert order["contact_phone"] == REAL, "用户本人不受严格模式影响"

m_view = call("GET", f"/orders/{no}", merchant)
assert m_view["contact_phone"] == MASKED
assert m_view["privacy_phone"] == "", \
    f"严格模式不得下发真号,实际 {m_view['privacy_phone']!r}"
print("✓ 严格模式:商家打码且 privacy_phone 为空(拨打按钮隐藏)")

call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
     {"is_on_sale": False})
print("\n电话脱敏(严格模式)验证通过 🎉")
