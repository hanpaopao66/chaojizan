"""骑手的「这单不好送」反馈:2026-09-14 起不当场补钱,只给以后的单定价(#301)。

原来反馈的这一单当场补钱、平台出(走 adjustment 入账);拍板「平台没有钱,不做平台出钱的
安抚和营销」之后停了。反馈照收照记,攒够共识后算进这个地址以后的配送费(顾客付、下单前
看得到、全归骑手)。

1. 骑手送达后反馈:回执说清楚这一单不当场补钱,comp_cents=0,这一单没有任何调整入账;
2. 规则接口:funder=customer、paid_now=false,说明里写着不当场补钱;
3. 第二个骑手在同一个地方反馈同一项 → 共识成立:顾客下一单的配送费预览和下单都带上这笔
   难度费,说明里写着骑手反馈过;
4. 那一单送完:骑手入账 == 配送费(含难度费)+ 小费 —— 这笔钱是顾客付的,平台一分没出;
5. 账务自检不报这几单。

在 server/ 目录下运行:python -m tests.e2e_hardship_no_pay
"""
import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import RiderEarning, RiderHardship
from tests.util import (audit_new_problems, audit_snapshot, call, demo_shop, login,
                        orderable_dish, register_fresh_rider, unique_spot)

customer = login("13800000001")
merchant = login("13800000002")
SHOP = demo_shop()


async def fresh_cell() -> tuple[float, float]:
    """挑一个还没人反馈过的地址格子(共识按 111m 网格 + 楼层攒,开发库里可能有别的跑动留下的)"""
    from app.services.hardship import address_consensus
    for _ in range(30):
        lat, lng = unique_spot()
        async with SessionLocal() as db:
            if (await address_consensus(db, lat, lng, None))["samples"] == 0:
                return lat, lng
    raise AssertionError("找不到一个没人反馈过的格子")


def run_order(rider, lat, lng, dish, tag):
    o = call("POST", "/orders", customer, {
        "merchant_id": SHOP["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": f"难度反馈测试地址{tag}", "lat": lat, "lng": lng})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    return o


async def adjustments_of(no: str) -> list[int]:
    async with SessionLocal() as db:
        return list((await db.scalars(select(RiderEarning.amount_cents).where(
            RiderEarning.order_no == no, RiderEarning.kind == "adjustment"))).all())


async def main():
    before = await audit_snapshot()
    lat, lng = await fresh_cell()
    dish = orderable_dish(call("GET", f"/merchants/{SHOP['id']}/dishes"), min_stock=4)
    r1 = await register_fresh_rider("难度反馈骑手甲")
    r2 = await register_fresh_rider("难度反馈骑手乙")

    # ---- 1) 反馈的这一单不当场补钱 ----
    a = run_order(r1, lat, lng, dish, "A")
    res = call("POST", f"/orders/{a['order_no']}/hardship", r1,
               {"kinds": ["no_vehicle"], "note": "车进不去,推了一段"})
    assert res["comp_cents"] == 0 and res["paid_now"] is False, res
    assert "不当场补钱" in res["message"], res["message"]
    assert await adjustments_of(a["order_no"]) == [], "反馈的这一单还是写了调整入账(平台出钱)"
    async with SessionLocal() as db:
        row = await db.scalar(select(RiderHardship).where(
            RiderHardship.order_no == a["order_no"]))
    assert row is not None and row.comp_cents == 0 and row.kinds == ["no_vehicle"], row
    print(f"✓ 反馈照收照记,这一单不当场补钱(回执:{res['message'][:24]}…)")

    # ---- 2) 规则接口照实说 ----
    rules = call("GET", "/orders/hardship-rules", r1)
    assert rules["funder"] == "customer" and rules["paid_now"] is False, rules
    assert any("不当场补钱" in n for n in rules["notes"]), rules["notes"]
    assert not any("平台出" in n for n in rules["notes"]), rules["notes"]
    print("✓ 规则:以后的单顾客付、这一单不当场补,不再说「这笔钱由平台出」")

    # ---- 3) 第二个骑手说了同一件事 → 共识成立,以后的单按真实难度计价 ----
    b = run_order(r2, lat, lng, dish, "B")
    call("POST", f"/orders/{b['order_no']}/hardship", r2, {"kinds": ["no_vehicle"]})
    assert await adjustments_of(b["order_no"]) == []
    from app.services import hardship as hs
    fee = call("GET", f"/orders/delivery-fee?merchant_id={SHOP['id']}&lat={lat}&lng={lng}",
               customer)
    assert fee["parts"]["hardship"] == hs.NO_VEHICLE_CENTS, fee["parts"]
    assert fee["hardship_samples"] == 2 and fee["hardship_lines"], fee
    c = run_order(r1, lat, lng, dish, "C")
    assert c["fee_parts"]["hardship"] == hs.NO_VEHICLE_CENTS, c["fee_parts"]
    assert "骑手反馈这里不好送" in c["promo_note"], c["promo_note"]
    print(f"✓ 两个骑手说过之后:下一单配送费带上难度费 {hs.NO_VEHICLE_CENTS} 分,顾客下单前看得到")

    # ---- 4) 这笔钱顾客付、全归骑手 ----
    call("POST", f"/orders/{c['order_no']}/transition", customer, {"to_status": "completed"})
    detail = call("GET", f"/orders/{c['order_no']}", r1)
    async with SessionLocal() as db:
        got = await db.scalar(select(RiderEarning.amount_cents).where(
            RiderEarning.order_no == c["order_no"], RiderEarning.kind == "earning"))
    assert got == detail["delivery_fee_cents"] + detail["tip_cents"], \
        (got, detail["delivery_fee_cents"], detail["tip_cents"])
    assert await adjustments_of(c["order_no"]) == []
    print(f"✓ 那一单骑手入账 {got} 分 = 配送费(含难度费)+ 小费,平台一分没出")

    # ---- 5) 账务自检不报 ----
    for o in (a, b):
        call("POST", f"/orders/{o['order_no']}/transition", customer,
             {"to_status": "completed"})
    problems = await audit_new_problems(before, a["order_no"], b["order_no"], c["order_no"])
    assert not problems, problems
    print("✓ 账务自检不报这几单")
    print("\ne2e_hardship_no_pay 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
