"""订单页上的数(/orders/counts,设计稿 3b「全部 38」「待支付 · 1」)。

守三件事:
- 数是**全量**,跟着单子的状态走(待支付 → 进行中 → 取消后不再算待办);
- 这条路由排在 `/{order_no}` 之前,不会被当成一个叫 counts 的订单号;
- 只给顾客:骑手/商家拿它没有意义,也不该拿到。

在 server/ 目录下运行:python -m tests.e2e_order_counts
"""
from .util import (MERCHANT, RIDER, call, demo_shop, login, orderable_dish,
                   register_fresh_customer)


def food_row(counts: dict) -> dict:
    rows = [r for r in counts["food"] if r["biz_type"] == "food"]
    return rows[0] if rows else {"total": 0, "pending_payment": 0,
                                 "active": 0, "to_review": 0}


def main() -> None:
    customer = register_fresh_customer()
    merchant = login(MERCHANT)

    empty = call("GET", "/orders/counts", customer)
    assert empty["food"] == [], empty
    assert empty["stay"] == {"total": 0, "pending_payment": 0,
                             "active": 0, "to_review": 0}, empty
    assert empty["tickets"] == {"total": 0, "usable": 0}, empty
    # 新用户可能领到新人券,这里只要求是个数
    assert isinstance(empty["coupons_usable"], int), empty
    coupons0 = empty["coupons_usable"]
    print(f"✓ 新用户:没有任何单,数全是 0(新人券 {coupons0} 张可用)")

    shop = demo_shop()
    dishes = call("GET", f"/merchants/{shop['id']}/dishes")
    dish = orderable_dish(dishes)
    o = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "计数测试地址", "lat": shop["lat"] + .01,
        "lng": shop["lng"]})
    no = o["order_no"]

    c = food_row(call("GET", "/orders/counts", customer))
    assert (c["total"], c["pending_payment"], c["active"]) == (1, 1, 0), c
    print("✓ 下单未付:全部 1、待支付 1")

    call("POST", f"/orders/{no}/pay/mock", customer)
    whole = call("GET", "/orders/counts", customer)
    # 券包的数和券包接口自己说的一致(那边只回近 30 张,新用户远不到)
    usable = [c for c in call("GET", "/orders/coupons/mine", customer)
              if c["usable"]]
    assert whole["coupons_usable"] == len(usable), (whole, len(usable))
    print(f"✓ 可用优惠券 {len(usable)} 张,和券包对得上")
    c = food_row(whole)
    assert (c["total"], c["pending_payment"], c["active"]) == (1, 0, 1), c
    print("✓ 付款后:待支付 0、进行中 1")

    call("POST", f"/orders/{no}/transition", merchant,
         {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant,
         {"to_status": "cancelled", "reason": "计数测试"})
    c = food_row(call("GET", "/orders/counts", customer))
    assert (c["total"], c["pending_payment"], c["active"],
            c["to_review"]) == (1, 0, 0, 0), c
    print("✓ 取消后:还算在全部里,但不是待办")

    err = call("GET", "/orders/counts", login(RIDER), expect_error=True)
    assert err["_error"] == 403, err
    print("✓ 骑手拿不到(403),不会被当成订单号「counts」回 404")

    print("\ne2e_order_counts 全部通过 ✅")


if __name__ == "__main__":
    main()
