"""节假日营业计划:歇业日强制关店、特殊时段替代每日时段、过期清理、非法计划 422。"""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests.util import call, login

CN = ZoneInfo("Asia/Shanghai")
merchant = login("13800000002")
orig = call("GET", "/merchants/me", merchant)

now_cn = datetime.now(CN)
today = now_cn.strftime("%Y-%m-%d")
yesterday = (now_cn - timedelta(days=1)).strftime("%Y-%m-%d")


def sync(now):
    async def _run():
        from app.db import engine
        from app.services.auto_flow import sync_business_hours
        result = await sync_business_hours(now)
        await engine.dispose()
        return result
    return asyncio.run(_run())


def at(hhmm: str):
    hour, minute = map(int, hhmm.split(":"))
    return now_cn.replace(hour=hour, minute=minute, second=30, microsecond=0)


# ---- 非法计划 422 ----
for bad in (
    [{"from": today, "to": yesterday, "closed": True}],          # 区间倒挂
    [{"from": today, "closed": False}],                          # 特殊时段没给时间
    [{"from": "2026/01/01", "closed": True}],                    # 日期格式错误
    [{"from": today, "closed": True}] * 21,                      # 超过 20 条
):
    err = call("PATCH", "/merchants/me", merchant,
               {"holiday_plans": bad}, expect_error=True)
    assert err["_error"] == 422, bad
print("✓ 非法计划四类全部 422(倒挂/缺时段/格式/条数)")

# ---- 歇业计划日:强制关店,自动开店不生效 ----
me = call("PATCH", "/merchants/me", merchant, {
    "holiday_plans": [{"from": today, "to": today, "closed": True}],
    "open_time": "08:00", "close_time": "22:00", "is_open": True,
})
assert me["holiday_plans"][0]["from"] == today  # 归一化存储
sync(at("08:01"))  # 撞上每日自动开店窗口
assert call("GET", "/merchants/me", merchant)["is_open"] is False
print("✓ 歇业计划日:开着的店被关,自动开店窗口被跳过")

# 手动强开也会被下一轮清扫关掉(计划优先级最高)
call("PATCH", "/merchants/me", merchant, {"is_open": True})
sync(at("12:00"))
assert call("GET", "/merchants/me", merchant)["is_open"] is False
print("✓ 计划优先于手动:强开被下一轮清扫关回")

# ---- 特殊时段日:按计划时段开关,每日时段失效 ----
call("PATCH", "/merchants/me", merchant, {
    "holiday_plans": [{"from": today, "to": today, "closed": False,
                       "open": "10:00", "close": "15:00"}],
})
sync(at("08:01"))  # 每日 08:00 开店窗口:被计划替代,不开
assert call("GET", "/merchants/me", merchant)["is_open"] is False
sync(at("10:01"))  # 计划 10:00 开店窗口:开
assert call("GET", "/merchants/me", merchant)["is_open"] is True
sync(at("15:01"))  # 计划 15:00 打烊窗口:关
assert call("GET", "/merchants/me", merchant)["is_open"] is False
print("✓ 特殊时段日:10:00 开 15:00 关,每日 08:00 窗口失效")

# ---- 计划外日期回归正常 ----
call("PATCH", "/merchants/me", merchant, {
    "holiday_plans": [{"from": yesterday, "to": yesterday, "closed": True}],
})
sync(at("08:01"))
assert call("GET", "/merchants/me", merchant)["is_open"] is True
print("✓ 计划只在区间内生效,昨天的计划不影响今天")

# ---- 过期条目清理 ----
def cleanup():
    async def _run():
        from app.db import SessionLocal, engine
        from app.services.auto_flow import cleanup_expired_holiday_plans
        async with SessionLocal() as db:
            count = await cleanup_expired_holiday_plans(db, today)
        await engine.dispose()
        return count
    return asyncio.run(_run())


assert cleanup() >= 1
assert call("GET", "/merchants/me", merchant)["holiday_plans"] == []
print("✓ 过期计划被每日任务清理")

# ---- 收尾还原 ----
call("PATCH", "/merchants/me", merchant, {
    "holiday_plans": [], "open_time": orig["open_time"],
    "close_time": orig["close_time"], "is_open": True,
})
print("\n节假日营业计划验证通过 🎉")
