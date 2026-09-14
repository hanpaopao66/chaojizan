"""平台券停发之后(2026-09-14 拍板「平台没有钱,不做平台出钱的安抚和营销」):

1. 后台新建平台批次 410、按手机号定向发券 410 —— 接口上造不出平台券了;
2. 存量的平台新客批次(写库造一个启用中的):营销总开关开着、新用户注册,一张都不发;
3. 平台批次只能停不能开:停用照旧,再启用 410;列表里标出谁出钱(merchant_id 为空 = 平台);
4. 停发之前发出去的平台券(写库造一张)照旧能用:下单抵扣走 subsidy 口径,
   批次转化统计照算,取消后回券包。

在 server/ 目录下运行:python -m tests.e2e_coupon_ops
"""
import asyncio
import random
import time

from app.db import SessionLocal
from app.models import CouponBatch
from tests.util import (call, demo_shop, grant_legacy_platform_coupon, login,
                        orderable_dish)

admin = login("13800000000")
ts = int(time.time())


def fresh_phone():
    return f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"


def register(phone, device=""):
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login", body={
        "phone": phone, "code": code, "device_id": device})["token"]


async def legacy_platform_batch(name: str) -> int:
    """写库造一个停发之前建的平台新客批次(启用中、预算充足)。"""
    async with SessionLocal() as db:
        b = CouponBatch(name=name, trigger="newcomer", amount_cents=500,
                        min_spend_cents=0, valid_days=7, total=100, active=True)
        db.add(b)
        await db.commit()
        return b.id


async def main():
    # 营销总开关默认关;打开它,证明不发券不是因为总开关关着
    call("POST", "/admin/flags/marketing", admin, {"value": "on"})
    try:
        await run()
    finally:
        call("POST", "/admin/flags/marketing", admin, {"value": "off"})


async def run():
    # ---- 1) 接口上造不出平台券 ----
    err = call("POST", "/admin/coupon-batches", admin, {
        "name": f"新客批次{ts}", "trigger": "newcomer", "amount_cents": 500,
        "min_spend_cents": 0, "valid_days": 7, "total": 2}, expect_error=True)
    assert err["_error"] == 410 and "平台不再出钱发券" in err["detail"], err
    print("✓ 新建平台批次:410,说清楚平台不再出钱发券")

    batch_id = await legacy_platform_batch(f"停发前的新客批次{ts}")
    phone = fresh_phone()
    register(phone)
    err = call("POST", "/admin/coupons/issue", admin,
               {"phone": phone, "batch_id": batch_id}, expect_error=True)
    assert err["_error"] == 410, err
    print("✓ 按手机号定向发券(客服补偿):410")

    # ---- 2) 存量平台新客批次:营销总开关开着也一张不发 ----
    u1 = register(fresh_phone())
    mine = [c for c in call("GET", "/orders/coupons/mine", u1)
            if f"停发前的新客批次{ts}" in c["note"]]
    assert not mine, f"平台批次停发之后,新用户注册还是拿到了平台券:{mine}"
    row = next(b for b in call("GET", "/admin/coupon-batches", admin)
               if b["id"] == batch_id)
    assert row["issued"] == 0 and row["merchant_id"] is None, row
    print("✓ 存量平台新客批次:新用户注册一张不发,列表里标着平台批次")

    # ---- 3) 平台批次只能停不能开 ----
    call("POST", f"/admin/coupon-batches/{batch_id}/toggle", admin, {"active": False})
    err = call("POST", f"/admin/coupon-batches/{batch_id}/toggle", admin,
               {"active": True}, expect_error=True)
    assert err["_error"] == 410, err
    row = next(b for b in call("GET", "/admin/coupon-batches", admin)
               if b["id"] == batch_id)
    assert row["active"] is False, row
    print("✓ 平台批次停用照旧、再启用 410(开了也发不出去,列表不许写着「启用」)")

    # ---- 4) 停发之前发出去的平台券照旧能用 ----
    phone2 = fresh_phone()
    u2 = register(phone2)
    cid = await grant_legacy_platform_coupon(
        phone2, 500, source=f"batch:{batch_id}:legacy{ts}",
        note=f"停发前的新客批次{ts}", batch_id=batch_id)
    coupon = next(c for c in call("GET", "/orders/coupons/mine", u2) if c["id"] == cid)
    assert coupon["usable"] is True, coupon
    dishes = call("GET", f"/merchants/{demo_shop()['id']}/dishes")
    dish = orderable_dish(dishes, min_stock=2)
    order = call("POST", "/orders", u2, {
        "merchant_id": demo_shop()["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": cid})
    assert order["subsidy_cents"] >= 500, order["subsidy_cents"]
    used = next(b for b in call("GET", "/admin/coupon-batches", admin)
                if b["id"] == batch_id)
    assert used["used"] == 1, used  # 转化统计照算
    call("POST", f"/orders/{order['order_no']}/transition", u2,
         {"to_status": "cancelled", "reason": "测试清场"})
    back = next(c for c in call("GET", "/orders/coupons/mine", u2) if c["id"] == cid)
    assert back["usable"] is True and back["used"] is False, back
    print("✓ 停发之前发的平台券照旧能用:抵扣走 subsidy 口径,统计照算,取消回券包")
    print("\ne2e_coupon_ops 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
