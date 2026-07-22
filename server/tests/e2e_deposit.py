"""商家保证金:从营收留存(不预缴),可提 = 余额 - 应留;平台可按店调、只降不追缴。"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")


def top_up_balance(target_cents):
    """余额不够就自己跑单挣(自取单核销即时结算,重置后的新库也能跑)。"""
    dish = None
    while True:
        w = call("GET", "/merchants/me/wallet", merchant)
        if w["balance_cents"] > target_cents:
            return
        if dish is None:
            dish = call("POST", "/merchants/me/dishes", merchant,
                        {"name": f"保证金测试菜-{int(time.time())}",
                         "price_cents": 8000, "stock": 50})
        order = call("POST", "/orders", customer, {
            "merchant_id": shop["id"],
            "items": [{"dish_id": dish["id"], "quantity": 1}],
            "pickup": True,
        })
        no = order["order_no"]
        call("POST", f"/orders/{no}/pay/mock", customer)
        call("POST", f"/orders/{no}/transition", merchant,
             {"to_status": "accepted"})
        call("POST", f"/orders/{no}/transition", merchant,
             {"to_status": "ready"})
        call("POST", f"/orders/{no}/pickup-verify", merchant,
             {"code": order["pickup_code"]})


top_up_balance(20000)

w = call("GET", "/merchants/me/wallet", merchant)
assert w["deposit_required_cents"] == 50000, w["deposit_required_cents"]
assert w["deposit_held_cents"] == min(w["balance_cents"], 50000)
assert w["withdrawable_cents"] == max(0, w["balance_cents"] - 50000)
print(f"✓ 钱包口径:余额 {w['balance_cents']/100:.2f},保证金留存 "
      f"{w['deposit_held_cents']/100:.2f},可提 {w['withdrawable_cents']/100:.2f}")

# 把应留调到「余额 - 100 元」:可提正好 100 元,验证边界
balance = w["balance_cents"]
assert balance > 20000, "演示商家余额太低,先跑几单"
call("POST", f"/admin/merchants/{shop['id']}/deposit", admin,
     {"deposit_required_cents": balance - 10000})
w = call("GET", "/merchants/me/wallet", merchant)
assert w["withdrawable_cents"] == 10000

err = call("POST", "/merchants/me/withdrawals", merchant,
           {"amount_cents": 10001}, expect_error=True)
assert err["_error"] == 409 and "保证金" in err["detail"]
print(f"✓ 超出可提额被拒且说明保证金:{err['detail']}")

wd = call("POST", "/merchants/me/withdrawals", merchant, {"amount_cents": 10000})
assert wd["status"] == "pending"
w2 = call("GET", "/merchants/me/wallet", merchant)
assert w2["withdrawable_cents"] == 0
err = call("POST", "/merchants/me/withdrawals", merchant,
           {"amount_cents": 1000}, expect_error=True)
assert err["_error"] == 409
print("✓ 可提额刚好提空后,保证金部分提不走")

# 应留调到天上:可提 0(不追缴已提部分,只影响后续)
call("POST", f"/admin/merchants/{shop['id']}/deposit", admin,
     {"deposit_required_cents": 1_000_000})
w3 = call("GET", "/merchants/me/wallet", merchant)
assert w3["withdrawable_cents"] == 0
assert w3["deposit_held_cents"] == max(0, w3["balance_cents"])
print("✓ 调高应留只影响后续可提额,不追缴")

# 非法金额
err = call("POST", f"/admin/merchants/{shop['id']}/deposit", admin,
           {"deposit_required_cents": -1}, expect_error=True)
assert err["_error"] == 422

# 恢复现场:默认 500 元,清掉测试提现
call("POST", f"/admin/merchants/{shop['id']}/deposit", admin,
     {"deposit_required_cents": 50000})
call("POST", f"/admin/withdrawals/{wd['id']}/reject", admin, {"reason": "e2e清场"})
w4 = call("GET", "/merchants/me/wallet", merchant)
assert w4["deposit_required_cents"] == 50000
assert w4["balance_cents"] == balance
print("✓ 现场恢复:应留回到默认 ¥500,余额复原")

print("\n商家保证金验证通过 🎉")
