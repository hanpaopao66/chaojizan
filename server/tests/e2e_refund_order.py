"""退款发起顺序:报给支付渠道的「原始支付总额」必须等于用户实付。

微信退款 API 要求同时给 `refund`(本次退多少)和 `total`(原始订单总额),
两者对不上就直接拒。我们没有单独存"原始支付总额"这一列,而是从
剩余应付反推(services/wechat_pay):

    original_total = order.total_cents + order.refund_cents

于是**发起退款和累计 refund_cents 的先后顺序变成了资金正确性的一部分**:
先把 refund_cents 加上去再发起,反推出来的就是 2T 而实际只退 T,
微信拒单 —— 而 refund_cents 已经加上去了,账面显示"已退",钱一分没动。

现在是模拟支付,mock 通道不校验这两个数,**所以这条错误在真机联调前
没有任何症状**。这条用例把渠道换成一个会记账的假客户端,把顺序钉死。

顺带钉死第二条:**渠道拒绝时不累计 refund_cents**。钱没退出去,
账面就不能写"已退",否则下一次退款反推出来的原始总额又错一轮。

## 跑法

用例在**自己的进程里**跑一份 ASGI 应用(与 8010 那个共库),
这样才能把 `wechat_pay.get_client` 换成假客户端 ——
换不了别人进程里的模块。数据准备照常走 8010。

    python -m tests.e2e_refund_order
"""
import asyncio
import time

import httpx
from sqlalchemy import text

from app.db import SessionLocal
from app.services import wechat_pay
from app.services.auto_flow import sweep_once

from .util import ADMIN, MERCHANT, RIDER, call, demo_shop, login

merchant = login(MERCHANT)
rider = login(RIDER)
admin = login(ADMIN)
SHOP = demo_shop()
TAG = str(int(time.time()))


class FakeChannel:
    """记账用的假微信客户端:把每次退款的入参原样留下。"""

    def __init__(self):
        self.calls = []
        self.reject = False

    def refund(self, out_trade_no, out_refund_no, amount, reason):
        self.calls.append({"order_no": out_trade_no, "amount": amount})
        if self.reject:
            return 500, {"code": "SYSTEM_ERROR", "message": "渠道拒绝(用例造的)"}
        return 200, {"status": "PROCESSING"}

    def last(self, order_no):
        for c in reversed(self.calls):
            if c["order_no"] == order_no:
                return c["amount"]
        raise AssertionError(f"{order_no} 没有发起过退款")


CH = FakeChannel()


def new_customer(suffix):
    phone = f"134{(int(TAG) + suffix) % 100000000:08d}"
    token = call("POST", "/auth/register",
                 body={"phone": phone, "password": "123456",
                       "name": f"退款顺序{suffix}", "role": "customer"})["token"]
    return token


async def ainvoke(method, path, token, body=None):
    """在本进程内跑一次请求(假渠道才生效)。"""
    from app.main import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://inproc") as client:
        resp = await client.request(
            method, path, json=body,
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code < 400, (path, resp.status_code, resp.text)
        return resp.json() if resp.content else None


def order_row(no, token):
    return call("GET", f"/orders/{no}", token)


async def refund_rows(no):
    async with SessionLocal() as db:
        return [tuple(r) for r in await db.execute(text(
            "SELECT amount_cents, status FROM refunds WHERE order_no = :n "
            "ORDER BY id"), {"n": no})]


def place(token, dish_id, to=None):
    o = call("POST", "/orders", token, {
        "merchant_id": SHOP["id"],
        "items": [{"dish_id": dish_id, "quantity": 1}],
        "address": "退款顺序测试", "lat": 30.66, "lng": 104.08})
    no = o["order_no"]
    paid = call("POST", f"/orders/{no}/pay/mock", token)["total_cents"]
    steps = {"accepted": (merchant, "accepted"), "ready": (merchant, "ready"),
             "picked_up": (rider, "picked_up"), "delivered": (rider, "delivered")}
    order = ["accepted", "ready", "picked_up", "delivered"]
    if to:
        call("POST", f"/orders/{no}/transition", merchant,
             {"to_status": "accepted"})
        if order.index(to) >= 1:
            call("POST", f"/riders/grab/{no}", rider)
            call("POST", f"/orders/{no}/transition", merchant,
                 {"to_status": "ready"})
        for step in order[2:order.index(to) + 1]:
            who, st = steps[step]
            call("POST", f"/orders/{no}/transition", who, {"to_status": st})
    return no, paid


def drain_rider():
    for o in call("GET", "/orders", rider):
        if o["status"] in ("accepted", "ready"):
            call("POST", f"/orders/{o['order_no']}/transition", rider,
                 {"to_status": "picked_up"}, expect_error=True)
        if o["status"] in ("accepted", "ready", "picked_up"):
            call("POST", f"/orders/{o['order_no']}/transition", rider,
                 {"to_status": "delivered"}, expect_error=True)


async def age_pool(no):
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET rider_pool_since = now() - interval "
            "'31 minutes' WHERE order_no = :n"), {"n": no})
        await db.commit()


def check(name, no, paid, expect_refund):
    amount = CH.last(no)
    assert amount["refund"] == expect_refund, (name, amount)
    assert amount["total"] == paid, (
        f"{name}:发给渠道的原始支付总额 {amount['total']} ≠ 用户实付 {paid}"
        f"(退 {amount['refund']});先累计 refund_cents 再发起退款,"
        f"反推出来的总额就多算了一遍已退金额,微信会直接拒掉这笔退款")
    assert amount["refund"] <= amount["total"], amount
    print(f"✓ {name}:退 {amount['refund']} / 原始支付总额 {amount['total']}"
          f"(= 用户实付)")


async def main():
    wechat_pay.get_client = lambda: CH          # 全进程唯一的替换点
    dish = call("POST", "/merchants/me/dishes", merchant,
                {"name": f"退款顺序测试菜-{TAG}", "price_cents": 2600,
                 "stock": 90})
    did = dish["id"]

    # ---- A) 无骑手兜底取消(services/auto_flow)----
    c1 = new_customer(1)
    no, paid = place(c1, did, to="accepted")
    await age_pool(no)
    await sweep_once()
    row = order_row(no, c1)
    assert row["status"] == "cancelled", row["status"]
    check("无骑手兜底取消", no, paid, paid)
    assert row["refund_cents"] == paid, row["refund_cents"]

    # ---- B) 平台仲裁:配送异常先行赔付(routers/admin)----
    drain_rider()
    c2 = new_customer(2)
    no2, paid2 = place(c2, did, to="picked_up")
    issue = call("POST", "/riders/issues", rider,
                 {"order_no": no2, "kind": "cannot_contact",
                  "note": "退款顺序用例"})
    await ainvoke("POST", f"/admin/delivery-issues/{issue['id']}/resolve",
                  admin, {"action": "refund", "note": "退款顺序用例"})
    check("配送异常先行赔付", no2, paid2, paid2)
    assert order_row(no2, c2)["refund_cents"] == paid2

    # ---- C) 平台仲裁:售后判骑手责任(routers/admin)----
    drain_rider()
    c3 = new_customer(3)
    no3, paid3 = place(c3, did, to="delivered")
    a3 = call("POST", f"/orders/{no3}/after-sale", c3,
              {"reason": "退款顺序用例:洒了",
               "images": ["/uploads/x.jpg"]})
    await ainvoke("POST", f"/admin/after-sales/{a3['id']}/rider-fault",
                  admin, {"reason": "退款顺序用例"})
    check("售后判骑手责任", no3, paid3, paid3)
    assert order_row(no3, c3)["refund_cents"] == paid3

    # ---- D) 商家同意售后:只退餐费,配送费已履约不退(routers/after_sales)----
    drain_rider()
    c4 = new_customer(4)
    no4, paid4 = place(c4, did, to="delivered")
    fee4 = order_row(no4, c4)["delivery_fee_cents"]
    a4 = call("POST", f"/orders/{no4}/after-sale", c4,
              {"reason": "退款顺序用例:少了一份",
               "images": ["/uploads/y.jpg"]})
    await ainvoke("POST", f"/after-sales/{a4['id']}/accept", merchant,
                  {"reply": "退款顺序用例"})
    check("商家同意售后(退餐费)", no4, paid4, paid4 - fee4)
    assert order_row(no4, c4)["refund_cents"] == paid4 - fee4

    # ---- E) 渠道拒绝这一笔:refund_cents 不能加上去 ----
    drain_rider()
    CH.reject = True
    try:
        c5 = new_customer(5)
        no5, paid5 = place(c5, did, to="accepted")
        await age_pool(no5)
        await sweep_once()
    finally:
        CH.reject = False
    row5 = order_row(no5, c5)
    assert row5["status"] == "cancelled", row5["status"]
    check("渠道拒绝(原始总额仍要对)", no5, paid5, paid5)
    rows = await refund_rows(no5)
    assert rows == [(paid5, "failed")], rows
    assert row5["refund_cents"] == 0, (
        f"渠道拒了这笔退款,refund_cents 却加到了 {row5['refund_cents']} —— "
        f"钱一分没退出去,账面写着已退 {row5['refund_cents']} 分;"
        "下一次退款按 total+已退 反推原始总额还会再错一轮")
    print(f"✓ 渠道拒绝:流水记 failed,refund_cents 停在 0(实付 {paid5} 未退)")

    call("PATCH", f"/merchants/me/dishes/{did}", merchant,
         {"is_on_sale": False})
    print("\ne2e_refund_order 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
