"""异常订单标记:商家标了,平台**真的**在看。

## 这条守什么

这个功能原来是半截的:服务端接口完整、库里攒了 45 条标记,
而**平台侧一个地方都没有在看它们**。

那比不做更坏 —— 商家点完看到的提示是「已上报平台核查,核查有结果会通知你」,
而实际上没有任何人核查、也没有任何通知。收下举报然后扔进抽屉。

而且这个功能的整个设计前提就是平台在看:平台不给商家拉黑顾客的权力
(那会变成报复工具),作为交换承诺了一件单店做不到的事 ——
把多家店的标记放在一起看。承诺不兑现,交换就不成立。

所以这条 e2e 守的是**闭环**,不是某个接口能不能调通:
标记 → 跨店聚合看得到 → 下结论 → 商家收到通知。

在 server/ 目录下运行:python -m tests.e2e_order_flag
"""
from tests.util import (call, demo_shop, login, orderable_dish,
                        register_fresh_customer)

merchant = login("13800000002")
admin = login("13800000000")
rider = login("13800000003")
shop = demo_shop()
dish = orderable_dish(call("GET", f"/merchants/{shop['id']}/dishes"))


def completed_order(customer) -> str:
    """跑一单到完成 —— 标记的是已经发生过的交易,不是凭空标人。"""
    no = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "标记测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "picked_up", "force": True})
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "delivered", "handoff": "hand"})
    return no


def main() -> None:
    customer = register_fresh_customer("被标记的")
    no = completed_order(customer)

    # ---------- 1) 标记 ----------
    r = call("POST", f"/merchants/me/orders/{no}/flag", merchant,
             {"kind": "claim", "reason": "收货后说少了一份小菜要求全额退款,"
                                         "但配送照片里袋子是封好的"})
    assert r["ok"] is True
    # 提示语里必须说清「不会自动处置」—— 不说清楚,商家会以为按下去就解决了
    assert "不会自动" in r["note"], f"提示没说清不会自动处置:{r['note']}"
    print("✓ 商家标记成功,提示里说清了「不会自动对顾客做任何处置」")

    # 同一单不能标两次
    err = call("POST", f"/merchants/me/orders/{no}/flag", merchant,
               {"kind": "claim", "reason": "再标一次看看能不能重复上报"},
               expect_error=True)
    assert err["_error"] == 409, f"同一单能重复标记:{err}"

    # 理由太短要拦 —— 平台要靠这段话去核查,一个字的理由核查不了
    no2 = completed_order(customer)
    err = call("POST", f"/merchants/me/orders/{no2}/flag", merchant,
               {"kind": "claim", "reason": "坏"}, expect_error=True)
    assert err["_error"] == 422
    print("✓ 重复标记 409、理由太短 422")

    # ---------- 2) 商家看得到自己标过什么 ----------
    mine = call("GET", "/merchants/me/order-flags", merchant)
    row = next((x for x in mine["items"] if x["order_no"] == no), None)
    assert row is not None and row["status"] == "pending"
    print(f"✓ 商家查得到自己的标记(当前状态:{row['status']})")

    # ---------- 3) 平台真的在看 ----------
    #
    # 这一步是整个功能的意义。以前这个接口**不存在** ——
    # 商家标了 45 条,平台一条都看不到。
    board = call("GET", "/admin/order-flags?only_cross_shop=false", admin)
    assert board["how_to_read"], "没有告诉看的人这些数字该怎么理解"
    me = next((x for x in board["items"]
               if any(d["order_no"] == no for d in x["details"])), None)
    assert me is not None, "商家标记的单在平台侧看不到 —— 举报被扔进了抽屉"
    assert me["flags"] >= 1 and me["shop_count"] >= 1
    assert me["phone"].count("*") >= 4, f"顾客手机号没打码:{me['phone']}"
    print(f"✓ 平台看得到:该顾客被 {me['shop_count']} 家店标了 "
          f"{me['flags']} 次(手机号已打码)")

    # 默认只看跨店的 —— 单店标记噪音太多
    cross = call("GET", "/admin/order-flags", admin)
    assert cross["only_cross_shop"] is True
    assert all(x["shop_count"] >= 2 for x in cross["items"]), (
        "默认视图里混进了只被一家店标过的顾客 —— 那些多半是噪音")
    print(f"✓ 默认只看跨店({len(cross['items'])} 个被两家以上的店标过)")

    # ---------- 4) 下结论,而且结论不等于处罚 ----------
    flag_id = next(d["id"] for d in me["details"] if d["order_no"] == no)
    err = call("POST", f"/admin/order-flags/{flag_id}/resolve", admin,
               {"result": "拉黑"}, expect_error=True)
    assert err["_error"] == 422, "结论字段没有校验,能填任意值"

    call("POST", f"/admin/order-flags/{flag_id}/resolve", admin,
         {"result": "reviewed"})
    again = call("GET", "/merchants/me/order-flags", merchant)
    row2 = next(x for x in again["items"] if x["order_no"] == no)
    assert row2["status"] == "reviewed", f"结论没回到商家侧:{row2}"
    print("✓ 平台下结论,商家侧状态跟着变")

    # 顾客账号不能因为这条标记被限制 —— 那条路要走风控处置(有申诉通道)
    who = call("GET", "/auth/me", customer)
    assert not who.get("risk_level"), (
        f"标记核查属实就把顾客账号限制了({who.get('risk_level')}) —— "
        f"限制账号必须走风控处置那条路,那条有留痕也有申诉通道")
    print("✓ 结论属实也没有自动限制顾客账号(限制要走风控,那条有申诉通道)")

    # 同一条不能重复下结论
    err = call("POST", f"/admin/order-flags/{flag_id}/resolve", admin,
               {"result": "dismissed"}, expect_error=True)
    assert err["_error"] == 409
    print("✓ 同一条标记不能重复下结论")

    print("\ne2e_order_flag 全部通过 ✅")


if __name__ == "__main__":
    main()
