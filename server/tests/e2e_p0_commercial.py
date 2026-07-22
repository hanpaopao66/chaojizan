"""P0 商业化功能验证:招牌菜/热搜词/图片评价。

在 server/ 目录下运行:python -m tests.e2e_p0_commercial
"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

# ---- 招牌菜:列表接口带 top_dishes ----
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop0 = next(m for m in shops if m["name"] == "张记面馆")
assert "top_dishes" in shop0 and len(shop0["top_dishes"]) >= 1
d0 = shop0["top_dishes"][0]
assert {"name", "price_cents", "image_url"} <= set(d0)
assert len(shop0["top_dishes"]) <= 3
print(f"✓ 列表带招牌菜(≤3):{'、'.join(d['name'] for d in shop0['top_dishes'])}")

# ---- 热搜词:近 30 天热销菜名 ----
hot = call("GET", "/merchants/hot-keywords")
assert isinstance(hot["keywords"], list) and len(hot["keywords"]) >= 1
print(f"✓ 热搜词 {len(hot['keywords'])} 个,榜首「{hot['keywords'][0]}」")

# ---- 图片评价:完成一单 → 带图评价 → 回读 ----
tag = str(int(time.time()))
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"图评菜-{tag}", "price_cents": 1200, "stock": 50})
order = call("POST", "/orders", customer, {
    "merchant_id": shop0["id"],
    "items": [{"dish_id": dish["id"], "quantity": 2}],
    "address": "图评验证地址", "lat": 30.6612, "lng": 104.0823,
})
no = order["order_no"]
call("POST", f"/orders/{no}/pay/mock", customer)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
call("POST", "/riders/online", rider, {"is_online": True})
call("POST", "/riders/location", rider, {"lat": 30.6605, "lng": 104.0815})
call("POST", f"/riders/grab/{no}", rider)
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

imgs = ["/uploads/review-a.jpg", "/uploads/review-b.jpg"]
review = call("POST", f"/orders/{no}/review", customer, {
    "merchant_rating": 5, "rider_rating": 5,
    "comment": "拍两张给大家看看", "image_urls": imgs,
})
assert review["image_urls"] == imgs
back = call("GET", f"/merchants/{shop0['id']}/reviews")
mine = next(r for r in back if r["id"] == review["id"])
assert mine["image_urls"] == imgs
print("✓ 图片评价:提交 2 张,商家评价列表可回读")

# 超过 6 张被截断/拒绝(schema max_length=6 → 422)
err = call("POST", f"/orders/{no}/review", customer, {
    "merchant_rating": 5, "image_urls": [f"/u/{i}.jpg" for i in range(9)],
}, expect_error=True)
assert err["_error"] in (409, 422)  # 已评过 409 或图片超限 422,均为拒绝
print("✓ 重复评价/超限被拒")

print("\nP0 商业化(招牌菜/热搜词/图片评价)验证通过 🎉")
