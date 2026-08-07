"""跑腿单进无人接单兜底时,不能被当成「商家已出餐」赔付。

## 为什么单独有这条用例

跑腿单支付后**直接进 READY**(语义是"可以取件了",不是"商家出餐完成"),
然后一直躺在抢单池里等骑手。而 `_sweep_no_rider` 的取消分支里有一句:

    if from_status == OrderStatus.READY:   # 商家已出餐 → 平台赔餐损

这句话对外卖是对的 —— 商家真的把餐做出来了,运力不足是平台的问题,
不能让他背锅。但对跑腿是**凭空造钱**:那个 merchant_id 指向的是每城一个的
虚拟服务主体,它没有经营者、没有厨房、也没有做任何东西;
而帮买单的 `food_cents` 装的是**用户预付的商品款** ——
一张没人抢的帮买单会给虚拟主体记一笔等于商品款的赔付,
同时商品款还全额退给了用户。同一笔钱付了两遍。

`services/errand.py` 的 docstring 里写着"结算里对跑腿单不生成 MerchantEarning",
那句话在 `settlement.py` 里是真的 —— 但这条清扫路径**绕过结算自己写入账行**。
写在两个地方的同一条规则,总有一个不知道例外情况,这个项目已经栽过几次。

在 server/ 目录下运行:python -m tests.e2e_errand_no_rider
"""
import asyncio

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from tests.util import CUSTOMER, call, login

customer = login(CUSTOMER)

BASE = {
    "pickup_address": "取件点·社区超市", "pickup_lat": 30.6598,
    "pickup_lng": 104.0810,
    "address": "送达点·天府大道 1 号", "lat": 30.6612, "lng": 104.0823,
    "contact_name": "收件人", "contact_phone": "13800002222",
    "no_forbidden": True,
}


async def backdate(order_no, interval="45 minutes"):
    """把入池时间推到取消线之外。计时基准是 rider_pool_since。"""
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE orders SET created_at = now() - interval "
                 f"'{interval}', rider_pool_since = now() - interval "
                 f"'{interval}' WHERE order_no = :no"), {"no": order_no})
        await db.commit()


async def earnings_for(order_no):
    """这单产生的商家入账行(正常情况下跑腿单一行都不该有)。"""
    async with SessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT kind, net_cents, note FROM merchant_earnings "
            "WHERE order_no = :n"), {"n": order_no})).all()
    return [tuple(r) for r in rows]


async def main():
    # ---- 帮买:food_cents 里装的是商品款,赔付一旦发生就是商品款的量级 ----
    buy = call("POST", "/errands/buy", customer,
               {**BASE, "errand_note": "两瓶矿泉水", "goods_budget_cents": 3000})
    no_buy = buy["order_no"]
    call("POST", f"/orders/{no_buy}/pay/mock", customer)

    send = call("POST", "/errands", customer,
                {**BASE, "errand_note": "一个文件袋"})
    no_send = send["order_no"]
    call("POST", f"/orders/{no_send}/pay/mock", customer)

    # 支付后直接 READY —— 这正是它会掉进「商家已出餐」分支的原因
    for no in (no_buy, no_send):
        assert call("GET", f"/orders/{no}", customer)["status"] == "ready", no
    print("✓ 跑腿单支付后直接进 READY(等取件,不是商家出餐完成)")

    await backdate(no_buy)
    await backdate(no_send)
    await sweep_once()

    # ---- 取消 + 全额退款是对的:没人接单,用户不该付钱 ----
    for no, kind in ((no_buy, "帮买"), (no_send, "帮送")):
        o = call("GET", f"/orders/{no}", customer)
        assert o["status"] == "cancelled", (kind, o["status"])
        assert o["refund_cents"] == o["total_cents"], (kind, o)
    print("✓ 无人接单:跑腿单照常取消并全额退款")

    # ---- 但不能顺手赔付一笔「餐损」给虚拟主体 ----
    for no, kind in ((no_buy, "帮买"), (no_send, "帮送")):
        rows = await earnings_for(no)
        assert not rows, (
            f"{kind}单被当成「商家已出餐」赔付了:{rows}。"
            "跑腿的 merchant_id 指向虚拟服务主体,它没做任何东西;"
            "帮买单这笔还等于商品款,而商品款已经全额退给用户了")
    print("✓ 跑腿单不产生任何商家入账行(没有餐可赔)")

    # ---- 账要平:退款之后这两单在自检里不留问题 ----
    from app.services.audit import run_audit
    problems = await run_audit()
    mine = {no_buy, no_send}
    bad = [p for p in problems
           if any(x in str(p.get("detail", "")) for x in mine)
           or "global_identity" in str(p.get("check"))]
    assert not bad, f"跑腿兜底把账务自检带红了:{bad}"
    print("✓ 账务自检全绿")

    print("\ne2e_errand_no_rider 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
