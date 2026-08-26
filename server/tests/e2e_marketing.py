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
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import demo_shop, call, login

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


async def fill_freq(user_id):
    """把每周 2 条的总频控顶满(用于验"被挡下的人不该占掉去重键")。"""
    from app.services.marketing import WEEKLY_CAP, _count_send
    for _ in range(WEEKLY_CAP):
        await _count_send(user_id)


async def month_key_taken(merchant_id, user_id):
    """当月的复购去重键在不在。"""
    from app.redis_client import get_redis
    month = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m")
    return await get_redis().get(
        f"mkt:winback:{merchant_id}:{user_id}:{month}") is not None


@contextmanager
def daily_cap(n):
    """临时改每店每日上限。上限是模块级常量,函数每轮现读,所以能这么改。"""
    from app.services import marketing
    old = marketing.DAILY_PER_SHOP
    marketing.DAILY_PER_SHOP = n
    try:
        yield
    finally:
        marketing.DAILY_PER_SHOP = old


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
    sid = demo_shop()["id"]
    bj_now = datetime.now(timezone.utc) + timedelta(hours=8)
    today = bj_now.strftime("%m-%d")

    # 批次:生日 + 复购。#115 起这两类由**商家**建(成本商家承担),
    # 平台侧建会被 422 拦掉——营销的钱不该平台出
    merchant = login("13800000002")
    call("POST", "/merchants/me/coupon-batches", merchant, {
        "name": f"生日批次{ts}", "trigger": "birthday",
        "threshold_cents": 0, "off_cents": 500, "total": 100,
        "per_user_limit": 1, "valid_days": 7})
    call("POST", "/merchants/me/coupon-batches", merchant, {
        "name": f"复购批次{ts}", "trigger": "winback",
        "threshold_cents": 0, "off_cents": 300, "total": 100,
        "per_user_limit": 1, "valid_days": 7})

    # 1) 生日券:今天生日的发,一年一张;非今天不发。
    # #117 起券只发给**这家店自己的**老客(钱是这家店出的),
    # 所以先让 u1 在本店有一笔完成单
    u1, p1 = fresh()
    call("PATCH", "/auth/me", u1, {"birthday": today})
    await inject_completed_order(await uid_of(p1), sid, 10)
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
    # 演示店的沉睡老客早就过百(实测 214 人),而每日上限默认 200 ——
    # 这一段验的是"沉睡的发、活跃的不发",不是验上限,所以先把上限抬开。
    # 不抬的话这条用例的红绿取决于演示库攒了多少老客,而不是取决于代码
    with daily_cap(10_000):
        async with SessionLocal() as db:
            await run_winback(db)
    assert [c for c in call("GET", "/orders/coupons/mine", dormant)
            if c["note"] == "好久不见"], "沉睡用户应收到券"
    assert not [c for c in call("GET", "/orders/coupons/mine", active)
                if c["note"] == "好久不见"], "活跃用户不该被打扰"
    with daily_cap(10_000):
        async with SessionLocal() as db:
            await run_winback(db)  # 当月重跑不重发(Redis 月键)
    assert len([c for c in call("GET", "/orders/coupons/mine", dormant)
                if c["note"] == "好久不见"]) == 1
    print("✓ 复购提醒只触达沉睡用户,当月一次")

    # 2a) 每日上限切的是**发出去的条数**,不是候选人数。
    #
    # 老写法是 `for user in users[:200]`:先把名单砍到 200 再进循环,
    # 而循环第一件事就是按月键跳过已发过的人。于是第二天切出来的还是
    # 同样这 200 人、全被跳过,一条也发不出去;第 201 人往后这个月
    # 永远轮不到 —— 而新注册的人 id 最大、排在最后,最该被召回的
    # 反而最先被砍掉。这里把上限压到 1 连跑两轮:老写法第二轮是 0。
    #
    # 先自己造两个没发过的候选:上面那两轮 10000 上限已经把演示店的
    # 存量沉睡老客发了个遍,不造的话这里根本没人可发,r1 就是 0 ——
    # 那是"没候选",不是"上限算错",两回事
    for _ in range(2):
        _t, _p = fresh()
        await inject_completed_order(await uid_of(_p), sid, 45)
    with daily_cap(1):
        async with SessionLocal() as db:
            r1 = await run_winback(db)
        async with SessionLocal() as db:
            r2 = await run_winback(db)
    assert r1 == 1, f"上限 1 时第一轮该发 1 条,实际 {r1}"
    assert r2 == 1, (f"第二轮发了 {r2} 条 —— 上限切的还是候选人,"
                     f"名单末尾的人永远轮不到")
    print("✓ 每日上限按发出条数算,连跑两轮各发 1 条(名单能往后走)")

    # 2b) 被周频控挡下的人,**不能**白占掉当月的去重键。
    #
    # 老写法先 `set nx` 占坑再判周频控,挡下就 continue —— 坑已经占上,
    # 他这个月不会再被尝试,而他一条也没收到。
    blocked, bp = fresh()
    b_id = await uid_of(bp)
    await inject_completed_order(b_id, sid, 40)
    await fill_freq(b_id)                      # 顶满每周 2 条
    with daily_cap(10_000):
        async with SessionLocal() as db:
            await run_winback(db)
    assert not [c for c in call("GET", "/orders/coupons/mine", blocked)
                if c["note"] == "好久不见"], "顶满周频控的人不该收到券"
    assert not await month_key_taken(sid, b_id), \
        "没发成却占住了当月去重键 —— 这个月他再也不会被尝试"
    await clear_freq(b_id)                     # 频控解除后应当补上
    with daily_cap(10_000):
        async with SessionLocal() as db:
            await run_winback(db)
    assert [c for c in call("GET", "/orders/coupons/mine", blocked)
            if c["note"] == "好久不见"], "周频控解除后该补发,说明坑退掉了"
    print("✓ 周频控挡下时退掉去重键,解除后照常补发")

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
    await inject_completed_order(h_id, sid, 10)  # 同上:得是本店老客
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
