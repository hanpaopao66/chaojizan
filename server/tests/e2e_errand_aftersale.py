"""跑腿单的售后必须有人受理,不能石沉大海。

## 为什么单独有这条用例

售后的处理端点是 `require_role("merchant")`,按商家维度取待办。
跑腿单的 `merchant_id` 指向的是每城一个的虚拟服务主体,它的 owner
挂的是平台管理员 —— 而管理员**进不去商家端点**(全站 81 处商家端点
没有一处同时放行 admin)。

于是跑腿单的售后是一条死路:用户提交成功、推送发给了管理员、
然后没有任何角色能受理它。用户等在那里,单子永远 pending。

对跑腿来说平台本来就是对家(没有商家),所以正确的做法不是绕过,
是**让平台自己受理**。这条路只对跑腿单开,不是给管理员一把
处理所有商家售后的钥匙 —— 用例里连这一点也一起断言。

在 server/ 目录下运行:python -m tests.e2e_errand_aftersale
"""
import asyncio

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import (ADMIN, MERCHANT, RIDER, call, login,
                        register_fresh_customer)

# 售后风控按用户 30 天累计,复用演示账号会被历史用例刷爆(实测已满 3 次)。
# util 的这个 helper 正是为售后类测试准备的
customer = register_fresh_customer()
rider = login(RIDER)
admin = login(ADMIN)
merchant = login(MERCHANT)

BASE = {
    "pickup_address": "取件点·社区超市", "pickup_lat": 30.6598,
    "pickup_lng": 104.0810,
    "address": "送达点·天府大道 1 号", "lat": 30.6612, "lng": 104.0823,
    "contact_name": "收件人", "contact_phone": "13800002222",
    "no_forbidden": True,
}


def _drain():
    """腾出骑手在途额度(同时在途上限 3 单)。best-effort。"""
    for o in call("GET", "/orders", rider):
        if o["status"] in ("accepted", "ready"):
            call("POST", f"/orders/{o['order_no']}/transition", rider,
                 {"to_status": "picked_up"}, expect_error=True)
        if o["status"] in ("accepted", "ready", "picked_up"):
            call("POST", f"/orders/{o['order_no']}/transition", rider,
                 {"to_status": "delivered"}, expect_error=True)


def place_buy(budget=3000):
    """下一张帮买单并送达(售后要求订单已送达)。"""
    _drain()
    o = call("POST", "/errands/buy", customer,
             {**BASE, "errand_note": "两瓶矿泉水", "goods_budget_cents": budget})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/errands/{no}/receipt", rider,
         {"actual_cents": budget, "receipt_url": "/uploads/r-as.jpg"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    return no


async def main():
    no = place_buy()

    # ---- 用户提交售后 ----
    a = call("POST", f"/orders/{no}/after-sale", customer,
             {"reason": "买错了,不是我要的牌子",
              "images": ["/uploads/as-proof.jpg"]})
    assert a["status"] == "pending", a
    print("✓ 用户提得上跑腿单的售后")

    # 摘要不能是空的 —— 跑腿单没有菜品行,照搬外卖那套只会得到空字符串,
    # 处理的人打开列表只看到一个订单号,不知道这单是什么
    listed = call("GET", "/admin/errand-after-sales?status=pending", admin)
    mine = [x for x in listed if x["order_no"] == no]
    assert mine, "平台侧列表里看不到这条跑腿售后 —— 那就是没人受理"
    assert "跑腿" in mine[0]["order_summary"], mine[0]
    assert "矿泉水" in mine[0]["order_summary"], mine[0]
    print(f"✓ 平台侧列表看得到,摘要说得清是什么单:{mine[0]['order_summary']}")

    # 这条售后**不该**出现在真实商家的待办里
    shop_list = call("GET", "/merchants/me/after-sales", merchant)
    assert not [x for x in shop_list if x["order_no"] == no], \
        "跑腿售后混进了真实商家的待办"
    print("✓ 不混进真实商家的售后待办")

    # ---- 平台受理:退商品款,跑腿费不退(骑手确实跑了这一趟)----
    before = call("GET", f"/orders/{no}", customer)
    done = call("POST", f"/after-sales/{a['id']}/accept", admin,
                {"reply": "确认买错,商品款全额退你"})
    assert done["status"] == "accepted", done
    assert done["fault"] == "platform", (
        f"定责写成了 {done['fault']} —— 跑腿没有商家,认责方是平台自己")
    after = call("GET", f"/orders/{no}", customer)
    refunded = after["refund_cents"] - before["refund_cents"]
    assert refunded == before["total_cents"] - before["delivery_fee_cents"], (
        refunded, before)
    print(f"✓ 平台受理:退 {refunded} 分(商品款),"
          "跑腿费不退 —— 骑手确实跑了这一趟")

    # ---- 这条路只对跑腿开:平台不能顺手处理外卖售后 ----
    from app.models import AfterSale, AfterSaleStatus, Order
    from sqlalchemy import select
    async with SessionLocal() as db:
        food_as = await db.scalar(
            select(AfterSale)
            .join(Order, Order.id == AfterSale.order_id)
            .where(Order.order_kind == "food",
                   AfterSale.status == AfterSaleStatus.pending)
            .limit(1))
        food_as_id = food_as.id if food_as else None
    if food_as_id is not None:
        err = call("POST", f"/after-sales/{food_as_id}/accept", admin,
                   {"reply": "平台不该能处理这条"}, expect_error=True)
        assert err["_error"] == 403, err
        print("✓ 平台碰不了外卖售后(403):这条路只对跑腿开")
    else:
        print("· 库里没有待处理的外卖售后,越权那条这次跳过")

    # ---- 账要平 ----
    async with SessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT COALESCE(SUM(net_cents), 0) FROM merchant_earnings "
            "WHERE order_no = :n"), {"n": no})).scalar()
    assert rows == 0, f"跑腿售后给虚拟主体记了商家入账 {rows} 分"

    from app.services.audit import run_audit
    problems = await run_audit()
    bad = [p for p in problems
           if no in str(p.get("detail", ""))
           or "global_identity" in str(p.get("check"))]
    assert not bad, f"跑腿售后把账务自检带红了:{bad}"
    print("✓ 账务自检全绿,虚拟主体上没有任何商家入账")

    print("\ne2e_errand_aftersale 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
