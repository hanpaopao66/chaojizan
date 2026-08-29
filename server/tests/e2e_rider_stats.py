"""骑手每日汇总(#310):跑一单,数字要进得去、查得出、且不叠加。

## 这条守什么

单测守的是「不进派单」那条边界(纯静态断言)。这条守的是**跑起来
的服务上真的在记**:骑手跑完一单,日汇总里要出现;汇总重跑一次,
数字不能翻倍 —— 补跑是运维的常规操作,不幂等就等于数据被污染。

顺带守住那个「不落库就永远丢掉」的数:被自己偏好挡掉的单。

在 server/ 目录下运行:python -m tests.e2e_rider_stats
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from tests.util import (ADMIN, CUSTOMER, MERCHANT, RIDER, DEMO_SHOP_ID,  # noqa: E402
                        call, login, orderable_dish)

customer = login(CUSTOMER)
merchant = login(MERCHANT)
rider = login(RIDER)
admin = login(ADMIN)
NEAR = {"lat": 30.6612, "lng": 104.0823}


async def rollup():
    from app.services.rider_stats import rollup_recent
    async with SessionLocal() as db:
        return await rollup_recent(db, days=2)


async def row_of(rider_id: int):
    from app.services.rider_stats import bj_day
    async with SessionLocal() as db:
        return (await db.execute(text(
            "SELECT orders, meters, earned_cents FROM rider_daily_stats "
            "WHERE rider_id = :r AND day = :d"),
            {"r": rider_id, "d": bj_day()})).first()


async def main() -> None:
    me = call("GET", "/auth/me", rider)
    rid = me["id"]

    await rollup()
    before = await row_of(rid)
    base_orders = before[0] if before else 0

    # ---------- 跑一单 ----------
    dish = orderable_dish(
        call("GET", f"/merchants/{DEMO_SHOP_ID}/dishes"), min_stock=2)
    o = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "日汇总测试地址", **NEAR})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    print(f"✓ 跑完一单({no[-6:]})")

    await rollup()
    after = await row_of(rid)
    assert after is not None, "跑完一单,日汇总里一行都没有"
    assert after[0] == base_orders + 1, \
        f"单量没进汇总:{base_orders} → {after[0]}"
    assert after[1] > 0, "里程没进汇总 —— 那「跑这些路值不值」就无从分析"
    print(f"✓ 单量与里程进了日汇总(共 {after[0]} 单 / {after[1]} 米)")

    # ---------- 幂等:补跑不能叠加 ----------
    await rollup()
    again = await row_of(rid)
    assert again[0] == after[0] and again[1] == after[1], \
        f"重跑汇总把数字叠加了:{after} → {again} —— 补跑是运维常规操作"
    print("✓ 汇总幂等:补跑一次数字不变")

    # ---------- 那个不落库就丢掉的数 ----------
    #
    # ⚠️ 这一段必须**先造出一单真的被挡掉的单**再断言。
    # 只是"设个高门槛然后拉一次池子"的话,池子本来就可能是空的,
    # filtered 恒为 0,断言空过 —— 测了个寂寞。
    async def filtered_now() -> int:
        from app.services.rider_stats import bj_day
        async with SessionLocal() as db:
            return (await db.execute(text(
                "SELECT filtered_by_prefs FROM rider_daily_stats "
                "WHERE rider_id = :r AND day = :d"),
                {"r": rid, "d": bj_day()})).scalar() or 0

    await rollup()
    filtered_before = await filtered_now()

    def set_prefs(**kw):
        return call("PATCH", "/riders/me/preferences", rider, kw)

    def pool(with_meta=False):
        q = "?with_meta=1" if with_meta else ""
        return call("GET", f"/riders/available-orders{q}", rider)

    # 留一单在池子里(付款 + 商家接单,但**不抢**)
    bait = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "日汇总测试地址", **NEAR})["order_no"]
    call("POST", f"/orders/{bait}/pay/mock", customer)
    call("POST", f"/orders/{bait}/transition", merchant,
         {"to_status": "accepted"})

    set_prefs(grab_min_fee_cents=0)
    assert any(o["order_no"] == bait for o in pool()), \
        "先确认这单本来看得见 —— 否则下面挡掉几单的断言是空过的"

    set_prefs(grab_min_fee_cents=2000)
    meta = pool(with_meta=True)
    assert meta["filtered_by_prefs"] >= 1, \
        f"没造出被挡掉的单,这条断言会空过:{meta}"
    set_prefs(grab_min_fee_cents=0)

    await rollup()
    filtered_after = await filtered_now()
    assert filtered_after > filtered_before, \
        (f"被偏好挡掉的单没进汇总:{filtered_before} → {filtered_after} —— "
         f"这个数是请求里现算的,不落库就永远还原不出来")
    print(f"✓ 被偏好挡掉的单数已留存({filtered_before} → {filtered_after})"
          f" —— 这个数不落库就永远还原不出来")

    # 收尾:把留的那单交给无人接单兜底,别在池子里留垃圾
    call("POST", f"/orders/{bait}/transition", customer,
         {"to_status": "cancelled", "reason": "日汇总用例收尾"})

    # ---------- 管理员查得出 ----------
    plat = call("GET", "/admin/rider-stats?days=3", admin)
    assert plat["scope"] == "platform" and plat["items"], plat
    one = call("GET", f"/admin/rider-stats?days=3&rider_id={rid}", admin)
    assert one["scope"] == "rider" and one["items"], one
    print("✓ 管理员能查全平台按天和单个骑手的时间线")

    # ---------- 红线:接口里不出现排名/评分 ----------
    blob = str(plat) + str(one)
    for banned in ("rank", "排名", "评分", "等级", "超过了"):
        assert banned not in blob, \
            f"统计接口里出现了「{banned}」—— 记录一旦变成排名就是另一根鞭子"
    print("✓ 统计接口里没有排名/评分/等级")

    print("\ne2e_rider_stats 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
