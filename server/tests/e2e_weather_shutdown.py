"""极端天气停运验证:开关下单 409、自动横幅公告挂/撤、
兜底取消线缩短到 15 分钟、关闭恢复。

在 server/ 目录下运行:python -m tests.e2e_weather_shutdown
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")

sid = call("GET", "/merchants/me", merchant)["id"]
call("PATCH", "/merchants/me", merchant, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"天气测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def order_body():
    return {"merchant_id": sid,
            "items": [{"dish_id": dish["id"], "quantity": 1}],
            "address": "测试地址", "lat": 30.66, "lng": 104.08}


async def backdate_pool(no, minutes):
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET rider_pool_since = now() - interval "
            f"'{minutes} minutes' WHERE order_no = :no"), {"no": no})
        await db.commit()


async def main():
    # 前置:先下一单接好(停运前的存量在途单),用于验证取消线缩短
    o = call("POST", "/orders", customer, order_body())
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})

    call("POST", "/admin/flags/weather_shutdown", admin, {"value": "on"})
    try:
        # 1) 停运中下单 409,文案说明已有订单履约
        err = call("POST", "/orders", customer, order_body(),
                   expect_error=True)
        assert err["_error"] == 409 and "极端天气" in err["detail"], err
        print("✓ 停运中下单 409")

        # 2) 三端横幅公告自动挂出
        anns = call("GET", "/announcements?audience=user")
        assert any(a["title"] == "极端天气临时停运" for a in anns), anns
        print("✓ 停运横幅公告自动挂出(三端公告通道)")

        # 3) 兜底取消线缩短:16 分钟无人接单即取消(平时 30 分钟)
        await backdate_pool(no, 16)
        await sweep_once()
        o2 = call("GET", f"/orders/{no}", customer)
        assert o2["status"] == "cancelled", o2["status"]
        assert o2["refund_cents"] == o2["total_cents"]
        print("✓ 停运中兜底取消线缩短到 15 分钟,全额退款")
    finally:
        call("POST", "/admin/flags/weather_shutdown", admin, {"value": "off"})

    # 4) 关闭恢复:下单成功、公告撤下
    ok = call("POST", "/orders", customer, order_body())
    assert ok["order_no"]
    anns = call("GET", "/announcements?audience=user")
    assert not any(a["title"] == "极端天气临时停运" for a in anns), anns
    print("✓ 关闭后恢复下单,横幅公告自动撤下")

    print("\ne2e_weather_shutdown 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
