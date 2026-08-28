"""判责能被质疑:用户对自动分摊、对「按送达处理」都能申诉,改判要真退钱。

## 为什么这条必须有

出餐后取消的分摊是**系统按口径自动判的,没有人看过**。自动判责必须配一个
能找人的口子,否则「谁的问题谁负责」里的「谁的问题」就成了系统单方面说了算。

另一格以前完全是空的:骑手报「联系不上顾客」、平台判按送达处理,于是用户
付了全款、一口没吃到,**连说话的地方都没有** —— 骑手能申诉判他责的,
用户不能申诉判他责的。判谁责谁就该能申诉,这是对称的。

## 还守一件事:改判之后审计不许报假红灯

改判会让平台额外退一笔,「商家 + 骑手 + 退款」就超过用户实付了。
审计不认得这块的话,每一次申诉成立都红一条 —— 而假红灯多了,真红灯没人看。

在 server/ 目录下运行:python -m tests.e2e_cancel_appeal
"""
import asyncio
import time

from tests.util import call, demo_shop, login

customer = call("POST", "/auth/register",
                body={"phone": f"138{int(time.time()) % 100000000:08d}",
                      "password": "123456", "name": "申诉测试",
                      "role": "customer"})["token"]
merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")
shop = demo_shop()
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"申诉测试菜-{int(time.time())}",
             "price_cents": 2000, "stock": 99})


def cancelled_split_order():
    """造一单走到配送中,然后按分摊取消。返回订单号。"""
    no = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "picked_up", "force": True})
    q = call("GET", f"/orders/{no}/cancel-quote", customer)
    call("POST", f"/orders/{no}/cancel-with-split", customer,
         {"agreed_stage": q["stage"], "agreed_refund_cents": q["refund_cents"]})
    return no


async def audit_problems():
    """跑一次账务自检。

    **跑完必须 dispose。** 这个脚本要在改判前后各跑一次自检,而每次
    `asyncio.run` 都是一个新事件循环 —— 模块级 engine 的连接还绑在上一个
    循环上,第二次就炸「attached to a different loop」。
    """
    import sys
    sys.path.insert(0, ".")
    from app.db import engine
    from app.services.audit import run_audit
    try:
        return await run_audit()
    finally:
        await engine.dispose()


def main() -> None:
    base = asyncio.run(audit_problems())
    base_split = [p for p in base
                  if p["check"].startswith("cancel_split")]
    assert not base_split, f"跑之前就有分摊告警:{base_split}"

    # ---------- 1) 对自动分摊申诉 ----------
    no = cancelled_split_order()
    order = call("GET", f"/orders/{no}", customer)
    # 用户承担的 = 已付 − 已退。配送中取消时他一分没拿回,
    # 也就是餐费(归商家)+ 配送费(归骑手)两笔都由他承担
    paid = (max(order["food_cents"] + order["packing_fee_cents"]
                - order["discount_cents"], 0)
            + order["delivery_fee_cents"] + order["tip_cents"])
    borne = paid - order["refund_cents"]
    assert order["refund_cents"] == 0, order
    assert borne == paid, "配送中取消,用户应当是一分没拿回"

    ap = call("POST", "/appeals", customer, {
        "target_type": "cancel_split", "target_id": order["id"],
        "reason": "商家把菜做错了,不该由我承担餐费"})
    assert ap["status"] == "open", ap
    print(f"✓ 用户能对自动分摊申诉(申诉 #{ap['id']})")

    # 同一单不能申诉两次
    dup = call("POST", "/appeals", customer, {
        "target_type": "cancel_split", "target_id": order["id"],
        "reason": "再来一次试试"}, expect_error=True)
    assert dup["_error"] == 409, dup
    print("✓ 一单一次,重复申诉 409")

    # 别人的单申诉不了
    other = call("POST", "/appeals", merchant, {
        "target_type": "cancel_split", "target_id": order["id"],
        "reason": "我是商家我来申诉"}, expect_error=True)
    assert other["_error"] == 403, other
    print("✓ 取消分摊只有下单本人能申诉")

    mine = call("GET", "/appeals/mine", customer)
    assert any(a["id"] == ap["id"] for a in mine), mine
    print(f"✓ 用户能看到自己的申诉列表({len(mine)} 条)")

    # ---------- 2) 平台改判,必须真退钱 ----------
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:商家出错,不该由用户承担"})
    after = call("GET", f"/orders/{no}", customer)
    assert after["refund_cents"] == borne, (
        f"改判了却只退了 {after['refund_cents']} 分,用户承担的是 {borne} 分 —— "
        f"申诉成立却拿不回钱,这个通道就是摆设")
    print(f"✓ 改判后 {borne} 分全额原路退回 —— 用户承担的是餐费 + 配送费两笔,"
          f"平台认亏,不向已经把活干完的商家和骑手追款")

    # ---------- 3) 改判之后审计不许报假红灯 ----------
    now = asyncio.run(audit_problems())
    bad = [p for p in now if p["check"].startswith("cancel_split")]
    assert not bad, (
        f"申诉成立之后审计报了 {len(bad)} 条:{[p['detail'][:80] for p in bad]}"
        f" —— 假红灯多了,真红灯就没人看了")
    print("✓ 改判之后审计仍然干净(平台补退的那块被认出来了,不是错账)")

    # ---------- 4) 出餐前的单没有分摊,不给申诉 ----------
    no2 = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no2}/pay/mock", customer)
    call("POST", f"/orders/{no2}/self-refund", customer)
    o2 = call("GET", f"/orders/{no2}", customer)
    err = call("POST", "/appeals", customer, {
        "target_type": "cancel_split", "target_id": o2["id"],
        "reason": "我想申诉这一单的分摊"}, expect_error=True)
    assert err["_error"] == 409, err
    print("✓ 全额退款的单没有分摊可申诉(409,不是把人放进来再说没得判)")

    print("\ne2e_cancel_appeal 全部通过 ✅")


if __name__ == "__main__":
    main()
