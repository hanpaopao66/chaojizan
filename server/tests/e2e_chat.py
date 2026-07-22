"""订单内聊天验证:双方收发落库、快捷语、敏感词拦截、非当事人 403、
终结 2 小时后只读 409、7 天后归档 403、未读数、admin 可查。

在 server/ 目录下运行:python -m tests.e2e_chat
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
            {"name": f"聊天测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("聊天测试骑手")

    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08})
    no = order["order_no"]

    # 1) 支付前不能聊
    err = call("POST", f"/orders/{no}/messages", customer,
               {"to": "merchant", "content": "在吗"}, expect_error=True)
    assert err["_error"] == 409, err
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)

    # 2) 三方收发:用户↔商家、用户↔骑手 两条线互不可见
    call("POST", f"/orders/{no}/messages", customer,
         {"to": "merchant", "content": "不要香菜"})
    call("POST", f"/orders/{no}/messages", merchant, {"content": "收到"})
    call("POST", f"/orders/{no}/messages", customer,
         {"to": "rider", "kind": "quick", "content": "放门口就行"})
    call("POST", f"/orders/{no}/messages", rider, {"content": "好的,到了拍照"})
    mc = call("GET", f"/orders/{no}/messages?peer=merchant", customer)
    assert [m["content"] for m in mc["messages"]] == ["不要香菜", "收到"], mc
    assert mc["messages"][0]["mine"] and not mc["messages"][1]["mine"]
    mr = call("GET", f"/orders/{no}/messages?peer=rider", customer)
    assert [m["content"] for m in mr["messages"]] == ["放门口就行", "好的,到了拍照"]
    assert mr["messages"][0]["kind"] == "quick"
    rv = call("GET", f"/orders/{no}/messages", rider)
    assert len(rv["messages"]) == 2  # 骑手只看到自己那条线(此时两条)
    print("✓ 双线会话收发落库,互不可见,快捷语标记")

    # 3) 未读数:骑手发消息后用户未读+1,读取后清零
    call("POST", f"/orders/{no}/messages", rider, {"content": "到楼下了"})
    n = call("GET", f"/orders/{no}/unread", customer)["unread"]
    assert n >= 1, n
    call("GET", f"/orders/{no}/messages?peer=rider", customer)
    assert call("GET", f"/orders/{no}/unread", customer)["unread"] == 0
    print("✓ 未读数累计与读取清零")

    # 4) 敏感词拦截、非当事人 403
    err = call("POST", f"/orders/{no}/messages", customer,
               {"to": "merchant", "content": "加微信转账便宜点"},
               expect_error=True)
    assert err["_error"] == 422, err
    outsider = await register_fresh_rider("路人骑手")
    err = call("GET", f"/orders/{no}/messages", outsider, expect_error=True)
    assert err["_error"] == 403, err
    print("✓ 敏感词 422,非当事人 403")

    # 5) 走完订单;终结 2 小时后只读,7 天后归档;admin 始终可查
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    call("POST", f"/orders/{no}/messages", customer,
         {"to": "merchant", "content": "味道不错"})  # 2 小时缓冲期内还能发
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET updated_at = now() - interval '3 hours' "
            "WHERE order_no = :no"), {"no": no})
        await db.commit()
    err = call("POST", f"/orders/{no}/messages", customer,
               {"to": "merchant", "content": "还在吗"}, expect_error=True)
    assert err["_error"] == 409 and "只读" in err["detail"], err
    assert call("GET", f"/orders/{no}/messages?peer=merchant",
                customer)["readonly"] is True
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET updated_at = now() - interval '8 days' "
            "WHERE order_no = :no"), {"no": no})
        await db.commit()
    err = call("GET", f"/orders/{no}/messages?peer=merchant", customer,
               expect_error=True)
    assert err["_error"] == 403 and "归档" in err["detail"], err
    logs = call("GET", f"/admin/orders/{no}/messages", admin)
    assert len(logs) == 6 and logs[0]["content"] == "不要香菜"
    print("✓ 终结 2 小时后只读,7 天后归档,admin 仲裁可查全量")

    print("\ne2e_chat 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
