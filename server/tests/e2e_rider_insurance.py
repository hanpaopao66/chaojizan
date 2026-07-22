"""骑手意外险(登记模式)验证:每日首次上线落保障记录、幂等不重复、
未配置保险服务时 status=registered(保障金池兜底)。

在 server/ 目录下运行:python -m tests.e2e_rider_insurance
"""
import asyncio

from tests.util import call, register_fresh_rider


async def main():
    rider = await register_fresh_rider("保障测试骑手")

    # 上线前无记录
    rows = call("GET", "/riders/insurance", rider)
    assert rows == [], rows

    # 1) 首次上线 → 落当日保障记录(未配置服务商=registered 登记模式)
    call("POST", "/riders/online", rider, {"is_online": True})
    rows = call("GET", "/riders/insurance", rider)
    assert len(rows) == 1 and rows[0]["status"] == "registered", rows
    day = rows[0]["day"]
    print(f"✓ 首次上线自动登记当日保障({day},保障金池兜底)")

    # 2) 同日反复上下线 → 幂等,仍只有一条
    call("POST", "/riders/online", rider, {"is_online": False})
    call("POST", "/riders/online", rider, {"is_online": True})
    call("POST", "/riders/online", rider, {"is_online": False})
    call("POST", "/riders/online", rider, {"is_online": True})
    rows = call("GET", "/riders/insurance", rider)
    assert len(rows) == 1 and rows[0]["day"] == day, rows
    print("✓ 同日反复上线幂等,保障记录不重复")

    call("POST", "/riders/online", rider, {"is_online": False})
    print("\ne2e_rider_insurance 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
