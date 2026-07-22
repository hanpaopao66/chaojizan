"""骑手收入与提现验证:完成单入账、余额计算、提现冻结/驳回退回/打款终结"""
from tests.util import orderable_dish, call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dishes = call("GET", f"/merchants/{shop['id']}/dishes")
main_dish = orderable_dish(dishes)


def run_order():
    order = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": main_dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    return no, order["delivery_fee_cents"]


err = call("GET", "/riders/wallet", customer, expect_error=True)
assert err["_error"] == 403
print("✓ 非骑手角色无钱包权限(403)")

w0 = call("GET", "/riders/wallet", rider)

# 完成一单 → 配送费入账
no, fee = run_order()
w1 = call("GET", "/riders/wallet", rider)
assert w1["total_earned_cents"] == w0["total_earned_cents"] + fee
assert w1["balance_cents"] == w0["balance_cents"] + fee
earnings = call("GET", "/riders/earnings", rider)
assert earnings[0]["order_no"] == no and earnings[0]["amount_cents"] == fee
print(f"✓ 订单完成配送费入账 +{fee/100} 元,收入明细可查")

# 凑够提现门槛
while call("GET", "/riders/wallet", rider)["balance_cents"] < 2000:
    run_order()
w = call("GET", "/riders/wallet", rider)
balance = w["balance_cents"]

err = call("POST", "/riders/withdrawals", rider, {"amount_cents": 500}, expect_error=True)
assert err["_error"] == 422
print(f"✓ 低于最低提现额被拒:{err['detail']}")

err = call("POST", "/riders/withdrawals", rider,
           {"amount_cents": balance + 1}, expect_error=True)
assert err["_error"] == 409
print(f"✓ 超出余额被拒:{err['detail']}")

# 提现 → 冻结
wd = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1000})
assert wd["status"] == "pending"
w = call("GET", "/riders/wallet", rider)
assert w["balance_cents"] == balance - 1000 and w["pending_withdrawal_cents"] >= 1000
print("✓ 提现申请冻结余额(可提现 -10 元,提现中 +10 元)")

# 管理员驳回 → 退回
pending = call("GET", "/admin/withdrawals?status=pending", admin)
mine = next(x for x in pending if x["id"] == wd["id"])
assert mine["phone"] == "13800000003" and mine["role"] == "rider"
call("POST", f"/admin/withdrawals/{wd['id']}/reject", admin, {"reason": "收款信息待补充"})
w = call("GET", "/riders/wallet", rider)
assert w["balance_cents"] == balance
my_wds = call("GET", "/riders/withdrawals", rider)
assert my_wds[0]["status"] == "rejected" and my_wds[0]["reject_reason"] == "收款信息待补充"
print("✓ 驳回后余额退回,骑手能看到原因")

# 再提一笔 → 打款
wd2 = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1000})
call("POST", f"/admin/withdrawals/{wd2['id']}/paid", admin)
w = call("GET", "/riders/wallet", rider)
assert w["balance_cents"] == balance - 1000 and w["withdrawn_cents"] >= 1000
print("✓ 打款完成,余额扣减、已提现累计")

# 已处理的申请不能重复操作
err = call("POST", f"/admin/withdrawals/{wd2['id']}/paid", admin, expect_error=True)
assert err["_error"] == 409
print(f"✓ 重复处理被拒:{err['detail']}")

print("\n骑手钱包验证通过 🎉")
