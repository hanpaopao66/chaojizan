"""多城市运营隔离验证:A 城骑手看不到 B 城单、未标注不隔离(存量宽限)、
后台按城筛与人工改城、开城清单外商家开店 409、逆地理未配置降级人工。

在 server/ 目录下运行:python -m tests.e2e_multi_city
"""
import asyncio
import time
from urllib.parse import quote

from tests.util import call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"城市测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def make_paid_order():
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    return no


def pool(rider):
    return [o["order_no"] for o in
            call("GET", "/riders/available-orders?lat=30.66&lng=104.08", rider)]


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("城市测试骑手")
    rider_id = call("GET", "/auth/me", rider)["id"]

    # 0) 逆地理未配置(测试环境无 key):商家/骑手 city 留空 = 人工填,先确认降级
    shop = next(m for m in call("GET", "/admin/merchants?status=approved",
                                admin) if m["id"] == sid)
    assert "city" in shop  # 字段存在;seed 店未回填时为空

    # 1) 未标注城市:不隔离,单子大家都看得见(存量宽限)
    call("POST", f"/admin/merchants/{sid}/city", admin, {"city": ""})
    no1 = make_paid_order()
    assert no1 in pool(rider)
    print("✓ 未标注城市不隔离(存量宽限)")

    # 2) A 城骑手看不到 B 城单:商家=成都市,骑手=绵阳市
    call("POST", f"/admin/merchants/{sid}/city", admin, {"city": "成都市"})
    call("POST", f"/admin/riders/{rider_id}/city", admin, {"city": "绵阳市"})
    assert no1 not in pool(rider)
    # 同城即可见
    call("POST", f"/admin/riders/{rider_id}/city", admin, {"city": "成都市"})
    assert no1 in pool(rider)
    print("✓ 跨城看不到、同城看得到")

    # 3) 后台按城筛
    listed = call("GET", "/admin/merchants?city=" + quote("成都市"), admin)
    assert any(m["id"] == sid for m in listed)
    listed = call("GET", "/admin/merchants?city=" + quote("绵阳市"), admin)
    assert not any(m["id"] == sid for m in listed)
    cities = call("GET", "/admin/cities", admin)
    assert any(c["city"] == "成都市" for c in cities["cities"])
    print("✓ 后台城市筛选与城市清单")

    # 4) 开城清单:清单外城市商家开店 409(文案:即将开通);清单内正常
    call("POST", "/admin/flags/open_cities", admin, {"value": "绵阳市"})
    try:
        err = call("PATCH", "/merchants/me", merchant, {"is_open": True},
                   expect_error=True)
        assert err["_error"] == 409 and "即将开通" in err["detail"], err
        call("POST", "/admin/flags/open_cities", admin,
             {"value": "绵阳市,成都市"})
        call("PATCH", "/merchants/me", merchant, {"is_open": True})
        print("✓ 开城清单外不可营业,加入清单后正常开店")
    finally:
        call("POST", "/admin/flags/open_cities", admin, {"value": ""})
        call("POST", f"/admin/merchants/{sid}/city", admin, {"city": ""})
        call("POST", f"/admin/riders/{rider_id}/city", admin, {"city": ""})
        call("PATCH", "/merchants/me", merchant, {"is_open": True})

    # 清场:把测试单转掉
    call("POST", f"/riders/grab/{no1}", rider)
    call("POST", f"/riders/transfer/{no1}", rider, {"reason": "other"})
    print("\ne2e_multi_city 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
