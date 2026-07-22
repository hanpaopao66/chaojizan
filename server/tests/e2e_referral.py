"""邀请有礼验证:填码(自邀/重复/同设备/过期/月上限)、
首单完成双发券且只发一次、取消单不触发、admin 漏斗。

在 server/ 目录下运行:python -m tests.e2e_referral
"""
import asyncio
import random
import time

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import call, login, register_fresh_rider

admin = login("13800000000")
merchant = login("13800000002")
ts = int(time.time())
# 独占坐标+地址:避开 #44 风控的同址高频标记(命中会挂起奖励,设计如此)
LAT = 30.6650 + (ts % 20) * 1.3e-3
LNG = 104.0823


def fresh(device=""):
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login", body={
        "phone": phone, "code": code, "device_id": device})["token"], phone


def referral_coupons(token):
    return [c for c in call("GET", "/orders/coupons/mine", token)
            if c["note"] == "邀请有礼"]


async def main():
    # 营销总开关默认关(没有预算一张不发);本测试临时打开,结尾恢复
    call("POST", "/admin/flags/marketing", admin, {"value": "on"})

    inviter, _ = fresh(device=f"invdev{ts}")
    code = call("GET", "/referrals/me", inviter)["code"]
    assert len(code) == 6

    # 1) 校验:自邀 422、同设备 422、不存在 404
    err = call("POST", "/referrals/claim", inviter, {"code": code},
               expect_error=True)
    assert err["_error"] == 422
    same_dev, _ = fresh(device=f"invdev{ts}")
    err = call("POST", "/referrals/claim", same_dev, {"code": code},
               expect_error=True)
    assert err["_error"] == 422 and "同一台设备" in err["detail"]
    err = call("POST", "/referrals/claim", same_dev, {"code": "000001"},
               expect_error=True)
    assert err["_error"] in (404, 422)
    print("✓ 自邀/同设备/不存在的码全被拦")

    # 2) 正常填码;重复 409;过期(backdate 注册时间)409
    invitee, invitee_phone = fresh(device=f"okdev{ts}")
    r = call("POST", "/referrals/claim", invitee, {"code": code})
    assert "首单" in r["hint"]
    err = call("POST", "/referrals/claim", invitee, {"code": code},
               expect_error=True)
    assert err["_error"] == 409
    late, late_phone = fresh()
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE users SET created_at = now() - interval '25 hours' "
            "WHERE phone = :p"), {"p": late_phone})
        await db.commit()
    err = call("POST", "/referrals/claim", late, {"code": code},
               expect_error=True)
    assert err["_error"] == 409 and "24 小时" in err["detail"]
    print("✓ 填码成功;重复 409;注册超 24 小时 409")

    # 3) 首单完成 → 双方发券且只发一次;取消单不触发
    shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
    sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
    dish = call("POST", "/merchants/me/dishes", merchant,
                {"name": f"邀请测试菜-{ts}", "price_cents": 2000,
                 "stock": 30})
    rider = await register_fresh_rider("邀请测试骑手")

    def run_order(token, cancel=False):
        order = call("POST", "/orders", token, {
            "merchant_id": sid,
            "items": [{"dish_id": dish["id"], "quantity": 1}],
            "address": f"邀请测试地址{ts}", "lat": LAT, "lng": LNG})
        no = order["order_no"]
        call("POST", f"/orders/{no}/pay/mock", token)
        if cancel:
            call("POST", f"/orders/{no}/transition", token,
                 {"to_status": "cancelled", "reason": "不要了"})
            return no
        call("POST", f"/orders/{no}/transition", merchant,
             {"to_status": "accepted"})
        call("POST", f"/riders/grab/{no}", rider)
        call("POST", f"/orders/{no}/transition", merchant,
             {"to_status": "ready"})
        call("POST", f"/orders/{no}/transition", rider,
             {"to_status": "picked_up"})
        call("POST", f"/orders/{no}/transition", rider,
             {"to_status": "delivered"})
        call("POST", f"/orders/{no}/transition", token,
             {"to_status": "completed"})
        return no

    run_order(invitee, cancel=True)  # 取消单:不该触发奖励
    assert not referral_coupons(invitee) and not referral_coupons(inviter)
    run_order(invitee)  # 首个完成单:双发券
    assert len(referral_coupons(invitee)) == 1
    assert len(referral_coupons(inviter)) == 1
    run_order(invitee)  # 第二单:不再发
    assert len(referral_coupons(invitee)) == 1
    me = call("GET", "/referrals/me", inviter)
    assert me["invited"] == 1 and me["rewarded"] == 1
    print("✓ 取消单不触发;首个完成单双发券;只发一次")

    # 4) admin 漏斗
    funnel = call("GET", "/admin/referrals", admin)["funnel"]
    assert funnel["claimed"] >= 1 and funnel["rewarded"] >= 1
    assert funnel["coupons_issued"] >= 2
    print("✓ admin 漏斗数字正确")

    call("POST", "/admin/flags/marketing", admin, {"value": "off"})
    print("\ne2e_referral 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
