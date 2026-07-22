"""分账合规(桩模式)验证:分账口径快照、完成单落台账(幂等)、
渠道未配置留 pending 且清扫重试到上限置 failed、售后全额退款分账回退、
钱包排除分账口径(防双发)、两种口径审计全绿、未配置全链路无感。

在 server/ 目录下运行:python -m tests.e2e_profit_sharing
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import (call, drain_order_pool, login, register_fresh_customer,
                        register_fresh_rider)

customer = register_fresh_customer()  # 售后风控按用户30天累计,用新号
merchant = login("13800000002")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"分账测试菜-{int(time.time())}", "price_cents": 4000,
             "stock": 50})


def full_flow(rider):
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08})
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    return no


async def mark_ps(no):
    """开发环境 wxpay 未配置,settle_mode 恒为 platform;
    直接把口径快照改成 profit_sharing 模拟资质就绪后的新订单。"""
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET settle_mode = 'profit_sharing' "
            "WHERE order_no = :no"), {"no": no})
        await db.commit()


async def ps_record(no):
    async with SessionLocal() as db:
        return (await db.execute(text(
            "SELECT status, attempts, net_cents, commission_cents, sub_mchid "
            "FROM profit_sharing_records WHERE order_no = :no"),
            {"no": no})).first()


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("分账测试骑手")
    call("POST", "/riders/online", rider, {"is_online": True})

    # 0) 未配置/未登记:全链路无感,settle_mode=platform,不落分账台账
    no0 = full_flow(rider)
    call("POST", f"/orders/{no0}/transition", customer,
         {"to_status": "completed"})
    detail = call("GET", f"/orders/{no0}", customer)
    assert await ps_record(no0) is None
    print("✓ 未配置分账:platform 口径,无分账记录,全链路无感")

    # 登记特约商户号(ready 需先有商户号)
    err = call("POST", f"/admin/merchants/{sid}/sub-mchid", admin,
               {"sub_mchid": "", "ready": True}, expect_error=True)
    assert err["_error"] == 422
    call("POST", f"/admin/merchants/{sid}/sub-mchid", admin,
         {"sub_mchid": "1900001109", "ready": True})

    try:
        # 1) 分账口径完成单:落台账(净额=应收-佣金),渠道未配置留 pending
        no1 = full_flow(rider)
        await mark_ps(no1)
        call("POST", f"/orders/{no1}/transition", customer,
             {"to_status": "completed"})
        rec = await ps_record(no1)
        assert rec is not None and rec.status == "pending", rec
        assert rec.sub_mchid == "1900001109"
        d = call("GET", f"/orders/{no1}", customer)
        gross = d["food_cents"]
        assert rec.net_cents == gross - d["commission_cents"], rec
        assert rec.commission_cents == d["commission_cents"]
        listed = call("GET", "/admin/profit-sharing?status=pending", admin)
        assert any(r["order_no"] == no1 for r in listed)
        print("✓ 分账单落台账(净额=应收-佣金),渠道未配置留 pending")

        # 2) 幂等:清扫重跑不重复;attempts 递增,到 5 置 failed 人工介入
        from app.services.auto_flow import sweep_once
        for _ in range(5):
            await sweep_once()
        rec = await ps_record(no1)
        assert rec.status == "failed" and rec.attempts >= 5, rec
        async with SessionLocal() as db:
            n = (await db.execute(text(
                "SELECT count(*) FROM profit_sharing_records "
                "WHERE order_no = :no"), {"no": no1})).scalar()
        assert n == 1  # unique(order_id) 幂等
        print("✓ 清扫重试幂等,超上限置 failed 供人工介入")

        # 3) 钱包口径:分账单净额不进平台侧可提现余额(防双发)
        wallet_before = call("GET", "/merchants/me/wallet", merchant)
        no2 = full_flow(rider)
        await mark_ps(no2)
        call("POST", f"/orders/{no2}/transition", customer,
             {"to_status": "completed"})
        wallet_after = call("GET", "/merchants/me/wallet", merchant)
        assert (wallet_after["total_earned_cents"]
                == wallet_before["total_earned_cents"]), (
            wallet_before, wallet_after)
        print("✓ 分账口径净额不进平台侧钱包(钱已在商家商户号)")

        # 4) 售后全额退款 → 分账回退
        after = call("POST", f"/orders/{no2}/after-sale", customer,
                     {"reason": "有异物,申请全额退款",
                      "images": ["https://x/evidence.jpg"]})
        call("POST", f"/after-sales/{after['id']}/accept", merchant,
             {"reply": "非常抱歉,全额退款"})
        rec2 = await ps_record(no2)
        assert rec2.status == "returned", rec2
        print("✓ 售后成立触发分账回退(returned)")

        # 5) 审计:两种口径同场全绿
        from app.services.audit import run_audit
        problems = [p for p in await run_audit()
                    if no1 in p.get("detail", "") or no2 in p.get("detail", "")
                    or no0 in p.get("detail", "")]
        assert not problems, problems
        print("✓ platform 与 profit_sharing 口径审计恒等式全绿")
    finally:
        call("POST", f"/admin/merchants/{sid}/sub-mchid", admin,
             {"sub_mchid": "", "ready": False})
    call("POST", "/riders/online", rider, {"is_online": False})
    assert detail["status"].lower() == "completed"
    print("\ne2e_profit_sharing 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
