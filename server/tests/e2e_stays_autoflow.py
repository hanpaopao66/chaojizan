"""住宿自动流转:超时关单回补、noshow 扣首晚零佣、自动离店结算、幂等。

直连数据库把时间戳/日期改到过去,手动调 sweep_once(跑两遍验幂等)。
在 server/ 目录下运行:python -m tests.e2e_stays_autoflow
"""
import asyncio
import random
from datetime import date, timedelta

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from tests.util import ADMIN, call, login

admin_token = login(ADMIN)
today = date.today()

phone = "138" + "".join(str(random.randint(0, 9)) for _ in range(8))
mt = call("POST", "/auth/register",
          body={"phone": phone, "password": "hotel123",
                "role": "merchant"})["token"]
shop = call("POST", "/merchants", token=mt, body={
    "name": f"清扫客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST06",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-006",
              "special_license_image_url": "https://example.com/sp.jpg"}})
call("POST", f"/admin/merchants/{shop['id']}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})
rt = call("POST", "/stays/me/room-types", token=mt,
          body={"name": "清扫房", "cancel_policy": "limited_free"})
call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt["id"]], "from_date": str(today),
    "to_date": str(today + timedelta(days=30)),
    "price_cents": 10000, "total_qty": 2})

cphone = "137" + "".join(str(random.randint(0, 9)) for _ in range(8))
ct = call("POST", "/auth/register",
          body={"phone": cphone, "password": "guest123",
                "role": "customer"})["token"]


def book(ci, co, pay=True):
    o = call("POST", "/stays/orders", token=ct, body={
        "room_type_id": rt["id"], "checkin_date": str(ci),
        "checkout_date": str(co), "rooms_qty": 1,
        "guest_name": "清扫客", "guest_phone": "13700000004"})
    if pay:
        call("POST", f"/stays/orders/{o['order_no']}/pay/mock", token=ct)
    return o["order_no"]


async def sql(stmt, **params):
    async with SessionLocal() as db:
        await db.execute(text(stmt), params)
        await db.commit()


def sold_on(day):
    grid = call("GET", f"/stays/me/calendar?from_date={day}&days=1", token=mt)
    return grid[0]["days"][0]["sold_qty"]


async def main():
    ci, co = today + timedelta(days=5), today + timedelta(days=7)

    # 1) 支付超时关单 + 回补
    no1 = book(ci, co, pay=False)
    assert sold_on(ci) == 1
    await sql("UPDATE stay_orders SET created_at = now() - interval "
              "'20 minutes' WHERE order_no = :no", no=no1)
    await sweep_once()
    o = call("GET", f"/stays/orders/{no1}", token=ct)
    assert o["status"] == "closed" and "超时" in o["refund_note"], o
    assert sold_on(ci) == 0, "关单后库存应回补"
    print("✓ 待支付 20 分钟 → 自动关单并回补库存")

    # 2) noshow:已确认、入住日改到前天 → 扣首晚归商家(fee=0),其余退
    no2 = book(ci, co)
    call("POST", f"/stays/me/orders/{no2}/confirm", token=mt)
    await sql("UPDATE stay_orders SET checkin_date = :ci, checkout_date = :co "
              "WHERE order_no = :no",
              ci=today - timedelta(days=2), co=today, no=no2)
    await sweep_once()
    o = call("GET", f"/stays/orders/{no2}", token=ct)
    assert o["status"] == "noshow", o["status"]
    assert o["net_cents"] == 10000 and o["fee_cents"] == 0
    assert o["refund_cents"] == 10000
    print("✓ noshow → 扣首晚 10000 归商家(平台 0 佣),其余 10000 退用户")

    # 3) 自动离店:在住、退房日改到前天 → completed + 5% 结算
    no3 = book(ci, co)
    call("POST", f"/stays/me/orders/{no3}/confirm", token=mt)
    call("POST", f"/stays/me/orders/{no3}/checkin", token=mt)
    await sql("UPDATE stay_orders SET checkout_date = :co WHERE order_no = :no",
              co=today - timedelta(days=2), no=no3)
    await sweep_once()
    o = call("GET", f"/stays/orders/{no3}", token=ct)
    assert o["status"] == "completed", o["status"]
    assert o["fee_cents"] == 1000 and o["net_cents"] == 19000
    print("✓ 商家忘办离店 → 次日自动 completed,佣金 5%")

    # 4) 幂等:再跑一遍,三单状态与金额不变、库存不双倍回补
    before = (o["fee_cents"], o["net_cents"], sold_on(ci))
    await sweep_once()
    o1 = call("GET", f"/stays/orders/{no1}", token=ct)
    o3 = call("GET", f"/stays/orders/{no3}", token=ct)
    assert o1["status"] == "closed" and o3["status"] == "completed"
    assert (o3["fee_cents"], o3["net_cents"], sold_on(ci)) == before
    print("✓ 清扫幂等:重复跑状态/金额/库存不变")

    print("PASS e2e_stays_autoflow")


asyncio.run(main())
