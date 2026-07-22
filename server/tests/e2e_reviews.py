"""评价体系验证:一单一评、只评完成单、评分聚合、姓名脱敏"""
from tests.util import orderable_dish, call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
sid = shop["id"]
dishes = call("GET", f"/merchants/{sid}/dishes")
main_dish = orderable_dish(dishes)
rating_count_before = shop["rating_count"]
rating_sum_before = round((shop["rating_avg"] or 0) * rating_count_before)


def run_order(to_completed=True):
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": main_dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    if not to_completed:
        return no
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    return no


# 未完成的订单不能评
no_pending = run_order(to_completed=False)
err = call("POST", f"/orders/{no_pending}/review", customer,
           {"merchant_rating": 5}, expect_error=True)
assert err["_error"] == 409
print(f"✓ 未完成订单不能评价:{err['detail']}")
call("POST", f"/orders/{no_pending}/transition", customer, {"to_status": "cancelled"})

# 完整走完一单再评
no = run_order()
err = call("POST", f"/orders/{no}/review", customer,
           {"merchant_rating": 6}, expect_error=True)
assert err["_error"] == 422
print("✓ 评分超出 1-5 被拒(422)")

review = call("POST", f"/orders/{no}/review", customer,
              {"merchant_rating": 5, "rider_rating": 4, "comment": "面很好吃,送得快"})
assert review["merchant_rating"] == 5 and review["rider_rating"] == 4
assert review["customer_name"] != "测试用户" and review["customer_name"].startswith("测")
print(f"✓ 评价成功,姓名已脱敏:{review['customer_name']}")

err = call("POST", f"/orders/{no}/review", customer,
           {"merchant_rating": 1}, expect_error=True)
assert err["_error"] == 409
print(f"✓ 重复评价被拒:{err['detail']}")

mine = call("GET", f"/orders/{no}/review", customer)
assert mine["comment"] == "面很好吃,送得快"
print("✓ 能查到自己这单的评价")

# 聚合分数
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["id"] == sid)
assert shop["rating_count"] == rating_count_before + 1
expected_avg = round((rating_sum_before + 5) / (rating_count_before + 1), 1)
assert shop["rating_avg"] == expected_avg, f"均分应为 {expected_avg},实际 {shop['rating_avg']}"
print(f"✓ 商家评分聚合正确:{shop['rating_avg']} 分 · {shop['rating_count']} 条")

# 公开评价列表
reviews = call("GET", f"/merchants/{sid}/reviews")
assert any(r["comment"] == "面很好吃,送得快" for r in reviews)
assert all("*" in r["customer_name"] or r["customer_name"] == "匿名用户" for r in reviews)
print(f"✓ 店铺评价列表公开可见({len(reviews)} 条,姓名全部脱敏)")

# 商家侧:查看自己店的评价并回复
my_reviews = call("GET", "/merchants/me/reviews", merchant)
target = next(r for r in my_reviews if r["id"] == review["id"])
replied = call("POST", f"/merchants/me/reviews/{target['id']}/reply", merchant,
               {"reply": "多谢捧场,下次送你一份小菜"})
assert replied["reply"] == "多谢捧场,下次送你一份小菜"
print("✓ 商家能查看并回复评价")

public = call("GET", f"/merchants/{sid}/reviews")
assert any(r["reply"] == "多谢捧场,下次送你一份小菜" for r in public)
print("✓ 商家回复对所有用户可见")

err = call("POST", f"/merchants/me/reviews/{target['id']}/reply", rider,
           {"reply": "无关人员"}, expect_error=True)
assert err["_error"] == 403
print("✓ 非商家角色不能回复评价(403)")

print("\n评价体系验证通过 🎉")
