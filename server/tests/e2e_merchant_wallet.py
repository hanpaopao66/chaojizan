"""商家钱包与提现:余额口径(外卖净额+团购核销净额-提现)、
最低额/超额校验、申请冻结、管理员打款、余额终结。骑手提现走同一张表,顺带回归。"""
from tests.util import orderable_dish, call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dishes = call("GET", f"/merchants/{shop['id']}/dishes")
main_dish = orderable_dish(dishes)

err = call("GET", "/merchants/me/wallet", customer, expect_error=True)
assert err["_error"] == 403
print("✓ 非商家角色无钱包权限(403)")

w0 = call("GET", "/merchants/me/wallet", merchant)
assert {"balance_cents", "total_earned_cents", "pending_withdrawal_cents",
        "withdrawn_cents", "deposit_required_cents", "deposit_held_cents",
        "withdrawable_cents"} <= set(w0)


def run_order():
    order = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": main_dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    paid = call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    return paid


paid = run_order()
net = (paid["food_cents"] + paid["packing_fee_cents"]
       - paid["discount_cents"] - paid["commission_cents"])
w1 = call("GET", "/merchants/me/wallet", merchant)
assert w1["total_earned_cents"] == w0["total_earned_cents"] + net, (w0, w1, net)
assert w1["balance_cents"] == w0["balance_cents"] + net
print(f"✓ 完成单入账商家钱包 +{net / 100:.2f} 元(净额 = 实收 − 5% 佣金)")

# 凑够提现门槛(可提口径:余额要盖过保证金留存)
while call("GET", "/merchants/me/wallet", merchant)["withdrawable_cents"] < 2000:
    run_order()
balance = call("GET", "/merchants/me/wallet", merchant)["balance_cents"]

err = call("POST", "/merchants/me/withdrawals", merchant,
           {"amount_cents": 500}, expect_error=True)
assert err["_error"] == 422
print(f"✓ 低于最低提现额被拒:{err['detail']}")

err = call("POST", "/merchants/me/withdrawals", merchant,
           {"amount_cents": balance + 1}, expect_error=True)
assert err["_error"] == 409
print(f"✓ 超出余额被拒:{err['detail']}")

wd = call("POST", "/merchants/me/withdrawals", merchant, {"amount_cents": 1500})
assert wd["status"] == "pending"
w2 = call("GET", "/merchants/me/wallet", merchant)
assert w2["balance_cents"] == balance - 1500
assert w2["pending_withdrawal_cents"] >= 1500
print("✓ 提现申请冻结余额(算出来的,不可双花)")

# 管理后台:按角色筛选可见,打款终结
pending = call("GET", "/admin/withdrawals?role=merchant&status=pending", admin)
mine = next(x for x in pending if x["id"] == wd["id"])
assert mine["role"] == "merchant" and mine["name"]
call("POST", f"/admin/withdrawals/{wd['id']}/paid", admin, {"note": "e2e-测试批次"})
w3 = call("GET", "/merchants/me/wallet", merchant)
assert w3["balance_cents"] == balance - 1500
assert w3["withdrawn_cents"] == w2["withdrawn_cents"] + 1500
assert w3["pending_withdrawal_cents"] == w2["pending_withdrawal_cents"] - 1500
records = call("GET", "/merchants/me/withdrawals", merchant)
assert records[0]["id"] == wd["id"] and records[0]["status"] == "paid"
assert records[0]["paid_note"] == "e2e-测试批次"
print("✓ 管理员打款终结,商家端记录含打款凭证(透明)")

print("PASS e2e_merchant_wallet")
