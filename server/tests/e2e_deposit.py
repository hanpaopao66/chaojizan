"""商家保证金:从营收留存(不预缴),可提 = 余额 - 应留;平台可按店调、只降不追缴。"""
import time

from tests.util import demo_shop, call, login

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = demo_shop()


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

# 先把应留归位再断言默认值:本用例末尾虽然会还原,但**跑到一半崩掉**
# 就会把上一次的中间值留在库里,下一次直接挂在自己的脏数据上。
# 自愈比"断言它本来就该是默认值"稳
call("POST", f"/admin/merchants/{shop['id']}/deposit", admin,
     {"deposit_required_cents": 50000})

w = call("GET", "/merchants/me/wallet", merchant)
assert w["deposit_required_cents"] == 50000, w["deposit_required_cents"]
assert w["deposit_held_cents"] == min(w["balance_cents"], 50000)
assert w["withdrawable_cents"] == max(0, w["balance_cents"] - 50000)
print(f"✓ 钱包口径:余额 {w['balance_cents']/100:.2f},保证金留存 "
      f"{w['deposit_held_cents']/100:.2f},可提 {w['withdrawable_cents']/100:.2f}")

# 把应留调到「余额 - 100 元」:可提正好 100 元,验证边界
balance = w["balance_cents"]
assert balance > 20000, "演示商家余额太低,先跑几单"
# 应留有上限(100 万分),而演示商家的余额会被历次测试养到很高 ——
# 直接写 balance-10000 迟早超过上限被 422。改成断言不变式:
# **可提 = 余额 − 应留**,这条与余额规模无关,长期共享库上也成立
required = min(balance - 10000, 1_000_000)
call("POST", f"/admin/merchants/{shop['id']}/deposit", admin,
     {"deposit_required_cents": required})
w = call("GET", "/merchants/me/wallet", merchant)
expected = max(0, w["balance_cents"] - required)
assert w["withdrawable_cents"] == expected, (w["withdrawable_cents"], expected)

err = call("POST", "/merchants/me/withdrawals", merchant,
           {"amount_cents": expected + 1}, expect_error=True)
assert err["_error"] == 409 and "保证金" in err["detail"]
print(f"✓ 超出可提额被拒且说明保证金:{err['detail']}")

# 提走全部可提额(不是写死 100 元):可提额取决于余额,而余额会被
# 历次测试养大,写死就会在"提完还有剩"的状态下断言失败
wd = call("POST", "/merchants/me/withdrawals", merchant,
          {"amount_cents": expected})
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
