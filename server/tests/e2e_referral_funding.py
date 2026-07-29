"""#115 验收:邀请有礼的券由商家出,平台不再掏钱。

覆盖商家建了「新客推荐券」批次之后的双发路径——没建批次的路径在
e2e_referral 里。关键断言是 funder=merchant:钱从商家的预算里走,
用户端「不靠补贴换增长」那句承诺才站得住。

在 server/ 目录下运行:python -m tests.e2e_referral_funding
"""
import asyncio
import random
import time

from tests.util import call, login, register_fresh_rider, unique_spot

admin = login("13800000000")
merchant = login("13800000002")
ts = int(time.time())
# 独占坐标由 tests.util.unique_spot 统一分配:格间距 88m(> 风控的 65m
# 包围盒)、仍在 4km 配送半径内。自己算坐标很容易踩两个坑——
# 撞风控格子(奖励被挂起,看着像发券坏了)或挪出配送范围(直接拒单)
LAT, LNG = unique_spot()


def fresh(device=""):
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login", body={
        "phone": phone, "code": code, "device_id": device})["token"], phone


def ref_coupons(token):
    return [c for c in call("GET", "/orders/coupons/mine", token)
            if c["note"] == "邀请有礼"]


async def main() -> None:
    call("POST", "/admin/flags/marketing", admin, {"value": "on"})

    # 1) 平台侧不再能建这三类批次
    for trigger in ("referral", "birthday", "winback"):
        err = call("POST", "/admin/coupon-batches", admin, {
            "name": f"平台{trigger}", "trigger": trigger,
            "amount_cents": 300, "total": 10}, expect_error=True)
        assert err["_error"] == 422, (trigger, err)
        assert "商家自建" in err["detail"], err
    print("✓ 平台不再能建 referral/birthday/winback 批次(营销的钱该商家出)")

    # 2) 商家建新客推荐券批次
    shop = call("GET", "/merchants/me", merchant)
    batch = call("POST", "/merchants/me/coupon-batches", merchant, {
        "name": f"新客推荐券{ts}", "trigger": "referral",
        "threshold_cents": 0, "off_cents": 300,
        "total": 2, "per_user_limit": 1, "valid_days": 7})
    print(f"✓ 商家建了 referral 批次(面额 ¥3,总量 2,店铺 {shop['name']})")

    # 3) 这类批次不能出现在「可主动领取」列表里,否则预算立刻被薅空
    claimable = call("GET", f"/merchants/{shop['id']}/coupons", login("13800000001"))
    assert all(c["batch_id"] != batch["id"] for c in claimable), claimable
    print("✓ 自动发放类批次不出现在可领券列表(不会被主动薅)")

    # 4) 邀请 → 首单完成 → 双发,且资金方是商家
    inviter, _ = fresh(device=f"fund_a{ts}")
    code = call("GET", "/referrals/me", inviter)["code"]
    invitee, _ = fresh(device=f"fund_b{ts}")
    call("POST", "/referrals/claim", invitee, {"code": code})

    rider = await register_fresh_rider()
    dishes = call("GET", f"/merchants/{shop['id']}/dishes", invitee)
    dish = next(d for d in dishes if d["is_on_sale"] and d["stock"] > 2
                and not d.get("is_alcohol"))  # 酒类要实名,普通用例账号没实名
    # 凑够起送价:/merchants/me 返回的 min_order_cents 与下单校验用的口径
    # 不是同一个(实测前者 0、后者 ¥15),别猜——直接下够 ¥25
    qty = max(2, -(-2500 // max(dish["price_cents"], 1)))
    order = call("POST", "/orders", invitee, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": qty}],
        "address": f"分账测试路{ts}号", "lat": LAT, "lng": LNG})
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", invitee)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", invitee, {"to_status": "completed"})

    mine = ref_coupons(invitee)
    theirs = ref_coupons(inviter)
    assert len(mine) == 1 and len(theirs) == 1, (mine, theirs)
    for c in mine + theirs:
        assert c["funder"] == "merchant", f"券的资金方还是平台:{c}"
        assert c["merchant_id"] == shop["id"], c
    print("✓ 双方各得一张,funder=merchant、限本店可用——平台一分没出")

    # 5) 预算封顶:总量 2 已发完,再来一对不发
    inviter2, _ = fresh(device=f"fund_c{ts}")
    code2 = call("GET", "/referrals/me", inviter2)["code"]
    invitee2, _ = fresh(device=f"fund_d{ts}")
    call("POST", "/referrals/claim", invitee2, {"code": code2})
    order2 = call("POST", "/orders", invitee2, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": qty}],
        "address": f"分账测试路{ts}号B", "lat": LAT, "lng": LNG})
    no2 = order2["order_no"]
    call("POST", f"/orders/{no2}/pay/mock", invitee2)
    call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no2}", rider)
    call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no2}/transition", invitee2, {"to_status": "completed"})
    assert not ref_coupons(invitee2), "预算发完了还在发券"
    print("✓ 批次总量发完自动停,商家预算不会被超支")

    # 收摊:关掉本用例建的批次,不留给后面的用例(e2e_referral 断言的是
    # 「没批次就不发券」,留着会让它随跑序时好时坏)
    call("POST", f"/merchants/me/coupon-batches/{batch['id']}/toggle", merchant)
    call("POST", "/admin/flags/marketing", admin, {"value": "off"})
    print("\ne2e_referral_funding 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
