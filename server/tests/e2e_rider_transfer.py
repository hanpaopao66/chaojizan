"""骑手转单验证:回池他人可抢、PICKED_UP 不可转、每日计数、
追加单跟随释放、兜底计时从转单时刻重新起算。

手法同 e2e_no_rider:直连数据库 backdate 时间戳,手动调 sweep_once。
在 server/ 目录下运行:python -m tests.e2e_rider_transfer
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from tests.util import call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"转单测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def make_order(to_status="accepted"):
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


async def db_row(sql, **params):
    async with SessionLocal() as db:
        return (await db.execute(text(sql), params)).first()


async def backdate(order_no, column, interval):
    async with SessionLocal() as db:
        await db.execute(
            text(f"UPDATE orders SET {column} = now() - interval "
                 f"'{interval}' WHERE order_no = :no"), {"no": order_no})
        await db.commit()


async def main():
    await drain_order_pool()  # 清掉历史残留,回池断言不被池子上限挤爆
    rider2 = await register_fresh_rider("转单测试骑手")

    # 1) 转单后回池,他人可抢;用户视角状态不变
    no1 = make_order()
    call("POST", f"/riders/grab/{no1}", rider)
    pool = call("GET", "/riders/available-orders", rider2)
    assert no1 not in [o["order_no"] for o in pool], "已被抢的单不该在池里"
    r = call("POST", f"/riders/transfer/{no1}", rider,
             {"reason": "vehicle_broken"})
    assert r["free_times"] == 2 and r["today_count"] >= 1, r
    pool = call("GET", "/riders/available-orders", rider2)
    assert no1 in [o["order_no"] for o in pool], "转出的单应回抢单池"
    call("POST", f"/riders/grab/{no1}", rider2)
    o1 = call("GET", f"/orders/{no1}", customer)
    assert o1["status"] == "accepted", o1["status"]
    row = await db_row(
        "SELECT note FROM order_events oe JOIN orders o ON o.id = oe.order_id "
        "WHERE o.order_no = :no AND oe.to_status = 'transferred'", no=no1)
    assert row and "车坏了" in row[0], row
    print("✓ 转单回池:他人可抢,事件留痕带原因,用户视角状态不变")

    # 2) 已取餐不能转单(餐在骑手手上,只能走异常仲裁)
    call("POST", f"/orders/{no1}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no1}/transition", rider2, {"to_status": "picked_up"})
    err = call("POST", f"/riders/transfer/{no1}", rider2,
               {"reason": "other"}, expect_error=True)
    assert err["_error"] == 409 and "已取餐" in err["detail"], err
    print("✓ PICKED_UP 转单 409")

    # 3) 非本人转单 403
    no2 = make_order()
    call("POST", f"/riders/grab/{no2}", rider)
    err = call("POST", f"/riders/transfer/{no2}", rider2,
               {"reason": "other"}, expect_error=True)
    assert err["_error"] == 403, err
    call("POST", f"/riders/transfer/{no2}", rider, {"reason": "other"})
    print("✓ 非本人转单 403")

    # 4) 每日计数:新骑手从零起算,第 3 次仍成功且计数=3(超免责不拦截)
    counts = []
    for _ in range(3):
        no = make_order()
        call("POST", f"/riders/grab/{no}", rider2)
        r = call("POST", f"/riders/transfer/{no}", rider2,
                 {"reason": "route_conflict"})
        counts.append(r["today_count"])
    assert counts == [1, 2, 3], counts
    print("✓ 每日计数:第 3 次转单仍成功,计数=3")

    # 5) 追加单跟随释放:原单转出,子单一起回池(不可单独转)
    no5 = make_order()
    call("POST", f"/riders/grab/{no5}", rider)
    child = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
        "append_to": no5,
    })
    call("POST", f"/orders/{child['order_no']}/pay/mock", customer)
    row = await db_row(
        "SELECT rider_id FROM orders WHERE order_no = :no",
        no=child["order_no"])
    assert row[0] is not None, "追加单应继承原单骑手"
    err = call("POST", f"/riders/transfer/{child['order_no']}", rider,
               {"reason": "other"}, expect_error=True)
    assert err["_error"] == 409 and "追加单" in err["detail"], err
    call("POST", f"/riders/transfer/{no5}", rider, {"reason": "unwell"})
    for no in (no5, child["order_no"]):
        row = await db_row(
            "SELECT rider_id FROM orders WHERE order_no = :no", no=no)
        assert row[0] is None, f"{no} 应一起释放"
    print("✓ 追加单跟随释放,子单不可单独转")

    # 6) 兜底计时从转单时刻重新起算(backdate 验证)
    no6 = make_order()
    call("POST", f"/riders/grab/{no6}", rider)
    # 把下单时间做旧到取消线之外:老口径(created_at)会立刻误杀
    await backdate(no6, "created_at", "35 minutes")
    await backdate(no6, "rider_pool_since", "35 minutes")
    call("POST", f"/riders/transfer/{no6}", rider, {"reason": "vehicle_broken"})
    await sweep_once()
    o6 = call("GET", f"/orders/{no6}", customer)
    assert o6["status"] == "accepted", f"转单后计时应重新起算:{o6['status']}"
    row = await db_row(
        "SELECT no_rider_alerted_at FROM orders WHERE order_no = :no", no=no6)
    assert row[0] is None, "转单后提醒标记应清空"
    # 转单时刻做旧 15 分钟 → 过提醒线未到取消线
    await backdate(no6, "rider_pool_since", "15 minutes")
    await sweep_once()
    o6 = call("GET", f"/orders/{no6}", customer)
    assert o6["status"] == "accepted"
    row = await db_row(
        "SELECT no_rider_alerted_at FROM orders WHERE order_no = :no", no=no6)
    assert row[0] is not None, "过提醒线应打标记"
    # 做旧 35 分钟 → 过取消线,全额退款
    await backdate(no6, "rider_pool_since", "35 minutes")
    await sweep_once()
    o6 = call("GET", f"/orders/{no6}", customer)
    assert o6["status"] == "cancelled" and "无骑手" in o6["cancel_reason"], o6
    assert o6["refund_cents"] == o6["total_cents"]
    print("✓ 兜底计时:转单时刻重新起算(不误杀),到点提醒/取消照旧")

    print("\ne2e_rider_transfer 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
