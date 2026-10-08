"""商家承担配送费(2026-10-08):商家在后台设固定金额或比例,顾客少付,骑手照拿全额。

守的几条:
- 预览和下单同一个数(结算页说 ¥3、付款变 ¥5 是同一种病);
- 商家只能摊距离 / 夜间 / 天气那几项,无电梯爬楼费仍由顾客付;
- 骑手入账 = 全额配送费,一分不少;
- 商家入账少掉这笔、佣金基数也扣掉它(商家让利不抽成);
- 账务自检不因为它多出任何一条问题。
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import MerchantEarning, Order, RiderEarning  # noqa: E402

from .util import (CUSTOMER, DEMO_SHOP_ID, MERCHANT, RIDER,  # noqa: E402
                   audit_new_problems, audit_snapshot, call, login)

customer = login(CUSTOMER)
merchant = login(MERCHANT)
rider = login(RIDER)

FAR = {"lat": 30.6927, "lng": 104.0823}


def set_share(**kw):
    return call("PATCH", "/merchants/me", merchant, kw)


def preview(**kw):
    q = "&".join(f"{k}={v}" for k, v in {"merchant_id": DEMO_SHOP_ID, **FAR, **kw}.items())
    return call("GET", f"/orders/delivery-fee?{q}", customer)


async def main():
    shop = call("GET", "/merchants/me", merchant)
    old = {"delivery_share_cents": shop["delivery_share_cents"],
           "delivery_share_pct": shop["delivery_share_pct"]}
    try:
        await run()
    finally:
        set_share(delivery_share_cents=0, delivery_share_pct=0)
        if old["delivery_share_cents"] or old["delivery_share_pct"]:
            set_share(**{k: v for k, v in old.items() if v})


async def run():
    # ---- 设置:二选一,设一个清另一个 ----
    bad = call("PATCH", "/merchants/me", merchant,
               {"delivery_share_cents": 100, "delivery_share_pct": 50},
               expect_error=True)
    assert bad.get("_error") == 422, bad
    s = set_share(delivery_share_pct=50)
    assert s["delivery_share_pct"] == 50 and s["delivery_share_cents"] == 0, s
    s = set_share(delivery_share_cents=200)
    assert s["delivery_share_cents"] == 200 and s["delivery_share_pct"] == 0, \
        f"改成固定金额后旧的比例要清零,否则它在暗中生效:{s}"
    print("✓ 承担配送费:固定金额 / 比例二选一,改一个清另一个")

    # ---- 预览:骑手拿的不变,顾客付的少 200 ----
    pv = preview(floor=6, has_elevator="false")
    assert pv["merchant_share_cents"] == 200, pv
    assert pv["customer_fee_cents"] == pv["fee_cents"] - 200, pv
    assert pv["parts"]["door"] == 200, "6 楼无电梯的爬楼费照收"
    print(f"✓ 预览:配送费 ¥{pv['fee_cents'] / 100:g}(全归骑手),"
          f"商家出 ¥2,顾客付 ¥{pv['customer_fee_cents'] / 100:g}")

    # 比例只摊距离 / 夜间 / 天气,爬楼费不摊
    set_share(delivery_share_pct=100)
    pv_all = preview(floor=6, has_elevator="false")
    assert pv_all["customer_fee_cents"] == pv_all["parts"]["door"] + pv_all["parts"]["hardship"], \
        f"商家全包也只包到爬楼费之前:{pv_all}"
    print("✓ 商家全包配送费时,顾客只付无电梯爬楼费")
    set_share(delivery_share_cents=200)

    # ---- 下单 → 完成:金额和入账 ----
    before = await audit_snapshot()
    dish = call("POST", "/merchants/me/dishes", merchant,
                {"name": f"分担配送费测试菜-{int(time.time())}",
                 "price_cents": 2000, "stock": 20})
    order = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "分担配送费测试地址", **FAR})
    no = order["order_no"]
    fee = order["delivery_fee_cents"]
    packing = order["packing_fee_cents"]
    assert order["merchant_delivery_cents"] == 200, order
    assert order["discount_cents"] >= 200, order
    assert order["total_cents"] == 2000 + packing - order["discount_cents"] + fee \
        + order["tip_cents"] - order["subsidy_cents"], order
    assert "商家承担配送费-2元" in order["promo_note"], order["promo_note"]
    print(f"✓ 下单:配送费 ¥{fee / 100:g} 不变,商家承担 ¥2 记进订单,顾客实付少 ¥2")

    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

    async with SessionLocal() as db:
        o = await db.scalar(select(Order).where(Order.order_no == no))
        re_ = await db.scalar(select(RiderEarning).where(RiderEarning.order_id == o.id))
        me_ = await db.scalar(select(MerchantEarning).where(MerchantEarning.order_id == o.id))
    assert re_.amount_cents == fee + o.tip_cents, \
        f"骑手要拿全额配送费:{re_.amount_cents} ≠ {fee} + 小费 {o.tip_cents}"
    gross = 2000 + packing - o.discount_cents
    assert me_.food_cents == gross, (me_.food_cents, gross)
    assert me_.net_cents == gross - o.commission_cents
    print(f"✓ 入账:骑手 ¥{re_.amount_cents / 100:g}(全额),"
          f"商家实收少 ¥2、佣金按扣掉后的数算")

    # ---- 缺货退一道菜:商家承担的配送费跟菜没关系,不随菜分摊 ----
    o2 = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 2}],
        "address": "分担配送费测试地址", **FAR})
    no2 = o2["order_no"]
    call("POST", f"/orders/{no2}/pay/mock", customer)
    r = call("POST", f"/orders/{no2}/refund-item", merchant,
             {"dish_id": dish["id"], "quantity": 1})
    assert r["merchant_delivery_cents"] == 200, r
    food_disc = o2["discount_cents"] - 200
    assert r["refund_cents"] == 2000 - food_disc * 2000 // 4000 - \
        o2["subsidy_cents"] * 2000 // 4000, (r, o2)
    print("✓ 缺货退菜:商家承担的 ¥2 配送费不随菜被收回")

    # ---- 改近地址:配送费降了,先还商家多出的那份,顾客没付过的钱不退给他 ----
    set_share(delivery_share_pct=100)
    far = {"lat": 30.6896, "lng": 104.0810}
    near = {"lat": 30.6630, "lng": 104.0810}
    o3 = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "远端小区 1 栋", **far})
    no3 = o3["order_no"]
    call("POST", f"/orders/{no3}/pay/mock", customer)
    after = call("POST", f"/orders/{no3}/change-address", customer,
                 {"address": "近端小区 2 栋", **near,
                  "contact_name": "改址人", "contact_phone": "13400000000"})
    diff = o3["delivery_fee_cents"] - after["delivery_fee_cents"]
    assert diff > 0, (o3, after)
    assert after["merchant_delivery_cents"] == o3["merchant_delivery_cents"] - diff, after
    assert after["refund_cents"] == 0, "商家全包的配送费降了,钱回商家,不退给顾客"
    assert after["total_cents"] == o3["total_cents"], after
    print(f"✓ 改近地址:配送费少 ¥{diff / 100:g},全回到商家承担的那份,顾客实付不变")
    set_share(delivery_share_cents=200)

    new = await audit_new_problems(before, no, no2, no3)
    assert not new, f"账务自检多出问题:{new}"
    print("✓ 账务自检没有新增问题")


if __name__ == "__main__":
    asyncio.run(main())
