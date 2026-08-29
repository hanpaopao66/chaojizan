"""三档取消政策退款:限时免费(时限内/过时限)、扣首晚、不可退、商家拒单全退。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_stays_cancel
"""
import random
from datetime import date, timedelta

from tests.util import ADMIN, call, login, register_user

admin_token = login(ADMIN)
today = date.today()

mt, phone = register_user("merchant", "hotel123", prefix="138")
shop = call("POST", "/merchants", token=mt, body={
    "name": f"退款客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST05",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-005",
              "special_license_image_url": "https://example.com/sp.jpg"}})
call("POST", f"/admin/merchants/{shop['id']}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})

ct, cphone = register_user("customer", "guest123", prefix="137")


def make_rt(name, policy, until="18:00"):
    rt = call("POST", "/stays/me/room-types", token=mt,
              body={"name": name, "cancel_policy": policy,
                    "free_cancel_until": until})
    call("PUT", "/stays/me/calendar", token=mt, body={
        "room_type_ids": [rt["id"]], "from_date": str(today),
        "to_date": str(today + timedelta(days=30)),
        "price_cents": 10000, "total_qty": 3})
    return rt["id"]


def book_and_pay(rt_id, ci, co, qty=1):
    o = call("POST", "/stays/orders", token=ct, body={
        "room_type_id": rt_id, "checkin_date": str(ci),
        "checkout_date": str(co), "rooms_qty": qty,
        "guest_name": "退款客", "guest_phone": "13700000003"})
    call("POST", f"/stays/orders/{o['order_no']}/pay/mock", token=ct)
    return o["order_no"]


ci, co = today + timedelta(days=10), today + timedelta(days=12)  # 2 晚 20000

# 1) limited_free 时限内:试算与实退都是全额,penalty 0
rt_free = make_rt("免费取消房", "limited_free")
no = book_and_pay(rt_free, ci, co)
pv = call("GET", f"/stays/orders/{no}/cancel-preview", token=ct)
assert pv["refund_cents"] == 20000 and pv["penalty_cents"] == 0, pv
done = call("POST", f"/stays/orders/{no}/cancel", token=ct)
assert done["refund_cents"] == 20000 and done["net_cents"] == 0
assert done["fee_cents"] == 0
print("OK limited_free 时限内全额退")

# 2) limited_free 已过时限(免费截止 00:01,入住今天):扣首晚
rt_late = make_rt("过时限房", "limited_free", until="00:01")
no = book_and_pay(rt_late, today, today + timedelta(days=2))
pv = call("GET", f"/stays/orders/{no}/cancel-preview", token=ct)
assert pv["refund_cents"] == 10000 and pv["penalty_cents"] == 10000, pv
done = call("POST", f"/stays/orders/{no}/cancel", token=ct)
assert done["refund_cents"] == 10000 and done["net_cents"] == 10000
assert done["fee_cents"] == 0, "扣首晚归商家,平台不抽佣"
print("OK limited_free 过时限扣首晚(商家得 10000,平台 0)")

# 3) first_night 档:任何时候取消都扣首晚;2 间 × 2 晚验证首晚 = 首晚价 × 间数
rt_fn = make_rt("扣首晚房", "first_night")
no = book_and_pay(rt_fn, ci, co, qty=2)  # 总 40000,首晚 20000
pv = call("GET", f"/stays/orders/{no}/cancel-preview", token=ct)
assert pv["refund_cents"] == 20000 and pv["penalty_cents"] == 20000, pv
done = call("POST", f"/stays/orders/{no}/cancel", token=ct)
assert done["refund_cents"] == 20000 and done["net_cents"] == 20000
print("OK first_night 扣首晚×间数")

# 4) strict 档:退 0,但库存回补商家可复卖
rt_st = make_rt("不可退房", "strict")
no = book_and_pay(rt_st, ci, co)
pv = call("GET", f"/stays/orders/{no}/cancel-preview", token=ct)
assert pv["refund_cents"] == 0 and pv["penalty_cents"] == 20000, pv
assert "不可退" in pv["note"]
done = call("POST", f"/stays/orders/{no}/cancel", token=ct)
assert done["refund_cents"] == 0 and done["net_cents"] == 20000
# 回补验证:同区间再订成功
no2 = book_and_pay(rt_st, ci, co)
print("OK strict 退 0 且库存可复卖")

# 5) 商家确认后拒单不可行(状态机);待确认拒单 = 全额退
r = call("POST", f"/stays/me/orders/{no2}/confirm", token=mt)
r = call("POST", f"/stays/me/orders/{no2}/reject", token=mt,
         body={"reason": "满房"}, expect_error=True)
assert r["_error"] == 409, "已确认单不能再拒"
no3 = book_and_pay(rt_free, ci, co)
rej = call("POST", f"/stays/me/orders/{no3}/reject", token=mt,
           body={"reason": "价格录错了"})
assert rej["status"] == "rejected" and rej["refund_cents"] == 20000
assert rej["fee_cents"] == 0 and rej["net_cents"] == 0
d = call("GET", f"/stays/orders/{no3}", token=ct)
assert d["reject_reason"] == "价格录错了"
print("OK 商家拒单全额退且原因可见")

# 6) 确认后的单用户仍可按政策取消
no4 = book_and_pay(rt_free, ci, co)
call("POST", f"/stays/me/orders/{no4}/confirm", token=mt)
done = call("POST", f"/stays/orders/{no4}/cancel", token=ct)
assert done["status"] == "cancelled" and done["refund_cents"] == 20000
print("OK 已确认单时限内取消全额退")

print("PASS e2e_stays_cancel")
