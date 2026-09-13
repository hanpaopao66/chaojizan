"""订单群验证:一单一个群(你 + 商家 + 骑手)。

- 三方都在一个群里:商家、骑手能看到彼此和顾客的消息;骑手接单后能翻到接单前的记录;
- 顾客对商家、骑手只显示「顾客」,自己是「你」;群头给群里有谁、置顶的订单条;
- 老版本用户端带 to / peer 的私聊照旧只有那两方看得到,第三方看不到;
- 未读数:群消息给除自己外的每个人 +1,读取清零;会话列表 /orders/chat-threads 一次给齐;
- 敏感词 422、非当事人 403;送达 24 小时后归档(能翻不能发)、7 天后当事人不可见,admin 始终可查。

在 server/ 目录下运行:python -m tests.e2e_chat
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import demo_shop, call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")

sid = demo_shop()["id"]
shop_name = demo_shop()["name"]
dish_name = f"聊天测试菜-{int(time.time())}"
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": dish_name, "price_cents": 2000, "stock": 50})


def texts(view):
    return [m["content"] for m in view["messages"]]


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("聊天测试骑手")

    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08})
    no = order["order_no"]

    # 1) 支付前不能聊
    err = call("POST", f"/orders/{no}/messages", customer, {"content": "在吗"},
               expect_error=True)
    assert err["_error"] == 409, err
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})

    # 2) 群:顾客和商家先说,骑手接单后能翻到前面的
    call("POST", f"/orders/{no}/messages", customer, {"content": "不要香菜"})
    call("POST", f"/orders/{no}/messages", merchant, {"content": "收到"})
    err = call("GET", f"/orders/{no}/messages", rider, expect_error=True)
    assert err["_error"] == 403, "还没接这一单的骑手进不了群"
    call("POST", f"/riders/grab/{no}", rider)
    rv = call("GET", f"/orders/{no}/messages", rider)
    assert texts(rv) == ["不要香菜", "收到"], rv
    assert [m["role"] for m in rv["members"]] == ["customer", "merchant", "rider"]
    assert rv["messages"][0]["sender_name"] == "顾客", "顾客对骑手只显示「顾客」"
    assert rv["messages"][1]["sender_name"] == shop_name
    call("POST", f"/orders/{no}/messages", rider,
         {"kind": "quick", "content": "已到店等出餐"})
    mv = call("GET", f"/orders/{no}/messages", merchant)
    assert texts(mv) == ["不要香菜", "收到", "已到店等出餐"], "商家看得到骑手说的"
    assert mv["messages"][2]["kind"] == "quick" and mv["messages"][2]["from"] == "rider"
    cv = call("GET", f"/orders/{no}/messages", customer)
    assert texts(cv) == ["不要香菜", "收到", "已到店等出餐"]
    assert cv["messages"][0]["mine"] and cv["messages"][0]["sender_name"] == "你"
    assert cv["title"].startswith(f"订单 #{no[-6:]}") and shop_name in cv["title"]
    assert dish_name in cv["order"]["items_summary"] and cv["order"]["status_label"]
    assert "phone" not in str(cv["members"]) and "phone" not in str(cv["order"]), \
        "群里不出现任何电话"
    print("✓ 一单一个群:三方互相看得到,骑手接单后能翻前面的;顾客只显示「顾客」;群头有人和订单条")

    # 3) 老版本用户端:带 to 的私聊只有那两方看得到
    call("POST", f"/orders/{no}/messages", customer,
         {"to": "merchant", "content": "发票抬头写公司"})
    mv = call("GET", f"/orders/{no}/messages", merchant)
    assert mv["messages"][-1]["content"] == "发票抬头写公司" and mv["messages"][-1]["private"]
    assert "发票抬头写公司" not in texts(call("GET", f"/orders/{no}/messages", rider)), \
        "老客户端的私聊不能漏给第三方"
    old_rider_view = call("GET", f"/orders/{no}/messages?peer=rider", customer)
    assert "已到店等出餐" in texts(old_rider_view) and "发票抬头写公司" not in texts(old_rider_view)
    old_merchant_view = call("GET", f"/orders/{no}/messages?peer=merchant", customer)
    assert "收到" in texts(old_merchant_view) and "发票抬头写公司" in texts(old_merchant_view)
    err = call("POST", f"/orders/{no}/messages", rider, {"to": "merchant", "content": "x"},
               expect_error=True)
    assert err["_error"] == 422, "私聊只有 用户↔商家、用户↔骑手 两条线"
    print("✓ 老版本带 to / peer 的私聊照旧只给那两方")

    # 4) 未读数:群消息给除自己外每个人 +1,读取清零;会话列表一次给齐
    call("GET", f"/orders/{no}/messages", customer)
    call("GET", f"/orders/{no}/messages", merchant)
    call("POST", f"/orders/{no}/messages", rider, {"content": "到楼下了"})
    assert call("GET", f"/orders/{no}/unread", customer)["unread"] == 1
    assert call("GET", f"/orders/{no}/unread", merchant)["unread"] == 1
    assert call("GET", f"/orders/{no}/unread", rider)["unread"] == 0, "自己发的不算未读"
    threads = call("GET", "/orders/chat-threads", customer)["items"]
    row = next(t for t in threads if t["order_no"] == no)
    assert row["unread"] == 1 and row["last"]["content"] == "到楼下了"
    assert row["last"]["from"] == "rider" and row["rider_name"] and not row["readonly"]
    assert row["title"] == cv["title"] and row["status_label"]
    assert threads[0]["order_no"] == no, "刚有人说话的单排最前"
    err = call("GET", "/orders/chat-threads", merchant, expect_error=True)
    assert err["_error"] == 403
    call("GET", f"/orders/{no}/messages", customer)
    assert call("GET", f"/orders/{no}/unread", customer)["unread"] == 0
    print("✓ 未读数按人累计、读取清零;会话列表按最后一条消息排、一次给齐")

    # 5) 敏感词拦截、非当事人 403
    err = call("POST", f"/orders/{no}/messages", customer,
               {"content": "加微信转账便宜点"}, expect_error=True)
    assert err["_error"] == 422, err
    outsider = await register_fresh_rider("路人骑手")
    err = call("GET", f"/orders/{no}/messages", outsider, expect_error=True)
    assert err["_error"] == 403, err
    print("✓ 敏感词 422,非当事人 403")

    # 6) 走完订单;送达 24 小时后归档(能翻不能发),7 天后当事人不可见;admin 始终可查
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET delivered_at = now() - interval '3 hours', "
            "updated_at = now() - interval '3 hours' WHERE order_no = :no"), {"no": no})
        await db.commit()
    call("POST", f"/orders/{no}/messages", customer, {"content": "味道不错"})  # 24 小时内还能发
    view = call("GET", f"/orders/{no}/messages", customer)
    assert not view["readonly"] and view["archive_at"], view
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET delivered_at = now() - interval '25 hours', "
            "updated_at = now() - interval '25 hours' WHERE order_no = :no"), {"no": no})
        await db.commit()
    err = call("POST", f"/orders/{no}/messages", customer, {"content": "还在吗"},
               expect_error=True)
    assert err["_error"] == 409 and "归档" in err["detail"], err
    view = call("GET", f"/orders/{no}/messages", rider)
    assert view["readonly"] is True and "味道不错" in texts(view), "归档后还能翻"
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET delivered_at = now() - interval '8 days', "
            "updated_at = now() - interval '8 days' WHERE order_no = :no"), {"no": no})
        await db.commit()
    err = call("GET", f"/orders/{no}/messages", customer, expect_error=True)
    assert err["_error"] == 403 and "归档" in err["detail"], err
    logs = call("GET", f"/admin/orders/{no}/messages", admin)
    assert len(logs) == 6 and logs[0]["content"] == "不要香菜"
    assert sum(1 for m in logs if m["to"] == "group") == 5   # 只有老客户端那条是私聊
    print("✓ 送达 24 小时后归档能翻不能发,7 天后当事人不可见,admin 仲裁可查全量")

    print("\ne2e_chat 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
