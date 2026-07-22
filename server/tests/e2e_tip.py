"""用户小费验证:带小费下单口径、骑手结算含小费、取消全退、
佣金基数不含小费、自取单拒收小费、审计恒等。

在 server/ 目录下运行:python -m tests.e2e_tip
"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

sid = call("GET", "/merchants/me", merchant)["id"]
call("PATCH", "/merchants/me", merchant, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"小费测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def make_order(tip=0, pickup=False, expect_error=False):
    body = {"merchant_id": sid,
            "items": [{"dish_id": dish["id"], "quantity": 1}],
            "tip_cents": tip}
    if pickup:
        body["pickup"] = True
    else:
        body.update({"address": "测试地址", "lat": 30.66, "lng": 104.08})
    return call("POST", "/orders", customer, body, expect_error=expect_error)


def main():
    # 1) 带小费下单:total 含小费,佣金基数不含
    o = make_order(tip=500)
    assert o["tip_cents"] == 500
    assert o["total_cents"] == (o["food_cents"] + o["packing_fee_cents"]
                                - o["discount_cents"]
                                + o["delivery_fee_cents"] + 500
                                - o["subsidy_cents"]), o
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    paid = call("GET", f"/orders/{no}", customer)
    expected_comm = round((paid["food_cents"] + paid["packing_fee_cents"]
                           - paid["discount_cents"]) * 0.05)
    assert paid["commission_cents"] == expected_comm, "佣金基数不含小费"
    print("✓ 带小费下单:实付含小费,佣金基数不含小费")

    # 2) 骑手结算 = 配送费 + 小费
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    before = call("GET", "/riders/wallet", rider)["total_earned_cents"]
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "picked_up", "verify_code": no[-4:]})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer,
         {"to_status": "completed"})
    after = call("GET", "/riders/wallet", rider)["total_earned_cents"]
    assert after - before == paid["delivery_fee_cents"] + 500, \
        f"骑手应多入账配送费+小费:{after - before}"
    earns = call("GET", "/riders/earnings", rider)
    assert any(e["order_no"] == no and
               e["amount_cents"] == paid["delivery_fee_cents"] + 500
               for e in earns)
    print("✓ 骑手结算 = 配送费 + 小费,一分不少")

    # 3) 取消全额退款(含小费)
    o2 = make_order(tip=300)
    no2 = o2["order_no"]
    call("POST", f"/orders/{no2}/pay/mock", customer)
    call("POST", f"/orders/{no2}/transition", customer,
         {"to_status": "cancelled"})
    o2 = call("GET", f"/orders/{no2}", customer)
    assert o2["refund_cents"] == o2["total_cents"] and o2["tip_cents"] == 300
    flows = call("GET", f"/orders/{no2}/refunds", customer)
    assert sum(f["amount_cents"] for f in flows) == o2["total_cents"]
    print("✓ 取消全额退款(小费一并退)")

    # 4) 自取单不收小费;超上限 422
    err = make_order(tip=200, pickup=True, expect_error=True)
    assert err["_error"] == 422 and "自取" in err["detail"], err
    err = make_order(tip=6000, expect_error=True)
    assert err["_error"] == 422, err
    print("✓ 自取单拒收小费;超 ¥50 上限 422")

    # 5) 审计手动跑一遍:恒等式含小费口径全绿
    import asyncio

    from app.services.audit import run_audit
    problems = asyncio.run(run_audit())
    tip_problems = [p for p in problems if no in p.get("detail", "")
                    or no2 in p.get("detail", "")]
    assert not tip_problems, tip_problems
    print("✓ 审计恒等式(骑手入账=配送费+小费 / 实付含小费)全绿")

    print("\ne2e_tip 全部通过 ✅")


if __name__ == "__main__":
    main()
