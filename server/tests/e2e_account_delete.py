"""账号注销验证(M4 上架合规硬性要求)。

  1. 新注册用户可直接注销:手机号匿名化、旧 token 失效、原手机号可重新注册
  2. 有进行中订单的用户被拒(409),完结后可注销
  3. 商家账号有店铺 → 引导走客服工单(409)
在 server/ 目录下运行:python -m tests.e2e_account_delete
"""
import time

from tests.util import call, login

tag = str(int(time.time()))
phone = "138" + tag[-8:]

# ---- 1. 干净账号直接注销 ----
token = call("POST", "/auth/register",
             body={"phone": phone, "password": "123456", "name": "过客", "role": "customer"})["token"]
call("DELETE", "/auth/me", token)
print("✓ 新用户注销成功")

err = call("GET", "/auth/me", token, expect_error=True)
assert err["_error"] == 401, "注销后旧 token 应失效"
print("✓ 注销后旧 token 立即失效(401)")

err = call("POST", "/auth/login", body={"phone": phone, "password": "123456"}, expect_error=True)
assert err["_error"] == 401, "注销后原手机号不能再登录旧账号"
token2 = call("POST", "/auth/register",
              body={"phone": phone, "password": "654321", "name": "重来", "role": "customer"})["token"]
print("✓ 手机号已释放,可重新注册全新账号")

# ---- 2. 有在途订单时拒绝 ----
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dishes = call("GET", f"/merchants/{sid}/dishes")
dish = next(d for d in dishes if d["stock"] > 0 and d["price_cents"] >= 1500)
order = call("POST", "/orders", token2, {
    "merchant_id": sid,
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "address": "注销测试地址", "lat": 30.6612, "lng": 104.0823,
})
err = call("DELETE", "/auth/me", token2, expect_error=True)
assert err["_error"] == 409 and "进行中" in err["detail"]
print(f"✓ 有在途订单被拒:{err['detail']}")

call("POST", f"/orders/{order['order_no']}/transition", token2, {"to_status": "cancelled"})
call("DELETE", "/auth/me", token2)
print("✓ 订单完结后注销成功")

# ---- 3. 商家有店铺时引导客服 ----
merchant = login("13800000002")
err = call("DELETE", "/auth/me", merchant, expect_error=True)
assert err["_error"] == 409 and "客服" in err["detail"]
print(f"✓ 商家有店铺被引导走客服:{err['detail']}")

print("\n账号注销全流程验证通过 🎉")
