"""P1 推送触达 + 退款可视化验证:回复触达 / 收藏触达(含每日上限) / 召回 / 退款流水。

JPush 未配置时触达类推送仍写 push_logs(意图留痕),据此断言触发链路;
配好 AppKey 后同一链路自动变真实发送,无需改代码。

在 server/ 目录下运行:python -m tests.e2e_p3_touch
"""
import time

from tests.util import orderable_dish, ADMIN, CUSTOMER, MERCHANT, RIDER, call, login

customer = login(CUSTOMER)
merchant = login(MERCHANT)
rider = login(RIDER)
admin = login(ADMIN)

tag = str(int(time.time()))
me = call("GET", "/auth/me", customer)


def my_push_logs():
    return call(f"GET", f"/admin/push-logs?user_id={me['id']}", admin)


# ---- 回复触达:首次回复推送用户,修改回复不重复推 ----
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dishes = call("GET", f"/merchants/{sid}/dishes")
main_dish = orderable_dish(dishes)

order = call("POST", "/orders", customer, {
    "merchant_id": sid,
    "items": [{"dish_id": main_dish["id"], "quantity": 1}],
    "address": "触达测试地址", "lat": 30.66, "lng": 104.08,
})
no = order["order_no"]
call("POST", f"/orders/{no}/pay/mock", customer)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/riders/grab/{no}", rider)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

review = call("POST", f"/orders/{no}/review", customer,
              {"merchant_rating": 5, "rider_rating": 5,
               "comment": f"触达测试-{tag}"})
before = len([r for r in my_push_logs() if "回复了你的评价" in r["title"]])
call("POST", f"/merchants/me/reviews/{review['id']}/reply", merchant,
     {"reply": f"感谢惠顾-{tag}"})
logs = [r for r in my_push_logs() if "回复了你的评价" in r["title"]]
assert len(logs) == before + 1, "首次回复应产生一条触达"
assert f"感谢惠顾-{tag}" in logs[0]["content"]
print("✓ 商家首次回复评价 → 触达用户(push_logs 留痕)")

call("POST", f"/merchants/me/reviews/{review['id']}/reply", merchant,
     {"reply": f"修改后的回复-{tag}"})
logs2 = [r for r in my_push_logs() if "回复了你的评价" in r["title"]]
assert len(logs2) == before + 1, "修改回复不应重复触达"
print("✓ 修改回复不重复触达(防打扰)")

# ---- 收藏触达:新店隔离每日上限;限时折扣触发,一天内第二次被抑制 ----
boss = call("POST", "/auth/register", body={
    "phone": "132" + tag[-8:], "password": "123456", "name": "触达老板",
    "role": "merchant"})["token"]
shop = call("POST", "/merchants", boss, {
    "name": f"触达测试店-{tag}", "address": "测试路 9 号",
    "lat": 30.6612, "lng": 104.0823,
    "license_no": "JY99900011188888",
    "license_image_url": "/uploads/license-demo.jpg"})
call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
call("PATCH", "/merchants/me", boss, {"is_open": True})
call("POST", f"/favorites/{shop['id']}", customer)

dish = call("POST", "/merchants/me/dishes", boss,
            {"name": f"触达菜-{tag}", "price_cents": 2000, "stock": 10})
call("PATCH", f"/merchants/me/dishes/{dish['id']}", boss,
     {"flash_price_cents": 1500, "flash_until": "2099-01-01T00:00:00Z"})
logs = [r for r in my_push_logs() if "限时折扣" in r["title"]]
assert logs and shop["name"] in logs[0]["title"]
print("✓ 收藏店开限时折扣 → 触达收藏者")

call("POST", "/vouchers", boss, {
    "title": f"触达券-{tag}", "sell_price_cents": 800,
    "face_value_cents": 1000, "total_count": 10})
assert not any("上新团购券" in r["title"] for r in my_push_logs()), \
    "同店当天已推过限时折扣,发券应被每日上限抑制"
print("✓ 每店每天最多触达一条(防打扰上限生效)")

# ---- 召回:仅管理员;dry_run 只统计不发送;参数校验 ----
err = call("POST", "/admin/push/recall", customer, {}, expect_error=True)
assert err["_error"] == 403
print("✓ 非管理员不能发起召回")

err = call("POST", "/admin/push/recall", admin,
           {"min_days": 30, "max_days": 7}, expect_error=True)
assert err["_error"] == 422
print("✓ 召回参数校验(min 必须小于 max)")

r = call("POST", "/admin/push/recall", admin,
         {"min_days": 7, "max_days": 30, "dry_run": True})
assert r["dry_run"] is True and r["pushed"] == 0 and r["candidates"] >= 0
print(f"✓ 召回 dry_run:{r['candidates']} 个候选,0 发送(运营先看人数再决策)")

# ---- 退款流水可视化:缺货退一份 → 用户可查逐笔进度 ----
order2 = call("POST", "/orders", customer, {
    "merchant_id": sid,
    "items": [{"dish_id": main_dish["id"], "quantity": 2}],
    "address": "退款流水测试", "lat": 30.66, "lng": 104.08,
})
no2 = order2["order_no"]
call("POST", f"/orders/{no2}/pay/mock", customer)
call("POST", f"/orders/{no2}/refund-item", merchant,
     {"dish_id": main_dish["id"], "quantity": 1})

rows = call("GET", f"/orders/{no2}/refunds", customer)
assert len(rows) == 1
assert rows[0]["amount_cents"] == main_dish["price_cents"]
assert rows[0]["status"] == "success" and rows[0]["channel"] == "mock"
print("✓ 退款流水可查:金额/通道/状态(mock 即时成功;微信通道为 requested→success)")

err = call("GET", f"/orders/{no2}/refunds", expect_error=True)
assert err["_error"] == 401
print("✓ 退款流水需登录")

print("\n全部通过:回复/收藏/召回触达 + 退款流水可视化 ✓")
