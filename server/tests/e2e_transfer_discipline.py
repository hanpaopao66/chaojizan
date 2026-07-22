"""转单考核软约束验证:非免责转单达 5 次当日暂停抢单(409 含次日恢复文案)、
免责转单(到店等餐超时)不计数、次日自动恢复(清 Redis 键模拟)、
规则中心计数接口。

在 server/ 目录下运行:python -m tests.e2e_transfer_discipline
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import SessionLocal
from app.redis_client import get_redis
from tests.util import call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"限抢测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def make_order():
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    return no


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("限抢测试骑手")
    rider_id = call("GET", "/auth/me", rider)["id"]
    bj_date = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    redis_key = f"rider:transfer:{rider_id}:{bj_date}"

    # 1) 免责转单不计数:到店未出餐工单满 10 分钟后转单
    no_free = make_order()
    call("POST", f"/riders/grab/{no_free}", rider)
    call("POST", "/riders/issues", rider,
         {"order_no": no_free, "kind": "not_ready", "note": "到店没出餐"})
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE delivery_issues SET created_at = now() - interval "
            "'11 minutes' WHERE order_no = :no"), {"no": no_free})
        await db.commit()
    r = call("POST", f"/riders/transfer/{no_free}", rider,
             {"reason": "other"})
    assert r["today_count"] == 0, r  # 免责:不计数
    assert r["suspend_threshold"] == 5, r
    d = call("GET", "/riders/discipline", rider)
    assert d["transfer_used_today"] == 0 and not d["grab_suspended_today"], d
    print("✓ 到店等餐超时的免责转单不计数")

    # 2) 非免责转单 5 次:计数递增,第 5 次后抢单 409(文案含次日恢复)
    for i in range(1, 6):
        no = make_order()
        call("POST", f"/riders/grab/{no}", rider)
        r = call("POST", f"/riders/transfer/{no}", rider,
                 {"reason": "route_conflict"})
        assert r["today_count"] == i, (i, r)
    d = call("GET", "/riders/discipline", rider)
    assert d["transfer_used_today"] == 5 and d["grab_suspended_today"], d
    no_more = make_order()
    err = call("POST", f"/riders/grab/{no_more}", rider, expect_error=True)
    assert err["_error"] == 409 and "次日自动恢复" in err["detail"], err
    print("✓ 非免责转单达 5 次,当日抢单 409(不罚款,次日自动恢复)")

    # 3) 次日自动恢复:清掉当日计数键(模拟跨天)后可正常抢单
    await get_redis().delete(redis_key)
    grabbed = call("POST", f"/riders/grab/{no_more}", rider)
    assert grabbed["rider_id"] == rider_id
    print("✓ 次日(计数键过期)自动恢复抢单")

    # 清场
    call("POST", f"/riders/transfer/{no_more}", rider, {"reason": "other"})
    await get_redis().delete(redis_key)
    print("\ne2e_transfer_discipline 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
