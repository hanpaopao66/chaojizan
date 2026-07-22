"""验证码登录链路:滑块挑战、每日频控、按端角色注册、登录清计数。

注意:同号发码有 60 秒冷却,本测试含两次 61 秒等待(总时长 ~2 分钟)。
用固定测试号 19900000001,幂等可重复跑(角色断言用"已存在即保持"语义)。
"""
import time

from tests.util import call

PHONE = "19900000001"


def send(extra=None, expect_error=False):
    return call("POST", "/auth/sms-code",
                body={"phone": PHONE, **(extra or {})}, expect_error=expect_error)


# 第 1 条:直接放行(开发模式返回 dev_code)
r1 = send()
assert r1.get("dev_code"), "本地未配短信,应返回 dev_code"
print("✓ 第 1 条发码放行")

print("  (等 61s 过冷却……)")
time.sleep(61)
r2 = send()
assert r2.get("dev_code")
print("✓ 第 2 条发码放行")

print("  (等 61s 过冷却……)")
time.sleep(61)
# 第 3 条:要求滑块
err = send(expect_error=True)
assert err["_error"] == 409 and "captcha_required" in str(err["detail"])
print("✓ 第 3 条触发滑块(409 captcha_required)")

# 滑块挑战:滑错被拒,滑对放行
ch = call("GET", "/auth/slider")
assert 0 <= ch["target"] <= 100 and ch["ticket"]
err = send({"ticket": ch["ticket"], "slide": (ch["target"] + 50) % 101},
           expect_error=True)
assert err["_error"] == 409
print("✓ 滑块位置不对被拒")
ch = call("GET", "/auth/slider")  # 票据一次性,重新领
r3 = send({"ticket": ch["ticket"], "slide": ch["target"]})
assert r3.get("dev_code")
print("✓ 滑块通过后发码成功")

# 按端角色注册:骑手端登录,新号注册成 rider;已有账号保持原角色
login = call("POST", "/auth/sms-login", body={
    "phone": PHONE, "code": r3["dev_code"], "role": "rider"})
assert login["role"] == "rider", f"应为 rider,实际 {login['role']}"
print(f"✓ 按端角色注册/保持:{login['role']}")

# 登录成功清当日计数:下一条发码不再要滑块(仍受 60s 冷却,等一下)
print("  (等 61s 过冷却……)")
time.sleep(61)
r4 = send()
assert r4.get("dev_code"), "登录后计数应已清零,无需滑块"
print("✓ 登录成功清频控计数")

print("\ne2e_auth_sms 全部通过 ✅")
