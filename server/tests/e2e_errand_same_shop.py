"""跑腿单在抢单池里不算「同店」。

同城的跑腿单都挂在同一个「本城跑腿服务」主体上(services/errand)。抢单池原来按 merchant_id 判同店:
骑手手上有一张跑腿单时,池子里别的跑腿单全成了「同店」—— 排序拿同店加分、还豁免他自设的接单半径,
可这些单的取件点散在全城,根本不在一处。那个服务主体的坐标又是 (0, 0),没取件的在途跑腿单
拿它当「下一站」,顺路判断的参照点就跑到了几内亚湾。

在 server/ 目录下运行:python -m tests.e2e_errand_same_shop
"""
import asyncio

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from tests.util import CUSTOMER, call, drain_order_pool, login, register_fresh_rider

customer = login(CUSTOMER)

PICKUP = {"pickup_address": "取件点·人民路 5 号", "pickup_lat": 30.6598,
          "pickup_lng": 104.0810, "pickup_contact_name": "寄件人",
          "pickup_contact_phone": "13800001111"}
DROP = {"address": "送达点·天府大道 1 号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "收件人", "contact_phone": "13800002222"}


def errand() -> str:
    o = call("POST", "/errands", customer, {
        **PICKUP, **DROP, "errand_note": "一份文件", "no_forbidden": True})
    call("POST", f"/orders/{o['order_no']}/pay/mock", customer)
    return o["order_no"]


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("跑腿同店测试骑手")

    first = errand()
    call("POST", f"/riders/grab/{first}", rider)
    second = errand()

    pool = call("GET", "/riders/available-orders", rider)
    row = next((x for x in pool if x["order_no"] == second), None)
    assert row is not None, "第二张跑腿单应当在池子里"
    assert row["same_shop"] is False, "跑腿单挂在同一个服务主体上,不能因此算「同店」"
    print("✓ 手上有一张跑腿单时,别的跑腿单不算同店")

    # 收尾:第二单没人接,按无人接单取消(全额退款);第一单走完
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET rider_pool_since = now() - interval '45 minutes', "
            "created_at = now() - interval '45 minutes' WHERE order_no = :no"), {"no": second})
        await db.commit()
    await sweep_once()
    call("POST", f"/errands/{first}/picked-photo", rider, {"photo_url": "/uploads/errand-demo.jpg"})
    call("POST", f"/orders/{first}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{first}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{first}/transition", customer, {"to_status": "completed"})
    print("\ne2e_errand_same_shop 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
