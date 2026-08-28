"""识别「提前点出餐」:出餐是商家自己点的,而它决定了用户还能不能全额退款。

## 为什么要盯这个

判责分摊把分界线划在「出餐」这个动作上,因为它是平台唯一看得见的事实。
但**看得见不等于可信**:出餐之后用户失去全额退款权、商家的餐费也保住了
—— 商家因此有一个明确的动机早点按「出餐」,哪怕锅还没热。

信号是骑手到店之后还要等多久:如实点出餐的话骑手到店就能取走。

## 只标不罚

与等餐补偿同一条立场:治理靠数据不靠罚钱。罚下去商家会改成「等骑手快到了
再点出餐」,数据一样失真,而平台连信号都没了。

这条守两件事:**信号真的会响**(造一单让骑手干等,它要出现在名单里),
以及**只有管理员看得到**。

在 server/ 目录下运行:python -m tests.e2e_early_ready
"""
import asyncio

from sqlalchemy import text

from tests.util import call, demo_shop, login, orderable_dish

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")
shop = demo_shop()
sid = shop["id"]
dish = orderable_dish(call("GET", f"/merchants/{sid}/dishes"))


async def make_rider_wait(order_no: str, minutes: int):
    """把到店时刻往前推,制造「骑手干等 N 分钟」的既成事实。

    走库是因为没有接口能造这个 —— 真等 20 分钟的用例没人愿意跑。
    """
    import sys
    sys.path.insert(0, ".")
    from app.db import SessionLocal, engine
    try:
        async with SessionLocal() as db:
            await db.execute(text("""
                UPDATE orders
                   SET arrived_shop_at = picked_up_at
                       - make_interval(mins => :m)
                 WHERE order_no = :no
            """), {"m": minutes, "no": order_no})
            await db.commit()
    finally:
        await engine.dispose()


def suspects(days=90):
    return call("GET", f"/admin/early-ready-suspects?days={days}", admin)


def one_order(wait_minutes: int) -> str:
    """跑完整的一单,并把骑手到店时刻按 wait_minutes 往前推。

    **跑到 delivered 才收手** —— 骑手同时最多 3 单在途,
    停在 picked_up 的话造到第 4 单就 409。
    """
    no = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "picked_up", "force": True})
    asyncio.run(make_rider_wait(no, wait_minutes))
    # 放门口要配一张照片(顾客说没收到时那张照片替骑手说话),这里交给顾客本人
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "delivered", "handoff": "hand"})
    return no


def main() -> None:
    base = suspects()
    thr = base["wait_threshold_minutes"]
    before = next((x for x in base["items"] if x["merchant_id"] == sid), None)
    before_waited = before["waited_orders"] if before else 0
    before_orders = before["orders"] if before else 0

    # ⚠️ 名单有 min_orders=5 的门槛(一家店只有一两单不该被点名),
    # 所以**用例要自己凑够这 5 单**,不能指望库里本来就有 ——
    # 原来只造 1 单,靠的是开发库里那家演示店攒了几百单,
    # 干净库上这家店压根进不了名单。CI 上就是这么红的。
    #
    # 4 单如实出餐(骑手到店 1 分钟就取走)+ 1 单干等,
    # 这样占比是 1/5 而不是 1/1,顺带把「占比算得对不对」也测了。
    for _ in range(4):
        one_order(1)
    one_order(thr + 10)
    print(f"✓ 造了 5 单:4 单如实出餐,1 单骑手到店后干等 {thr + 10} 分钟")

    now = suspects()
    hit = next((x for x in now["items"] if x["merchant_id"] == sid), None)
    assert hit is not None, (
        "骑手白等了这么久,这家店却没出现在嫌疑名单里 —— 信号是哑的"
        "(名单有 min_orders=5 的门槛,用例已自己凑够)")
    assert hit["waited_orders"] == before_waited + 1, (
        f"可疑单数没涨:{before_waited} → {hit['waited_orders']}")
    assert hit["orders"] == before_orders + 5, (
        f"总单数对不上:{before_orders} + 5 ≠ {hit['orders']} —— "
        f"如实出餐的那 4 单没被算进分母,占比会虚高")
    assert 0 < hit["suspect_ratio"] <= 1, hit
    print(f"✓ 信号响了:{hit['merchant_name']} 可疑 {hit['waited_orders']}/"
          f"{hit['orders']} 单(占比 {hit['suspect_ratio']:.1%},"
          f"平均等待 {hit['avg_wait_minutes']} 分钟)")

    assert now["how_to_read"], "没告诉看的人该怎么理解这个数字"
    print("✓ 带了口径说明(去谈,不要直接扣钱)")

    # 只标不罚:商家的状态不该因此变化
    me = call("GET", "/merchants/me", merchant)
    assert me["status"] == "approved", (
        f"被标了嫌疑就改了商家状态({me['status']})—— 说好的只标不罚")
    print("✓ 只标不罚:商家状态没有被自动改动")

    for who, token in (("商家", merchant), ("骑手", rider), ("用户", customer)):
        err = call("GET", "/admin/early-ready-suspects", token,
                   expect_error=True)
        assert err["_error"] == 403, (who, err)
    print("✓ 只有管理员看得到这份名单(商家/骑手/用户一律 403)")

    print("\ne2e_early_ready 全部通过 ✅")


if __name__ == "__main__":
    main()
