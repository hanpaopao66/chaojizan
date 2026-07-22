"""云打印小票:状态查询 / 未启用降级 / 自动出票开关。

飞鹅账号一般不在测试环境配置,所以这里主要验证"未启用"路径的中文提示
和开关持久化;真机出票靠绑定真实打印机后的测试页按钮验证。
"""
from tests.util import call, login

merchant = login("13800000002")

# 状态查询:字段齐全
status = call("GET", "/merchants/me/printer", merchant)
assert set(status) == {"enabled", "sn", "auto"}, status
print(f"✓ 云打印状态:enabled={status['enabled']} sn={status['sn'] or '未绑定'}")

# 自动出票开关:关 → 开,持久化
call("PATCH", "/merchants/me/printer", merchant, {"auto": False})
assert call("GET", "/merchants/me/printer", merchant)["auto"] is False
call("PATCH", "/merchants/me/printer", merchant, {"auto": True})
assert call("GET", "/merchants/me/printer", merchant)["auto"] is True
print("✓ 自动出票开关可切换且持久化")

if not status["enabled"]:
    # 平台未配置飞鹅账号:绑定/测试/补打都应给出可读的中文降级提示
    err = call("POST", "/merchants/me/printer", merchant,
               {"sn": "TEST0001", "key": "abcd1234"}, expect_error=True)
    assert err["_error"] == 503 and "云打印未启用" in err["detail"], err
    err = call("POST", "/merchants/me/printer/test", merchant, expect_error=True)
    assert err["_error"] == 503, err
    print("✓ 未配置打印服务商时,绑定/测试返回中文降级提示(蓝牙路仍可用)")
else:
    print("· 平台已配置飞鹅账号,绑定/出票需真机验证(跳过)")

print("PASS e2e_printer")
