"""反作弊闭环(清单#63):分级处置(limit软限领券补贴、下单不拦)、回滚恢复、刷评标记不删。"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from tests.util import call, login, register_fresh_customer

admin = login("13800000000")
merchant = login("13800000002")
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
addr = {"address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "测试", "contact_phone": "13800000001"}
ts = int(time.time())
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"风控测试菜-{ts}", "price_cents": 3000, "stock": 200})

# 店铺券(用于验证 limit 软限领券)
batch = call("POST", "/merchants/me/coupon-batches", merchant, {
    "name": f"风控券-{ts}", "threshold_cents": 0, "off_cents": 500,
    "total": 100, "per_user_limit": 5, "valid_days": 7})

# 全新用户(拿到 user_id)
fresh = register_fresh_customer()
me = call("GET", "/auth/me", fresh)
uid = me["id"]
assert me["risk_level"] == ""

# 正常态:能领券
call("POST", f"/merchants/{shop['id']}/coupons/{batch['id']}/claim", fresh)
print("✓ 正常用户能领券")

# 升级到 limit:领券被软限(可见提示),但下单照常
call("POST", f"/admin/users/{uid}/risk-level", admin,
     {"level": "limit", "reason": "疑似异常下单,已限制营销权益"})
me = call("GET", "/auth/me", fresh)
assert me["risk_level"] == "limit" and "限制" in me["risk_note"]
err = call("POST", f"/merchants/{shop['id']}/coupons/{batch['id']}/claim",
           fresh, expect_error=True)
assert err["_error"] == 403 and "申诉" in err["detail"]
# 下单不拦
o = call("POST", "/orders", fresh, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}], **addr})
assert o["order_no"]
# 平台补贴不给(首单立减被暂停)
assert o["subsidy_cents"] == 0, "limit 用户不应获得平台补贴"
print("✓ limit:领券403(带申诉提示)、平台补贴暂停,但下单正常")

# 回滚:解除限制后恢复领券
call("POST", f"/admin/users/{uid}/risk-level", admin, {"level": ""})
me = call("GET", "/auth/me", fresh)
assert me["risk_level"] == "" and me["risk_note"] == ""
call("POST", f"/merchants/{shop['id']}/coupons/{batch['id']}/claim", fresh)
print("✓ 回滚后恢复领券")

# 非法 level 422
err = call("POST", f"/admin/users/{uid}/risk-level", admin,
           {"level": "ban"}, expect_error=True)
assert err["_error"] == 422
print("✓ 非法处置级别 422")

# ---- 刷评识别:下单到评价间隔异常 → 标记但不删 ----
buyer = register_fresh_customer()
o2 = call("POST", "/orders", buyer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "contact_name": "测试", "contact_phone": "13800000001", **addr})
no2 = o2["order_no"]
call("POST", f"/orders/{no2}/pay/mock", buyer)
call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "ready"})
rider = login("13800000003")
call("POST", f"/riders/grab/{no2}", rider)
for st in ("picked_up", "delivered"):
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": st})
call("POST", f"/orders/{no2}/transition", buyer, {"to_status": "completed"})
# 刚下单几秒就评价 → 间隔异常,标记 flagged
rv = call("POST", f"/orders/{no2}/review", buyer,
          {"merchant_rating": 5, "comment": "好吃"})
# 评价仍成功可见(不自动删/隐藏)
got = call("GET", f"/orders/{no2}/review", buyer)
assert got["id"] == rv["id"]
flagged = call("GET", "/admin/reviews/flagged", admin)
assert any(f["id"] == rv["id"] and f["flag_reason"] for f in flagged), \
    "疑似刷评应进待复核列表"
print("✓ 刷评识别:标记待复核但评价不自动删/隐藏")

call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
call("POST", f"/merchants/me/coupon-batches/{batch['id']}/toggle", merchant)
print("\n反作弊闭环验证通过 🎉")
