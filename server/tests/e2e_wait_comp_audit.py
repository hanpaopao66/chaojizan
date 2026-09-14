"""等餐超时补偿(#145)停发之后:等再久也不结补偿,等餐时长照旧记着(申诉的证据)。

2026-09-14 拍板「平台没有钱,不做平台出钱的赔付」:等餐补偿原来是平台另付给骑手的钱
(不进顾客付的配送费),现在停发 —— 不是「默认关」,后台开关一起下掉了,拨不回来。
等餐时长照旧记录、照旧公示,也不向商家收钱(出餐时长君子协定)。之前结过的补偿不动,
审计照历史口径认(fee_parts.wait,见 audit._rider_due)。

1. 后台开关没了:POST /admin/flags/wait_comp → 404 未知开关;
2. 骑手到店后等了远超正常出餐区间的时间:这单完成后骑手入账 == 配送费 + 小费,
   订单的费用拆分里没有 wait;
3. 等餐时长照旧在:骑手对这单申诉时,系统自动附上的证据里有等餐分钟数;
4. 规则页、商家承诺页都不说「有补偿」,说清楚只记录;
5. 账务自检照旧全绿(这一单不报)。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402

from .util import CUSTOMER, MERCHANT, RIDER, call, login  # noqa: E402
from .util import DEMO_SHOP_ID  # noqa: E402
from .util import orderable_dish  # noqa: E402

customer = login(CUSTOMER)
merchant = login(MERCHANT)
rider = login(RIDER)
admin = login("13800000000")

NEAR = {"lat": 30.6612, "lng": 104.0823}


def run_order():
    """下一单,骑手点到店,返回单号。"""
    dishes = call("GET", f"/merchants/{DEMO_SHOP_ID}/dishes")
    dish = orderable_dish(dishes, min_stock=4)
    o = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "等餐补偿停发测试地址", **NEAR})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/riders/orders/{no}/arrived", rider, NEAR)
    return no


async def age_arrival(no: str, minutes: int):
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE orders SET arrived_shop_at = now() - interval "
                 f"'{minutes} minutes' WHERE order_no = :n"), {"n": no})
        await db.commit()


def finish(no: str):
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer,
         {"to_status": "completed"})


async def main():
    from app.config import settings

    # ---- 1. 后台开关没了:拨不回来 ----
    err = call("POST", "/admin/flags/wait_comp", admin, {"value": "on"}, expect_error=True)
    assert err.get("_error") == 404, f"等餐补偿开关还在后台:{err}"
    print("✓ 后台没有等餐补偿开关了(404 未知开关)—— 停发不是默认关")

    # ---- 2. 等了远超正常出餐区间,也不结补偿 ----
    free = settings.delivery_wait_free_minutes
    no = run_order()
    await age_arrival(no, free + 25)
    finish(no)
    row = call("GET", f"/orders/{no}", rider)
    assert not (row.get("fee_parts") or {}).get("wait"), \
        f"停发之后还结了等餐补偿:{row.get('fee_parts')}"
    async with SessionLocal() as db:
        got = await db.scalar(text(
            "SELECT amount_cents FROM rider_earnings WHERE order_no = :n "
            "AND kind = 'earning'"), {"n": no})
    assert got == row["delivery_fee_cents"] + row["tip_cents"], \
        (got, row["delivery_fee_cents"], row["tip_cents"])
    print(f"✓ 到店等了 {free + 25} 分钟:骑手入账 {got} 分 = 配送费 + 小费,没有等餐补偿")

    # ---- 3. 等餐时长照旧记着:申诉时系统自动附上 ----
    ap = call("POST", "/riders/appeals", rider,
              {"order_no": no, "kind": "late", "reason": "到店后商家一直没出餐,等了很久"})
    wait = (ap.get("evidence") or {}).get("wait_minutes")
    assert wait is not None and wait >= free + 20, f"证据里没有等餐时长:{ap.get('evidence')}"
    print(f"✓ 等餐时长照旧记着:申诉证据里是 {wait} 分钟")

    # ---- 4. 规则页、承诺页都不说「有补偿」 ----
    rider_rules = call("GET", "/rules/rider")
    blob = str(rider_rules)
    assert "等餐超时有补偿" not in blob and "等餐的时长照实记录" in blob, rider_rules
    shop_rules = call("GET", "/merchants/me/rules", merchant)
    assert "等餐超时有补偿" not in str(shop_rules), shop_rules
    print("✓ 规则页、商家承诺页不说有补偿,写明等餐时长只记录、公示")

    # ---- 5. 账务自检照旧全绿 ----
    from app.services.audit import run_audit
    problems = await run_audit()
    bad = [p for p in problems if no in str(p.get("detail", ""))]
    assert not bad, f"这一单在账务自检里报了告警:{bad}"
    print("✓ 账务自检不报这一单")

    print("\ne2e_wait_comp_audit 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
