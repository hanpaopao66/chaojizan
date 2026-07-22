"""商家经营分析验证:各维度数字与手算一致、0 元赠品行不计销量金额、
估清损失估算、非商家 403、days 参数校验。

历史订单直接落库(status=completed + settle_order 入账,审计口径合法)。
在 server/ 目录下运行:python -m tests.e2e_merchant_analytics
"""
import asyncio
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from tests.util import call, login, register_fresh_customer

admin = login("13800000000")
ts = int(time.time())


def fresh_merchant(name):
    phone = f"139{random.randrange(10**8, 10**9) % 10**8:08d}"
    call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "role": "merchant",
        "name": name})
    token = login(phone)
    shop = call("POST", "/merchants", token, {
        "name": name, "address": "分析测试地址", "lat": 30.66, "lng": 104.08,
        "license_no": f"JY{ts}", "license_image_url": "https://x/lic.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    call("PATCH", "/merchants/me", token, {"is_open": True})
    return token, shop["id"]


async def inject_completed(merchant_id, customer_id, items, bj_day_offset,
                           bj_hour, pickup=True):
    """直接落一笔完成单(金额=Σ正价行,配送费 0,结算入账,审计恒等式合法)。"""
    from app.db import SessionLocal
    from app.models import Order
    from app.services.settlement import settle_order
    from app.state_machine import OrderStatus

    total = sum(i["price_cents"] * i["quantity"] for i in items)
    bj = (datetime.now(timezone.utc) + timedelta(hours=8)).replace(
        hour=bj_hour, minute=5, second=0, microsecond=0) \
        - timedelta(days=bj_day_offset)
    created = bj - timedelta(hours=8)
    async with SessionLocal() as db:
        order = Order(
            order_no=uuid.uuid4().hex[:20],
            customer_id=customer_id, merchant_id=merchant_id,
            status=OrderStatus.COMPLETED, items=items,
            food_cents=total, packing_fee_cents=0, discount_cents=0,
            subsidy_cents=0, promo_note="", delivery_fee_cents=0,
            tip_cents=0, total_cents=total,
            commission_cents=int(total * 0.05),
            address="到店自取", lat=30.66, lng=104.08,
            pickup=pickup, pickup_code="0000",
        )
        db.add(order)
        await db.flush()
        order.created_at = created.replace(tzinfo=timezone.utc)
        await settle_order(db, order)
        await db.commit()


def row(name, price, qty):
    return {"dish_id": 0, "name": name, "options": [],
            "price_cents": price, "quantity": qty}


async def main():
    merchant, sid = fresh_merchant(f"分析测试店-{ts}")
    ca = call("GET", "/auth/me", register_fresh_customer())["id"]
    cb = call("GET", "/auth/me", register_fresh_customer())["id"]

    # 手工可算的数据集:
    # 昨天 12 点 顾客A:招牌面×7@10 + [赠]小菜×1@0 → ¥70
    # 昨天 18 点 顾客B:卤蛋×1@15 → ¥15(配送口径 pickup=False)
    # 前天 12 点 顾客A:招牌面×7@10 → ¥70
    await inject_completed(sid, ca, [row("招牌面", 1000, 7), row("[赠]小菜", 0, 1)], 1, 12)
    await inject_completed(sid, cb, [row("卤蛋", 1500, 1)], 1, 18, pickup=False)
    await inject_completed(sid, ca, [row("招牌面", 1000, 7)], 2, 12)

    a = call("GET", "/merchants/me/analytics?days=7", merchant)
    assert a["orders"] == 3, a["orders"]
    assert a["hourly"][12] == 2 and a["hourly"][18] == 1, a["hourly"]
    top = {d["name"]: d for d in a["top_dishes"]}
    assert top["招牌面"]["qty"] == 14 and top["招牌面"]["amount_cents"] == 14000
    assert top["卤蛋"]["qty"] == 1 and top["卤蛋"]["amount_cents"] == 1500
    assert "[赠]小菜" not in top, "赠品行不应计入销量"
    assert a["repurchase_rate"] == 0.5, a["repurchase_rate"]  # A 复购,B 没有
    assert a["pickup_orders"] == 2 and a["delivery_orders"] == 1
    assert len(a["ticket_trend"]) == 2
    day1 = a["ticket_trend"][-1]  # 昨天:(7000+1500)/2
    assert day1["orders"] == 2 and day1["avg_cents"] == 4250, day1
    print("✓ 单量/时段分布/销量排行/复购率/客单价/自取占比全部与手算一致(赠品不计)")

    # 估清损失估算:真实建一道「招牌面」并估清 → 排行里带 missed_estimate
    dish = call("POST", "/merchants/me/dishes", merchant,
                {"name": "招牌面", "price_cents": 1000, "stock": 10})
    call("POST", f"/merchants/me/dishes/{dish['id']}/sell-out", merchant)
    a = call("GET", "/merchants/me/analytics?days=7", merchant)
    entry = next(d for d in a["top_dishes"] if d["name"] == "招牌面")
    assert entry["sold_out_today"] is True
    assert entry["missed_estimate"] == round(14 / 7), entry  # 日均 2 份(估算)
    print("✓ 估清菜带售罄损失估算(日均口径,标注估算)")

    # 参数与权限
    err = call("GET", "/merchants/me/analytics?days=10", merchant,
               expect_error=True)
    assert err["_error"] == 422
    err = call("GET", "/merchants/me/analytics?days=7",
               register_fresh_customer(), expect_error=True)
    assert err["_error"] == 403
    print("✓ days 校验 422,非商家 403")

    print("\ne2e_merchant_analytics 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
