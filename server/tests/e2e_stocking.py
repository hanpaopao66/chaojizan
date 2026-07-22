"""高峰备货建议验证:建议值=同餐段日销量 P80、库存充足不进清单、
数据不足标积累中、一键采纳补库存并解除估清、饭点提醒 Redis 防重。

在 server/ 目录下运行:python -m tests.e2e_stocking
"""
import asyncio
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from tests.util import call, login

admin = login("13800000000")
ts = int(time.time())

# 10 天午市销量:P80 = sorted[ceil(0.8*10)-1] = 第 8 个 = 9
LUNCH_QTY = [2, 3, 4, 5, 6, 7, 8, 9, 10, 20]
P80_EXPECT = 9


def fresh_merchant(name):
    phone = f"139{random.randrange(10**8, 10**9) % 10**8:08d}"
    call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "role": "merchant",
        "name": name})
    token = login(phone)
    shop = call("POST", "/merchants", token, {
        "name": name, "address": "备货测试地址", "lat": 30.66, "lng": 104.08,
        "license_no": f"JY{ts}b", "license_image_url": "https://x/lic.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    call("PATCH", "/merchants/me", token, {"is_open": True})
    return token, shop["id"]


async def inject_lunch_sale(merchant_id, dish_id, name, qty, days_ago):
    from app.db import SessionLocal
    from app.models import Order
    from app.services.settlement import settle_order
    from app.state_machine import OrderStatus

    total = 1000 * qty
    bj = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(
        hour=12, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    async with SessionLocal() as db:
        order = Order(
            order_no=uuid.uuid4().hex[:20],
            customer_id=1, merchant_id=merchant_id,
            status=OrderStatus.COMPLETED,
            items=[{"dish_id": dish_id, "name": name, "options": [],
                    "price_cents": 1000, "quantity": qty}],
            food_cents=total, packing_fee_cents=0, discount_cents=0,
            subsidy_cents=0, promo_note="", delivery_fee_cents=0,
            tip_cents=0, total_cents=total,
            commission_cents=int(total * 0.05),
            address="到店自取", lat=30.66, lng=104.08,
            pickup=True, pickup_code="0000",
        )
        db.add(order)
        await db.flush()
        order.created_at = (bj - timedelta(hours=8)).replace(
            tzinfo=timezone.utc)
        await settle_order(db, order)
        await db.commit()


async def main():
    merchant, sid = fresh_merchant(f"备货测试店-{ts}")
    low = call("POST", "/merchants/me/dishes", merchant,
               {"name": "缺货面", "price_cents": 1000, "stock": 3})
    high = call("POST", "/merchants/me/dishes", merchant,
                {"name": "充足饭", "price_cents": 1000, "stock": 50})
    new = call("POST", "/merchants/me/dishes", merchant,
               {"name": "新品汤", "price_cents": 1000, "stock": 5})

    for days_ago, qty in enumerate(LUNCH_QTY, start=1):
        await inject_lunch_sale(sid, low["id"], "缺货面", qty, days_ago)
        await inject_lunch_sale(sid, high["id"], "充足饭", qty, days_ago)
    for days_ago in (1, 2, 3):  # 新品只有 3 天数据 → 积累中
        await inject_lunch_sale(sid, new["id"], "新品汤", 2, days_ago)

    # 1) 建议值 = P80;库存充足的不进「可能不够卖」;数据不足标积累中
    st = call("GET", "/merchants/me/stocking?meal=lunch", merchant)
    by_name = {s["name"]: s for s in st["suggestions"]}
    assert by_name["缺货面"]["suggested"] == P80_EXPECT, by_name["缺货面"]
    assert by_name["充足饭"]["suggested"] == P80_EXPECT
    assert by_name["新品汤"]["suggested"] is None
    assert by_name["新品汤"]["data_days"] == 3
    short_names = [s["name"] for s in st["shortlist"]]
    assert "缺货面" in short_names and "充足饭" not in short_names
    assert "新品汤" not in short_names
    print(f"✓ 建议值=P80({P80_EXPECT}),库存充足不进清单,数据不足标积累中")

    # 2) 估清后一键采纳:库存生效且解除估清
    call("POST", f"/merchants/me/dishes/{low['id']}/sell-out", merchant)
    call("POST", "/merchants/me/dishes/batch-stock", merchant,
         {"items": [{"dish_id": low["id"], "stock": P80_EXPECT}]})
    dishes = {d["name"]: d for d in
              call("GET", "/merchants/me/dishes", merchant)}
    assert dishes["缺货面"]["stock"] == P80_EXPECT
    assert dishes["缺货面"]["sold_out_today"] is False
    err = call("POST", "/merchants/me/dishes/batch-stock", merchant,
               {"items": [{"dish_id": 999999, "stock": 5}]},
               expect_error=True)
    assert err["_error"] == 422, err  # 别家的菜/不存在的菜改不了
    print("✓ 一键采纳补库存并解除估清,非本店菜 422")

    # 3) 饭点提醒防重(直接调服务函数,注入 10:00 北京时间);
    # 先把库存调回缺口态,保证至少本店会被提醒
    call("POST", "/merchants/me/dishes/batch-stock", merchant,
         {"items": [{"dish_id": low["id"], "stock": 3}]})
    from app.redis_client import get_redis
    from app.services.stocking import push_stocking_reminders
    beijing = timezone(timedelta(hours=8))
    at_ten = datetime.now(beijing).replace(hour=10, minute=1, second=0)
    await get_redis().delete(f"stocking:{at_ten.date()}:lunch")
    first = await push_stocking_reminders(at_ten)
    second = await push_stocking_reminders(at_ten)
    assert first >= 1 and second == 0, (first, second)  # 同日同餐段只推一次
    off_window = at_ten.replace(hour=11)
    assert await push_stocking_reminders(off_window) == 0  # 不在窗口不推
    await get_redis().delete(f"stocking:{at_ten.date()}:lunch")
    print(f"✓ 饭点提醒 Redis 防重(首轮推 {first} 家,重跑 0)")

    print("\ne2e_stocking 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
