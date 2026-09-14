"""跑腿单的售后必须有人受理,不能石沉大海 —— 而且受理了也不是平台出钱。

## 为什么单独有这条用例

售后的处理端点是 `require_role("merchant")`,按商家维度取待办。
跑腿单的 `merchant_id` 指向的是每城一个的虚拟服务主体,它的 owner
挂的是平台管理员 —— 而管理员**进不去商家端点**。于是跑腿单的售后原来是一条死路。
对跑腿来说平台本来就是对家(没有商家),所以做法是**让平台自己处理**,
这条路只对跑腿单开,不是给管理员一把处理所有商家售后的钥匙。

## 2026-09-14 起平台不再认赔

原来平台「同意」跑腿售后 = 平台认赔(判责记 platform,商品款平台出)。拍板「平台没有钱」之后:

1. 平台「同意」跑腿售后回 409;
2. 是骑手的问题:售后仲裁判骑手责任 —— 顾客全额退款(含跑腿费),这单骑手收入冲回、平台服务费
   不收(跑腿没有商家那份,池子和骑手都不用另出),骑手 72 小时内可以申诉;
3. 不是骑手的问题:驳回,不退钱;顾客可以对驳回申诉 —— 改判成立判的是骑手责任(同上);
4. 账务自检全绿,虚拟主体上没有任何商家入账,没有一条售后记成 platform。

在 server/ 目录下运行:python -m tests.e2e_errand_aftersale
"""
import asyncio

from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import AfterSale, AfterSaleStatus, Order
from tests.util import (ADMIN, MERCHANT, audit_new_problems, audit_snapshot, call, login,
                        register_fresh_customer, register_fresh_rider)

# 售后风控按用户 30 天累计,复用演示账号会被历史用例刷爆(实测已满 3 次)。
# util 的这个 helper 正是为售后类测试准备的
customer = register_fresh_customer()
admin = login(ADMIN)
merchant = login(MERCHANT)

BASE = {
    "pickup_address": "取件点·社区超市", "pickup_lat": 30.6598,
    "pickup_lng": 104.0810,
    "address": "送达点·天府大道 1 号", "lat": 30.6612, "lng": 104.0823,
    "contact_name": "收件人", "contact_phone": "13800002222",
    "no_forbidden": True,
}


def place_buy(rider, budget=3000):
    """下一张帮买单并送达(售后要求订单已送达)。"""
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


def submit(no, reason):
    return call("POST", f"/orders/{no}/after-sale", customer,
                {"reason": reason, "images": ["/uploads/as-proof.jpg"]})


async def rider_rows(no):
    async with SessionLocal() as db:
        return dict((await db.execute(text(
            "SELECT kind, sum(amount_cents) FROM rider_earnings WHERE order_no = :n "
            "GROUP BY kind"), {"n": no})).all())


async def main():
    before = await audit_snapshot()
    rider = await register_fresh_rider("跑腿售后骑手")

    # ---- 1) 用户提得上,平台侧看得到,不混进真实商家的待办 ----
    no = place_buy(rider)
    a = submit(no, "买错了,不是我要的牌子")
    assert a["status"] == "pending", a
    listed = call("GET", "/admin/errand-after-sales?status=pending", admin)
    mine = [x for x in listed if x["order_no"] == no]
    assert mine, "平台侧列表里看不到这条跑腿售后 —— 那就是没人受理"
    assert "跑腿" in mine[0]["order_summary"] and "矿泉水" in mine[0]["order_summary"], mine[0]
    shop_list = call("GET", "/merchants/me/after-sales", merchant)
    assert not [x for x in shop_list if x["order_no"] == no], "跑腿售后混进了真实商家的待办"
    row = next(x for x in call("GET", "/admin/after-sales?days=7", admin) if x["order_no"] == no)
    assert row["is_errand"] is True, row
    print(f"✓ 用户提得上跑腿售后,平台侧看得到({mine[0]['order_summary']}),不混进商家待办")

    # ---- 2) 平台不再认赔:「同意」回 409 ----
    err = call("POST", f"/after-sales/{a['id']}/accept", admin,
               {"reply": "确认买错,商品款全额退你"}, expect_error=True)
    assert err["_error"] == 409 and "不再认赔" in err["detail"], err
    print(f"✓ 平台「同意」跑腿售后:409({err['detail'][:20]}…)")

    # ---- 3) 是骑手的问题:判骑手责任,平台不出钱 ----
    before_o = call("GET", f"/orders/{no}", customer)
    r = call("POST", f"/admin/after-sales/{a['id']}/rider-fault", admin,
             {"reason": "骑手买错了牌子,小票可证"})
    after_o = call("GET", f"/orders/{no}", customer)
    assert after_o["refund_cents"] - before_o["refund_cents"] == before_o["total_cents"], \
        (before_o, after_o)
    assert r["merchant_cents"] == 0 and r["fund_cents"] == 0 and r["rider_charge_cents"] == 0, r
    rows = await rider_rows(no)
    assert rows.get("earning", 0) + rows.get("fault_reversal", 0) == 0, rows
    print(f"✓ 判骑手责任:顾客全额退 {before_o['total_cents']} 分(含跑腿费),"
          "这单骑手收入冲回;跑腿没有商家那份,池子和骑手都不另出")

    # ---- 4) 不是骑手的问题:驳回;顾客申诉成立 → 判的是骑手责任 ----
    no2 = place_buy(rider)
    a2 = submit(no2, "东西不想要了")
    rej = call("POST", f"/after-sales/{a2['id']}/reject", admin,
               {"reply": "骑手照单买对了,不支持退"})
    assert rej["status"] == "rejected", rej
    assert call("GET", f"/orders/{no2}", customer)["refund_cents"] == 0
    ap = call("POST", "/appeals", customer,
              {"target_type": "after_sale_rejected", "target_id": a2["id"],
               "reason": "骑手买的是临期货,有照片(申诉测试)"})
    queue = call("GET", "/admin/appeals?status=open", admin)
    summary = next(x for x in queue if x["id"] == ap["id"])["target_summary"]
    assert "判骑手责任" in summary, summary
    before_o2 = call("GET", f"/orders/{no2}", customer)
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:照片可证是临期货,骑手没核对"})
    after_o2 = call("GET", f"/orders/{no2}", customer)
    assert after_o2["refund_cents"] == before_o2["total_cents"], after_o2
    rows2 = await rider_rows(no2)
    assert rows2.get("earning", 0) + rows2.get("fault_reversal", 0) == 0, rows2
    print("✓ 驳回不退钱;顾客申诉改判成立 → 判骑手责任(全额退、骑手这单收入冲回),平台不出钱")

    # ---- 5) 这条路只对跑腿开:平台不能顺手处理外卖售后 ----
    async with SessionLocal() as db:
        food_as = await db.scalar(
            select(AfterSale.id)
            .join(Order, Order.id == AfterSale.order_id)
            .where(Order.order_kind == "food",
                   AfterSale.status == AfterSaleStatus.pending)
            .limit(1))
    if food_as is not None:
        err = call("POST", f"/after-sales/{food_as}/accept", admin,
                   {"reply": "平台不该能处理这条"}, expect_error=True)
        assert err["_error"] == 403, err
        print("✓ 平台碰不了外卖售后(403):这条路只对跑腿开")
    else:
        print("· 库里没有待处理的外卖售后,越权那条这次跳过")

    # ---- 6) 账要平:没有商家入账、没有一条记成平台认赔 ----
    async with SessionLocal() as db:
        net = (await db.execute(text(
            "SELECT COALESCE(SUM(net_cents), 0) FROM merchant_earnings "
            "WHERE order_no IN (:a, :b)"), {"a": no, "b": no2})).scalar()
        faults = set((await db.execute(text(
            "SELECT s.fault FROM after_sales s JOIN orders o ON o.id = s.order_id "
            "WHERE o.order_no IN (:a, :b)"), {"a": no, "b": no2})).scalars())
    assert net == 0, f"跑腿售后给虚拟主体记了商家入账 {net} 分"
    assert faults == {"rider"}, f"跑腿售后的判责方:{faults}(不该再有 platform)"
    problems = await audit_new_problems(before, no, no2)
    assert not problems, f"跑腿售后把账务自检带红了:{problems}"
    print("✓ 账务自检全绿:虚拟主体上没有商家入账,没有一条售后记成平台认赔")

    print("\ne2e_errand_aftersale 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
