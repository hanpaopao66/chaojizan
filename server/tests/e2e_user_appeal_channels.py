"""用户侧的另外两个申诉口:售后被拒、账号被风控限制。

## 为什么这两条必须有

**售后被拒**:商家**同意**售后(自己赔钱)一直有 72 小时结构化申诉、
管理端复核、改判有定论;商家**拒绝**售后(用户一分拿不到),用户只能看到
一句「如有异议可联系平台客服」—— 而售后一单一次,被拒之后连重提都不行。
判谁责谁能申诉,这条以前只对一半的人成立。

**风控限制**:`admin.set_user_risk_level` 的 docstring 写着「reason 会展示
给用户,**用户可申诉**」,但申诉的 target_type 里一直没有它,界面上那个
「申请复核」点进去是人工工单,没有确定的结论。**声称有的通道必须真的存在。**

在 server/ 目录下运行:python -m tests.e2e_user_appeal_channels
"""
from tests.util import (call, demo_shop, login, orderable_dish,
                        register_fresh_customer)

merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")
shop = demo_shop()
sid = shop["id"]
dish = orderable_dish(call("GET", f"/merchants/{sid}/dishes"))
EVIDENCE = ["/uploads/demo-evidence-1.jpg"]


def delivered_order(customer):
    no = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    return no


def main() -> None:
    # ============ 一、售后被商家拒绝 ============
    customer = register_fresh_customer("售后被拒申诉")
    no = delivered_order(customer)
    call("POST", f"/orders/{no}/after-sale", customer,
         {"reason": "汤洒了大半,盒子是破的", "images": EVIDENCE})
    pending = call("GET", "/merchants/me/after-sales?status=pending", merchant)
    a = next(x for x in pending if x["order_no"] == no)
    call("POST", f"/after-sales/{a['id']}/reject", merchant,
         {"reply": "出餐时是好的,可能是运输问题"})

    before = call("GET", f"/orders/{no}", customer)
    assert before["refund_cents"] == 0, "被拒了却退了钱?"

    # 只有本人能申诉
    err = call("POST", "/appeals", merchant,
               {"target_type": "after_sale_rejected", "target_id": a["id"],
                "reason": "我是商家,我也来申诉这条拒绝"}, expect_error=True)
    assert err["_error"] == 403, err
    other = register_fresh_customer("路人甲")
    err = call("POST", "/appeals", other,
               {"target_type": "after_sale_rejected", "target_id": a["id"],
                "reason": "不是我的单但我想申诉"}, expect_error=True)
    assert err["_error"] == 404, err
    print("✓ 售后被拒:只有申请人能申诉(商家 403、路人 404)")

    ap = call("POST", "/appeals", customer,
              {"target_type": "after_sale_rejected", "target_id": a["id"],
               "reason": "有照片为证,盒子确实是破的,请复核"})
    assert ap["status"] == "open", ap
    print(f"✓ 用户能对「售后被拒」发起结构化申诉(申诉 #{ap['id']})")

    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:照片可证,该售后应当受理"})
    after = call("GET", f"/orders/{no}", customer)
    assert after["refund_cents"] > 0, (
        f"申诉成立却一分没退({after['refund_cents']})—— 通道就是摆设")
    mine = call("GET", f"/orders/{no}/after-sale", customer)
    assert mine["status"] == "accepted", mine
    print(f"✓ 改判后按「商家同意」的口径走:退款 {after['refund_cents']} 分,"
          f"售后状态转为已受理")

    # 改判之后商家还能再申诉一次(两条 target_type 各管各的,最多两轮)
    ap2 = call("POST", "/appeals", merchant,
               {"target_type": "after_sale", "target_id": a["id"],
                "reason": "我仍然认为不是我的责任,请再复核"})
    assert ap2["status"] == "open", ap2
    print("✓ 商家对改判结果还能再申诉一次 —— 两边都有说话的机会")

    # ============ 二、账号被风控限制 ============
    victim = register_fresh_customer("风控申诉")
    uid = call("GET", "/auth/me", victim)["id"]
    call("POST", f"/admin/users/{uid}/risk-level", admin,
         {"level": "limit", "reason": "同设备多账号领券"})
    me = call("GET", "/auth/me", victim)
    assert me["risk_level"] == "limit" and me["risk_note"], me
    print(f"✓ 被限制且原因对用户可见:{me['risk_note']}")

    # **申诉得有个能指的目标。** /auth/me 直接给出这次处置的记录 id ——
    # 只给 level 和 reason 的话,客户端知道自己被限制了,
    # 却不知道拿什么去申诉,那个入口就是点不动的。
    aid = me["risk_action_id"]
    assert aid > 0, "被限制了却没告诉用户该申诉哪条处置,入口点不动"

    err = call("POST", "/appeals", victim,
               {"target_type": "risk_flag", "target_id": 999999999,
                "reason": "我没有多账号,请复核"}, expect_error=True)
    assert err["_error"] == 404, err
    err = call("POST", "/appeals", other,
               {"target_type": "risk_flag", "target_id": aid,
                "reason": "不是我被限制但我想申诉"}, expect_error=True)
    assert err["_error"] == 404, err
    print("✓ 不存在的记录 404;别人的处置记录也 404")

    ap3 = call("POST", "/appeals", victim,
               {"target_type": "risk_flag", "target_id": aid,
                "reason": "这台设备是家里共用的,不是我在多开账号"})
    assert ap3["status"] == "open", ap3
    print(f"✓ 用户能对「账号被限制」发起结构化申诉(申诉 #{ap3['id']})")

    call("POST", f"/admin/appeals/{ap3['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:家庭共用设备,限制解除"})
    me2 = call("GET", "/auth/me", victim)
    assert me2["risk_level"] == "", (
        f"申诉成立了限制却还在({me2['risk_level']})—— 通道就是摆设")
    assert me2["risk_action_id"] == 0, me2
    print("✓ 改判后限制当场解除,权益恢复")

    # 已经解除了,同一条处置不能再申诉
    err = call("POST", "/appeals", victim,
               {"target_type": "risk_flag", "target_id": aid,
                "reason": "再申诉一次"}, expect_error=True)
    assert err["_error"] == 409, err
    print("✓ 已解除的处置不再受理申诉")

    # ============ 三、风控申诉不限角色 ============
    #
    # 风控处置接口接受任何 user_id,商家和骑手的账号一样会被限制、被冻结,
    # 而冻结对他们是断收入。只开给顾客的话,恰恰把最受影响的两类人
    # 挡在外面 —— 判据是「是不是本人」,不是「是什么角色」。
    rider_id = call("GET", "/auth/me", rider)["id"]
    call("POST", f"/admin/users/{rider_id}/risk-level", admin,
         {"level": "limit", "reason": "测试:骑手账号被限制"})
    rme = call("GET", "/auth/me", rider)
    assert rme["risk_action_id"] > 0, rme
    rap = call("POST", "/appeals", rider,
               {"target_type": "risk_flag", "target_id": rme["risk_action_id"],
                "reason": "我没有违规,请复核这次限制"})
    assert rap["status"] == "open", rap
    call("POST", f"/admin/appeals/{rap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:限制解除"})
    assert call("GET", "/auth/me", rider)["risk_level"] == "", "骑手的限制没解除"
    print("✓ 骑手账号被限制也能申诉并解除(不限角色 —— 冻结对他们是断收入)")

    print("\ne2e_user_appeal_channels 全部通过 ✅")


if __name__ == "__main__":
    main()
