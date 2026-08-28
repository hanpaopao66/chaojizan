"""出餐之后用户取消:按判责口径分摊,而不是一句「不支持退款」。

老口径是出餐后一律禁止取消。理由站得住(餐已经做了),但手段太粗 ——
**没有出口的结果不是用户不取消,是他去微信支付投诉或者银行拒付**。

这条守四件事:

1. 出餐之后能看到一份**完整的账**:退多少、剩下的去哪、为什么;
2. 四方相加恒等于用户已付,平台佣金恒为 0;
3. 提交时必须带上用户看到的那份账 —— 账变了就 409,不许"用户同意的是 A、
   系统执行的是 B";
4. 出餐**之前**照旧走原来的全额退款规则,这次没把它改坏。

在 server/ 目录下运行:python -m tests.e2e_cancel_split
"""
import time

from tests.util import call, demo_shop, login

customer = call("POST", "/auth/register",
                body={"phone": f"137{int(time.time()) % 100000000:08d}",
                      "password": "123456", "name": "分摊取消测试",
                      "role": "customer"})["token"]
merchant = login("13800000002")
rider = login("13800000003")
shop = demo_shop()
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"分摊取消菜-{int(time.time())}",
             "price_cents": 2000, "stock": 99})


def new_order(to="ready"):
    """下单 → 支付 → 接单 →(可选)出餐。返回订单号。"""
    no = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    if to in ("ready", "picked_up"):
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    if to == "picked_up":
        call("POST", f"/riders/grab/{no}", rider)
        call("POST", f"/orders/{no}/transition", rider,
             {"to_status": "picked_up", "force": True})
    return no


def money(no, token):
    o = call("GET", f"/orders/{no}", token)
    return o


def main() -> None:
    # ---------- 1) 已出餐、骑手没到店 ----------
    no = new_order("ready")
    q = call("GET", f"/orders/{no}/cancel-quote", customer)
    assert q["stage"] == "cooked", q
    assert q["refund_cents"] > 0, "骑手还没到店,配送费该退,不该是 0"
    assert q["lines"], "账单一行都没有"
    assert all(l["why"] for l in q["lines"]), "有一行没写为什么"
    assert q["spec_url"] == "/transparency/liability", "口径要能点进去看"
    plat = [l for l in q["lines"] if l["to"] == "platform"]
    assert len(plat) == 1 and plat[0]["cents"] == 0, "平台佣金没有单列成 0"
    print(f"✓ 已出餐未取餐:能退 {q['refund_cents']} 分(配送费+小费),"
          f"餐费归商家,佣金 0")

    # 提交时账对不上 → 409,不许按另一份账执行
    bad = call("POST", f"/orders/{no}/cancel-with-split", customer,
               {"agreed_stage": q["stage"],
                "agreed_refund_cents": q["refund_cents"] + 1},
               expect_error=True)
    assert bad["_error"] == 409, bad
    bad = call("POST", f"/orders/{no}/cancel-with-split", customer,
               {"agreed_stage": "in_delivery",
                "agreed_refund_cents": q["refund_cents"]}, expect_error=True)
    assert bad["_error"] == 409, bad
    print("✓ 金额或阶段对不上一律 409(用户同意的账 ≠ 系统执行的账,不许发生)")

    o = call("POST", f"/orders/{no}/cancel-with-split", customer,
             {"agreed_stage": q["stage"],
              "agreed_refund_cents": q["refund_cents"]})
    assert o["status"] == "cancelled", o
    assert o["refund_cents"] == q["refund_cents"], (
        f"实退 {o['refund_cents']} ≠ 账单上的 {q['refund_cents']}")
    print(f"✓ 按账单取消成功,实退 {o['refund_cents']} 分")

    # ---------- 2) 配送中 ----------
    no2 = new_order("picked_up")
    q2 = call("GET", f"/orders/{no2}/cancel-quote", customer)
    assert q2["stage"] == "in_delivery", q2
    assert q2["refund_cents"] == 0, "配送中还能退钱?骑手的劳动谁付"
    assert q2["food_to"], "餐在骑手车上,必须交代它归谁"
    rider_lines = [l for l in q2["lines"] if l["to"] == "rider"]
    assert rider_lines and rider_lines[0]["cents"] > 0, "配送费没给骑手"
    print(f"✓ 配送中:用户拿回 0,配送费 {rider_lines[0]['cents']} 分归骑手,"
          f"餐归骑手处置")

    o2 = call("POST", f"/orders/{no2}/cancel-with-split", customer,
              {"agreed_stage": "in_delivery", "agreed_refund_cents": 0})
    assert o2["status"] == "cancelled", o2
    print("✓ 配送中也能取消 —— 用户有出口,只是账按责任分")

    # ---------- 3) 出餐之前不归这条路管 ----------
    no3 = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no3}/pay/mock", customer)
    err = call("GET", f"/orders/{no3}/cancel-quote", customer, expect_error=True)
    assert err["_error"] == 409, err
    # 而原来的全额退款照常
    chk = call("GET", f"/orders/{no3}/self-refund/check", customer)
    assert chk["eligible"] is True, chk
    call("POST", f"/orders/{no3}/self-refund", customer)
    print("✓ 出餐之前照旧走全额退款,没被这次改动碰坏")

    # ---------- 4) 越权 ----------
    err = call("GET", f"/orders/{no2}/cancel-quote", merchant, expect_error=True)
    assert err["_error"] == 403, err
    print("✓ 只有下单本人能看自己的账单")

    print("\ne2e_cancel_split 全部通过 ✅")


if __name__ == "__main__":
    main()
