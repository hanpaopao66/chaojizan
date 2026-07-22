"""平台券运营化验证:批次创建/校验、注册自动发新客券、每人一张、
限量停发、同设备多账号不发(风控)、停用不发、定向发、
统计数字、券下单抵扣(subsidy 口径复用 #34 通道)。

在 server/ 目录下运行:python -m tests.e2e_coupon_ops
"""
import asyncio
import random
import time

from tests.util import call, login

admin = login("13800000000")
merchant = login("13800000002")
ts = int(time.time())


def fresh_phone():
    return f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"


def register(phone, device=""):
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login", body={
        "phone": phone, "code": code, "device_id": device})["token"]


def my_batch_coupons(token, batch_id):
    return [c for c in call("GET", "/orders/coupons/mine", token)
            if f"批次{ts}" in c["note"]]


async def main():
    # 营销总开关默认关(没有预算一张不发);本测试临时打开,结尾恢复
    call("POST", "/admin/flags/marketing", admin, {"value": "on"})

    # 1) 批次创建与校验
    err = call("POST", "/admin/coupon-batches", admin,
               {"name": "", "amount_cents": 500, "total": 10},
               expect_error=True)
    assert err["_error"] == 422
    err = call("POST", "/admin/coupon-batches", admin,
               {"name": "大额", "amount_cents": 999999, "total": 10},
               expect_error=True)
    assert err["_error"] == 422  # 补贴要克制
    batch_id = call("POST", "/admin/coupon-batches", admin, {
        "name": f"新客批次{ts}", "trigger": "newcomer",
        "amount_cents": 500, "min_spend_cents": 0,
        "valid_days": 7, "total": 2})["id"]
    print("✓ 批次创建与参数校验")

    # 2) 注册自动发;同一用户不重复(source 唯一)
    u1 = register(fresh_phone())
    c1 = my_batch_coupons(u1, batch_id)
    assert len(c1) == 1 and c1[0]["amount_cents"] == 500 and c1[0]["usable"]
    print("✓ 新用户注册自动发新客券")

    # 3) 同设备多账号:第二个号不发(风控口径)
    device = f"riskdev{ts}"
    ua = register(fresh_phone(), device=device)
    assert len(my_batch_coupons(ua, batch_id)) == 1  # 第一个号正常发(占第2张)
    ub = register(fresh_phone(), device=device)
    assert len(my_batch_coupons(ub, batch_id)) == 0, "同设备第二个号不该发"
    print("✓ 同设备多账号不发(防薅)")

    # 4) 限量:总量 2 已发完,新注册不再发
    uc = register(fresh_phone())
    assert len(my_batch_coupons(uc, batch_id)) == 0, "预算发完应自动停"
    stats = next(b for b in call("GET", "/admin/coupon-batches", admin)
                 if b["id"] == batch_id)
    assert stats["issued"] == 2 and stats["total"] == 2
    print("✓ 预算封顶自动停发,统计发放数正确")

    # 5) 定向发:manual 批次按手机号;重复发 409;停用后 409
    manual_id = call("POST", "/admin/coupon-batches", admin, {
        "name": f"补偿批次{ts}", "trigger": "manual",
        "amount_cents": 300, "total": 10})["id"]
    phone_c = fresh_phone()
    ud = register(phone_c)
    call("POST", "/admin/coupons/issue", admin,
         {"phone": phone_c, "batch_id": manual_id})
    err = call("POST", "/admin/coupons/issue", admin,
               {"phone": phone_c, "batch_id": manual_id}, expect_error=True)
    assert err["_error"] == 409  # 每人每批次一张
    call("POST", f"/admin/coupon-batches/{manual_id}/toggle", admin,
         {"active": False})
    err = call("POST", "/admin/coupons/issue", admin,
               {"phone": fresh_phone(), "batch_id": manual_id},
               expect_error=True)
    assert err["_error"] in (404, 409)
    print("✓ 定向发/防重发/停用停发")

    # 6) 新客券下单抵扣走 subsidy 口径(复用 #34 通道)
    shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
    sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
    dish = call("POST", "/merchants/me/dishes", merchant,
                {"name": f"券测试菜-{ts}", "price_cents": 2000, "stock": 20})
    coupon = my_batch_coupons(u1, batch_id)[0]
    order = call("POST", "/orders", u1, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
        "coupon_id": coupon["id"]})
    assert order["subsidy_cents"] >= 500, order["subsidy_cents"]
    used = next(b for b in call("GET", "/admin/coupon-batches", admin)
                if b["id"] == batch_id)
    assert used["used"] == 1  # 转化统计
    call("POST", f"/orders/{order['order_no']}/transition", u1,
         {"to_status": "cancelled", "reason": "测试清场"})
    print("✓ 新客券抵扣走 subsidy 口径,批次转化统计正确")

    # 7) 营销总开关关掉后:新客批次仍启用,但一张不发(没有预算的兜底)
    call("POST", "/admin/flags/marketing", admin, {"value": "off"})
    batch2 = call("POST", "/admin/coupon-batches", admin, {
        "name": f"关停验证批次{ts}", "trigger": "newcomer",
        "amount_cents": 500, "total": 10})["id"]
    ue = register(fresh_phone())
    assert not [c for c in call("GET", "/orders/coupons/mine", ue)
                if f"关停验证批次{ts}" in c["note"]], "总开关关着不该发券"
    call("POST", f"/admin/coupon-batches/{batch2}/toggle", admin,
         {"active": False})
    print("✓ 营销总开关关:批次照留,一张不发")
    print("\ne2e_coupon_ops 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
