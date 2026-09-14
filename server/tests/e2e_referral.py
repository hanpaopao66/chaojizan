"""邀请有礼停了之后(2026-09-14 拍板「平台没有钱,不做平台出钱的安抚和营销」):

1. 「我的邀请」:enabled=false、stopped=true,不给邀请码,战绩照报,说明照实;
2. 填码一律 410,说清楚停了;
3. 停之前填了码、还没完成首单的邀请(写库造一条 pending 关系):被邀请人完成首单,
   关系还是 pending,双方一张券都不发 —— 即使首单那家店开着「新客推荐券」批次;
4. 已经到账的券照旧能用(写库造一张停之前发的邀请有礼券,下单能抵);
5. 后台漏斗照旧能看历史。

商家那一侧(不许再建新客推荐券批次)在 e2e_referral_funding。

在 server/ 目录下运行:python -m tests.e2e_referral
"""
import asyncio
import random
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Coupon, CouponBatch, Referral, User, UserRole
from tests.util import (call, demo_shop, login, orderable_dish, register_fresh_rider,
                        unique_spot)

admin = login("13800000000")
merchant = login("13800000002")
ts = int(time.time())


def fresh(device=""):
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login", body={
        "phone": phone, "code": code, "device_id": device})["token"], phone


def referral_coupons(token):
    return [c for c in call("GET", "/orders/coupons/mine", token)
            if c["note"] == "邀请有礼"]


async def uid_of(phone: str) -> int:
    async with SessionLocal() as db:
        return await db.scalar(select(User.id).where(
            User.phone == phone, User.role == UserRole.customer))


async def main():
    # 营销总开关打开:证明不发是因为活动停了,不是因为总开关关着
    call("POST", "/admin/flags/marketing", admin, {"value": "on"})
    try:
        await run()
    finally:
        call("POST", "/admin/flags/marketing", admin, {"value": "off"})


async def run():
    inviter, inviter_phone = fresh(device=f"invdev{ts}")

    # ---- 1) 我的邀请:停了,不给码 ----
    me = call("GET", "/referrals/me", inviter)
    assert me["enabled"] is False and me["stopped"] is True, me
    assert me["code"] == "" and me["can_claim"] is False, me
    assert "停了" in me["note"] and "照旧能用" in me["note"], me
    print("✓ 我的邀请:活动已停,不再给邀请码,说明里写清楚到账的券照旧能用")

    # ---- 2) 填码 410 ----
    invitee, invitee_phone = fresh(device=f"okdev{ts}")
    err = call("POST", "/referrals/claim", invitee, {"code": "123456"},
               expect_error=True)
    assert err["_error"] == 410 and "停了" in err["detail"], err
    print("✓ 填邀请码:410,说清楚停了")

    # ---- 3) 停之前留下的 pending 邀请:首单完成也不发 ----
    shop = demo_shop()
    inviter_id, invitee_id = await uid_of(inviter_phone), await uid_of(invitee_phone)
    async with SessionLocal() as db:
        db.add(Referral(inviter_id=inviter_id, invitee_id=invitee_id, status="pending"))
        # 店里开着一个「新客推荐券」批次(停之前建的):停了之后它也不许再发
        batch = CouponBatch(name=f"停前的新客推荐券{ts}", trigger="referral",
                            merchant_id=shop["id"], amount_cents=300,
                            min_spend_cents=0, valid_days=7, total=10, active=True)
        db.add(batch)
        await db.commit()
        batch_id = batch.id

    rider = await register_fresh_rider("邀请停发测试骑手")
    dish = orderable_dish(call("GET", f"/merchants/{shop['id']}/dishes"), min_stock=2)
    lat, lng = unique_spot(band=1)
    order = call("POST", "/orders", invitee, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": f"邀请停发测试地址{ts}", "lat": lat, "lng": lng})
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", invitee)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", invitee, {"to_status": "completed"})

    assert not referral_coupons(invitee), "邀请有礼停了,被邀请人首单完成还是发了券"
    assert not referral_coupons(inviter), "邀请有礼停了,邀请人还是拿到了券"
    async with SessionLocal() as db:
        status = await db.scalar(select(Referral.status).where(
            Referral.invitee_id == invitee_id))
        issued = await db.scalar(select(CouponBatch.issued).where(
            CouponBatch.id == batch_id))
        # 收摊:这个批次是本用例造的,关掉不留给后面的用例
        await db.execute(CouponBatch.__table__.update()
                         .where(CouponBatch.id == batch_id).values(active=False))
        await db.commit()
    assert status == "pending", f"停了之后 pending 的邀请变成了 {status}"
    assert issued == 0, f"停了之后新客推荐券批次还发出去 {issued} 张"
    me = call("GET", "/referrals/me", inviter)
    assert me["invited"] == 1 and me["rewarded"] == 0, me
    print("✓ 停之前填了码、首单在停之后完成:关系照旧 pending,双方一张券都不发")

    # ---- 4) 已经到账的券照旧能用 ----
    async with SessionLocal() as db:
        # 面额给大一点:演示店有满减,店铺券和满减二选一取优,小额券会被「满减更优」拒掉
        c = Coupon(user_id=inviter_id, amount_cents=1500, min_spend_cents=0,
                   expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                   source=f"batch:{batch_id}:{inviter_id}", batch_id=batch_id,
                   note="邀请有礼", funder="merchant", merchant_id=shop["id"])
        db.add(c)
        await db.commit()
        cid = c.id
    held = next(x for x in referral_coupons(inviter) if x["id"] == cid)
    assert held["usable"] is True, held
    o2 = call("POST", "/orders", inviter, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": f"邀请停发测试地址{ts}B", "lat": lat, "lng": lng,
        "coupon_id": cid})
    assert "店铺券" in o2["promo_note"], o2["promo_note"]
    call("POST", f"/orders/{o2['order_no']}/transition", inviter,
         {"to_status": "cancelled", "reason": "测试清场"})
    print("✓ 停之前已经到账的邀请有礼券照旧能用")

    # ---- 5) 后台漏斗照旧能看历史 ----
    funnel = call("GET", "/admin/referrals", admin)["funnel"]
    assert funnel["claimed"] >= 1, funnel
    print("✓ 后台漏斗照旧能看历史")
    print("\ne2e_referral 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
