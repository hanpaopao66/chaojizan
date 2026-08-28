"""订单实时通道要验身份:这一单的三方连得上,别人连不上。

## 为什么改

`/ws/orders/{order_no}` 以前是敞开的 —— 而隔壁商家听单通道
(`/ws/merchants/{id}`)验了 JWT + 店铺归属。播出去的载荷是克制的
(只有 type/order_no/status/rider_id,没有地址、手机号、金额),
拿到完整订单号才连得上(平台只公开尾 6 位),所以它不是一条能拿到数据的路;
但"谁都能订阅别人订单的状态流"没有任何存在理由。

## 这条守两头

**挡住无关的人**,以及**三方都别挡错**:骑手端要看状态推进、商家端也要。
收窄成"只有顾客"的话,表现是"配送中页面不刷新"——
那种故障没人会往鉴权上想,能安静地坏很久。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_ws_order_auth
"""
import json
import os
import urllib.parse

from tests.util import call, demo_shop, login, orderable_dish, register_fresh_customer

try:
    from websockets.sync.client import connect
except ImportError:  # pragma: no cover
    raise SystemExit("需要 websockets 库(requirements 里已有)")

BASE = os.environ.get("SUPERZ_API", "http://127.0.0.1:8010")
WS = BASE.replace("http://", "ws://").replace("https://", "wss://")

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")
shop = demo_shop()
dish = orderable_dish(call("GET", f"/merchants/{shop['id']}/dishes"))


def can_connect(order_no: str, token: str) -> bool:
    """连得上返回 True;被 4401 关掉返回 False。"""
    url = f"{WS}/ws/orders/{order_no}"
    if token:
        url += "?token=" + urllib.parse.quote(token)
    try:
        with connect(url, open_timeout=5) as ws:
            # 连上之后服务端不会主动推,能建立连接本身就是结论。
            # 发一个 ping 确认通道真的活着,而不是握手完立刻被关
            ws.ping()
            return True
    except Exception:
        return False


def main() -> None:
    no = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)

    # ---------- 该连得上的三方 ----------
    assert can_connect(no, customer), "下单的顾客连不上自己的订单通道"
    assert can_connect(no, merchant), (
        "这单的商家连不上 —— 商家端要看状态推进,挡错了表现是页面不刷新")
    assert can_connect(no, rider), (
        "接这单的骑手连不上 —— 骑手端同理")
    print("✓ 这一单的顾客 / 商家 / 骑手都连得上")

    # ---------- 该被挡住的 ----------
    assert not can_connect(no, ""), "不带 token 也能连,通道是敞开的"
    assert not can_connect(no, "not-a-jwt"), "随便一个字符串就能连"
    outsider = register_fresh_customer("路人乙")
    assert not can_connect(no, outsider), (
        "无关用户拿着自己的合法 token 就能订阅别人的订单 —— "
        "token 有效不等于跟这一单有关系")
    print("✓ 无 token / 假 token / 无关用户一律连不上")

    # ---------- 不存在的订单号 ----------
    assert not can_connect("nosuchorderno000000", customer), (
        "不存在的订单号也放行 —— 那等于可以拿它探测订单号是否存在")
    print("✓ 不存在的订单号连不上(不给探测订单号的口子)")

    print("\ne2e_ws_order_auth 全部通过 ✅")


if __name__ == "__main__":
    main()
