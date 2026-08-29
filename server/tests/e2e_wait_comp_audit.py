"""等餐补偿进不进审计恒等式(潜伏 bug 的回归锁)。

## 这个坑长什么样

等餐补偿由**平台承担**、不进 `delivery_fee_cents`(顾客不该为商家出餐慢
买单),但它确实进了骑手入账。而审计的配送侧恒等式左边原本只算
「配送费 + 小费」——只要有一单真的付了等餐补偿,每日账务自检就会报红:

    配送侧恒等不平:Σ(配送费+小费) 800 ≠ Σ骑手入账 950

发现它的时候库里一单都还没有(要骑手点过到店、等超 15 分钟、并且这单
真的完成),所以它一直潜伏着。跑腿的 2% 服务费会踩同一个坑,
所以恒等式左边改成**骑手应得**而不是**顾客付的配送费**。

这条用例的作用是把这个口径锁死:以后谁再往骑手入账里加一笔平台承担的
钱而忘了改审计,这里就红。
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
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

NEAR = {"lat": 30.6612, "lng": 104.0823}


async def main():
    from app.config import settings
    from app.services.pricing import wait_compensation_cents

    # 先对函数下断言:等餐补偿本身要真的算得出钱来,
    # 否则下面整条链路可能因为补偿恰好为 0 而"通过"
    free = settings.delivery_wait_free_minutes
    assert wait_compensation_cents(free) == 0, "免费区间内不补"
    assert wait_compensation_cents(free + 10) > 0, "超出部分要补"
    print(f"✓ 等餐补偿:前 {free} 分钟不补,超出按分钟计")

    dishes = call("GET", f"/merchants/{DEMO_SHOP_ID}/dishes")
    dish = orderable_dish(dishes, min_stock=4)
    o = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "等餐补偿测试地址", **NEAR})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/riders/orders/{no}/arrived", rider, NEAR)

    # 把到店时刻做旧,制造一段真实的等餐时长
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE orders SET arrived_shop_at = now() - interval "
                 f"'{free + 20} minutes' WHERE order_no = :n"), {"n": no})
        await db.commit()

    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

    row = call("GET", f"/orders/{no}", rider)
    wait_cents = (row.get("fee_parts") or {}).get("wait", 0)
    assert wait_cents > 0, f"这一单应当产生等餐补偿:{row.get('fee_parts')}"
    # 补偿**不进 delivery_fee_cents** —— 那是顾客付的钱
    assert sum(v for k, v in row["fee_parts"].items() if k != "wait") \
        == row["delivery_fee_cents"], row["fee_parts"]
    print(f"✓ 产生等餐补偿 {wait_cents} 分,且不计入顾客付的配送费")

    # 骑手实际入账 = 配送费 + 小费 + 等餐补偿
    async with SessionLocal() as db:
        got = await db.scalar(text(
            "SELECT amount_cents FROM rider_earnings WHERE order_no = :n "
            "AND kind = 'earning'"), {"n": no})
    assert got == row["delivery_fee_cents"] + row["tip_cents"] + wait_cents, \
        (got, row["delivery_fee_cents"], row["tip_cents"], wait_cents)
    print(f"✓ 骑手入账 {got} 分 = 配送费 + 小费 + 等餐补偿")

    # ---- 关键:账务自检必须仍然全绿 ----
    from app.services.audit import run_audit
    problems = await run_audit()
    # 断言范围要够宽:只查全局恒等的话,逐单的 rider_earning_mismatch
    # 会漏网 —— 第一版就是这么漏的,日志里明明打了告警,用例还是绿的
    bad = [p for p in problems if "global_identity" in str(p.get("check"))
           or no in str(p.get("detail", ""))]
    assert not bad, f"这一单在账务自检里报了告警:{bad}"
    print("✓ 账务自检仍全绿 —— 恒等式左边算的是「骑手应得」不是「顾客付的配送费」")

    print("\ne2e_wait_comp_audit 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
