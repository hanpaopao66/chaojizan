"""骑手取餐交接验证:尾号核验(错码 422/对码通过/强制取餐留痕)、
到店未出餐(催商家推送 + 出餐延误标记 + 出餐自动销单 + 等满 10 分钟无责转单)、
餐不齐必须拍照。

在 server/ 目录下运行:python -m tests.e2e_pickup_handover
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import call, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"交接测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def make_order(to_status="ready"):
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


async def main():
    rider = await register_fresh_rider("交接测试骑手")

    # 1) 错码 422(计数递增,第 3 次提示可强制),对码通过且留痕
    no1 = make_order()
    call("POST", f"/riders/grab/{no1}", rider)
    tail = no1[-4:]
    wrong = "0000" if tail != "0000" else "1111"
    for i in (1, 2, 3):
        err = call("POST", f"/orders/{no1}/transition", rider,
                   {"to_status": "picked_up", "verify_code": wrong},
                   expect_error=True)
        assert err["_error"] == 422 and f"已输错 {i} 次" in err["detail"], err
        if i == 3:
            assert "强制取餐" in err["detail"], err
    call("POST", f"/orders/{no1}/transition", rider,
         {"to_status": "picked_up", "verify_code": tail})
    row = await db_row(
        "SELECT note FROM order_events oe JOIN orders o ON o.id = oe.order_id "
        "WHERE o.order_no = :no AND oe.to_status = 'picked_up'", no=no1)
    assert row and row[0] == "取餐核验通过", row
    print("✓ 错码 422(3 次后提示可强制),对码通过留痕")

    # 2) 强制取餐:放行但事件留痕
    no2 = make_order()
    call("POST", f"/riders/grab/{no2}", rider)
    call("POST", f"/orders/{no2}/transition", rider,
         {"to_status": "picked_up", "force": True})
    row = await db_row(
        "SELECT note FROM order_events oe JOIN orders o ON o.id = oe.order_id "
        "WHERE o.order_no = :no AND oe.to_status = 'picked_up'", no=no2)
    assert row and "强制取餐" in row[0], row
    # no1 送掉腾在途额度;no2 留在 PICKED_UP 给场景 3 做断言
    call("POST", f"/orders/{no1}/transition", rider, {"to_status": "delivered"})
    print("✓ 强制取餐放行且留痕")

    # 3) 到店未出餐:商家收催单推送、订单记出餐延误;已取餐的单不能报
    no3 = make_order(to_status="accepted")
    call("POST", f"/riders/grab/{no3}", rider)
    call("POST", "/riders/issues", rider,
         {"order_no": no3, "kind": "not_ready", "note": "到店了,后厨说还要等"})
    row = await db_row(
        "SELECT ready_late FROM orders WHERE order_no = :no", no=no3)
    assert row[0] is True, "not_ready 应标记出餐延误"
    row = await db_row(
        "SELECT id FROM push_logs WHERE title = '骑手到店等餐' "
        "AND content LIKE :pat ORDER BY id DESC LIMIT 1",
        pat=f"%{no3[-6:]}%")
    assert row, "商家应收到催单推送记录"
    err = call("POST", "/riders/issues", rider,
               {"order_no": no2, "kind": "not_ready"}, expect_error=True)
    assert err["_error"] == 409 and "已确认取餐" in err["detail"], err
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": "delivered"})
    print("✓ not_ready:商家收催单推送,订单记出餐延误;已取餐不能报")

    # 4) 商家出餐 → not_ready 自动销单;出餐延误标记保持(粘性)
    call("POST", f"/orders/{no3}/transition", merchant, {"to_status": "ready"})
    row = await db_row(
        "SELECT di.status, di.resolve_note FROM delivery_issues di "
        "JOIN orders o ON o.id = di.order_id WHERE o.order_no = :no "
        "AND di.kind = 'not_ready'", no=no3)
    assert row[0] == "resolved" and "自动销单" in row[1], row
    row = await db_row(
        "SELECT ready_late FROM orders WHERE order_no = :no", no=no3)
    assert row[0] is True, "补出餐不清延误标记"
    print("✓ 出餐自动销掉 not_ready 工单,延误标记粘性保持")

    # 5) 餐不齐必须拍照;带图上报成功
    err = call("POST", "/riders/issues", rider,
               {"order_no": no3, "kind": "items_missing", "note": "少一份"},
               expect_error=True)
    assert err["_error"] == 422 and "拍照" in err["detail"], err
    call("POST", "/riders/issues", rider,
         {"order_no": no3, "kind": "items_missing", "note": "少一份",
          "photo_url": "https://example.com/bag.jpg"})
    print("✓ items_missing 必须带图,带图成功(走平台仲裁)")

    # 6) 无责转单:not_ready 上报满 10 分钟仍未出餐,转单不占当日次数
    noA = make_order(to_status="accepted")
    call("POST", f"/riders/grab/{noA}", rider)
    r = call("POST", f"/riders/transfer/{noA}", rider, {"reason": "other"})
    assert r["today_count"] == 1, r  # 正常转单计 1 次
    noB = make_order(to_status="accepted")
    call("POST", f"/riders/grab/{noB}", rider)
    call("POST", "/riders/issues", rider,
         {"order_no": noB, "kind": "not_ready", "note": "一直没出餐"})
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE delivery_issues SET created_at = now() - interval "
                 "'11 minutes' WHERE order_id = "
                 "(SELECT id FROM orders WHERE order_no = :no)"), {"no": noB})
        await db.commit()
    r = call("POST", f"/riders/transfer/{noB}", rider, {"reason": "other"})
    assert r["today_count"] == 1, f"等餐超时转单不该计数:{r}"
    row = await db_row(
        "SELECT note FROM order_events oe JOIN orders o ON o.id = oe.order_id "
        "WHERE o.order_no = :no AND oe.to_status = 'transferred'", no=noB)
    assert row and "无责" in row[0], row
    print("✓ 等餐满 10 分钟转单:不占当日次数,事件注明无责")

    print("\ne2e_pickup_handover 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
