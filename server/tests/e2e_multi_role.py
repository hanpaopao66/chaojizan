"""手机号跨角色注册:同一手机号可分别注册 用户/商家/骑手,互不影响。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_multi_role
"""
import random

from tests.util import call

phone = "137" + "".join(str(random.randint(0, 9)) for _ in range(8))
P_CUSTOMER, P_RIDER = "pw-customer-1", "pw-rider-22"

# 1) 同号先后注册 用户 与 骑手 账号,都应成功且 user_id 不同
r1 = call("POST", "/auth/register",
          body={"phone": phone, "password": P_CUSTOMER, "role": "customer"})
r2 = call("POST", "/auth/register",
          body={"phone": phone, "password": P_RIDER, "role": "rider"})
assert r1["role"] == "customer" and r2["role"] == "rider"
assert r1["user_id"] != r2["user_id"], "两角色应是两个独立账号"
print(f"OK 同号双角色注册: customer={r1['user_id']} rider={r2['user_id']}")

# 2) 同号同角色重复注册应 409
dup = call("POST", "/auth/register",
           body={"phone": phone, "password": "x" * 6, "role": "customer"},
           expect_error=True)
assert dup["_error"] == 409, dup
print("OK 同角色重复注册被拒:", dup["detail"])

# 3) 带 role 登录:各回各的账号
la = call("POST", "/auth/login",
          body={"phone": phone, "password": P_CUSTOMER, "role": "customer"})
lb = call("POST", "/auth/login",
          body={"phone": phone, "password": P_RIDER, "role": "rider"})
assert la["user_id"] == r1["user_id"] and lb["user_id"] == r2["user_id"]

# 4) 不带 role 的旧式登录:按密码命中对应账号(两账号密码不同,无歧义)
lc = call("POST", "/auth/login", body={"phone": phone, "password": P_RIDER})
assert lc["user_id"] == r2["user_id"], "旧式登录应按密码命中骑手账号"
# 角色与密码不匹配要拒绝
bad = call("POST", "/auth/login",
           body={"phone": phone, "password": P_RIDER, "role": "customer"},
           expect_error=True)
assert bad["_error"] == 401
print("OK 登录路由与密码命中正确")

# 5) 验证码登录在第三个端(商家)首登自动注册,不影响已有两个账号
code = call("POST", "/auth/sms-code", body={"phone": phone}).get("dev_code")
assert code, "本地应处于短信开发模式(未配置短信服务)"
lm = call("POST", "/auth/sms-login",
          body={"phone": phone, "code": code, "role": "merchant"})
assert lm["role"] == "merchant"
assert lm["user_id"] not in (r1["user_id"], r2["user_id"])
me = call("GET", "/auth/me", token=lm["token"])
assert me["role"] == "merchant" and me["phone"] == phone
print(f"OK 商家端首登自动注册第三账号: merchant={lm['user_id']}")

print("PASS e2e_multi_role")
