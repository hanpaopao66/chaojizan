"""订单超时自动流转验证。

通过直连数据库把订单时间戳改到过去,然后手动调一次 sweep_once,
断言以最终 API 状态为准(服务进程里的后台清扫同时在跑也不影响结果)。
在 server/ 目录下运行:python -m tests.e2e_auto_flow
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
# 专属菜品:库存断言不受其他订单/后台回补干扰
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"超时测试菜-{int(time.time())}", "price_cents": 2000, "stock": 50})


def make_order(pay=False):
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    if pay:
        call("POST", f"/orders/{order['order_no']}/pay/mock", customer)
    return order["order_no"]


async def backdate(order_no, column, interval):
    async with SessionLocal() as db:
        await db.execute(
            text(f"UPDATE orders SET {column} = now() - interval '{interval}' WHERE order_no = :no"),
            {"no": order_no},
        )
        await db.commit()


def dish_stock():
    menu = call("GET", f"/merchants/{sid}/dishes")
    return next(d for d in menu if d["id"] == dish["id"])["stock"]


async def main():
    stock_before = dish_stock()
    assert stock_before == 50

    # 1. 支付超时自动关单
    no1 = make_order(pay=False)
    await backdate(no1, "created_at", "20 minutes")
    # 2. 商家超时未接单自动取消
    no2 = make_order(pay=True)
    await backdate(no2, "updated_at", "10 minutes")
    # 3. 送达超时自动确认
    no3 = make_order(pay=True)
    call("POST", f"/orders/{no3}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no3}", rider)
    call("POST", f"/orders/{no3}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no3}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no3}/transition", rider, {"to_status": "delivered"})
    await backdate(no3, "updated_at", "25 hours")

    await sweep_once()

    o1 = call("GET", f"/orders/{no1}", customer)
    o2 = call("GET", f"/orders/{no2}", customer)
    s1, s2 = o1["status"], o2["status"]
    s3 = call("GET", f"/orders/{no3}", customer)["status"]
    assert s1 == "cancelled", f"支付超时订单应为 cancelled,实际 {s1}"
    assert o1["cancel_reason"] == "支付超时"
    print("✓ 待支付 20 分钟 → 自动关单(原因:支付超时)")
    assert s2 == "cancelled", f"接单超时订单应为 cancelled,实际 {s2}"
    assert o2["cancel_reason"] == "商家超时未接单"
    print("✓ 商家 10 分钟未接单 → 自动取消退款(原因可见)")
    # 超时取消的是已支付订单:全额退款,流水与 refund_cents 一致(审计规则 5 口径)
    assert o2["refund_cents"] == o2["total_cents"] > 0, o2
    flows2 = call("GET", f"/orders/{no2}/refunds", customer)
    assert sum(f["amount_cents"] for f in flows2) == o2["refund_cents"], flows2
    # 支付超时关单的是未支付订单,不产生退款
    assert o1["refund_cents"] == 0 and not call("GET", f"/orders/{no1}/refunds", customer)
    print(f"✓ 超时取消全额退款 ¥{o2['refund_cents']/100},退款流水一致;未支付关单无退款")
    assert s3 == "completed", f"送达超时订单应为 completed,实际 {s3}"
    print("✓ 送达 25 小时未确认 → 自动完成")

    # 库存核对:三单各扣 1 份,前两单取消回补,只有已完成的那单真正消耗
    stock_after = dish_stock()
    assert stock_after == stock_before - 1, f"库存应净减 1,实际 {stock_before} → {stock_after}"
    print(f"✓ 取消订单库存已回补:{stock_before} → {stock_after}(净消耗 1 份)")

    # 清场:测试菜品下架
    call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
    print("\n订单超时自动流转验证通过 🎉")


asyncio.run(main())
