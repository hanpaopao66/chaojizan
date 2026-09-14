"""送达超时:2026-09-14 起只致歉、不发券(services/eta.compensate_if_late)。

原来是「准时宝-lite」—— 超时 15 分钟自动发 3 元无门槛安抚券、平台出钱;拍板「平台没有钱,
不做平台出钱的安抚和营销」之后 eta_compensation_enabled 默认关。

1. 支付生成 ETA;没超时送达:不致歉;
2. 超时 20 分钟送达:这一单记一条致歉事件,**一张券都不发**;清扫重跑不重复致歉;
   后台超时统计看得到(kind=apology、金额 0、有归因);透明中心有致歉次数;
3. 准时送到、顾客迟迟没确认的单:清扫不当成超时(原来按「现在」算晚了多少,这种单也发券);
4. 改址单、极端天气窗口不算超时;
5. 停发之前发出去的超时安抚券(写库造一张)照旧能用:下单抵扣走 subsidy 口径、审计全绿,
   取消后回券包。

**一律按单号断言**,不数总数:开发库是共享的,一次 sweep_once 会把别人留下的超时单一起处理。

在 server/ 目录下运行:python -m tests.e2e_eta_apology
"""
import asyncio
import time

from sqlalchemy import func, select, text

from app.db import SessionLocal
from app.models import Coupon, Order, OrderEvent
from tests.util import (audit_new_problems, audit_snapshot, call, demo_shop,
                        drain_order_pool, grant_legacy_platform_coupon, login,
                        register_fresh_rider)

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")
CUSTOMER_PHONE = "13800000001"

sid = demo_shop()["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"准时测试菜-{int(time.time())}", "price_cents": 2500,
             "stock": 50})


def make_paid_order(**extra):
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08, **extra,
    })
    no = order["order_no"]
    paid = call("POST", f"/orders/{no}/pay/mock", customer)
    return no, paid


async def backdate_eta(order_no, minutes):
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET eta_at = now() - interval "
            f"'{minutes} minutes' WHERE order_no = :no"), {"no": order_no})
        await db.commit()


def to_picked_up(no, rider):
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})


def deliver(no, rider):
    to_picked_up(no, rider)
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})


async def late_state(no):
    """(致歉事件条数, 这一单有没有超时安抚券)"""
    async with SessionLocal() as db:
        oid = await db.scalar(select(Order.id).where(Order.order_no == no))
        apologies = await db.scalar(select(func.count(OrderEvent.id)).where(
            OrderEvent.order_id == oid, OrderEvent.to_status == "eta_late_apology"))
        coupon = await db.scalar(select(Coupon.id).where(Coupon.source == f"eta:{no}"))
    return apologies, coupon is not None


async def main():
    from app.config import settings
    assert settings.eta_compensation_enabled is False, "超时安抚券默认该是关的"

    await drain_order_pool()
    audit_before = await audit_snapshot()  # 见 util.audit_new_problems
    rider = await register_fresh_rider("准时测试骑手")
    call("POST", "/riders/online", rider, {"is_online": True})

    # 1) 支付生成 ETA;没超时送达:不致歉
    no1, paid = make_paid_order()
    assert paid["eta_at"], paid.get("eta_at")
    deliver(no1, rider)
    assert await late_state(no1) == (0, False), "没超时却致歉/发券了"
    print("✓ 支付时生成预计送达时间;没超时送达不致歉")

    # 2) 超时 20 分钟送达:致歉一次、不发券;清扫重跑不重复
    no2, _ = make_paid_order()
    to_picked_up(no2, rider)
    await backdate_eta(no2, 20)
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": "delivered"})
    assert await late_state(no2) == (1, False), \
        f"超时 20 分钟:应当致歉一次、不发券,实际(致歉条数, 有券)= {await late_state(no2)}"
    from app.services.auto_flow import sweep_once
    await sweep_once()
    assert await late_state(no2) == (1, False), "清扫重跑又致歉了一次(或者补发了券)"
    rows = call("GET", "/admin/eta-compensations", admin)
    row = next((r for r in rows if r["order_no"] == no2), None)
    assert row and row["kind"] == "apology" and row["amount_cents"] == 0 \
        and "归因" in row["note"], row
    comp = call("GET", "/transparency/compensation")
    assert comp["eta_apologies"]["total"]["count"] >= 1, comp.get("eta_apologies")
    assert comp["eta_apologies"]["total"]["cents"] == 0, comp["eta_apologies"]
    print("✓ 超时 20 分钟:只致歉一次、一张券不发;后台看得到归因,透明中心记着致歉次数")

    # 3) 准时送到、顾客迟迟没确认:清扫不当成超时
    no3, _ = make_paid_order()
    deliver(no3, rider)
    async with SessionLocal() as db:  # 送达在 ETA 前 10 分钟,而现在已经过了 ETA 50 分钟
        await db.execute(text(
            "UPDATE orders SET delivered_at = now() - interval '60 minutes', "
            "eta_at = now() - interval '50 minutes' WHERE order_no = :no"), {"no": no3})
        await db.commit()
    await sweep_once()
    from app.services.eta import compensate_if_late
    async with SessionLocal() as db:
        order3 = await db.scalar(select(Order).where(Order.order_no == no3))
        handled = await compensate_if_late(db, order3)
    assert handled is False and await late_state(no3) == (0, False), \
        "准时送到的单被当成超时了(晚了多少要按送达那一刻算,不按现在)"
    print("✓ 准时送到、顾客还没确认的单:清扫和判定都不当成超时")

    # 4) 改址单、极端天气窗口不算超时
    no4, _ = make_paid_order()
    call("POST", f"/orders/{no4}/change-address", customer, {
        "address": "改后的新地址", "lat": 30.661, "lng": 104.081})
    to_picked_up(no4, rider)
    await backdate_eta(no4, 30)
    call("POST", f"/orders/{no4}/transition", rider, {"to_status": "delivered"})
    assert await late_state(no4) == (0, False), "用户自己改了地址,这单不算超时"
    no5, _ = make_paid_order()
    to_picked_up(no5, rider)
    call("POST", "/admin/flags/weather_shutdown", admin, {"value": "on"})
    call("POST", "/admin/flags/weather_shutdown", admin, {"value": "off"})
    await backdate_eta(no5, 30)
    call("POST", f"/orders/{no5}/transition", rider, {"to_status": "delivered"})
    assert await late_state(no5) == (0, False), "极端天气窗口内的超时不算"
    from app.redis_client import get_redis
    from app.services.eta import WEATHER_TOGGLE_KEY
    await get_redis().delete(WEATHER_TOGGLE_KEY)  # 清掉豁免窗,不影响后面
    print("✓ 改过地址的单、极端天气开关切换前后 1 小时的单不算超时")

    # 5) 停发之前发出去的超时安抚券照旧能用
    cid = await grant_legacy_platform_coupon(
        CUSTOMER_PHONE, 300, source=f"eta:{no2}",
        note=f"订单尾号{no2[-6:]}超时20分钟;归因:接单等待久/综合")
    no6 = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": cid,
    })["order_no"]
    detail = call("GET", f"/orders/{no6}", customer)
    assert detail["subsidy_cents"] >= 300 and "安抚券" in detail["promo_note"], detail
    err = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": cid,
    }, expect_error=True)
    assert err["_error"] == 409 and "用过" in err["detail"], err  # 锁定防复用
    call("POST", f"/orders/{no6}/pay/mock", customer)
    deliver(no6, rider)
    call("POST", f"/orders/{no6}/transition", customer, {"to_status": "completed"})
    problems = await audit_new_problems(audit_before, no6)
    assert not problems, problems
    print("✓ 停发之前的安抚券照旧能用:抵扣走 subsidy 口径,下单锁定防复用,审计全绿")

    cid2 = await grant_legacy_platform_coupon(
        CUSTOMER_PHONE, 300, source=f"eta:{no4}", note="停发之前的超时安抚券")
    no7 = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": cid2,
    })["order_no"]
    call("POST", f"/orders/{no7}/transition", customer,
         {"to_status": "cancelled", "reason": "不想要了"})
    again = next(c for c in call("GET", "/orders/coupons/mine", customer)
                 if c["id"] == cid2)
    assert again["usable"], again  # 取消后券回到券包
    print("✓ 订单取消后券自动回券包")

    call("POST", "/riders/online", rider, {"is_online": False})
    print("\ne2e_eta_apology 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
