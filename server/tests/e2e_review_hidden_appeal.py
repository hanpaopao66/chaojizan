"""评价被隐藏,写的人要知道、要能申诉、改判要真恢复。

## 为什么这条必须有

商家就某条差评申诉成立 → 评价从店铺页消失、店铺评分加回去。而在这之前,
**写评价的人一无所知,也没有任何说话的地方** —— 平台在两个当事人之间做了
单方面裁决,只通知了赢的那一方。一方能申诉、另一方连通知都收不到,
不叫公平。

## 还守一件事:公示不许按「不可能证伪」的方式算

`/transparency/fairness` 原来只 `count(*)`,不带 hidden 过滤,而店铺页是
`WHERE hidden IS FALSE` —— 于是「删了一成」和「一条没删」在公示上长得
一模一样。这和 clean_streak_days 那次是同一个形状:拿没结论冒充没问题。

在 server/ 目录下运行:python -m tests.e2e_review_hidden_appeal
"""
from tests.util import call, demo_shop, login, orderable_dish, register_fresh_customer

merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")
shop = demo_shop()
sid = shop["id"]
main_dish = orderable_dish(call("GET", f"/merchants/{sid}/dishes"))


def completed_order(customer):
    no = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": main_dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    return no


def visible_ids():
    return {r["id"] for r in call("GET", f"/merchants/{sid}/reviews")}


def main() -> None:
    customer = register_fresh_customer("评价隐藏申诉")

    # ---------- 1) 用户写一条差评 ----------
    no = completed_order(customer)
    review = call("POST", f"/orders/{no}/review", customer,
                  {"merchant_rating": 2, "comment": "菜是凉的,而且少了一样"})
    rid = review["id"]
    assert review["hidden"] is False
    assert rid in visible_ids(), "刚写的评价没出现在店铺页"
    print(f"✓ 差评已发布并在店铺页可见(评价 #{rid})")

    fair_before = call("GET", "/transparency/fairness")["reviews"]

    # ---------- 2) 商家申诉,平台判隐藏 ----------
    ap = call("POST", "/appeals", merchant,
              {"target_type": "review", "target_id": rid,
               "reason": "这条评价与事实不符,菜品当时是热的,有出餐记录"})
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:有出餐记录佐证,该评价不成立"})
    assert rid not in visible_ids(), "判了隐藏,店铺页却还看得到"
    mine = call("GET", f"/orders/{no}/review", customer)
    assert mine["hidden"] is True, "用户自己查却看不出评价被隐藏了"
    print("✓ 商家申诉成立:店铺页不再显示,而作者自己查得到「已隐藏」状态")

    # ---------- 3) 公示必须把隐藏数报出来 ----------
    #
    # ⚠️ 这个接口缓存 1 小时,**跑之前要把 PUBLIC_CACHE_MAX_SECONDS 设成 0**
    # (server/.env 和 CI 都设了)。否则 fair_before 那一读会把旧快照缓存住,
    # 后面读到的是隐藏之前的数字。
    #
    # 原来这里写的是 `fair["hidden"] > 0`,配上缓存等于**在断言开发库里
    # 攒了多少历史隐藏评价** —— 跟这个用例做了什么完全无关,本地永远绿,
    # CI 干净库上当场红。改成断言**差值**:数字必须跟着这次操作动。
    fair = call("GET", "/transparency/fairness")["reviews"]
    assert "hidden" in fair and "visible" in fair, (
        f"公示里没有隐藏数:{sorted(fair)} —— "
        f"店铺页会滤掉 hidden,公示不报的话「删了一成」和「一条没删」"
        f"长得一模一样")
    assert fair["hidden"] == fair_before["hidden"] + 1, (
        f"刚隐藏了一条评价,公示的隐藏数却从 {fair_before['hidden']} "
        f"变成 {fair['hidden']} —— 要么公示根本没在数 hidden,"
        f"要么你在拿缓存跑(把 PUBLIC_CACHE_MAX_SECONDS 设成 0)")
    assert fair["visible"] == fair_before["visible"] - 1, (
        f"隐藏了一条,可见数却从 {fair_before['visible']} "
        f"变成 {fair['visible']} —— 隐藏的评价还留在可见数里")
    assert fair["total"] == fair_before["total"], (
        "总数变了 —— 隐藏不是删除,总数不该动")
    assert fair["visible"] == fair["total"] - fair["hidden"], (
        f"可见 {fair['visible']} + 隐藏 {fair['hidden']} "
        f"≠ 总数 {fair['total']}")
    assert fair["hidden_rule"] and fair["hidden_recourse"], "规则和救济没写清楚"
    print(f"✓ 公示如实报出:共 {fair['total']} 条、可见 {fair['visible']}、"
          f"隐藏 {fair['hidden']}(比隐藏前正好多 1 条)")

    # ---------- 4) 只有作者能申诉这个隐藏 ----------
    err = call("POST", "/appeals", merchant,
               {"target_type": "review_hidden", "target_id": rid,
                "reason": "我是商家,我也来申诉隐藏"}, expect_error=True)
    assert err["_error"] == 403, err
    other = register_fresh_customer("路人")
    err = call("POST", "/appeals", other,
               {"target_type": "review_hidden", "target_id": rid,
                "reason": "不是我写的但我想申诉"}, expect_error=True)
    assert err["_error"] == 404, err
    print("✓ 只有写这条评价的人能申诉隐藏(商家 403、其他用户 404)")

    # ---------- 5) 作者申诉,平台改判 → 恢复显示 + 评分加回 ----------
    before = call("GET", f"/merchants/{sid}")
    ap2 = call("POST", "/appeals", customer,
               {"target_type": "review_hidden", "target_id": rid,
                "reason": "我写的是真实经历,当时菜确实是凉的"})
    assert ap2["status"] == "open", ap2
    call("POST", f"/admin/appeals/{ap2['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:顾客描述可信,恢复显示"})
    assert rid in visible_ids(), "改判了却没恢复显示,申诉就是摆设"
    after = call("GET", f"/merchants/{sid}")
    assert after["rating_count"] == before["rating_count"] + 1, (
        f"评价恢复了,评分却没跟着加回来:{before['rating_count']} → "
        f"{after['rating_count']}")
    print("✓ 作者申诉成立:评价恢复显示,并重新计入店铺评分")

    # ---------- 6) 已经显示的评价不能再申诉隐藏 ----------
    err = call("POST", "/appeals", customer,
               {"target_type": "review_hidden", "target_id": rid,
                "reason": "再申诉一次"}, expect_error=True)
    assert err["_error"] in (409, 422), err
    print("✓ 已恢复显示的评价不再受理隐藏申诉")

    print("\ne2e_review_hidden_appeal 全部通过 ✅")


if __name__ == "__main__":
    main()
