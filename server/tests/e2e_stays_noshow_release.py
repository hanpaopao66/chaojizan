"""住宿「未入住」:**只扣首晚,后面几晚的房要还给商家**。

NOSHOW 的判定发生在入住日的**次日**,过去的只有第一晚。原来那条分支
按「日期已过」一次都不回补,后果是订 5 晚没到店的单:

    钱:扣首晚归商家,后 4 晚退给客人   ✓
    房:5 晚的 sold_qty 全都还挂着 1     ✗

后 4 晚商家收不到钱也卖不出去,而且自己救不了 ——
`PUT /stays/me/calendar` 明文禁止把总房量调到低于已售(stays.py),
他连"手动把这几晚清出来"这条路都没有。

在 server/ 目录下运行:python -m tests.e2e_stays_noshow_release
"""
import asyncio
import random
from datetime import date, timedelta

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once

from .util import ADMIN, call, login

admin_token = login(ADMIN)
today = date.today()

phone = "138" + "".join(str(random.randint(0, 9)) for _ in range(8))
mt = call("POST", "/auth/register",
          body={"phone": phone, "password": "hotel123",
                "role": "merchant"})["token"]
shop = call("POST", "/merchants", token=mt, body={
    "name": f"未入住客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST07",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-007",
              "special_license_image_url": "https://example.com/sp.jpg"}})
call("POST", f"/admin/merchants/{shop['id']}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})
rt = call("POST", "/stays/me/room-types", token=mt,
          body={"name": "未入住房", "cancel_policy": "limited_free"})
RT = rt["id"]
call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [RT], "from_date": str(today),
    "to_date": str(today + timedelta(days=30)),
    "price_cents": 10000, "total_qty": 2})

cphone = "137" + "".join(str(random.randint(0, 9)) for _ in range(8))
ct = call("POST", "/auth/register",
          body={"phone": cphone, "password": "guest123",
                "role": "customer"})["token"]

NIGHTS = 5
CHECKIN = today - timedelta(days=2)      # 判定要求「次日中午已过」,退两天最稳
CHECKOUT = CHECKIN + timedelta(days=NIGHTS)


async def sql(stmt, **params):
    async with SessionLocal() as db:
        await db.execute(text(stmt), params)
        await db.commit()


async def sold(day):
    async with SessionLocal() as db:
        return await db.scalar(text(
            "SELECT sold_qty FROM room_calendar WHERE room_type_id = :rt "
            "AND date = :d"), {"rt": RT, "d": day})


async def main():
    # 不能订过去的日期,也不能给过去的日期设房态(两条都是接口硬拦的),
    # 所以先按未来日期正常订、再把订单和房态整体平移到过去 ——
    # 平移后的占用格局与「两天前入住、连住 5 晚」一字不差
    o = call("POST", "/stays/orders", token=ct, body={
        "room_type_id": RT, "checkin_date": str(today),
        "checkout_date": str(today + timedelta(days=NIGHTS)),
        "rooms_qty": 1, "guest_name": "未入住客", "guest_phone": "13700000007"})
    no = o["order_no"]
    call("POST", f"/stays/orders/{no}/pay/mock", token=ct)
    call("POST", f"/stays/me/orders/{no}/confirm", token=mt)
    paid = call("GET", f"/stays/orders/{no}", token=ct)["total_cents"]
    assert paid == 10000 * NIGHTS, paid

    await sql("UPDATE stay_orders SET checkin_date = :ci, checkout_date = :co "
              "WHERE order_no = :no", ci=CHECKIN, co=CHECKOUT, no=no)
    # 房态跟着平移:前两晚补进来(占用 1),末两晚让出去
    for i in (2, 1):
        await sql(
            "INSERT INTO room_calendar (room_type_id, date, price_cents, "
            "total_qty, sold_qty, closed) VALUES (:rt, :d, 10000, 2, 1, false) "
            "ON CONFLICT (room_type_id, date) DO UPDATE SET sold_qty = 1",
            rt=RT, d=today - timedelta(days=i))
    for i in (3, 4):
        await sql("UPDATE room_calendar SET sold_qty = 0 WHERE "
                  "room_type_id = :rt AND date = :d",
                  rt=RT, d=today + timedelta(days=i))

    nights = [CHECKIN + timedelta(days=i) for i in range(NIGHTS)]
    for d in nights:
        assert await sold(d) == 1, f"{d} 平移后应占用 1 间"
    print(f"✓ 起点:{CHECKIN} 起连住 {NIGHTS} 晚,实付 {paid} 分,5 晚各占 1 间")

    # ---- 判未入住 ----
    await sweep_once()
    row = call("GET", f"/stays/orders/{no}", token=ct)
    assert row["status"] == "noshow", row["status"]
    assert row["net_cents"] == 10000, row["net_cents"]      # 首晚归商家
    assert row["fee_cents"] == 0, row["fee_cents"]          # 平台分文不取
    assert row["refund_cents"] == paid - 10000 == 40000, row["refund_cents"]
    assert row["refund_cents"] <= paid, (row["refund_cents"], paid)
    print(f"✓ 未入住:扣首晚 10000 归商家,退 {row['refund_cents']} 分给客人")

    # ---- 房:首晚留着(那一晚商家确实留了房),后 4 晚必须回补 ----
    assert await sold(nights[0]) == 1, "首晚不该回补:那一晚商家确实为他留了房"
    for d in nights[1:]:
        got = await sold(d)
        assert got == 0, (
            f"{d} 的房没回补(sold_qty={got}):客人的钱退了、房还锁着,"
            "商家收不到钱也卖不出去,而且改总量会被「不能低于已售」拦住")
    print(f"✓ 首晚保留占用,{nights[1]} 起 4 晚房态已回补")

    # 回补不是把数字抹掉:这几晚真的能再卖出去。
    #
    # 只买得到今天起的那几晚 —— 下单接口硬拦「入住日期不能早于今天」,
    # 而这条拦截是对的:**昨天那一晚在真实世界里也没有任何人能再订**,
    # 商家救不回来的是日历,不是这条回补逻辑。所以再售只覆盖
    # nights[1:] 里今天及以后的部分,昨晚那一格由上面的 sold_qty == 0
    # 断言把关(它才是「房还给商家了」的证据)
    resale_nights = [d for d in nights[1:] if d >= today]
    assert len(resale_nights) == 3, resale_nights
    resale = call("POST", "/stays/orders", token=ct, body={
        "room_type_id": RT, "checkin_date": str(resale_nights[0]),
        "checkout_date": str(CHECKOUT), "rooms_qty": 2,
        "guest_name": "补位客", "guest_phone": "13700000008"},
        expect_error=True)
    assert "_error" not in resale, (
        f"回补后的房卖不出去:{resale.get('detail')}")
    assert resale["total_cents"] == 10000 * len(resale_nights) * 2, \
        resale["total_cents"]
    print(f"✓ 回补的 {len(resale_nights)} 晚满房(2 间)可再售出 —— 商家救得回来")

    # ---- 幂等:再扫一遍不能二次回补 ----
    # 二次回补会把 sold_qty 再减一次:卖掉的那几晚从 2 掉到 1,
    # 没卖掉的那晚从 0 掉到 -1 —— 两种都抓得住
    await sweep_once()
    assert await sold(nights[0]) == 1
    for d in nights[1:]:
        want = 2 if d in resale_nights else 0
        got = await sold(d)
        assert got == want, f"{d} 被二次回补了(sold_qty={got},应为 {want})"
    fin = call("GET", f"/stays/orders/{no}", token=ct)
    assert fin["refund_cents"] == 40000 and fin["net_cents"] == 10000, fin
    print("✓ 幂等:重复清扫不二次回补、金额不变")

    print("\ne2e_stays_noshow_release 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
