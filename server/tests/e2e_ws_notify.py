"""商家听单 WebSocket 验证:支付成功即刻收到 new_order 推送;坏 token 被拒。
在 server/ 目录下运行:python -m tests.e2e_ws_notify
(websockets 库由 uvicorn[standard] 自带,无需额外安装)
"""
import asyncio
import json

import websockets

from tests.util import orderable_dish, BASE, call, login

customer = login("13800000001")
merchant = login("13800000002")

shop = call("GET", "/merchants/me", merchant)
dishes = call("GET", f"/merchants/{shop['id']}/dishes")
main_dish = orderable_dish(dishes)
WS_BASE = BASE.replace("http", "ws", 1)


async def main():
    # 1. 坏 token 连不上
    try:
        async with websockets.connect(
            f"{WS_BASE}/ws/merchants/{shop['id']}?token=bad-token"
        ) as ws:
            await asyncio.wait_for(ws.recv(), 3)
        raise SystemExit("FAIL: 坏 token 竟然连上了听单通道")
    except (websockets.exceptions.WebSocketException, asyncio.TimeoutError, OSError):
        print("✓ 坏 token 被拒绝")

    # 2. 用户 token 也不行(角色不对)
    try:
        async with websockets.connect(
            f"{WS_BASE}/ws/merchants/{shop['id']}?token={customer}"
        ) as ws:
            await asyncio.wait_for(ws.recv(), 3)
        raise SystemExit("FAIL: 用户 token 竟然连上了商家听单通道")
    except (websockets.exceptions.WebSocketException, asyncio.TimeoutError, OSError):
        print("✓ 非商家角色被拒绝")

    # 3. 正常连接,下单支付后应实时收到 new_order
    async with websockets.connect(
        f"{WS_BASE}/ws/merchants/{shop['id']}?token={merchant}"
    ) as ws:
        order = call("POST", "/orders", customer, {
            "merchant_id": shop["id"],
            "items": [{"dish_id": main_dish["id"], "quantity": 1}],
            "address": "测试地址", "lat": 30.66, "lng": 104.08,
        })
        no = order["order_no"]
        call("POST", f"/orders/{no}/pay/mock", customer)

        msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert msg["type"] == "new_order" and msg["order_no"] == no, msg
        assert "×" in msg["summary"] and msg["total_cents"] > 0
        print(f"✓ 支付后商家实时收到新单推送:{msg['summary']} ¥{msg['total_cents']/100}")

    # 清场:取消订单回补库存
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "cancelled"})
    print("\n商家听单推送验证通过 🎉")


asyncio.run(main())
