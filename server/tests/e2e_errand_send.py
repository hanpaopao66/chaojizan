"""跑腿·帮送:下单 → 支付直接进抢单池 → 取件 → 送达 → 结算(#184)。

## 这一批守的四条

1. **没有商家环节**:支付成功直接落「待取餐」进抢单池,
   不经过"商家接单/出餐"。那个跑腿服务主体只是外键占位,
   给它推"新订单来了"没有任何人会看;
2. **2% 服务费要摆出来**:与外卖"配送费一分不抽"是两个口径,
   同时存在而不讲清楚,就是"你不是说配送费不抽吗";
3. **禁运硬编码拦截**:只写在用户协议里等于没写;
4. **账要平**:用户实付 == 骑手入账 + 平台服务费,
   而且不能把外卖那两条恒等式带红。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import CUSTOMER, RIDER, audit_regressions, call, login  # noqa: E402

customer = login(CUSTOMER)
rider = login(RIDER)

PICKUP = {"pickup_address": "取件点·人民路 5 号", "pickup_lat": 30.6598,
          "pickup_lng": 104.0810, "pickup_contact_name": "寄件人",
          "pickup_contact_phone": "13800001111"}
DROP = {"address": "送达点·天府大道 1 号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "收件人", "contact_phone": "13800002222"}


def body(**kw):
    return {**PICKUP, **DROP, "errand_note": "一个文件袋",
            "no_forbidden": True, **kw}


async def main():
    from app.services.audit import run_audit
    from app.services.errand import service_fee_cents

    # 下单之前先记一份自检基线:开发库里有历次 e2e 的存量问题
    # (住宿 PAID 挂起、分账已放弃这些不设时间窗的挂账检查只增不减),
    # 本用例只对**本次运行新增的**负责。用法见文件末尾那段断言
    baseline_checks = {p["check"] for p in await run_audit()}

    # ---- 报价:服务费单列,不藏在总价里 ----
    q = call("POST", "/errands/quote", customer, body())
    assert q["fee_cents"] > 0 and q["distance_m"] > 0, q
    assert q["service_fee_cents"] == service_fee_cents(q["fee_cents"])
    assert set(q["parts"]) >= {"base", "night", "weather", "door"}, q["parts"]
    assert "2%" in q["note"] and "一分不抽" in q["note"], q["note"]
    print(f"✓ 报价 {q['fee_cents'] / 100:g} 元,服务费 "
          f"{q['service_fee_cents'] / 100:g} 元单列;口径差别写在返回体里")

    # ---- 禁运硬拦 ----
    for note, why in [("一箱汽油", "危险化学品"), ("活体螃蟹", "活体动物"),
                      ("一盒处方药", "药品")]:
        err = call("POST", "/errands", customer, body(errand_note=note),
                   expect_error=True)
        assert err["_error"] == 422 and why in err["detail"], (note, err)
    print("✓ 禁运物品下单被拒,并说清是哪一类(不是干巴巴一句提交失败)")

    # 不勾「不含违禁品」不让下单 —— 让他在按下单之前真的想一遍
    err = call("POST", "/errands", customer, body(no_forbidden=False),
               expect_error=True)
    assert err["_error"] == 422, err
    print("✓ 不确认「不含违禁品」不让下单")

    # ---- 下单 → 支付 → **直接进抢单池** ----
    o = call("POST", "/errands", customer, body())
    no = o["order_no"]
    assert o["status"] == "pending_payment", o["status"]
    assert o["fee_parts"] and o["total_cents"] == q["fee_cents"], o
    # 取件点在订单自己身上,不是那个服务主体的坐标(它是 0,0)
    assert abs(o["merchant_lat"] - PICKUP["pickup_lat"]) < 1e-6, o
    assert PICKUP["pickup_address"] in o["merchant_address"], o
    print("✓ 取件点取的是订单自带的地址,不是服务主体的坐标")

    paid = call("POST", f"/orders/{no}/pay/mock", customer)
    assert paid["status"] == "ready", \
        f"跑腿单支付后应直接到待取餐(没有商家出餐这一步),实际 {paid['status']}"
    print("✓ 支付成功直接进抢单池,不经过商家接单/出餐")

    pool = call("GET", "/riders/available-orders", rider)
    row = next((x for x in pool if x["order_no"] == no), None)
    assert row is not None, "跑腿单应当出现在抢单池里"
    print("✓ 骑手在抢单池里看得到这一单")

    # ---- 取件 → 送达 → 完成 ----
    call("POST", f"/riders/grab/{no}", rider)
    got = call("POST", f"/errands/{no}/picked-photo", rider,
               {"photo_url": "/uploads/errand-demo.jpg"})
    assert got["order_no"] == no
    print("✓ 取件拍照留证(丢件纠纷时唯一的事实来源)")

    # 跑腿取件不走「取餐核验」:那个核验对的是小票上的单号尾号,
    # 而跑腿没有商家、没有小票。骑手端要是照搬外卖那套弹窗,
    # 他只能去点「核验不了?强制取餐」,于是每一单跑腿都在事件流里
    # 留下一条「强制取餐(未通过尾号核验)」—— 那条记录是给
    # 「拿错别人的餐」追溯用的,被跑腿单填满就废了
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    events = call("GET", f"/orders/{no}/events", customer)
    forced = [e for e in events if "强制取餐" in str(e.get("note", ""))]
    assert not forced, f"跑腿取件留下了强制取餐痕迹:{forced}"
    print("✓ 取件不留「强制取餐」痕迹(跑腿没有小票可核验)")

    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer,
         {"to_status": "completed"})

    # ---- 钱:骑手拿 98%,平台拿 2%,账要平 ----
    from sqlalchemy import text

    from app.db import SessionLocal
    done = call("GET", f"/orders/{no}", customer)
    fee = service_fee_cents(done["delivery_fee_cents"])
    async with SessionLocal() as db:
        got_cents = await db.scalar(text(
            "SELECT amount_cents FROM rider_earnings WHERE order_no = :n "
            "AND kind = 'earning'"), {"n": no})
        merchant_rows = await db.scalar(text(
            "SELECT count(*) FROM merchant_earnings me JOIN orders o "
            "ON o.id = me.order_id WHERE o.order_no = :n"), {"n": no})
    assert got_cents == done["delivery_fee_cents"] - fee, (got_cents, fee)
    assert got_cents + fee == done["total_cents"], (got_cents, fee, done)
    print(f"✓ 骑手入账 {got_cents} 分 = 跑腿费 − 服务费 {fee} 分;"
          "两者相加等于用户实付")

    # 跑腿单**不产生商家入账** —— 那个服务主体没有经营者也没有收款账户,
    # 给它记一行负净额,每日核账的「商家余额不得为负」当场报红
    assert merchant_rows == 0, "跑腿单不该有商家入账行"
    print("✓ 不产生商家入账(否则服务主体钱包变负,核账当场报红)")

    # ---- 账务自检必须仍然全绿 ----
    #
    # 断言的是「**这一单**有没有把自检带红」,按本次运行的订单号匹配,
    # 不按检查项名一刀切。原来还多一句 `"errand_identity" in check`,
    # 那等于"库里任何一张历史跑腿单不平,这条用例就红" —— 而
    # errand_identity_mismatch 的文案里本来就带订单号,`no in detail`
    # 已经把本单盖住了,那一刀切只会把别人的历史账算到这一单头上。
    #
    # 聚合类检查(文案不带订单号)靠对基线取差来兜:本次运行让哪个检查项
    # 从无到有,照样红。比原来只盯 global_identity 一个名字更严。
    problems = await run_audit()
    bad = [p for p in problems if no in str(p.get("detail", ""))]
    assert not bad, f"跑腿单把账务自检带红了:{bad}"
    fresh = audit_regressions(problems, baseline_checks)
    assert not fresh, f"本次运行新增了自检问题:{fresh}"
    print("✓ 账务自检全绿:跑腿有自己的恒等式,外卖那两条也没被带红")

    # ---- 跑腿单不许渗进商家的任何口径 ----
    #
    # 这是这个方案最容易出的错:跑腿单复用了 Order 表,凡是"统计所有订单"
    # 的地方都会把它算进去 —— 真实商家看到自己的营业额凭空多一截,
    # 或者待出餐里冒出一单他根本没做的东西
    from .util import MERCHANT
    merchant = login(MERCHANT)
    mine = call("GET", "/orders", merchant)
    assert not any(x["order_no"] == no for x in mine), \
        "跑腿单出现在了真实商家的订单列表里"
    today = call("GET", "/merchants/me/today", merchant)
    todos = call("GET", "/merchants/me/todos", merchant)
    assert isinstance(today, dict) and isinstance(todos, dict)
    print("✓ 跑腿单不进真实商家的订单列表(挂在独立的服务主体上)")

    # 出餐超时清扫不该盯上跑腿单 —— 那个"店"根本不出餐。
    # 支付后直接落 READY 而不是 ACCEPTED 就是为了躲开它
    ev = call("GET", f"/orders/{no}/events", customer)
    statuses = [e["to_status"] for e in ev]
    assert "accepted" not in statuses, \
        f"跑腿单不该经过「商家已接单」:{statuses}"
    print("✓ 状态流里没有商家接单这一步(出餐超时清扫盯不上它)")

    print("\ne2e_errand_send 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
