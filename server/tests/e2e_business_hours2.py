"""临时歇业(到点自动恢复) + 平台深夜保护窗。

sync_business_hours 支持注入 now,进程内直调做确定性时间断言。
"""
import asyncio
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests.util import call, login

CN = ZoneInfo("Asia/Shanghai")
admin = login("13800000000")
customer = login("13800000001")
merchant = login("13800000002")

orig = call("GET", "/merchants/me", merchant)


def sync(now):
    async def _run():
        from app.db import engine
        from app.services.auto_flow import sync_business_hours
        result = await sync_business_hours(now)
        await engine.dispose()
        return result
    return asyncio.run(_run())


# ---- 临时歇业 2 小时 ----
me = call("POST", "/merchants/me/rest", merchant, {"hours": 2})
assert me["is_open"] is False and me["closed_until"] is not None
cu = datetime.fromisoformat(me["closed_until"]).astimezone(CN)
print(f"✓ 歇业 2 小时:关店,{cu:%H:%M} 自动恢复")

# 歇业期内即使撞上自动开店时刻也不开
before = cu - timedelta(minutes=30)
call("PATCH", "/merchants/me", merchant,
     {"open_time": before.strftime("%H:%M"), "close_time": "23:59"})
sync(before)
assert call("GET", "/merchants/me", merchant)["is_open"] is False
print("✓ 歇业期内自动开店不生效")

# 到点自动恢复营业(清标记 + 在营业区间内则开店)
sync(cu + timedelta(minutes=1))
me = call("GET", "/merchants/me", merchant)
assert me["is_open"] is True and me["closed_until"] is None
print("✓ 到点自动恢复营业,歇业标记清空")

# ---- 歇业到今天打烊 ----
me = call("POST", "/merchants/me/rest", merchant, {"until_close": True})
cu2 = datetime.fromisoformat(me["closed_until"]).astimezone(CN)
assert cu2.strftime("%H:%M") == "23:59"
# 商家改主意提前恢复:开店动作清歇业标记
me = call("PATCH", "/merchants/me", merchant, {"is_open": True})
assert me["is_open"] is True and me["closed_until"] is None
print("✓ 歇业到打烊 23:59;手动开店即提前恢复并清标记")

# 二选一校验
err = call("POST", "/merchants/me/rest", merchant,
           {"hours": 2, "until_close": True}, expect_error=True)
assert err["_error"] == 422
print("✓ 时长与到打烊二选一,同传被拒")

# ---- 平台深夜保护窗 ----
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"宵禁测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})
order_body = {
    "merchant_id": orig["id"],
    "items": [{"dish_id": dish["id"], "quantity": 1}],
    "address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
    "contact_name": "测试", "contact_phone": "13800000001",
}
err = call("POST", "/admin/flags/night_curfew_hours", admin,
           {"value": "25:00-99:99"}, expect_error=True)
assert err["_error"] == 422
call("POST", "/admin/flags/night_curfew_hours", admin, {"value": "00:00-23:59"})
call("POST", "/admin/flags/night_curfew", admin, {"value": "on"})
err = call("POST", "/orders", customer, order_body, expect_error=True)
assert err["_error"] == 409 and "深夜时段" in err["detail"], err
print(f"✓ 保护窗内下单被拒:{err['detail']}")

call("POST", "/admin/flags/night_curfew", admin, {"value": "off"})
order = call("POST", "/orders", customer, order_body)
assert order["order_no"]
print("✓ 保护窗关闭后恢复接单")

# ---- 收尾还原 ----
call("PATCH", "/merchants/me", merchant, {
    "open_time": orig["open_time"], "close_time": orig["close_time"],
    "is_open": True,
})
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
     {"is_on_sale": False})
print("\n临时歇业 + 深夜保护窗验证通过 🎉")
