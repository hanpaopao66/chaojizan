"""帮买小票:一单只结一次账。

小票提交(`/errands/{no}/receipt`)会按差额**真的发起退款**。它原来既没有
行锁、也不看订单是不是已经结过账 —— `settle_goods` 每次都拿**没变过的**
`goods_budget_cents` 重算差额,于是重复提交就重复退款:

    预付 30 元,小票 20 元 → 退 10 元
    再提交一次同样的小票   → 又退 10 元(用户白拿 10 元)

同一个文件里的「买不到」(`/unavailable`)是照着做对了的样板:行锁 +
终态判断。这条用例把两个端点摆在一起,顺带补上它们之间的互斥 ——
先传小票退了差额,再点「买不到」退 `total - keep`,两笔加起来能超过实付。

不变量只有一条,四条路径上都得成立:**Σ退款 ≤ 用户实付**。
"""
from .util import CUSTOMER, RIDER, call, login

customer = login(CUSTOMER)
rider = login(RIDER)

BASE = {
    "pickup_address": "取件点·社区超市", "pickup_lat": 30.6598,
    "pickup_lng": 104.0810,
    "address": "送达点·天府大道 1 号", "lat": 30.6612, "lng": 104.0823,
    "contact_name": "收件人", "contact_phone": "13800002222",
    "no_forbidden": True, "errand_note": "两瓶矿泉水和一包纸巾",
    "goods_budget_cents": 3000,
}


def drain():
    """骑手同时在途上限 3 单,先把手头的送掉,否则抢单 409(与本用例无关)。"""
    for o in call("GET", "/orders", rider):
        if o["status"] in ("accepted", "ready"):
            call("POST", f"/orders/{o['order_no']}/transition", rider,
                 {"to_status": "picked_up"}, expect_error=True)
        if o["status"] in ("accepted", "ready", "picked_up"):
            call("POST", f"/orders/{o['order_no']}/transition", rider,
                 {"to_status": "delivered"}, expect_error=True)


def place():
    """下单 + 支付 + 抢单,返回 (订单号, 用户实付)。"""
    drain()
    o = call("POST", "/errands/buy", customer, dict(BASE))
    no = o["order_no"]
    paid = call("POST", f"/orders/{no}/pay/mock", customer)["total_cents"]
    call("POST", f"/riders/grab/{no}", rider)
    return no, paid


def receipt(no, actual, expect_error=False, url="/uploads/replay.jpg"):
    return call("POST", f"/errands/{no}/receipt", rider,
                {"actual_cents": actual, "receipt_url": url},
                expect_error=expect_error)


def main():
    # ---- 1) 同一张小票重复提交:第二次必须被拒,退款只发生一次 ----
    no, paid = place()
    first = receipt(no, 2000)
    assert first["goods_actual_cents"] == 2000, first
    assert first["refund_cents"] == 1000, first["refund_cents"]
    print(f"✓ 小票 20 元 vs 预付 30 元:退差额 1000 分(实付 {paid})")

    again = receipt(no, 2000, expect_error=True)
    assert "_error" in again, (
        f"小票重复提交没被拒:refund_cents={again['refund_cents']} "
        f"(第一次退了 1000,这一次又退了一遍)")
    assert again["_error"] == 409, again
    now = call("GET", f"/orders/{no}", customer)
    assert now["refund_cents"] == 1000, (
        f"重复提交把退款累计到了 {now['refund_cents']} 分,应停在 1000 分")
    assert now["refund_cents"] <= paid, (now["refund_cents"], paid)
    print(f"✓ 重复提交被拒({again['detail']}),退款仍是 1000 分")

    # 改个金额再提交也不行 —— 重放的本质是"再结一次账",跟金额无关
    other = receipt(no, 1000, expect_error=True)
    assert other.get("_error") == 409, other
    assert call("GET", f"/orders/{no}", customer)["refund_cents"] == 1000
    print("✓ 换个金额重提也被拒(结账只发生一次)")

    # ---- 2) 已结过账的单不能再点「买不到」 ----
    keep = None
    row = call("GET", f"/orders/{no}", customer)
    from app.services.errand import unavailable_fee_cents
    keep = unavailable_fee_cents(row["fee_parts"])
    bad = call("POST", f"/errands/{no}/unavailable", rider,
               {"note": "重放测试"}, expect_error=True)
    assert "_error" in bad, (
        f"传完小票还能点买不到:又退了 {row['total_cents'] - keep} 分,"
        f"累计退款 {bad.get('refund_cents')} > 实付 {paid}")
    assert bad["_error"] == 409, bad
    final = call("GET", f"/orders/{no}", customer)
    assert final["refund_cents"] == 1000, final["refund_cents"]
    assert final["refund_cents"] <= paid, (final["refund_cents"], paid)
    print(f"✓ 已提交小票的单不能再标买不到({bad['detail']}),"
          f"累计退款 {final['refund_cents']} ≤ 实付 {paid}")

    # 把这单走完,别留在骑手手头占额度
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer,
         {"to_status": "completed"})

    # ---- 3) 反过来:标了买不到的单不能再传小票 ----
    no2, paid2 = place()
    row2 = call("GET", f"/orders/{no2}", customer)
    keep2 = unavailable_fee_cents(row2["fee_parts"])
    res = call("POST", f"/errands/{no2}/unavailable", rider, {"note": "货架空了"})
    assert res["status"] == "cancelled", res["status"]
    assert res["refund_cents"] == paid2 - keep2, (res["refund_cents"], paid2)
    late = receipt(no2, 2000, expect_error=True)
    assert late.get("_error") == 409, (
        f"已取消的单还能传小票结账:{late}")
    after = call("GET", f"/orders/{no2}", customer)
    assert after["refund_cents"] == paid2 - keep2, after["refund_cents"]
    assert after["refund_cents"] <= paid2, (after["refund_cents"], paid2)
    print(f"✓ 已取消的单不能再传小票({late['detail']}),"
          f"退款停在 {after['refund_cents']} ≤ 实付 {paid2}")

    # ---- 4) 退款流水之和 == 订单退款汇总(审计规则 5) ----
    import asyncio

    from sqlalchemy import text

    from app.db import SessionLocal

    async def check_flows():
        async with SessionLocal() as db:
            for order_no, expect in ((no, 1000), (no2, paid2 - keep2)):
                total = await db.scalar(text(
                    "SELECT coalesce(sum(amount_cents), 0) FROM refunds "
                    "WHERE order_no = :n AND status <> 'failed'"),
                    {"n": order_no})
                assert total == expect, (
                    f"{order_no} 退款流水之和 {total} ≠ 订单退款汇总 {expect}")
    asyncio.run(check_flows())
    print("✓ 退款流水之和与订单退款汇总一致(每笔退款只发一次)")

    print("\ne2e_errand_receipt_replay 全部通过 ✅")


if __name__ == "__main__":
    main()
