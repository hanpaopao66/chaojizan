"""多骑手调度(顺路多单)验证:并发上限 3 单、抢单池距离与顺路标记、
无定位不报错(退化为按等待时长)。

在 server/ 目录下运行:python -m tests.e2e_multi_order
"""
import asyncio
import time

from tests.util import call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
sid = shop["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"多单测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def make_order(lat=30.66, lng=104.08):
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": lat, "lng": lng,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    return no


async def main():
    await drain_order_pool()  # 清掉历史残留,membership 断言不被池子上限挤爆
    rider = await register_fresh_rider("多单测试骑手")

    # 1) 并发上限:3 单在途后第 4 单 409(追加单不占额度不在此验,交给转单套)
    nos = [make_order() for _ in range(4)]
    for no in nos[:3]:
        call("POST", f"/riders/grab/{no}", rider)
    err = call("POST", f"/riders/grab/{nos[3]}", rider, expect_error=True)
    assert err["_error"] == 409 and "先送完" in err["detail"], err
    print("✓ 并发上限:3 单在途,第 4 单 409")

    # 2) 无定位不报错:distance_m 为空,顺路标记照常
    pool = call("GET", "/riders/available-orders", rider)
    mine4 = next(o for o in pool if o["order_no"] == nos[3])
    assert mine4["distance_m"] is None, mine4["distance_m"]
    assert mine4["same_shop"] is True, "手头单同店应标顺路"
    print("✓ 无定位:distance_m 为空不报错,same_shop 标记正确")

    # 3) 上报位置后:distance_m 有值且合理(骑手就站在店门口 → 距离≈0)
    call("POST", "/riders/location", rider,
         {"lat": shop["lat"], "lng": shop["lng"]})
    pool = call("GET", "/riders/available-orders", rider)
    mine4 = next(o for o in pool if o["order_no"] == nos[3])
    assert mine4["distance_m"] is not None and mine4["distance_m"] < 50, mine4
    print("✓ 有定位:distance_m 正确(店门口 ≈ 0)")

    # 4) same_way:收货点与手头单相近(<800m)标顺路,远的不标
    near = make_order(lat=30.661, lng=104.081)   # 距手头单收货点几百米
    far = make_order(lat=30.685, lng=104.10)     # 距手头单收货点 ~3km(仍在配送半径)
    pool = call("GET", "/riders/available-orders", rider)
    by_no = {o["order_no"]: o for o in pool}
    assert by_no[near]["same_way"] is True, by_no[near]
    assert by_no[far]["same_way"] is False, by_no[far]
    print("✓ same_way:收货点相近标顺路,远的不标")

    # 5) 综合分:同距离下等待久的排前面(新单不永远垫底,老单不被饿死)
    idx_near = list(by_no).index(near)
    idx_4 = list(by_no).index(nos[3])
    assert idx_4 < idx_near, "同店同距离,等得久的 nos[3] 应排在更新的 near 前"
    print("✓ 综合分:距离相同等待久的靠前")

    # 6) 无关骑手(另一个新骑手,无手头单):顺路标记全 false
    rider2 = await register_fresh_rider("多单测试骑手2")
    pool = call("GET", "/riders/available-orders", rider2)
    o = next(o for o in pool if o["order_no"] == nos[3])
    assert o["same_shop"] is False and o["same_way"] is False, o
    print("✓ 无手头单的骑手:顺路标记全 false")

    print("\ne2e_multi_order 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
