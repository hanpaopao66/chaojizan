"""提现打款失败闭环:paid→failed 余额退回、自动工单、终态不可再改、可重新申请。
骑手与商家两侧共用同一张表同一套流程,两侧都验。"""
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


def wallet(role_token, path):
    return call("GET", path, role_token)


# 凑余额
while wallet(rider, "/riders/wallet")["balance_cents"] < 2000:
    run_order()

# ---------- 骑手侧 ----------
w0 = wallet(rider, "/riders/wallet")
wd = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1200})
call("POST", f"/admin/withdrawals/{wd['id']}/paid", admin, {"note": "e2e批次"})
w1 = wallet(rider, "/riders/wallet")
assert w1["withdrawn_cents"] == w0["withdrawn_cents"] + 1200

tickets_before = len(call("GET", "/admin/tickets", admin))
failed = call("POST", f"/admin/withdrawals/{wd['id']}/failed", admin,
              {"reason": "银行卡信息有误"})
assert failed["status"] == "failed" and failed["role"] == "rider"
w2 = wallet(rider, "/riders/wallet")
assert w2["balance_cents"] == w1["balance_cents"] + 1200, (w1, w2)
assert w2["withdrawn_cents"] == w1["withdrawn_cents"] - 1200
print("✓ 骑手侧:退票后余额自动退回,已提现同步扣减")

mine = call("GET", "/riders/withdrawals", rider)
rec = next(x for x in mine if x["id"] == wd["id"])
assert rec["status"] == "failed" and "银行卡" in rec["reject_reason"]
print("✓ 骑手端可见失败状态与原因")

tickets_after = call("GET", "/admin/tickets", admin)
assert len(tickets_after) == tickets_before + 1
assert "打款被退回" in tickets_after[0]["content"]
print("✓ 退票自动生成客服工单跟进")

# 终态:不可再标退票/打款/驳回
for action, body in [("failed", {"reason": "再次退票"}), ("paid", None),
                     ("reject", {"reason": "重复处理"})]:
    err = call("POST", f"/admin/withdrawals/{wd['id']}/{action}", admin,
               body, expect_error=True)
    assert err["_error"] == 409, (action, err)
print("✓ failed 是终态,不可再改")

# 重新申请畅通
wd2 = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1200})
assert wd2["status"] == "pending" and wd2["id"] != wd["id"]
call("POST", f"/admin/withdrawals/{wd2['id']}/reject", admin, {"reason": "e2e清场"})
print("✓ 退票后可重新发起申请")

# pending 不能直接标退票
wd3 = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1000})
err = call("POST", f"/admin/withdrawals/{wd3['id']}/failed", admin,
           {"reason": "没打款就退票"}, expect_error=True)
assert err["_error"] == 409
call("POST", f"/admin/withdrawals/{wd3['id']}/reject", admin, {"reason": "e2e清场"})
print("✓ 未打款的申请不能标记退票")

# ---------- 商家侧 ----------
mw0 = wallet(merchant, "/merchants/me/wallet")
assert mw0["withdrawable_cents"] >= 1500, "商家可提余额不足,先跑单"
mwd = call("POST", "/merchants/me/withdrawals", merchant, {"amount_cents": 1500})
call("POST", f"/admin/withdrawals/{mwd['id']}/paid", admin, {"note": "e2e批次"})
call("POST", f"/admin/withdrawals/{mwd['id']}/failed", admin, {"reason": "对公账户名不符"})
mw1 = wallet(merchant, "/merchants/me/wallet")
assert mw1["balance_cents"] == mw0["balance_cents"], (mw0, mw1)
recs = call("GET", "/merchants/me/withdrawals", merchant)
assert recs[0]["status"] == "failed"
print("✓ 商家侧:退票后余额复原,记录状态正确")

print("\n提现打款失败闭环验证通过 🎉")
