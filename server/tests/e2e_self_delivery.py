"""商家自配送验证:自配送单不进抢单池/不可抢/不可改派、商家操作配送三态、
配送费入商家账(佣金只抽餐费)、小费拒收、审计恒等式全绿。

在 server/ 目录下运行:python -m tests.e2e_self_delivery
"""
import asyncio
import time

from tests.util import (audit_new_problems, audit_snapshot, call, demo_shop,
                        drain_order_pool, login, register_fresh_rider)

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = demo_shop()["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"自送测试菜-{int(time.time())}", "price_cents": 3000,
             "stock": 50})


async def main():
    await drain_order_pool()
    audit_before = await audit_snapshot()  # 见 util.audit_new_problems
    rider = await register_fresh_rider("自送测试骑手")

    call("PATCH", "/merchants/me", merchant, {"self_delivery": True})
    try:
        # 1) 小费拒收(自送单没有骑手,小费是给骑手的)
        err = call("POST", "/orders", customer, {
            "merchant_id": sid,
            "items": [{"dish_id": dish["id"], "quantity": 1}],
            "address": "测试地址", "lat": 30.66, "lng": 104.08,
            "tip_cents": 200}, expect_error=True)
        assert err["_error"] == 422 and "自送" in err["detail"], err
        print("✓ 自配送单拒收小费")

        # 2) 下单:快照自配送,备注标注;不进抢单池、不可抢、不可改派
        order = call("POST", "/orders", customer, {
            "merchant_id": sid,
            "items": [{"dish_id": dish["id"], "quantity": 1}],
            "address": "测试地址", "lat": 30.66, "lng": 104.08})
        no = order["order_no"]
        assert order["self_delivery"] is True
        assert "商家自送" in order["promo_note"]
        fee = order["delivery_fee_cents"]
        assert fee > 0, "配送单应照常向用户收配送费"
        call("POST", f"/orders/{no}/pay/mock", customer)
        call("POST", f"/orders/{no}/transition", merchant,
             {"to_status": "accepted"})
        pool = call("GET", "/riders/available-orders?lat=30.66&lng=104.08",
                    rider)
        assert not any(o["order_no"] == no for o in pool), "自送单不该进池"
        err = call("POST", f"/riders/grab/{no}", rider, expect_error=True)
        assert err["_error"] == 409, err
        err = call("POST", f"/admin/orders/{no}/reassign", admin,
                   {"action": "release"}, expect_error=True)
        assert err["_error"] == 409 and "自配送" in err["detail"], err
        print("✓ 自配送单不进抢单池、不可抢、不可改派")

        # 3) 商家操作配送三态;骑手/用户不能越权操作取餐
        call("POST", f"/orders/{no}/transition", merchant,
             {"to_status": "ready"})
        err = call("POST", f"/orders/{no}/transition", customer,
                   {"to_status": "picked_up"}, expect_error=True)
        assert err["_error"] in (403, 409), err
        call("POST", f"/orders/{no}/transition", merchant,
             {"to_status": "picked_up"})
        call("POST", f"/orders/{no}/transition", merchant,
             {"to_status": "delivered"})
        call("POST", f"/orders/{no}/transition", customer,
             {"to_status": "completed"})
        print("✓ 商家操作 出餐→取餐出发→送达,用户确认完成")

        # 4) 结算:配送费归商家(并入商家入账行),佣金**只抽餐费**。
        # 费率按该店实际值取,不写死 5% —— 阶梯佣金会把老店降到 4.5%/4%,
        # 演示店在跑久了的库上必然进入降档区间。
        # 这条真正要守的是「佣金基数只含餐费」,不是费率具体多少
        detail = call("GET", f"/orders/{no}", customer)
        shop_now = call("GET", f"/merchants/{detail['merchant_id']}")
        rate = float(shop_now["commission_rate"])
        gross_food = detail["food_cents"]
        commission = detail["commission_cents"]
        assert commission == int(gross_food * rate), (commission, gross_food, rate)
        assert rate <= 0.05, "任何档位都不得高于 5% 的承诺上限"
        from app.db import SessionLocal
        from sqlalchemy import text as sql
        async with SessionLocal() as db:
            row = (await db.execute(sql(
                "SELECT food_cents, commission_cents, net_cents "
                "FROM merchant_earnings WHERE order_no = :no "
                "AND kind = 'earning'"), {"no": no})).first()
        assert row is not None, "缺商家入账行"
        assert row.food_cents == gross_food + fee, row  # 配送费并入商家行
        assert row.net_cents == row.food_cents - row.commission_cents
        assert row.commission_cents == commission
        # 骑手侧无入账行
        async with SessionLocal() as db:
            r2 = (await db.execute(sql(
                "SELECT count(*) FROM rider_earnings WHERE order_no = :no"),
                {"no": no})).scalar()
        assert r2 == 0, "自送单不该有骑手入账"
        print("✓ 配送费入商家账(net==food-commission 恒等),佣金只抽餐费,无骑手行")

        # 5) 审计恒等式全绿(本单无问题)。
        #    聚合类检查的 detail 不带订单号,只按 `no in detail` 过滤会把
        #    global_identity_mismatch 这类整个滤掉 —— 按 check 名的增量一起判
        problems = await audit_new_problems(audit_before, no)
        assert not problems, problems
        print("✓ 审计恒等式全绿(逐单 + 聚合类增量都为 0)")
    finally:
        call("PATCH", "/merchants/me", merchant, {"self_delivery": False})

    print("\ne2e_self_delivery 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
