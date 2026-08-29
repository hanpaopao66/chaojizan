"""住宿结算财务打通:钱包余额、对账 CSV、发票口径、税务导出、审计、admin 查询。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_stays_settle
"""
import random
from datetime import datetime
from zoneinfo import ZoneInfo
import urllib.request
from datetime import date, timedelta

from tests.util import ADMIN, BASE, call, login, register_user


def fetch_csv(path, token):
    req = urllib.request.Request(
        BASE + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8").replace("\r", "")

admin_token = login(ADMIN)
today = date.today()          # 住宿日期用本地日期即可(房态按天,不涉及账期)
# 账期一律按**北京时间**算,和服务端 invoices._period_ended 同口径。
# 用 date.today()(机器本地时区)的话,跨月那几个小时会算出上个月的账期,
# 而订单已经属于新月份 —— 查不到,用例挂。实测 2026-08-01 00:03 北京时间
# 挂过一次:本地还是 7-31,服务端已经是 8 月
_bj = datetime.now(ZoneInfo("Asia/Shanghai"))
period = f"{_bj.year:04d}-{_bj.month:02d}"

mt, phone = register_user("merchant", "hotel123", prefix="138")
shop = call("POST", "/merchants", token=mt, body={
    "name": f"结算客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST07",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-007",
              "special_license_image_url": "https://example.com/sp.jpg"}})
sid = shop["id"]
call("POST", f"/admin/merchants/{sid}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})

rt_free = call("POST", "/stays/me/room-types", token=mt,
               body={"name": "结算房", "cancel_policy": "limited_free"})
rt_fn = call("POST", "/stays/me/room-types", token=mt,
             body={"name": "扣款房", "cancel_policy": "first_night"})
call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt_free["id"], rt_fn["id"]], "from_date": str(today),
    "to_date": str(today + timedelta(days=30)),
    "price_cents": 20000, "total_qty": 3})

ct, cphone = register_user("customer", "guest123", prefix="137")

ci, co = today + timedelta(days=3), today + timedelta(days=5)  # 2 晚 40000

wallet0 = call("GET", "/merchants/me/wallet", token=mt)
assert wallet0["balance_cents"] == 0

# 1) 一单走完离店:钱包 +38000(40000-5%)
o1 = call("POST", "/stays/orders", token=ct, body={
    "room_type_id": rt_free["id"], "checkin_date": str(ci),
    "checkout_date": str(co), "rooms_qty": 1,
    "guest_name": "结算客", "guest_phone": "13700000005"})
no1 = o1["order_no"]
call("POST", f"/stays/orders/{no1}/pay/mock", token=ct)
call("POST", f"/stays/me/orders/{no1}/confirm", token=mt)
call("POST", f"/stays/me/orders/{no1}/checkin", token=mt)
call("POST", f"/stays/me/orders/{no1}/checkout", token=mt)
w = call("GET", "/merchants/me/wallet", token=mt)
assert w["balance_cents"] == 38000, w
print("OK 离店结算入钱包: +38000 (佣金 2000)")

# 2) 一单取消扣首晚:钱包再 +20000(扣款归商家,平台 0 佣)
o2 = call("POST", "/stays/orders", token=ct, body={
    "room_type_id": rt_fn["id"], "checkin_date": str(ci),
    "checkout_date": str(co), "rooms_qty": 1,
    "guest_name": "扣款客", "guest_phone": "13700000006"})
no2 = o2["order_no"]
call("POST", f"/stays/orders/{no2}/pay/mock", token=ct)
call("POST", f"/stays/orders/{no2}/cancel", token=ct)
w = call("GET", "/merchants/me/wallet", token=mt)
assert w["balance_cents"] == 38000 + 20000, w
print("OK 取消扣款入钱包: +20000")

# 3) 对账 CSV 含住宿行且金额正确
text = fetch_csv("/merchants/me/finance/statement.csv", mt)
assert "住宿离店" in text and "住宿取消扣款" in text, text[:300]
assert f"{no1},住宿离店,400.00,20.00,380.00" in text
assert f"{no2},住宿取消扣款,400.00,0.00,200.00" in text
print("OK 对账 CSV 住宿行")

# 4) 发票口径:当月可开票 = 住宿佣金 2000(取消扣款不产生服务费)
summary = call("GET", f"/invoices/summary?period={period}", token=mt)
fee = summary.get("fee", summary)
assert fee["stay_fee_cents"] == 2000, fee
assert fee["total_cents"] == 2000
print("OK 发票口径 stay_fee=2000")

# 5) 税务导出:平台收入含住宿服务费行;商家结算含住宿净额列
text = fetch_csv(f"/admin/tax/platform-income.csv?period={period}", admin_token)
assert "住宿服务费" in text and "20.00" in text
text = fetch_csv(f"/admin/tax/merchant-settlement.csv?period={period}", admin_token)
assert "住宿净额" in text and "580.00" in text, text[:400]
text = fetch_csv(f"/admin/tax/commission-invoice.csv?period={period}", admin_token)
assert "住宿服务费" in text
print("OK 税务三张导出含住宿")

# 6) admin 住宿订单查询(资金三行)
rows = call("GET", f"/admin/stay-orders?merchant_id={sid}", token=admin_token)
by_no = {r["order_no"]: r for r in rows}
assert by_no[no1]["fee_cents"] == 2000 and by_no[no1]["net_cents"] == 38000
assert by_no[no2]["status"] == "cancelled" and by_no[no2]["net_cents"] == 20000
rows = call("GET", "/admin/stay-orders?status=completed", token=admin_token)
assert any(r["order_no"] == no1 for r in rows)
print("OK admin 住宿订单查询")

# 7) 审计:住宿恒等式全绿(无 stay_split_mismatch)
result = call("POST", "/admin/audit/run", token=admin_token)
stay_bad = [p for p in result["detail"]
            if p.get("check") == "stay_split_mismatch"]
assert not stay_bad, stay_bad
print("OK 审计住宿恒等式绿")

print("PASS e2e_stays_settle")
