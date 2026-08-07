"""跑腿·帮买:用户预付商品款给平台(#185)。

## 资金模型

用户下单时把**预估商品款**先付给平台,平台在结算时把**实付商品款**
结给骑手。骑手不垫自己的钱 —— 让收入最低的那个人先掏钱,
是把平台的资金风险转嫁给他。

## 三条规则(写死,不留给客服临场判断)

1. 实付 < 预估 → 差额原路退;
2. 实付 > 预估 → 20% 且 ≤20 元以内平台先垫再向用户补收;
   **超出上限骑手必须先发起确认**,用户同意才买;
3. 买不到 → 商品款全额退,跑腿费只收到店那一段的距离费。

## 品类限制是合规硬约束

帮买只做包装商品与商超日用。代购即食食品需要食品经营许可 ——
让骑手去一个没证的摊子买一份小笼包就是给无证经营导流,
而我们外卖那边卡证卡得很严,两套标准会自己打架。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import CUSTOMER, RIDER, call, login  # noqa: E402

customer = login(CUSTOMER)
rider = login(RIDER)

BASE = {
    "pickup_address": "取件点·社区超市", "pickup_lat": 30.6598,
    "pickup_lng": 104.0810,
    "address": "送达点·天府大道 1 号", "lat": 30.6612, "lng": 104.0823,
    "contact_name": "收件人", "contact_phone": "13800002222",
    "no_forbidden": True,
}


def body(**kw):
    return {**BASE, "errand_note": "两瓶矿泉水和一包纸巾",
            "goods_budget_cents": 3000, **kw}


def place(**kw):
    """下单 + 支付 + 抢单,返回订单号。

    骑手同时在途上限是 3 单,而这条用例要跑好几单 ——
    每次抢单前先把手头的送掉,否则第 4 单直接 409,
    而那个 409 和帮买本身毫无关系
    """
    _drain()
    o = call("POST", "/errands/buy", customer, body(**kw))
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/riders/grab/{no}", rider)
    return no


def _drain():
    """把骑手手头的在途单清掉,给这一单腾出额度。best-effort。"""
    for o in call("GET", "/orders", rider):
        if o["status"] in ("accepted", "ready"):
            call("POST", f"/orders/{o['order_no']}/transition", rider,
                 {"to_status": "picked_up"}, expect_error=True)
        if o["status"] in ("accepted", "ready", "picked_up"):
            call("POST", f"/orders/{o['order_no']}/transition", rider,
                 {"to_status": "delivered"}, expect_error=True)


async def main():
    from app.services.errand import (RAISE_MAX_CENTS, raise_limit_cents,
                                     settle_goods, unavailable_fee_cents)

    # ---- 规则函数先对断言:链路里出问题时能分清是规则错还是接线错 ----
    assert settle_goods(3000, 2800)["refund_cents"] == 200
    assert settle_goods(3000, 3400)["extra_charge_cents"] == 400
    assert settle_goods(3000, 3000)["refund_cents"] == 0
    # 上限 20% 且封顶 20 元 —— 骑手不该被迫做"超一点点先垫上"这个判断题
    assert raise_limit_cents(3000) == 600
    assert raise_limit_cents(500000) == RAISE_MAX_CENTS
    # 买不到只收到店那段:上门那一段根本没发生
    assert unavailable_fee_cents({"base": 300, "night": 200, "door": 300}) == 300
    print("✓ 规则:差额双向、超支上限 20%/≤20 元、买不到只收到店距离费")

    # ---- 报价:商品款与跑腿费分开列 ----
    q = call("POST", "/errands/buy/quote", customer, body())
    assert q["goods_budget_cents"] == 3000
    assert q["total_cents"] == q["fee_cents"] + 3000, q
    assert q["raise_limit_cents"] == 600, q
    assert "一分不抽" in q["note"] and "全额退" in q["note"], q["note"]
    print(f"✓ 报价:商品款 30 元 + 跑腿费 {q['fee_cents'] / 100:g} 元分开列,"
          "规则写在返回体里")

    # ---- 品类限制(合规硬约束)----
    for note, why in [("一份小笼包", "即食餐饮"), ("两包烟", "烟草"),
                      ("一瓶白酒", "酒类"), ("一盒处方药", "药品")]:
        err = call("POST", "/errands/buy", customer, body(errand_note=note),
                   expect_error=True)
        assert err["_error"] == 422 and why in err["detail"], (note, err)
    print("✓ 即食餐饮/烟/酒/药一律拒,并说清为什么(不给无证经营导流)")

    # ---- 买少了:差额原路退 ----
    no = place()
    got = call("POST", f"/errands/{no}/receipt", rider,
               {"actual_cents": 2800, "receipt_url": "/uploads/receipt1.jpg"})
    assert got["goods_actual_cents"] == 2800, got
    assert got["goods_receipt_url"], "小票是唯一对账依据,必须存下来"
    print("✓ 买少了:实付与小票落库")

    # 小票不传不让提交 —— 代买最容易起的纠纷就是"你是不是多报了"
    no2 = place()
    err = call("POST", f"/errands/{no2}/receipt", rider,
               {"actual_cents": 2800}, expect_error=True)
    assert err["_error"] == 422 and "小票" in err["detail"], err
    print("✓ 不传小票不让提交实付金额")

    # ---- 买多了但在上限内:骑手自己就能买,不用打扰用户 ----
    ok = call("POST", f"/errands/{no2}/receipt", rider,
              {"actual_cents": 3500, "receipt_url": "/uploads/r2.jpg"})
    assert ok["goods_actual_cents"] == 3500
    print("✓ 超预估但在 20%/20 元以内:骑手直接买,不打扰用户")

    # ---- 超出上限:必须先问用户 ----
    no3 = place()
    err = call("POST", f"/errands/{no3}/receipt", rider,
               {"actual_cents": 5000, "receipt_url": "/uploads/r3.jpg"},
               expect_error=True)
    assert err["_error"] == 409 and "别自己垫" in err["detail"], err
    print("✓ 超出上限直接拒:不让骑手自己垫钱(那是把平台的规则缺失转嫁给他)")

    call("POST", f"/errands/{no3}/raise", rider, {"actual_cents": 5000})
    pending = call("GET", f"/orders/{no3}", customer)
    assert pending["goods_raise_status"] == "pending", pending

    # 用户不同意 → 骑手按买不到处理
    call("POST", f"/errands/{no3}/raise/decide", customer, {"agree": False})
    assert call("GET", f"/orders/{no3}", customer)["goods_raise_status"] \
        == "rejected"
    print("✓ 加价确认:骑手发起 → 用户可拒 → 拒了就按买不到处理")

    # 用户同意 → 可以按新价买
    no4 = place()
    call("POST", f"/errands/{no4}/raise", rider, {"actual_cents": 5000})
    call("POST", f"/errands/{no4}/raise/decide", customer, {"agree": True})
    done = call("POST", f"/errands/{no4}/receipt", rider,
                {"actual_cents": 5000, "receipt_url": "/uploads/r4.jpg"})
    assert done["goods_actual_cents"] == 5000
    print("✓ 用户同意后骑手才买得成")

    # ---- 买不到:商品款全额退,只收到店那段 ----
    row = call("GET", f"/orders/{no3}", customer)
    keep = unavailable_fee_cents(row["fee_parts"])
    res = call("POST", f"/errands/{no3}/unavailable", rider,
               {"note": "货架空了"})
    assert res["status"] == "cancelled", res["status"]
    assert res["refund_cents"] == row["total_cents"] - keep, (res, keep)
    print(f"✓ 买不到:退 {res['refund_cents']} 分,"
          f"只保留到店距离费 {keep} 分(骑手确实跑了这一趟)")

    # 用户看得到小票 —— 这才是"你是不是多报了"这个纠纷不会发生的原因
    seen = call("GET", f"/orders/{no4}", customer)
    assert seen["goods_receipt_url"], "用户必须看得到小票"
    print("✓ 小票对用户可见")

    # ---- 送达完成:商品款按小票实付结给骑手,账要平 ----
    call("POST", f"/orders/{no4}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no4}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no4}/transition", customer,
         {"to_status": "completed"})

    from sqlalchemy import text

    from app.db import SessionLocal
    from app.services.errand import service_fee_cents
    fin = call("GET", f"/orders/{no4}", customer)
    async with SessionLocal() as db:
        earned = await db.scalar(text(
            "SELECT amount_cents FROM rider_earnings WHERE order_no = :n "
            "AND kind = 'earning'"), {"n": no4})
    fee = service_fee_cents(fin["delivery_fee_cents"])
    # 骑手拿到:跑腿费 98% + 小票实付的商品款(商品款平台一分不抽 ——
    # 那是他替用户垫付的钱)
    assert earned == fin["delivery_fee_cents"] - fee + 5000, (earned, fee)
    print(f"✓ 结算:骑手拿 {earned} 分 = 跑腿费 98% + 小票实付商品款 5000 分")

    # ---- 评价不能打到虚拟服务主体头上 ----
    #
    # 跑腿单的 merchant_id 指向每城一个的「跑腿服务」主体,
    # 星级累加上去就是给一个不存在的经营者打分;更糟的是 ≤3 星会触发
    # 「你收到一条差评」推送,而那个主体的 owner 挂的是平台管理员
    async with SessionLocal() as db:
        shop_id = await db.scalar(text(
            "SELECT merchant_id FROM orders WHERE order_no = :n"), {"n": no4})
        before = await db.scalar(text(
            "SELECT rating_count FROM merchants WHERE id = :i"), {"i": shop_id})
    call("POST", f"/orders/{no4}/review", customer, {
        "merchant_rating": 1, "rider_rating": 5,
        "comment": "测试:跑腿单评价不该计入商家评分"})
    async with SessionLocal() as db:
        after = await db.scalar(text(
            "SELECT rating_count FROM merchants WHERE id = :i"), {"i": shop_id})
    assert before == after, (
        f"跑腿单的评价累加到虚拟服务主体上了({before} → {after})")
    print("✓ 跑腿单评价不计入商家评分,也不触发差评推送(那头没有经营者)")

    # 只看**本次跑出来的单**。开发库里躺着修复前的历史脏单
    # (那时补收还没实现,骑手按小票拿钱、用户还按预估付钱),
    # 30 天窗口会一直扫到它们 —— 拿它们判红,这条用例就永远绿不了,
    # 而"永远红"的下场是所有人习惯"红了也没关系"
    from app.services.audit import run_audit
    problems = await run_audit()
    mine_nos = {no, no2, no3, no4}
    bad = [p for p in problems
           if any(x in str(p.get("detail", "")) for x in mine_nos)
           or "global_identity" in str(p.get("check"))]
    assert not bad, f"帮买把账务自检带红了:{bad}"
    print("✓ 账务自检全绿(帮买的商品款走了小票实付这条口径)")

    print("\ne2e_errand_buy 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
