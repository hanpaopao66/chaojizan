"""估清(今日售罄)是**下单闸门**,不是库存数字的副作用。

商家点「估清」的语义是「这道菜今天没有了」,而不是「库存清零」。
两者在一处会分叉:任何一条**回补库存**的路径(缺货退款、取消回补)
都会把 stock 加回去,而 sold_out_today 还挂着 —— 闸门只看 stock 的话,
这道菜就在商家不知情的情况下复活了,顾客下单成功、商家做不出来。

    商家点售罄 → stock=0, sold_out_today=true
    顾客下单   → 409「今日已售罄」          ✓
    商家做一笔缺货退款 → stock 回补
    顾客再下单 → **必须仍然 409**,而不是成功

回补本身是对的(那份菜确实退回来了),不该顺手解除估清 ——
解除估清只有商家自己点「撤销估清」或次日 04:00 自动恢复两条路。
"""
import time

from .util import CUSTOMER, MERCHANT, call, demo_shop, login

customer = login(CUSTOMER)
merchant = login(MERCHANT)
SHOP = demo_shop()


def place(dish_id, qty=1, expect_error=False):
    return call("POST", "/orders", customer, {
        "merchant_id": SHOP["id"],
        "items": [{"dish_id": dish_id, "quantity": qty}],
        "address": "估清闸门测试", "lat": 30.66, "lng": 104.08,
    }, expect_error=expect_error)


def dish_state(dish_id):
    menu = call("GET", f"/merchants/{SHOP['id']}/dishes")
    return next(d for d in menu if d["id"] == dish_id)


def reject(dish_id, why):
    """下单必须被闸门挡住。**下成功了要说清是哪一步漏了**,
    不然只看到一个 KeyError('_error'),排查还得回头猜。"""
    got = place(dish_id, 1, expect_error=True)
    if "_error" not in got:
        # 下成功了:把这单撤掉,别把估清的菜挂在商家的待接单列表里
        call("POST", f"/orders/{got['order_no']}/transition", customer,
             {"to_status": "cancelled", "reason": "估清闸门测试清场"},
             expect_error=True)
        raise AssertionError(
            f"{why}:估清的菜下单成功了(订单 {got['order_no']}),"
            "下单闸门没看 sold_out_today")
    assert got["_error"] == 409, got
    assert "售罄" in got["detail"], got["detail"]
    return got


def main():
    tag = str(int(time.time()))
    dish = call("POST", "/merchants/me/dishes", merchant,
                {"name": f"估清闸门测试菜-{tag}", "price_cents": 2000,
                 "stock": 5})
    did = dish["id"]

    # ---- 1) 缺货退款回补的库存不得让估清菜复活 ----
    o = place(did, 2)
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    assert dish_state(did)["stock"] == 3, dish_state(did)

    sold = call("POST", f"/merchants/me/dishes/{did}/sell-out", merchant)
    assert sold["sold_out_today"] is True and sold["stock"] == 0, sold
    err = place(did, 1, expect_error=True)
    assert err["_error"] == 409 and "售罄" in err["detail"], err
    print(f"✓ 估清后下单被拒:{err['detail']}")

    back = call("POST", f"/orders/{no}/refund-item", merchant,
                {"dish_id": did, "quantity": 2})
    assert back["status"] == "cancelled", back["status"]
    st = dish_state(did)
    assert st["stock"] == 2, f"缺货退款应回补 2 份,现在 stock={st['stock']}"
    assert st["sold_out_today"] is True, "回补库存不该顺手解除估清"
    print("✓ 缺货退款回补了 2 份库存,估清标志仍在")

    err = reject(did, "缺货退款回补了库存")
    print(f"✓ 回补之后再下单仍被拒:{err['detail']}")

    # ---- 2) 取消回补(restore_stock)同样不得解除估清 ----
    call("POST", f"/merchants/me/dishes/{did}/sell-out/cancel", merchant)
    o2 = place(did, 1)
    no2 = o2["order_no"]
    call("POST", f"/orders/{no2}/pay/mock", customer)
    call("POST", f"/merchants/me/dishes/{did}/sell-out", merchant)
    # 商家拒单 → restore_stock 回补
    call("POST", f"/orders/{no2}/transition", merchant,
         {"to_status": "cancelled", "reason": "估清闸门测试"})
    st = dish_state(did)
    assert st["stock"] == 1, f"拒单应回补 1 份,现在 stock={st['stock']}"
    assert st["sold_out_today"] is True, "取消回补不该解除估清"
    err = reject(did, "拒单 restore_stock 回补了库存")
    print(f"✓ 取消回补之后再下单仍被拒:{err['detail']}")

    # ---- 3) 撤销估清是唯一的解除方式 ----
    ok = call("POST", f"/merchants/me/dishes/{did}/sell-out/cancel", merchant)
    assert ok["sold_out_today"] is False and ok["stock"] >= 1, ok
    o3 = place(did, 1)
    assert o3["order_no"], o3
    call("POST", f"/orders/{o3['order_no']}/transition", customer,
         {"to_status": "cancelled", "reason": "估清闸门测试清场"})
    print("✓ 撤销估清后恢复可下单")

    call("PATCH", f"/merchants/me/dishes/{did}", merchant,
         {"is_on_sale": False})
    print("\ne2e_soldout_gate 全部通过 ✅")


if __name__ == "__main__":
    main()
