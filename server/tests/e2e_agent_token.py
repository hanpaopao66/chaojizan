"""AI 助手令牌:能下单,**付不了钱**。

## 这条守什么

整个 MCP 接入押在一句话上:

    助手能创建待支付订单,但**付款那一下在人手里**。

单测在纯函数那一层证过白名单的判据,这条要证的是**跑起来的服务上也成立** ——
拿着真的助手令牌去调支付接口,必须被拒。这两件事不是一回事:
判据对而没接进 get_current_user,或者接了但某条路绕过了它,单测都看不见。

顺带守住吊销:用户在设置里点吊销,**下一次调用就得 401** ——
JWT 自己吊销不了,所以每次都回库查一行。这个代价是故意付的。

在 server/ 目录下运行:python -m tests.e2e_agent_token
"""
import urllib.parse

from tests.util import call, demo_shop, login, orderable_dish

customer = login("13800000001")
shop = demo_shop()
dish = orderable_dish(call("GET", f"/merchants/{shop['id']}/dishes"))


def main() -> None:
    # ---------- 1) 签发 ----------
    issued = call("POST", "/auth/agent-tokens", customer,
                  {"name": "我的 Claude", "days": 30})
    agent = issued["token"]
    assert issued["note"] and "付不了款" in issued["note"], (
        f"签发时没说清「它付不了款」:{issued.get('note')}")
    print("✓ 签发成功,提示里说清了它付不了款")

    # ---------- 2) 能干的活 ----------
    me = call("GET", "/auth/me", agent)
    assert me["id"] == call("GET", "/auth/me", customer)["id"], "身份不是同一个人"

    q = urllib.parse.quote(shop["name"][:2])   # 中文要编码,否则 http.client 直接炸
    found = call("GET", f"/merchants/search?q={q}&lat=30.66&lng=104.08", agent)
    assert isinstance(found, list)
    menu = call("GET", f"/merchants/{shop['id']}/dishes", agent)
    assert menu, "助手看不到菜单"
    fee = call("GET", f"/orders/delivery-fee?merchant_id={shop['id']}"
               f"&lat=30.66&lng=104.08", agent)
    assert "total_cents" in fee or "base" in str(fee), f"算不了配送费:{fee}"
    print("✓ 查店 / 看菜单 / 算配送费都能做")

    order = call("POST", "/orders", agent, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "助手下单测试", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    assert order["status"] == "pending_payment", (
        f"助手创建的单不是待支付:{order['status']} —— "
        f"「付款在人手里」的前提是它只能创建到待支付为止")
    print(f"✓ 能创建待支付订单({no[-6:]}),状态就停在 pending_payment")

    detail = call("GET", f"/orders/{no}", agent)
    assert detail["order_no"] == no
    mine = call("GET", "/orders", agent)
    assert any(o["order_no"] == no for o in mine)
    print("✓ 能查自己的订单和进度")

    # ---------- 3) 付款一律被拒 ----------
    #
    # 这是整个设计的支点。这一条红了,「令牌泄露也花不掉钱」就不成立。
    err = call("POST", f"/orders/{no}/pay/mock", agent, expect_error=True)
    assert err["_error"] == 403, (
        f"助手能付款({err})—— 那这个令牌和登录 token 就没区别了")
    assert "付款" in err.get("detail", ""), (
        f"拒绝的话没说清能做什么不能做什么:{err.get('detail')}")
    print("✓ 付款被拒(403),而且拒绝的话说清了该去哪付")

    # 人自己付,同一单立刻付得掉 —— 证明拒的是「谁在付」不是「这单有问题」
    paid = call("POST", f"/orders/{no}/pay/mock", customer)
    assert paid["status"] == "paid"
    print("✓ 同一单用户自己付,立刻付得掉(拒的是身份,不是这一单)")

    # ---------- 4) 别的动钱/动身份的动作也一律被拒 ----------
    for label, method, path, body in (
        ("自助退款", "POST", f"/orders/{no}/self-refund", None),
        ("改地址", "POST", f"/orders/{no}/change-address",
         {"address": "换个地方", "lat": 30.7, "lng": 104.1}),
        ("加收货地址", "POST", "/addresses",
         {"label": "家", "address": "某地", "contact_name": "张三",
          "contact_phone": "13800000001", "lat": 30.66, "lng": 104.08}),
        ("再签一个助手令牌", "POST", "/auth/agent-tokens", {"name": "套娃"}),
        ("提申诉", "POST", "/appeals",
         {"target_type": "queue_pass", "target_id": 1, "reason": "随便写点什么"}),
    ):
        err = call(method, path, agent, body, expect_error=True)
        assert err["_error"] == 403, f"助手能「{label}」:{err}"
    print("✓ 退款 / 改地址 / 动地址簿 / 套娃发令牌 / 提申诉,全部 403")

    # ---------- 5) 吊销之后立刻失效 ----------
    tokens = call("GET", "/auth/agent-tokens", customer)
    row = next(t for t in tokens if t["name"] == "我的 Claude" and not t["revoked"])
    assert row["last_used_at"], "用过了却没记录最后使用时间 —— 用户分不清哪个还在用"
    call("DELETE", f"/auth/agent-tokens/{row['id']}", customer)
    err = call("GET", "/auth/me", agent, expect_error=True)
    assert err["_error"] == 401, f"吊销之后还能用:{err}"
    print("✓ 吊销之后下一次调用就 401(每次都回库查,JWT 自己吊销不了)")

    after = call("GET", "/auth/agent-tokens", customer)
    assert next(t for t in after if t["id"] == row["id"])["revoked"] is True
    print("✓ 列表里标着已吊销")

    print("\ne2e_agent_token 全部通过 ✅")


if __name__ == "__main__":
    main()
