"""客服自助化(清单#64):未接单自助退不建工单、已出餐转人工带上下文、超时未出餐自助退、FAQ 直达。"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
addr = {"address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "测试", "contact_phone": "13800000001"}
ts = int(time.time())
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"自助退测试菜-{ts}", "price_cents": 3000, "stock": 100})


def new_paid():
    o = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}], **addr})
    call("POST", f"/orders/{o['order_no']}/pay/mock", customer)
    return o["order_no"]


def backdate_accept(order_no, minutes):
    async def _run():
        from datetime import datetime, timezone, timedelta
        from sqlalchemy import update
        from app.db import SessionLocal, engine
        from app.models import Order
        async with SessionLocal() as db:
            await db.execute(update(Order).where(Order.order_no == order_no)
                             .values(accepted_at=datetime.now(timezone.utc)
                                     - timedelta(minutes=minutes)))
            await db.commit()
        await engine.dispose()
    asyncio.run(_run())


# ---- FAQ 分流 ----
faq = call("GET", "/support/faq")["faq"]
assert len(faq) >= 3 and all("action" in f for f in faq)
print(f"✓ FAQ 自助分流返回 {len(faq)} 条,含直达 action")

# ---- 未接单(PAID)自助退款成功,不建工单 ----
no = new_paid()
chk = call("GET", f"/orders/{no}/self-refund/check", customer)
assert chk["eligible"] is True and "未接单" in chk["reason"]
tickets_before = len(call("GET", "/tickets/mine", customer))
done = call("POST", f"/orders/{no}/self-refund", customer)
assert done["status"] == "cancelled" and done["refund_cents"] == done["total_cents"]
tickets_after = len(call("GET", "/tickets/mine", customer))
assert tickets_after == tickets_before, "自助退款不应生成工单"
print("✓ 未接单自助退款成功且全额退,不建工单")

# ---- 已出餐/配送中 → 转人工带上下文 ----
no2 = new_paid()
call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "ready"})
chk = call("GET", f"/orders/{no2}/self-refund/check", customer)
assert chk["eligible"] is False and chk["suggest_ticket"] is True
assert "订单#" in chk["ticket_context"]
err = call("POST", f"/orders/{no2}/self-refund", customer, expect_error=True)
assert err["_error"] == 409
print("✓ 已出餐自助退被拒,转人工带工单上下文")
# 收尾 no2:骑手送达完成
call("POST", f"/riders/grab/{no2}", rider)
for st in ("picked_up", "delivered"):
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": st})
call("POST", f"/orders/{no2}/transition", customer, {"to_status": "completed"})

# ---- 商家超时未出餐(ACCEPTED 超 promise×1.5)→ 自助退成功 ----
call("PATCH", "/merchants/me", merchant, {"promise_ready_minutes": 10})
no3 = new_paid()
call("POST", f"/orders/{no3}/transition", merchant, {"to_status": "accepted"})
# 未超时:不可自助退
chk = call("GET", f"/orders/{no3}/self-refund/check", customer)
assert chk["eligible"] is False, "刚接单未超时不可自助退"
backdate_accept(no3, 20)  # 超 10×1.5=15 分钟
chk = call("GET", f"/orders/{no3}/self-refund/check", customer)
assert chk["eligible"] is True and "超时" in chk["reason"]
done = call("POST", f"/orders/{no3}/self-refund", customer)
assert done["status"] == "cancelled"
print("✓ 商家超时未出餐可自助退(未超时不可退)")

call("PATCH", "/merchants/me", merchant, {"promise_ready_minutes": 15})
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\n客服自助化验证通过 🎉")
