"""退款金额上限:**Σ退款 ≤ 用户实付**,total_cents 永不为负。

## 为什么单开一条

满减是**整单**优惠,而缺货退款是**单菜**操作。退款金额如果按菜单原价算,
用户就把从来没付过的那部分优惠也退走了:

    下单 food=5300 满减=2000 配送=300 → 用户实付 3600
    退掉 4500 的那道菜 → 按原价退 4500,比实付还多 900
    total_cents = 3600 - 4500 = -900

负的 total_cents 会顺着 settlement 的 gross 一路传下去,商家净额为负、
钱包被倒扣,而公开账本(services/ledger)读的就是这些数。

## 口径

满减**不整单回收**(用户不会因为退了一道菜而突然不满门槛、要补差价),
而是按该菜在餐品总额中的占比分摊:

    退款 = 原价×份数 - (满减 + 平台补贴) × 原价×份数 / 当前 food_cents

用户留下的那部分继续享受同样的折扣率,平台/商家各自认自己那一份成本。
这样订单自洽式 total = food + 打包 - 满减 + 配送 + 小费 - 补贴 天然守恒
(审计规则 3 就是这条),而且 Σ退款 ≤ 实付 是它的推论。
"""
import asyncio

from .util import ADMIN, CUSTOMER, MERCHANT, RIDER, call, demo_shop, login

customer = login(CUSTOMER)
merchant = login(MERCHANT)
rider = login(RIDER)
admin = login(ADMIN)

SHOP = demo_shop()
# 满 50 减 20:门槛低于本单餐费,退掉大菜后剩余餐费(8 元)远低于满减额,
# 正是"按原价退就会退超"的那种单
PROMO = [{"threshold_cents": 5000, "off_cents": 2000}]


def identity(o):
    """订单金额自洽式(审计规则 3):实付 = 菜品+打包-满减+配送+小费-补贴。"""
    return (o["food_cents"] + o["packing_fee_cents"] - o["discount_cents"]
            + o["delivery_fee_cents"] + o["tip_cents"] - o["subsidy_cents"])


def place(dishes, tag=""):
    o = call("POST", "/orders", customer, {
        "merchant_id": SHOP["id"],
        "items": dishes,
        "address": f"退款上限测试{tag}", "lat": 30.66, "lng": 104.08,
    })
    call("POST", f"/orders/{o['order_no']}/pay/mock", customer)
    return o


async def main():
    call("PATCH", "/merchants/me", merchant, {"promo_rules": PROMO})
    try:
        await run()
    finally:
        call("PATCH", "/merchants/me", merchant, {"promo_rules": []})
        print("(已撤回满减规则)")


async def run():
    import time
    tag = str(int(time.time()))
    big = call("POST", "/merchants/me/dishes", merchant,
               {"name": f"上限测试招牌菜-{tag}", "price_cents": 4500,
                "stock": 50})
    small = call("POST", "/merchants/me/dishes", merchant,
                 {"name": f"上限测试小菜-{tag}", "price_cents": 800,
                  "stock": 50})

    # ---- 1) 满减单退一道菜:不能退超实付 ----
    o = place([{"dish_id": big["id"], "quantity": 1},
               {"dish_id": small["id"], "quantity": 1}], tag)
    no = o["order_no"]
    fee = o["delivery_fee_cents"]
    paid = o["total_cents"]                      # 用户实付
    assert o["food_cents"] == 5300, o
    assert o["discount_cents"] == 2000, f"满减没生效:{o['promo_note']}"
    assert o["subsidy_cents"] == 0, o            # 演示号不是新用户,无立减
    assert o["packing_fee_cents"] == 0, o
    assert paid == 5300 - 2000 + fee, (paid, fee)
    print(f"✓ 下单:餐品 5300 - 满减 2000 + 配送 {fee} = 实付 {paid}")

    # 分摊:2000 × 4500/5300 = 1698(向下取整,零头算用户的)
    share = 2000 * 4500 // 5300
    assert share == 1698, share
    r = call("POST", f"/orders/{no}/refund-item", merchant,
             {"dish_id": big["id"], "quantity": 1})
    assert r["refund_cents"] == 4500 - share == 2802, (
        f"退款 {r['refund_cents']} 分,应为原价 4500 摊掉满减 {share} 后的 2802 分")
    assert r["total_cents"] == paid - 2802, (r["total_cents"], paid)
    assert r["total_cents"] == 498 + fee, r["total_cents"]
    assert r["food_cents"] == 800, r["food_cents"]
    assert r["discount_cents"] == 2000 - share == 302, r["discount_cents"]
    assert r["total_cents"] == identity(r), (r["total_cents"], identity(r))
    assert r["refund_cents"] <= paid, f"退了 {r['refund_cents']},用户只付了 {paid}"
    assert r["commission_cents"] == int((800 - 302)
                                        * float(SHOP["commission_rate"])), r
    print(f"✓ 退招牌菜×1:退 {r['refund_cents']} 分(≤ 实付 {paid}),"
          f"剩余实付 {r['total_cents']} 分,金额自洽式成立")

    # ---- 2) 接着把剩下的也退光:两次退款之和仍不超实付 ----
    r2 = call("POST", f"/orders/{no}/refund-item", merchant,
              {"dish_id": small["id"], "quantity": 1})
    assert r2["status"] == "cancelled", r2["status"]
    assert r2["refund_cents"] == paid, (
        f"退光后累计退款 {r2['refund_cents']} ≠ 用户实付 {paid}")
    assert r2["total_cents"] == 0, r2["total_cents"]
    print(f"✓ 再退光剩余:累计退款 {r2['refund_cents']} == 实付 {paid},实付归零")

    # ---- 3) 一次退多份:占比按份数算 ----
    o3 = place([{"dish_id": big["id"], "quantity": 2}], tag + "b")
    no3, paid3, fee3 = (o3["order_no"], o3["total_cents"],
                        o3["delivery_fee_cents"])
    assert o3["food_cents"] == 9000 and o3["discount_cents"] == 2000, o3
    assert paid3 == 9000 - 2000 + fee3, o3
    share3 = 2000 * 4500 // 9000
    assert share3 == 1000, share3
    r3 = call("POST", f"/orders/{no3}/refund-item", merchant,
              {"dish_id": big["id"], "quantity": 1})
    assert r3["refund_cents"] == 4500 - 1000 == 3500, r3["refund_cents"]
    assert r3["total_cents"] == paid3 - 3500, (r3["total_cents"], paid3)
    assert r3["total_cents"] == identity(r3), (r3["total_cents"], identity(r3))
    assert r3["refund_cents"] <= paid3, (r3["refund_cents"], paid3)
    print(f"✓ 退 1/2 份:摊掉满减 {share3},退 {r3['refund_cents']} 分,自洽式成立")

    # ---- 4) 走完这单,商家结算净额不能为负 ----
    call("POST", f"/orders/{no3}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no3}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no3}", rider)
    call("POST", f"/orders/{no3}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no3}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no3}/transition", customer, {"to_status": "completed"})

    from sqlalchemy import text

    from app.db import SessionLocal
    async with SessionLocal() as db:
        row = (await db.execute(text(
            "SELECT food_cents, commission_cents, net_cents FROM "
            "merchant_earnings WHERE order_no = :n AND kind = 'earning'"),
            {"n": no3})).first()
    assert row is not None, "完成单没有商家入账"
    food_row, comm_row, net_row = row
    # 剩 1 份 4500,满减余额 1000 → 商家应收 3500,佣金 4%
    assert food_row == 3500, f"商家应收口径 {food_row},应为 4500-1000=3500"
    assert net_row == food_row - comm_row, (net_row, food_row, comm_row)
    assert net_row > 0, f"商家净额 {net_row} 不该为负(退款不能倒扣商家)"
    print(f"✓ 结算:商家应收 {food_row} - 佣金 {comm_row} = 净额 {net_row}(不为负)")

    # ---- 4.5) 整单缺货退款之后,恒等式仍要成立 ----
    #
    # 整单缺货那条路径把 菜/打包/满减/补贴/实付/佣金 全置 0,**唯独漏了配送费**
    # (和小费)。于是 total(0) ≠ 0+0-0+配送费+小费-0 —— 254 单已取消订单
    # 因此不自洽,而审计规则 3 又把已取消单整个排除在外,所以一直没人看见。
    #
    # 这单带小费下:小费和配送费同样是「取餐前取消、骑手一分没拿」,
    # 漏掉哪一个恒等式都不成立。
    tipped = call("POST", "/orders", customer, {
        "merchant_id": SHOP["id"],
        "items": [{"dish_id": big["id"], "quantity": 1}],
        "address": "整单缺货测试", "lat": 30.66, "lng": 104.08,
        "tip_cents": 300,
    })
    call("POST", f"/orders/{tipped['order_no']}/pay/mock", customer)
    paid = call("GET", f"/orders/{tipped['order_no']}", customer)
    assert paid["delivery_fee_cents"] > 0 and paid["tip_cents"] == 300, paid
    call("POST", f"/orders/{tipped['order_no']}/refund-item", merchant,
         {"dish_id": big["id"], "quantity": 1})
    done = call("GET", f"/orders/{tipped['order_no']}", customer)
    assert done["status"] == "cancelled", done["status"]
    assert done["total_cents"] == identity(done), (
        f"整单缺货退款后恒等式不成立:实付 {done['total_cents']} ≠ "
        f"{identity(done)}(配送费 {done['delivery_fee_cents']}、"
        f"小费 {done['tip_cents']} 没跟着清零)")
    assert done["refund_cents"] == paid["total_cents"], (
        f"退的钱和用户实付对不上:退 {done['refund_cents']} vs "
        f"实付 {paid['total_cents']}")
    print("✓ 整单缺货退款:配送费与小费一并清零,恒等式成立,退款等于实付")

    # ---- 5) 账务自检不能被这几单带红 ----
    from app.services.audit import run_audit
    problems = await run_audit()
    mine = {no, no3, tipped['order_no']}
    bad = [p for p in problems
           if any(x in str(p.get("detail", "")) for x in mine)]
    assert not bad, f"退款上限用例把账务自检带红了:{bad}"
    print("✓ 账务自检:本用例的订单全绿")

    for d in (big, small):
        call("PATCH", f"/merchants/me/dishes/{d['id']}", merchant,
             {"is_on_sale": False})
    print("\ne2e_refund_bounds 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
