"""订单超时赔付(准时宝-lite)验证:支付生成 ETA、超时自动发券且只发一次、
未超时不发、改址/极端天气豁免、券下单抵扣走 subsidy 口径审计绿、
取消释放券。

在 server/ 目录下运行:python -m tests.e2e_eta_compensation
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
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


def deliver(no, rider):
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})


def my_eta_coupons():
    return [c for c in call("GET", "/orders/coupons/mine", customer)
            if "超时" in c["note"]]


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("准时测试骑手")
    call("POST", "/riders/online", rider, {"is_online": True})
    base_coupons = len(my_eta_coupons())

    # 1) 支付生成 ETA(距离朴素公式,最少 30 分钟)
    no1, paid = make_paid_order()
    assert paid["eta_at"], paid.get("eta_at")
    print("✓ 支付时生成预计送达时间")

    # 2) 未超时送达:不发券
    deliver(no1, rider)
    assert len(my_eta_coupons()) == base_coupons
    print("✓ 未超时不发券")

    # 3) 超时 20 分钟送达:自动发 3 元安抚券,且只发一次(清扫重跑不重复)
    no2, _ = make_paid_order()
    call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no2}", rider)
    call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": "picked_up"})
    await backdate_eta(no2, 20)
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": "delivered"})
    coupons = my_eta_coupons()
    assert len(coupons) == base_coupons + 1, coupons
    coupon = next(c for c in coupons if no2[-6:] in c["note"])
    assert coupon["amount_cents"] == 300 and coupon["usable"], coupon
    from app.services.auto_flow import sweep_once
    await sweep_once()  # 兜底补发重跑:source 唯一,不重复
    assert len(my_eta_coupons()) == base_coupons + 1
    comps = call("GET", "/admin/eta-compensations", admin)
    assert any(c["order_no"] == no2 and "归因" in c["note"] for c in comps)
    print("✓ 超时 20 分钟自动发 3 元券,只发一次,后台归因可见")

    # 4) 改址单豁免
    no3, _ = make_paid_order()
    call("POST", f"/orders/{no3}/change-address", customer, {
        "address": "改后的新地址", "lat": 30.661, "lng": 104.081})
    call("POST", f"/orders/{no3}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no3}", rider)
    call("POST", f"/orders/{no3}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no3}/transition", rider, {"to_status": "picked_up"})
    await backdate_eta(no3, 30)
    call("POST", f"/orders/{no3}/transition", rider, {"to_status": "delivered"})
    assert len(my_eta_coupons()) == base_coupons + 1
    print("✓ 用户改过地址的单不赔")

    # 5) 极端天气豁免:开关切换过(1 小时内)的送达超时不赔
    no4, _ = make_paid_order()
    call("POST", f"/orders/{no4}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no4}", rider)
    call("POST", f"/orders/{no4}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no4}/transition", rider, {"to_status": "picked_up"})
    call("POST", "/admin/flags/weather_shutdown", admin, {"value": "on"})
    call("POST", "/admin/flags/weather_shutdown", admin, {"value": "off"})
    await backdate_eta(no4, 30)
    call("POST", f"/orders/{no4}/transition", rider, {"to_status": "delivered"})
    assert len(my_eta_coupons()) == base_coupons + 1
    async with SessionLocal() as db:  # 清掉豁免窗,不影响后续测试
        pass
    from app.redis_client import get_redis
    from app.services.eta import WEATHER_TOGGLE_KEY
    await get_redis().delete(WEATHER_TOGGLE_KEY)
    print("✓ 极端天气开关切换前后 1 小时的超时不赔")

    # 6) 券下单抵扣:subsidy 口径(平台承担),完整履约后审计恒等式全绿
    no5 = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": coupon["id"],
    })["order_no"]
    detail = call("GET", f"/orders/{no5}", customer)
    assert detail["subsidy_cents"] >= 300 and "安抚券" in detail["promo_note"], detail
    err = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": coupon["id"],
    }, expect_error=True)
    assert err["_error"] == 409 and "用过" in err["detail"], err  # 锁定防复用
    call("POST", f"/orders/{no5}/pay/mock", customer)
    deliver(no5, rider)
    call("POST", f"/orders/{no5}/transition", customer, {"to_status": "completed"})
    from app.services.audit import run_audit
    problems = [p for p in await run_audit() if no5 in p.get("detail", "")]
    assert not problems, problems
    print("✓ 券抵扣走 subsidy 口径,下单锁定防复用,审计恒等式全绿")

    # 7) 未支付关单/取消释放券:换张新券验证
    no6, _ = make_paid_order()
    call("POST", f"/orders/{no6}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no6}", rider)
    call("POST", f"/orders/{no6}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no6}/transition", rider, {"to_status": "picked_up"})
    await backdate_eta(no6, 20)
    call("POST", f"/orders/{no6}/transition", rider, {"to_status": "delivered"})
    fresh = next(c for c in my_eta_coupons() if c["usable"])
    no7 = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": fresh["id"],
    })["order_no"]
    call("POST", f"/orders/{no7}/transition", customer,
         {"to_status": "cancelled", "reason": "不想要了"})
    again = next(c for c in call("GET", "/orders/coupons/mine", customer)
                 if c["id"] == fresh["id"])
    assert again["usable"], again  # 取消后券回到券包
    print("✓ 订单取消后券自动释放回券包")

    call("POST", "/riders/online", rider, {"is_online": False})
    print("\ne2e_eta_compensation 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
