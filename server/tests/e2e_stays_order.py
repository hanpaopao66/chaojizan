"""住宿订单主链路:并发抢房不超卖、支付幂等、确认/入住/离店结算、状态机护栏。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_stays_order
"""
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from tests.util import ADMIN, call, login, register_user

admin_token = login(ADMIN)
today = date.today()
ci, co = today + timedelta(days=10), today + timedelta(days=12)  # 2 晚


def new_customer():
    return register_user("customer", "guest123", prefix="137")[0]


# 建酒店:1 个房型,区间内每晚只有 1 间
mt, phone = register_user("merchant", "hotel123", prefix="138")
shop = call("POST", "/merchants", token=mt, body={
    "name": f"抢房客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST04",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-004",
              "special_license_image_url": "https://example.com/sp.jpg"}})
call("POST", f"/admin/merchants/{shop['id']}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})
rt = call("POST", "/stays/me/room-types", token=mt,
          body={"name": "唯一大床房", "cancel_policy": "limited_free"})
call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt["id"]], "from_date": str(today),
    "to_date": str(today + timedelta(days=30)),
    "price_cents": 20000, "total_qty": 1})

# 1) 并发抢房:6 个用户抢同 2 晚的 1 间,只能成 1 单
tokens = [new_customer() for _ in range(6)]


def try_book(t):
    return call("POST", "/stays/orders", token=t, body={
        "room_type_id": rt["id"], "checkin_date": str(ci),
        "checkout_date": str(co), "rooms_qty": 1,
        "guest_name": "并发客", "guest_phone": "13700000000"},
        expect_error=True)


with ThreadPoolExecutor(max_workers=6) as ex:
    results = list(ex.map(try_book, tokens))
wins = [r for r in results if "_error" not in r]
fails = [r for r in results if "_error" in r]
assert len(wins) == 1, f"应恰好 1 单成功,实际 {len(wins)}"
assert all(f["_error"] == 409 for f in fails)
order = wins[0]
assert order["total_cents"] == 40000 and len(order["nightly_prices"]) == 2
winner = tokens[results.index(order)]
print(f"OK 并发 6 抢 1 不超卖: {order['order_no']},失败方提示如「{fails[0]['detail']}」")

# 2) 已售护栏:总量下调到 0 被拒(#67 遗留验收)
r = call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt["id"]], "from_date": str(ci), "to_date": str(ci),
    "total_qty": 0}, expect_error=True)
assert r["_error"] == 422 and "已售" in r["detail"], r
print("OK 总量不能下调到低于已售:", r["detail"])

# 3) 支付幂等 → 商家确认 → 入住 → 离店结算 5%
no = order["order_no"]
paid = call("POST", f"/stays/orders/{no}/pay/mock", token=winner)
assert paid["status"] == "paid"
paid2 = call("POST", f"/stays/orders/{no}/pay/mock", token=winner)
assert paid2["status"] == "paid", "重复支付应幂等"
# 状态机:未确认不能入住
r = call("POST", f"/stays/me/orders/{no}/checkin", token=mt, expect_error=True)
assert r["_error"] == 409, r
lst = call("GET", "/stays/me/orders?state=pending", token=mt)
assert any(o["order_no"] == no for o in lst)
call("POST", f"/stays/me/orders/{no}/confirm", token=mt)
call("POST", f"/stays/me/orders/{no}/checkin", token=mt)
done = call("POST", f"/stays/me/orders/{no}/checkout", token=mt)
assert done["status"] == "completed"
assert done["fee_cents"] == 2000, f"佣金应 5%: {done['fee_cents']}"
assert done["net_cents"] == 38000
print("OK 支付→确认→入住→离店,佣金 5% 商家实收 38000")

# 4) 完结单不能再取消;用户视角详情带酒店信息与政策文案
r = call("POST", f"/stays/orders/{no}/cancel", token=winner, expect_error=True)
assert r["_error"] == 409
detail = call("GET", f"/stays/orders/{no}", token=winner)
assert detail["hotel_name"].startswith("抢房客栈")
assert "免费取消" in detail["cancel_policy_text"]
mine = call("GET", "/stays/orders/mine", token=winner)
assert any(o["order_no"] == no for o in mine)
print("OK 完结单守护与订单详情")

# 5) 待支付取消 → 关闭并回补(马上能再订同区间)
o2 = call("POST", "/stays/orders", token=tokens[1], body={
    "room_type_id": rt["id"], "checkin_date": str(ci + timedelta(days=5)),
    "checkout_date": str(co + timedelta(days=5)), "rooms_qty": 1,
    "guest_name": "回补客", "guest_phone": "13700000001"})
closed = call("POST", f"/stays/orders/{o2['order_no']}/cancel", token=tokens[1])
assert closed["status"] == "closed" and closed["refund_cents"] == 0
o3 = call("POST", "/stays/orders", token=tokens[2], body={
    "room_type_id": rt["id"], "checkin_date": str(ci + timedelta(days=5)),
    "checkout_date": str(co + timedelta(days=5)), "rooms_qty": 1,
    "guest_name": "接盘客", "guest_phone": "13700000002"})
assert "_error" not in o3, "回补后应能再订"
print("OK 待支付取消回补库存")

print("PASS e2e_stays_order")
