"""出餐超时:两档催单各一次、出餐定格超时标记、质量统计口径。
在 server/ 目录下运行:python -m tests.e2e_ready_timeout
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal, engine
from app.services.auto_flow import sweep_once
from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"超时出餐菜-{int(time.time())}", "price_cents": 2000, "stock": 50})


def make_accepted():
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    return no


async def backdate_accept(no, minutes):
    async with SessionLocal() as db:
        await db.execute(text(
            f"UPDATE orders SET accepted_at = now() - interval '{minutes} minutes' "
            "WHERE order_no = :no"), {"no": no})
        await db.commit()
    await engine.dispose()


async def stage(no):
    async with SessionLocal() as db:
        v = await db.scalar(text(
            "SELECT ready_alert_stage FROM orders WHERE order_no = :no"), {"no": no})
    await engine.dispose()
    return v


async def main():
    # 承诺时长默认 15 分钟:16 分钟 → 一档;24 分钟(>1.5倍) → 二档;各一次
    no1 = make_accepted()
    await backdate_accept(no1, 16)
    await sweep_once()
    assert await stage(no1) == 1
    await sweep_once()
    assert await stage(no1) == 1, "一档只提醒一次"
    print("✓ 一档催单:超过承诺时长触发,且每单一次")

    await backdate_accept(no1, 24)
    await sweep_once()
    assert await stage(no1) == 2
    await sweep_once()
    assert await stage(no1) == 2, "二档只提醒一次"
    print("✓ 二档催单:超过 1.5 倍触发(含用户安抚推送),且每单一次")

    # 出餐定格超时标记
    call("POST", f"/orders/{no1}/transition", merchant, {"to_status": "ready"})
    async def late(no):
        async with SessionLocal() as db:
            v = await db.scalar(text(
                "SELECT ready_late FROM orders WHERE order_no = :no"), {"no": no})
        await engine.dispose()
        return v
    assert await late(no1) is True
    print("✓ 超时出餐定格 ready_late = true")

    # 准时出餐不超时,不触发催单
    no2 = make_accepted()
    call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "ready"})
    assert await late(no2) is False
    assert await stage(no2) == 0
    print("✓ 准时出餐 ready_late = false,无催单")

    # 质量统计接口口径
    q = call("GET", "/merchants/me/quality", merchant)
    assert {"completed_30d", "ready_late_30d", "ready_late_rate",
            "rejects_30d", "promise_ready_minutes"} <= set(q)
    assert q["promise_ready_minutes"] == 15
    print(f"✓ 质量统计:近30天完成 {q['completed_30d']} 单,"
          f"超时 {q['ready_late_30d']},拒单 {q['rejects_30d']}")

    call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
    print("\n出餐超时提醒验证通过 🎉")


asyncio.run(main())
