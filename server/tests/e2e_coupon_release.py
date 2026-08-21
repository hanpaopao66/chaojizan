"""券的释放:**订单全额退款/关单时,券回券包**(models.Coupon 的不变量)。

用户拿券下单,抵扣走的是订单金额;订单一旦全额退回来,他拿回的是
**打完折的实付**。券如果不跟着还回去,那张券的面额就凭空蒸发了 ——
用户既没吃到饭,也没拿回那部分钱。

人工路径(用户取消/商家拒单/自助退款/缺货退光)都调了 release_coupon,
**两条后台清扫路径漏了**:

  - 无骑手兜底取消(auto_flow `_sweep_no_rider`)——最讽刺的一条:
    超时赔付券本身就是平台赔给用户的,转头被下一单的无骑手取消吃掉;
  - 孤儿追加单级联取消(auto_flow `_sweep_orphan_appends`)。

两条都是**平台侧的原因**取消的单,吃掉用户的券尤其说不过去。
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once

from .util import ADMIN, MERCHANT, call, demo_shop, login

admin = login(ADMIN)
merchant = login(MERCHANT)
SHOP = demo_shop()
TAG = str(int(time.time()))


def new_customer(suffix):
    phone = f"135{(int(TAG) + suffix) % 100000000:08d}"
    token = call("POST", "/auth/register",
                 body={"phone": phone, "password": "123456",
                       "name": f"券释放测试{suffix}",
                       "role": "customer"})["token"]
    return phone, token


def grant(phone, amount=500):
    """建一个 manual 批次并定向发一张券,返回 coupon_id。
    一个批次每人只发一张,所以每张券单独建批次。"""
    batch = call("POST", "/admin/coupon-batches", admin, {
        "name": f"券释放测试-{TAG}-{phone[-4:]}", "trigger": "manual",
        "amount_cents": amount, "min_spend_cents": 0,
        "valid_days": 7, "total": 5})
    return call("POST", "/admin/coupons/issue", admin,
                {"phone": phone, "batch_id": batch["id"],
                 "note": "券释放测试"})["coupon_id"]


def coupon_state(token, coupon_id):
    row = next(c for c in call("GET", "/orders/coupons/mine", token)
               if c["id"] == coupon_id)
    return row


async def age_pool(order_no):
    """把这一单在抢单池里的等待时刻做旧到取消线之外,让兜底清扫接管。"""
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE orders SET rider_pool_since = now() - interval "
            "'31 minutes' WHERE order_no = :n"), {"n": order_no})
        await db.commit()


async def main():
    dish = call("POST", "/merchants/me/dishes", merchant,
                {"name": f"券释放测试菜-{TAG}", "price_cents": 2000,
                 "stock": 50})

    # ---- 1) 无骑手兜底取消:券必须回券包 ----
    phone, cust = new_customer(1)
    cid = grant(phone)
    assert coupon_state(cust, cid)["usable"] is True

    o = call("POST", "/orders", cust, {
        "merchant_id": SHOP["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "券释放测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": cid})
    no = o["order_no"]
    fee = o["delivery_fee_cents"]
    assert o["subsidy_cents"] == 500, f"券没抵上:{o['promo_note']}"
    assert o["total_cents"] == 2000 + fee - 500, o
    paid = call("POST", f"/orders/{no}/pay/mock", cust)["total_cents"]
    assert paid == 2000 + fee - 500, paid
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    assert coupon_state(cust, cid)["used"] is True, "下单后券应处于已用"

    await age_pool(no)
    await sweep_once()
    done = call("GET", f"/orders/{no}", cust)
    assert done["status"] == "cancelled", done["status"]
    assert "无骑手" in done["cancel_reason"], done["cancel_reason"]
    assert done["refund_cents"] == paid, (done["refund_cents"], paid)
    print(f"✓ 无骑手兜底取消:全额退 {paid} 分(= 用户实付)")

    back = coupon_state(cust, cid)
    assert back["used"] is False and back["usable"] is True, (
        f"无骑手兜底取消吃掉了用户的券:{back} —— 用户只拿回打完折的 {paid} 分,"
        f"那 500 分的券面额凭空蒸发了")
    print("✓ 券已回券包,未过期可再用")

    # 真的还能再用一次(不是只把标志清了)
    o2 = call("POST", "/orders", cust, {
        "merchant_id": SHOP["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "券释放测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": cid})
    assert o2["subsidy_cents"] == 500, o2["promo_note"]
    call("POST", f"/orders/{o2['order_no']}/transition", cust,
         {"to_status": "cancelled", "reason": "券释放测试清场"})
    print("✓ 放回去的券确实能再抵一次(不是只清了标志)")

    # ---- 2) 孤儿追加单级联取消:券同样要回券包 ----
    phone3, cust3 = new_customer(2)
    cid3 = grant(phone3, 300)
    parent = call("POST", "/orders", cust3, {
        "merchant_id": SHOP["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "券释放测试地址", "lat": 30.66, "lng": 104.08})
    pno = parent["order_no"]
    call("POST", f"/orders/{pno}/pay/mock", cust3)
    child = call("POST", "/orders", cust3, {
        "merchant_id": SHOP["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "append_to": pno, "coupon_id": cid3})
    cno = child["order_no"]
    assert child["subsidy_cents"] == 300, child["promo_note"]
    assert child["delivery_fee_cents"] == 0, child
    child_paid = call("POST", f"/orders/{cno}/pay/mock", cust3)["total_cents"]
    assert child_paid == 2000 - 300, child_paid

    call("POST", f"/orders/{pno}/transition", cust3,
         {"to_status": "cancelled", "reason": "券释放测试:原单取消"})
    await sweep_once()
    kid = call("GET", f"/orders/{cno}", cust3)
    assert kid["status"] == "cancelled", kid["status"]
    assert "原订单已取消" in kid["cancel_reason"], kid["cancel_reason"]
    assert kid["refund_cents"] == child_paid, (kid["refund_cents"], child_paid)
    print(f"✓ 孤儿追加单级联取消:全额退 {child_paid} 分(= 用户实付)")

    back3 = coupon_state(cust3, cid3)
    assert back3["used"] is False and back3["usable"] is True, (
        f"孤儿追加单级联取消吃掉了用户的券:{back3}")
    print("✓ 券已回券包,未过期可再用")

    call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
         {"is_on_sale": False})
    print("\ne2e_coupon_release 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
