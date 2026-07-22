"""骑手接单半径验证:半径过滤、顺路豁免、无定位全量、恢复不限。

在 server/ 目录下运行:python -m tests.e2e_grab_radius
"""
import asyncio
import time

from tests.util import call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")

shop = call("GET", "/merchants/me", merchant)
sid = shop["id"]
call("PATCH", "/merchants/me", merchant, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"半径测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def make_order():
    o = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    return no


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("半径测试骑手")
    no = make_order()

    # 1) 骑手位置在店铺 ~3km 外:设 2km 半径 → 看不到;不限 → 看得到
    call("POST", "/riders/location", rider,
         {"lat": shop["lat"] + 0.028, "lng": shop["lng"]})  # ≈3.1km
    call("PATCH", "/riders/me/preferences", rider, {"grab_radius_km": 2})
    pool = call("GET", "/riders/available-orders", rider)
    assert no not in [o["order_no"] for o in pool], "2km 半径应过滤 3km 外的单"
    saved = call("PATCH", "/riders/me/preferences", rider,
                 {"grab_radius_km": None})
    assert saved["grab_radius_km"] is None
    pool = call("GET", "/riders/available-orders", rider)
    assert no in [o["order_no"] for o in pool], "不限半径应看到"
    print("✓ 半径过滤生效,改回不限恢复")

    # 2) 顺路豁免:手头有同店单时,半径外的同店单也给看
    call("POST", f"/riders/grab/{no}", rider)
    no2 = make_order()
    call("PATCH", "/riders/me/preferences", rider, {"grab_radius_km": 2})
    pool = call("GET", "/riders/available-orders", rider)
    hit = next((o for o in pool if o["order_no"] == no2), None)
    assert hit is not None and hit["same_shop"] is True, "同店顺路单应豁免半径"
    print("✓ 顺路单(同店)豁免半径限制")

    # 3) 无定位:半径设置被忽略,按等待时长全量返回
    rider2 = await register_fresh_rider("半径测试骑手2")
    call("PATCH", "/riders/me/preferences", rider2, {"grab_radius_km": 1})
    pool = call("GET", "/riders/available-orders", rider2)
    assert no2 in [o["order_no"] for o in pool], "无定位应忽略半径"
    print("✓ 无定位时忽略半径设置")

    # 4) 非法半径 422
    err = call("PATCH", "/riders/me/preferences", rider,
               {"grab_radius_km": 99}, expect_error=True)
    assert err["_error"] == 422, err
    print("✓ 非法半径 422")

    print("\ne2e_grab_radius 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
