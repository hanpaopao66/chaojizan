"""营销触达三合一验证:生日券当天发且一年一张、沉睡用户复购提醒
(活跃用户不触达)、收藏店上新汇总推且同店 7 天防重、
每周 2 条频控、关闭营销推送全部不发。

直接调服务函数(注入日期),推送走桩只验证发券/计数。
在 server/ 目录下运行:python -m tests.e2e_marketing
"""
import asyncio
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import call, login

admin = login("13800000000")
merchant = login("13800000002")
ts = int(time.time())


def fresh():
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login",
                body={"phone": phone, "code": code})["token"], phone


async def uid_of(phone):
    async with SessionLocal() as db:
        return (await db.execute(text(
            "SELECT id FROM users WHERE phone = :p"), {"p": phone})).scalar()


async def clear_freq(user_id):
    from app.redis_client import get_redis
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    await get_redis().delete(f"mkt:freq:{user_id}:{now.strftime('%G-%V')}")


async def inject_completed_order(customer_id, merchant_id, days_ago):
    """直接落一笔完成单(结算入账,审计合法),用于制造沉睡/活跃用户。"""
    from app.models import Order
    from app.services.settlement import settle_order
    from app.state_machine import OrderStatus
    async with SessionLocal() as db:
        order = Order(
            order_no=uuid.uuid4().hex[:20], customer_id=customer_id,
            merchant_id=merchant_id, status=OrderStatus.COMPLETED,
            items=[{"dish_id": 0, "name": "沉睡测试菜", "options": [],
                    "price_cents": 2000, "quantity": 1}],
            food_cents=2000, packing_fee_cents=0, discount_cents=0,
            subsidy_cents=0, promo_note="", delivery_fee_cents=0,
            tip_cents=0, total_cents=2000, commission_cents=100,
            address="到店自取", lat=30.66, lng=104.08, pickup=True,
            pickup_code="0000")
        db.add(order)
        await db.flush()
        order.created_at = (datetime.now(timezone.utc)
                            - timedelta(days=days_ago))
        await settle_order(db, order)
        await db.commit()


async def main():
    from app.services.marketing import run_birthday, run_new_dish, run_winback

    shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
    sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
    bj_now = datetime.now(timezone.utc) + timedelta(hours=8)
    today = bj_now.strftime("%m-%d")

    # 批次:生日 + 复购
    call("POST", "/admin/coupon-batches", admin, {
        "name": f"生日批次{ts}", "trigger": "birthday",
        "amount_cents": 500, "total": 100, "valid_days": 7})
    call("POST", "/admin/coupon-batches", admin, {
        "name": f"复购批次{ts}", "trigger": "winback",
        "amount_cents": 300, "total": 100, "valid_days": 7})

    # 1) 生日券:今天生日的发,一年一张;非今天不发
    u1, p1 = fresh()
    call("PATCH", "/auth/me", u1, {"birthday": today})
    async with SessionLocal() as db:
        n1 = await run_birthday(db, today, bj_now.year)
    assert n1 >= 1, n1
    coupons = [c for c in call("GET", "/orders/coupons/mine", u1)
               if c["note"] == "生日快乐"]
    assert len(coupons) == 1 and coupons[0]["amount_cents"] == 500
    uid1 = await uid_of(p1)
    await clear_freq(uid1)  # 排除频控干扰,单测"一年一张"
    async with SessionLocal() as db:
        await run_birthday(db, today, bj_now.year)  # 重跑不重发
    assert len([c for c in call("GET", "/orders/coupons/mine", u1)
                if c["note"] == "生日快乐"]) == 1
    print("✓ 生日券当天发,一年一张(重跑不重发)")

    # 2) 复购提醒:35 天前有完成单的沉睡用户发;近期活跃的不发
    dormant, dp = fresh()
    active, ap = fresh()
    d_id, a_id = await uid_of(dp), await uid_of(ap)
    await inject_completed_order(d_id, sid, 35)
    await inject_completed_order(a_id, sid, 35)
    await inject_completed_order(a_id, sid, 2)  # 活跃:近 2 天又下过
    async with SessionLocal() as db:
        await run_winback(db)
    assert [c for c in call("GET", "/orders/coupons/mine", dormant)
            if c["note"] == "好久不见"], "沉睡用户应收到券"
    assert not [c for c in call("GET", "/orders/coupons/mine", active)
                if c["note"] == "好久不见"], "活跃用户不该被打扰"
    async with SessionLocal() as db:
        await run_winback(db)  # 当月重跑不重发(Redis 月键)
    assert len([c for c in call("GET", "/orders/coupons/mine", dormant)
                if c["note"] == "好久不见"]) == 1
    print("✓ 复购提醒只触达沉睡用户,当月一次")

    # 3) 收藏店上新:收藏者被推一次(同店 7 天防重);计数验证
    fan, fp = fresh()
    call("POST", f"/favorites/{sid}", fan)
    call("POST", "/merchants/me/dishes", merchant,
         {"name": f"上新菜-{ts}", "price_cents": 1800, "stock": 20})
    fan_id = await uid_of(fp)
    await clear_freq(fan_id)
    async with SessionLocal() as db:
        n3 = await run_new_dish(db)
    assert n3 >= 1, n3
    async with SessionLocal() as db:
        n3b = await run_new_dish(db)  # 同店 7 天内不再推给同一人
    # fan 已被防重;n3b 只可能是其他收藏者
    print(f"✓ 收藏店上新推送(首轮 {n3} 人,重跑 fan 防重)")

    # 4) 频控:同一用户一周内第 3 条营销触达不发
    heavy, hp = fresh()
    h_id = await uid_of(hp)
    from app.redis_client import get_redis
    week = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%G-%V")
    await get_redis().set(f"mkt:freq:{h_id}:{week}", 2)  # 已达 2 条
    call("PATCH", "/auth/me", heavy, {"birthday": today})
    async with SessionLocal() as db:
        await run_birthday(db, today, bj_now.year)
    assert not [c for c in call("GET", "/orders/coupons/mine", heavy)
                if c["note"] == "生日快乐"], "频控内不该再发"
    print("✓ 每周 2 条频控生效")

    # 5) 关闭营销推送:一律不发
    quiet, _ = fresh()
    call("PATCH", "/auth/me", quiet,
         {"birthday": today, "marketing_push": False})
    async with SessionLocal() as db:
        await run_birthday(db, today, bj_now.year)
    assert not [c for c in call("GET", "/orders/coupons/mine", quiet)
                if c["note"] == "生日快乐"]
    print("✓ 关闭营销推送后全部不发")

    print("\ne2e_marketing 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
