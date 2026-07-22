"""深夜配送信息保护与地址精度验证:保护单骑手视角粗地址+中性称呼/
用户本人全量、临时放行后骑手可见完整门牌、送达照片仅用户可见、
深夜保护单无照片送达 422(时间敏感断言按当前时段分支)、
骑手地址反馈两次触发下单核对提示。

在 server/ 目录下运行:python -m tests.e2e_address_privacy
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from tests.util import call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"保护测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})

FULL_ADDR = "锦江花园 3栋2单元501"
PUBLIC_ADDR = "锦江花园 3栋"


def make_protected_order():
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": FULL_ADDR, "lat": 30.66, "lng": 104.08,
        "contact_name": "王小美",
        "addr_protect": True, "address_public": PUBLIC_ADDR,
        "salutation": "王女士"})
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    return no


def is_night():
    bj = datetime.now(timezone.utc) + timedelta(hours=8)
    return bj.hour >= 21 or bj.hour < 6


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("保护测试骑手")

    # 1) 保护单:骑手视角粗地址+中性称呼;用户本人全量
    no = make_protected_order()
    call("POST", f"/riders/grab/{no}", rider)
    rv = call("GET", f"/orders/{no}", rider)
    assert rv["address"] == PUBLIC_ADDR, rv["address"]
    assert "501" not in rv["address"]
    assert rv["contact_name"] == "王女士"
    assert rv["lat"] == 30.66  # 坐标保留,导航要用
    mine = call("GET", f"/orders/{no}", customer)
    assert mine["address"] == FULL_ADDR and mine["contact_name"] == "王小美"
    print("✓ 保护单骑手只见粗地址+中性称呼,用户本人全量,坐标保留")

    # 2) 临时放行:骑手可见完整门牌
    call("POST", f"/orders/{no}/reveal-address", customer)
    rv = call("GET", f"/orders/{no}", rider)
    assert rv["address"] == FULL_ADDR and rv["addr_revealed"] is True
    print("✓ 用户临时放行后骑手可见完整门牌")

    # 3) 送达照片:存档且仅用户/平台可见;深夜无照片 422(按时段分支)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    no2 = make_protected_order()  # 备一单测无照片分支
    if is_night():
        err = call("POST", f"/orders/{no}/transition", rider,
                   {"to_status": "delivered"}, expect_error=True)
        assert err["_error"] == 422 and "拍照" in err["detail"], err
        print("✓ 深夜保护单无照片送达 422")
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "delivered",
          "photo_url": "https://x/door_photo.jpg"})
    mine = call("GET", f"/orders/{no}", customer)
    assert mine["delivery_photo_url"] == "https://x/door_photo.jpg"
    rv = call("GET", f"/orders/{no}", rider)
    assert rv["delivery_photo_url"] == "", "留证照片不给骑手侧回看"
    print("✓ 送达照片存档,仅用户/平台可见")

    # 4) 地址反馈:每单一条,两条后下单提示核对(不拦截)
    call("POST", f"/riders/grab/{no2}", rider)
    call("POST", f"/orders/{no2}/address-feedback", rider,
         {"note": "小区门禁进不去"})
    err = call("POST", f"/orders/{no2}/address-feedback", rider,
               {"note": "再报一次"}, expect_error=True)
    assert err["_error"] == 409
    call("POST", f"/orders/{no}/address-feedback", rider,
         {"note": "楼栋标识不清"})
    order3 = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": FULL_ADDR, "lat": 30.66, "lng": 104.08})
    assert "请核对门牌" in order3["promo_note"], order3["promo_note"]
    print("✓ 地址反馈每单一条,两条后下单提示核对(不拦截)")

    # 清场
    call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no2}/transition", rider,
         {"to_status": "picked_up"})
    call("POST", f"/orders/{no2}/transition", rider,
         {"to_status": "delivered", "photo_url": "https://x/p.jpg"})
    call("POST", f"/orders/{order3['order_no']}/transition", customer,
         {"to_status": "cancelled", "reason": "测试清场"})
    print("\ne2e_address_privacy 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
