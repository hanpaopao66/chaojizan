"""内容审核验证:敏感词同步拦截(评价/昵称/菜名/公告/工单)、
词库增删即时生效、图片先发后审队列、驳回隐藏图并留痕。

在 server/ 目录下运行:python -m tests.e2e_moderation
"""
import time

from tests.util import call, login, register_fresh_customer, register_fresh_rider  # noqa: F401

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")

sid = call("GET", "/merchants/me", merchant)["id"]
call("PATCH", "/merchants/me", merchant, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"审核测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def completed_order(cust):
    order = call("POST", "/orders", cust, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", cust)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "picked_up", "verify_code": no[-4:]})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", cust, {"to_status": "completed"})
    return no


def main():
    # 1) 敏感词拦截:评价 / 昵称 / 菜名 / 公告 / 工单 五处入口(种子词"办证")
    user = register_fresh_customer()
    no = completed_order(user)
    err = call("POST", f"/orders/{no}/review", user,
               {"merchant_rating": 5, "comment": "味道不错,顺便办证加我",
                "image_urls": []}, expect_error=True)
    assert err["_error"] == 422 and "不允许发布" in err["detail"], err
    err = call("PATCH", "/auth/me", user, {"name": "办证小王"},
               expect_error=True)
    assert err["_error"] == 422, err
    err = call("POST", "/merchants/me/dishes", merchant,
               {"name": "办证套餐", "price_cents": 2000}, expect_error=True)
    assert err["_error"] == 422, err
    err = call("PATCH", "/merchants/me", merchant,
               {"announcement": "本店可代开发票"}, expect_error=True)
    assert err["_error"] == 422, err
    err = call("POST", "/tickets", user,
               {"contact": "", "content": "有人在店里搞博彩推广"},
               expect_error=True)
    assert err["_error"] == 422, err
    print("✓ 敏感词五处入口全部同步拦截(不透出命中词)")

    # 2) 白样本通过:正常评价成功且图片进审核队列
    review = call("POST", f"/orders/{no}/review", user,
                  {"merchant_rating": 5, "comment": "味道不错,下次还点",
                   "image_urls": ["https://example.com/food.jpg"]})
    assert review["id"]
    queue = call("GET", "/admin/content-reviews?status=pending", admin)
    mine = [q for q in queue if q["url"] == "https://example.com/food.jpg"
            and q["kind"] == "review"]
    assert mine, "评价图应进审核队列"
    print("✓ 白样本通过,评价图入先发后审队列")

    # 3) 驳回:评价图被隐藏,记录留痕
    call("POST", f"/admin/content-reviews/{mine[0]['id']}/reject", admin,
         {"note": "图片与餐品无关"})
    r = call("GET", f"/orders/{no}/review", user)
    assert "https://example.com/food.jpg" not in r["image_urls"], r
    done = call("GET", "/admin/content-reviews?status=rejected", admin)
    assert any(q["id"] == mine[0]["id"] and "无关" in q["note"] for q in done)
    print("✓ 驳回后评价图隐藏,处理留痕")

    # 4) 词库增删即时生效
    magic = f"测试禁词{int(time.time())}"
    call("POST", "/admin/moderation-words", admin, {"word": magic})
    err = call("POST", "/tickets", user,
               {"contact": "", "content": f"这句话包含{magic}三个字"},
               expect_error=True)
    assert err["_error"] == 422, err
    words = call("GET", "/admin/moderation-words", admin)
    wid = next(w["id"] for w in words if w["word"] == magic)
    call("DELETE", f"/admin/moderation-words/{wid}", admin)
    ok = call("POST", "/tickets", user,
              {"contact": "", "content": f"这句话包含{magic}三个字"})
    assert ok["id"]
    print("✓ 管理后台加词立即拦截,删词立即放行")

    # 5) 菜品图入队列,驳回后清空;非 admin 无权访问审核接口
    d2 = call("POST", "/merchants/me/dishes", merchant,
              {"name": f"图审菜-{int(time.time())}", "price_cents": 2000,
               "image_url": "https://example.com/dish.jpg"})
    queue = call("GET", "/admin/content-reviews?status=pending", admin)
    q = next(x for x in queue if x["kind"] == "dish" and x["ref_id"] == d2["id"])
    call("POST", f"/admin/content-reviews/{q['id']}/reject", admin,
         {"note": "盗图"})
    dishes = call("GET", "/merchants/me/dishes", merchant)
    assert next(d for d in dishes if d["id"] == d2["id"])["image_url"] == ""
    err = call("GET", "/admin/content-reviews", user, expect_error=True)
    assert err["_error"] == 403, err
    print("✓ 菜品图驳回清空;非 admin 403")

    print("\ne2e_moderation 全部通过 ✅")


if __name__ == "__main__":
    main()
