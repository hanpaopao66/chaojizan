"""无人接单兜底验证:提醒线(标记+不动单)、取消线(全额退款)、
已出餐取消的商家餐损赔付(佣金不收)。

手法同 e2e_auto_flow:直连数据库把时间戳改到过去,手动调 sweep_once,
以最终 API 状态断言(后台清扫并行跑也不影响结果)。
在 server/ 目录下运行:python -m tests.e2e_no_rider
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"无骑手测试菜-{int(time.time())}", "price_cents": 2000, "stock": 50})


def make_order(to_status=None):
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    if to_status == "ready":
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    return no


async def backdate(order_no, interval):
    # 计时基准是 rider_pool_since(支付/转单时写入,见清单#9),created_at 一并做旧
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE orders SET created_at = now() - interval "
                 f"'{interval}', rider_pool_since = now() - interval "
                 f"'{interval}' WHERE order_no = :no"),
            {"no": order_no})
        await db.commit()


async def alerted_at(order_no):
    async with SessionLocal() as db:
        return await db.scalar(
            text("SELECT no_rider_alerted_at FROM orders WHERE order_no = :no"),
            {"no": order_no})


async def main():
    # 1) 提醒线:超过提醒阈值但未到取消线 → 打标记,订单不动
    no1 = make_order()
    await backdate(no1, "15 minutes")
    await sweep_once()
    o1 = call("GET", f"/orders/{no1}", customer)
    assert o1["status"] == "accepted", o1["status"]
    assert await alerted_at(no1) is not None
    print("✓ 提醒线:标记已提醒(推送在线骑手+商家),订单保持等待")

    # 2) 取消线(未出餐):全额退款,无赔付
    w0 = call("GET", "/merchants/me/wallet", merchant)
    no2 = make_order()
    await backdate(no2, "35 minutes")
    await sweep_once()
    o2 = call("GET", f"/orders/{no2}", customer)
    assert o2["status"] == "cancelled"
    assert "无骑手" in o2["cancel_reason"]
    assert o2["refund_cents"] == o2["total_cents"]
    flows = call("GET", f"/orders/{no2}/refunds", customer)
    assert sum(f["amount_cents"] for f in flows) == o2["refund_cents"]
    print("✓ 取消线(未出餐):全额退款,退款流水与订单一致")

    # 3) 取消线(已出餐):用户全额退款 + 商家按应收赔付(佣金不收)
    no3 = make_order(to_status="ready")
    o3_before = call("GET", f"/orders/{no3}", customer)
    comp = (o3_before["food_cents"] + o3_before["packing_fee_cents"]
            - o3_before["discount_cents"])
    await backdate(no3, "35 minutes")
    await sweep_once()
    o3 = call("GET", f"/orders/{no3}", customer)
    assert o3["status"] == "cancelled"
    assert o3["refund_cents"] == o3["total_cents"]
    w1 = call("GET", "/merchants/me/wallet", merchant)
    assert w1["total_earned_cents"] == w0["total_earned_cents"] + comp, (w0, w1, comp)
    print(f"✓ 取消线(已出餐):用户全额退款,平台赔付商家餐损 ¥{comp / 100:.2f}(佣金不收)")

    call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
    print("\n无人接单兜底验证通过 🎉")


asyncio.run(main())
