"""验证码登录链路:滑块挑战、每日频控、按端角色注册、登录清计数。

注意:同号发码有冷却(生产 60 秒,settings.sms_resend_seconds),本测试要等三次冷却;
CI 里 SMS_RESEND_SECONDS 调短,服务端和本进程读的是同一个环境变量。
用固定测试号 19900000001,幂等可重复跑(角色断言用"已存在即保持"语义)。
"""
import time

from app.config import settings
from tests.util import call

PHONE = "19900000001"
#: 等冷却过去:服务端的冷却秒数 + 1
WAIT = settings.sms_resend_seconds + 1


def _reset_daily_quota():
    """清掉本测试号当天的发码计数(Redis)。

    用例的语义是"从零开始数到第 3 条触发滑块",但 sms:day:p:{phone}
    是按自然日累加的 —— 一天里跑第二遍,第 1 条就已经要滑块了。
    只清这一个测试号,不碰 IP 维度,也不放宽任何生产阈值。
    """
    try:
        import redis as _redis

        from app.config import settings as _settings
        r = _redis.Redis.from_url(_settings.redis_url)
        r.delete(f"sms:day:p:{PHONE}")
        r.close()
    except Exception:
        pass


_reset_daily_quota()


def send(extra=None, expect_error=False):
    return call("POST", "/auth/sms-code",
                body={"phone": PHONE, **(extra or {})}, expect_error=expect_error)


# 第 1 条:直接放行(开发模式返回 dev_code)
r1 = send()
assert r1.get("dev_code"), "本地未配短信,应返回 dev_code"
print("✓ 第 1 条发码放行")

print(f"  (等 {WAIT}s 过冷却……)")
time.sleep(WAIT)
r2 = send()
assert r2.get("dev_code")
print("✓ 第 2 条发码放行")

print(f"  (等 {WAIT}s 过冷却……)")
time.sleep(WAIT)
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

# 登录成功清当日计数:下一条发码不再要滑块(仍受冷却,等一下)
print(f"  (等 {WAIT}s 过冷却……)")
time.sleep(WAIT)
r4 = send()
assert r4.get("dev_code"), "登录后计数应已清零,无需滑块"
print("✓ 登录成功清频控计数")

print("\ne2e_auth_sms 全部通过 ✅")
