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
#
# 营业时段要**真的覆盖恢复时刻**(cu + 1 分钟)。原先写死 close_time
# "23:59",而歇业 2 小时会跨午夜 —— CI 在北京时间 22:12 跑,
# 恢复时刻是次日 00:12,窗口 23:42–23:59 根本不含它,
# 于是「到点自动恢复营业」那条必红。**只在晚上 22 点后跑才会红**,
# 本地跑在别的时段一直是绿的。
# 服务端本来就支持跨天区间(auto_flow 的营业判定,如 18:00-02:00),
# 是这条用例自己把窗口写死了
before = cu - timedelta(minutes=30)
after = cu + timedelta(hours=1)
call("PATCH", "/merchants/me", merchant,
     {"open_time": before.strftime("%H:%M"),
      "close_time": after.strftime("%H:%M")})
sync(before)
assert call("GET", "/merchants/me", merchant)["is_open"] is False
print("✓ 歇业期内自动开店不生效")

# 到点自动恢复营业(清标记 + 在营业区间内则开店)
sync(cu + timedelta(minutes=1))
me = call("GET", "/merchants/me", merchant)
assert me["is_open"] is True and me["closed_until"] is None
print("✓ 到点自动恢复营业,歇业标记清空")

# ---- 歇业到今天打烊 ----
#
# 断言**跟着商家自己的 close_time 走**,不写死 23:59 ——
# 服务端读的就是 shop.close_time(见 merchants.py 的 rest),
# 而上面那段刚把它改过。写死一个值等于要求这条用例
# 只能在某种前置状态下跑
close_hhmm = call("GET", "/merchants/me", merchant)["close_time"]
me = call("POST", "/merchants/me/rest", merchant, {"until_close": True})
cu2 = datetime.fromisoformat(me["closed_until"]).astimezone(CN)
assert cu2.strftime("%H:%M") == close_hhmm, (cu2, close_hhmm)
# 商家改主意提前恢复:开店动作清歇业标记
me = call("PATCH", "/merchants/me", merchant, {"is_open": True})
assert me["is_open"] is True and me["closed_until"] is None
print(f"✓ 歇业到打烊 {close_hhmm};手动开店即提前恢复并清标记")

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
#
# 还原到**全天营业**,不是还原到"进来时是什么样"。
#
# 原先是 orig["open_time"]/orig["close_time"] —— 看着更保守,实际相反:
# 这条用例中途失败过一次(跨午夜那个坑),脏值留在库里;下一次跑
# 把脏值当成 orig 捕获、再原样写回去,于是**脏状态被永久传下去**。
# 演示店一度是 23:43-01:13,只要跑批时间落在窗口外,auto_flow 会把它
# 自动打烊,后面所有下单套件一起红,而红的原因跟它们毫无关系。
#
# 空字符串 = 不限营业时间,这也是种子数据的口径 ——
# 其余套件全都假定演示店随时能下单
call("PATCH", "/merchants/me", merchant, {
    "open_time": "", "close_time": "", "is_open": True,
})
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
     {"is_on_sale": False})
print("\n临时歇业 + 深夜保护窗验证通过 🎉")
