"""店铺评价概览、筛选翻页、「点过这道菜的订单」的评价。

## 守的是「一个数」

店铺页顶上写「4.8 分 · 268 条」,取自商家表的 rating_sum / rating_count;
评价页签的概览(条数、均分、1–5 星、五个筛选)从评价表数。两边必须是同一批评价 ——
写一条、隐藏一条、恢复一条之后,概览和商家表都得同时动、动得一样。
原来公开列表只给最近 50 条,店铺页的分布只能按那 50 条算,和「268 条」对不上。

断言一律按**差值**和**两边相等**写,不断言演示店攒下来的绝对数。

在 server/ 目录下运行:python -m tests.e2e_review_overview
"""
import time

from tests.util import call, demo_shop, login, orderable_dish, register_fresh_customer

merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")
sid = demo_shop()["id"]
dish = orderable_dish(call("GET", f"/merchants/{sid}/dishes"))


def completed_order(customer):
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
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    return no


def overview():
    return call("GET", f"/merchants/{sid}/reviews/overview")


def same_as_shop(ov, when):
    """概览的条数、均分必须和店铺页(商家表)的是同一个数。"""
    shop = demo_shop()
    assert ov["count"] == shop["rating_count"], (
        f"{when}:概览 {ov['count']} 条,店铺页 {shop['rating_count']} 条 —— 出了两个数")
    assert ov["avg"] == shop["rating_avg"], (
        f"{when}:概览 {ov['avg']} 分,店铺页 {shop['rating_avg']} 分")
    assert sum(ov["stars"].values()) == ov["count"], "1–5 星加起来不等于总条数"


def page_through(kind, page_size):
    """按筛选一页页翻到底,返回全部评价 id(按接口给的顺序)。"""
    ids, before = [], None
    while True:
        q = f"/merchants/{sid}/reviews?filter={kind}&limit={page_size}"
        page = call("GET", q + (f"&before={before}" if before else ""))
        ids += [r["id"] for r in page]
        if len(page) < page_size:
            return ids
        before = page[-1]["id"]


def main() -> None:
    tag = f"概览e2e-{int(time.time())}"
    ov0 = overview()
    same_as_shop(ov0, "开始时")
    dish0 = call("GET", f"/merchants/{sid}/dishes/{dish['id']}/order-reviews")
    print(f"✓ 概览和店铺页同一个数:{ov0['count']} 条、{ov0['avg']} 分")

    # ---------- 1) 写一条带图的差评:概览、商家表、筛选、菜品摘要一起动 ----------
    customer = register_fresh_customer("概览")
    no = completed_order(customer)
    review = call("POST", f"/orders/{no}/review", customer, {
        "merchant_rating": 2, "comment": f"{tag} 面坨了",
        "image_urls": ["/uploads/e2e-review-overview.jpg"]})
    rid = review["id"]
    ov1 = overview()
    same_as_shop(ov1, "写了一条之后")
    assert ov1["count"] == ov0["count"] + 1
    assert ov1["stars"]["2"] == ov0["stars"]["2"] + 1
    assert ov1["bad"] == ov0["bad"] + 1 and ov1["good"] == ov0["good"]
    assert ov1["photo"] == ov0["photo"] + 1
    print("✓ 写一条 2 星带图:总数、2 星、差评、有图各 +1,和店铺页一起动")

    bad_first = call("GET", f"/merchants/{sid}/reviews?filter=bad&limit=1")
    assert bad_first and bad_first[0]["id"] == rid, "差评筛选的第一条应当是刚写的这条"
    good_ids = page_through("good", 50)
    assert rid not in good_ids, "2 星出现在了好评里"
    print("✓ 差评筛选里排第一,好评里没有它")

    # 每个筛选翻到底的条数 = 概览里的数(列表和概览共用一份筛选条件)
    for kind in ("photo", "bad", "append"):
        ids = page_through(kind, 20)
        assert len(ids) == len(set(ids)), f"{kind} 翻页翻出了重复"
        assert len(ids) == ov1[kind], f"{kind} 翻到底 {len(ids)} 条,概览写 {ov1[kind]}"
    assert len(good_ids) == ov1["good"]
    print("✓ 有图 / 好评 / 差评 / 有追评:翻到底的条数和概览一致,不重不漏")

    dish1 = call("GET", f"/merchants/{sid}/dishes/{dish['id']}/order-reviews")
    assert dish1["count"] == dish0["count"] + 1, "点过这道菜的订单多了一条评价,摘要没跟上"
    assert dish1["good"] == dish0["good"], "2 星不该算进好评"
    assert dish1["recent"] and dish1["recent"][0]["id"] == rid
    assert dish1["recent"][0]["customer_name"] != "", "名字要脱敏,但不能是空的"
    other = call("GET", "/merchants/2/dishes/%d/order-reviews" % dish["id"],
                 expect_error=True)
    assert other["_error"] == 404, "菜不是这家店的,应当 404"
    print("✓ 点过这道菜的订单:评价数 +1,最近一条就是它;别家店的菜 404")

    # ---------- 2) 申诉隐藏:概览和商家表一起减 ----------
    ap = call("POST", "/appeals", merchant,
              {"target_type": "review", "target_id": rid,
               "reason": "e2e:评价与出餐记录不符,申请复核"})
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "e2e 复核"})
    ov2 = overview()
    same_as_shop(ov2, "隐藏之后")
    assert ov2["count"] == ov0["count"] and ov2["bad"] == ov0["bad"]
    assert rid not in page_through("bad", 50), "隐藏了还在差评筛选里"
    dish2 = call("GET", f"/merchants/{sid}/dishes/{dish['id']}/order-reviews")
    assert dish2["count"] == dish0["count"], "隐藏的评价还算在菜品摘要里"
    print("✓ 申诉隐藏:概览、商家表、筛选、菜品摘要一起减回去")

    # ---------- 3) 作者申诉恢复:一起加回来 ----------
    ap2 = call("POST", "/appeals", customer,
               {"target_type": "review_hidden", "target_id": rid,
                "reason": "e2e:我写的是真实经历"})
    call("POST", f"/admin/appeals/{ap2['id']}/resolve", admin,
         {"result": "overturned", "note": "e2e 恢复"})
    ov3 = overview()
    same_as_shop(ov3, "恢复之后")
    assert ov3["count"] == ov1["count"] and ov3["bad"] == ov1["bad"]
    print("✓ 恢复显示:概览和店铺页一起加回来")

    # ---------- 4) 参数 ----------
    err = call("GET", f"/merchants/{sid}/reviews?filter=nope", expect_error=True)
    assert err["_error"] == 422
    assert call("GET", f"/merchants/{sid}/reviews?before=999999999") == []
    assert len(call("GET", f"/merchants/{sid}/reviews")) <= 50, "不带参数仍是最新 50 条"
    print("✓ 不认识的筛选 422;游标对不上给空;不带参数行为不变")

    print("\ne2e_review_overview 全部通过 ✅")


if __name__ == "__main__":
    main()
