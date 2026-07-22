"""外部服务骨架验证:短信验证码登录(开发模式)+ 微信支付降级行为
在 server/ 目录下运行:python -m tests.e2e_external_stubs
"""
import asyncio
import time

from app.redis_client import get_redis
from tests.util import orderable_dish, call, login

# 清掉固定演示号的发送冷却,保证连续跑两遍也能过
asyncio.run(get_redis().delete("sms:cd:13800000001"))

# ---------- 短信验证码登录 ----------
phone = "137" + str(int(time.time()))[-8:]

resp = call("POST", "/auth/sms-code", body={"phone": phone})
assert resp["sent"] is False and len(resp["dev_code"]) == 6
code = resp["dev_code"]
print(f"✓ 未配置短信服务 → 开发模式返回验证码 {code}")

err = call("POST", "/auth/sms-code", body={"phone": phone}, expect_error=True)
assert err["_error"] == 429
print(f"✓ 60 秒内重复发送被限流:{err['detail']}")

err = call("POST", "/auth/sms-login", body={"phone": phone, "code": "000000"}, expect_error=True)
assert err["_error"] == 401
print(f"✓ 错误验证码被拒:{err['detail']}")

data = call("POST", "/auth/sms-login", body={"phone": phone, "code": code})
assert data["role"] == "customer" and data["token"]
uid = data["user_id"]
print(f"✓ 验证码登录成功,新号自动注册为用户(id={uid})")

err = call("POST", "/auth/sms-login", body={"phone": phone, "code": code}, expect_error=True)
assert err["_error"] == 401
print("✓ 验证码一次性,用过即废")

# 老用户再次验证码登录 → 同一账号
resp2 = call("POST", "/auth/sms-code", body={"phone": "13800000001"})
data2 = call("POST", "/auth/sms-login", body={"phone": "13800000001", "code": resp2["dev_code"]})
assert data2["name"] == "测试用户"
print("✓ 已有账号验证码登录不重复建号")

# ---------- 微信支付降级 ----------
customer = login("13800000001")
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dishes = call("GET", f"/merchants/{shop['id']}/dishes")
main_dish = orderable_dish(dishes)
order = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": main_dish["id"], "quantity": 1}],
    "address": "测试地址", "lat": 30.66, "lng": 104.08,
})
no = order["order_no"]

err = call("POST", f"/orders/{no}/pay/wechat", customer, expect_error=True)
assert err["_error"] == 503
print(f"✓ 未配置商户号,微信支付明确拒绝(503):{err['detail'][:20]}…")

# 降级路径:模拟支付照常可用(payment_core 统一入账)
paid = call("POST", f"/orders/{no}/pay/mock", customer)
assert paid["status"] == "paid" and paid["commission_cents"] > 0
print("✓ 降级到模拟支付,统一入账逻辑正常(佣金已计)")

err = call("POST", "/payments/wechat/notify", body={"fake": "callback"}, expect_error=True)
assert err["_error"] == 400
print("✓ 伪造支付回调被验签拒绝(400)")

# 清场(已支付订单用户可取消,库存回补)
call("POST", f"/orders/{no}/transition", customer, {"to_status": "cancelled"})

print("\n外部服务骨架验证通过 🎉")
