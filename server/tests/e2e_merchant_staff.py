"""商家子账号(清单#62):店员能接单/出餐/估清/看单,不能提现/改价/改设置/加店员。"""
import random
import time

from tests.util import call, login


def sms_login(phone):
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login",
                body={"phone": phone, "code": code})["token"]


owner = login("13800000002")   # 张记面馆店主
customer = login("13800000001")
rider = login("13800000003")
shop = call("GET", "/merchants/me", owner)
ts = int(time.time())
dish = call("POST", "/merchants/me/dishes", owner,
            {"name": f"子账号测试菜-{ts}", "price_cents": 3000, "stock": 100})

# 造一个新用户当店员(先登录注册)
staff_phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
staff = sms_login(staff_phone)

# 加店员前:该用户是 customer,进不了商家端(拿不到店)
err = call("GET", "/merchants/me", staff, expect_error=True)
assert err["_error"] in (403, 404)

# 店主添加店员
r = call("POST", "/merchants/me/staff", owner,
         {"phone": staff_phone, "name": "小工"})
assert r["ok"]
staff_uid = r["user_id"]
staff = call("POST", "/auth/refresh", staff)["token"]  # 角色已变 merchant,刷新 token
print("✓ 店主按手机号添加店员")

# 店员能看店(viewer_is_staff=true)
me = call("GET", "/merchants/me", staff)
assert me["id"] == shop["id"] and me["viewer_is_staff"] is True
print("✓ 店员能看店,viewer_is_staff=true")

# 店员能估清(运营操作)
sold = call("POST", f"/merchants/me/dishes/{dish['id']}/sell-out", staff)
assert sold["sold_out_today"] is True
call("POST", f"/merchants/me/dishes/{dish['id']}/sell-out/cancel", staff)
print("✓ 店员能估清/撤销估清")

# 下单 → 店员能接单、出餐(运营核心)
addr = {"address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "测试", "contact_phone": "13800000001"}
o = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}], **addr})
no = o["order_no"]
call("POST", f"/orders/{no}/pay/mock", customer)
# 店员能看到本店订单列表
orders = call("GET", "/orders", staff)
assert any(x["order_no"] == no for x in orders), "店员应能看到本店订单"
acc = call("POST", f"/orders/{no}/transition", staff, {"to_status": "accepted"})
assert acc["status"] == "accepted"
call("POST", f"/orders/{no}/transition", staff, {"to_status": "ready"})
print("✓ 店员能看单/接单/出餐")

# 店员不能:提现、改价、改店铺设置、加店员(敏感=店主专属)
err = call("GET", "/merchants/me/withdrawals", staff, expect_error=True)
assert err["_error"] == 404, "店员访问提现应被拒(非店主,还没开店口径)"
err = call("PATCH", f"/merchants/me/dishes/{dish['id']}", staff,
           {"price_cents": 9999}, expect_error=True)
assert err["_error"] == 404, "店员改价应被拒(非店主)"
err = call("PATCH", "/merchants/me", staff,
           {"announcement": "店员乱改"}, expect_error=True)
assert err["_error"] == 404, "店员改设置应被拒"
err = call("POST", "/merchants/me/staff", staff,
           {"phone": "13800000009"}, expect_error=True)
assert err["_error"] == 403, "店员不能加店员"
print("✓ 店员不能提现/改价/改设置/加店员(敏感=店主专属)")

# 校验:不能把店主/已有店的人加为店员
err = call("POST", "/merchants/me/staff", owner,
           {"phone": "13800000002"}, expect_error=True)  # 自己
assert err["_error"] == 409
err = call("POST", "/merchants/me/staff", owner,
           {"phone": "19900000000"}, expect_error=True)  # 未注册
assert err["_error"] == 404
print("✓ 加店员校验:自己409、未注册404")

# 店主能看店员列表 + 移除(按本次 staff 的 user_id 精确匹配,避开历史残留)
lst = call("GET", "/merchants/me/staff", owner)
assert any(s["user_id"] == staff_uid for s in lst)
call("DELETE", f"/merchants/me/staff/{staff_uid}", owner)
lst2 = call("GET", "/merchants/me/staff", owner)
assert all(s["user_id"] != staff_uid for s in lst2)
print("✓ 店主查看/移除店员")

# 移除后店员失去店铺访问
err = call("GET", "/merchants/me", staff, expect_error=True)
assert err["_error"] in (403, 404)
print("✓ 移除后店员失去访问")

call("PATCH", f"/merchants/me/dishes/{dish['id']}", owner, {"is_on_sale": False})
print("\n商家子账号验证通过 🎉")
