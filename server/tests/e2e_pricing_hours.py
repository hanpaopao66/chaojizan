"""配送费按距离计价 + 营业时间自动开关店验证。
在 server/ 目录下运行:python -m tests.e2e_pricing_hours
"""
import asyncio
from datetime import datetime

from app.services.auto_flow import BEIJING, sync_business_hours
from tests.util import demo_shop, call, login, orderable_dish

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = demo_shop()
sid = shop["id"]
dishes = call("GET", f"/merchants/{sid}/dishes")
main_dish = orderable_dish(dishes)

# ---------- 配送费计价(距离阶梯 + 夜间/天气加价 + 配送半径) ----------
admin = login("13800000000")

near = call("GET", f"/orders/delivery-fee?merchant_id={sid}&lat=30.6612&lng=104.0823", customer)
assert near["parts"]["base"] == 300, near
assert near["fee_cents"] == sum(near["parts"].values()), near
assert near["in_range"] is True
print(f"✓ 2km 内基础配送费 ¥3(距离 {near['distance_m']}m,组成 {near['parts']})")

# 直线 ≈3.7km、**骑行路网 ≈5.0km**:基础 3 + ceil(3.0)×1 = 7 元。
#
# 断言从写死 500 改成"按返回的距离自己算一遍"(#300):
# 计价距离已经不是直线了,写死一个数就等于把当年那条直线钉在测试里 ——
# 而路网距离会随腾讯的数据更新而变,钉死只会让这条用例长期假红。
# 要验的本来就是「阶梯算对了没有」,不是「那天恰好是 5 块」。
mid = call("GET", f"/orders/delivery-fee?merchant_id={sid}&lat=30.6927&lng=104.0823", customer)
import math
expect_base = min(300 + math.ceil(max(0.0, mid["distance_m"] / 1000 - 2)) * 100,
                  1000)
assert mid["parts"]["base"] == expect_base, mid
# ⚠️ 不断言 source 一定是 route:**CI 上没有 TENCENT_MAP_KEY**,
# 那里只会走直线兜底。把"必须走路网"写成硬断言,等于要求跑测试的人
# 先有一把生产 Key —— 而这个仓库是开源的,fork 的人第一次跑就红。
#
# 真正要守的是「不管哪条路走过来,费用都要和返回的距离对得上」,
# 上面那条断言已经守住了。source 只做提示。
assert mid["distance_source"] in ("route", "straight"), mid
if mid["distance_source"] == "straight":
    print("  (本机/CI 没配 TENCENT_MAP_KEY,计价走直线兜底)")
# 半径按**直线**判:路网比直线长,若这里也用路网,用户在附近商家列表
# (PostGIS 球面直线)看得见的店会点不了 —— 看得见点不了比看不见更伤人
assert mid["in_range"] is True
print(f"✓ 远距离阶梯加价:路网 {mid['distance_m']}m → 基础 ¥{mid['parts']['base']/100:.0f}")

# ≈5.6km:超出 4km 配送半径,预览标记 + 下单被拒
far = call("GET", f"/orders/delivery-fee?merchant_id={sid}&lat=30.7098&lng=104.0810", customer)
assert far["in_range"] is False, far
err = call("POST", "/orders", customer, {
    "merchant_id": sid,
    "items": [{"dish_id": main_dish["id"], "quantity": 1}],
    "address": "远郊测试地址", "lat": 30.7098, "lng": 104.0810,
}, expect_error=True)
assert err["_error"] == 409 and "配送范围" in err["detail"]
print(f"✓ 超出 4km 配送半径:预览标记 in_range=false,下单 409({far['distance_m']}m)")

# 恶劣天气加价(#146):按区县**自动判定**,管理员保留强制开、不保留强制关。
#
# 这一段刻意**不依赖真实天气** —— 用例跑的时候外面到底下不下雨是随机的
# (实测跑到过成都雷暴:降水 1.1mm、天气码 95,自动判定正确触发)。
# 要验的是「强制开一定加价」这条机制,不是「今天天气如何」。
call("POST", "/admin/flags/weather_surcharge", admin, {"value": "off"})
before = call("GET", f"/orders/delivery-fee?merchant_id={sid}&lat=30.6612&lng=104.0823", customer)
call("POST", "/admin/flags/weather_surcharge", admin, {"value": "on"})
stormy = call("GET", f"/orders/delivery-fee?merchant_id={sid}&lat=30.6612&lng=104.0823", customer)
assert stormy["parts"]["weather"] == 200, stormy
assert stormy["fee_cents"] == before["fee_cents"] + (
    200 - before["parts"]["weather"]), stormy
call("POST", "/admin/flags/weather_surcharge", admin, {"value": "off"})
# 关掉强制开后**不断言一定为 0**:自动判定仍在生效,
# 真下雨时照样加价 —— 那正是这次改动的目的(不保留"强制关")
calm = call("GET", f"/orders/delivery-fee?merchant_id={sid}&lat=30.6612&lng=104.0823", customer)
assert calm["parts"]["weather"] in (0, 200), calm
err = call("POST", "/admin/flags/weather_surcharge", customer, None, expect_error=True)
assert err["_error"] == 403
print("✓ 恶劣天气加价:管理员开 +¥2 → 关恢复,非管理员 403")

# 真实下单的配送费必须和预览一致(夜间加价由服务端统一判定,两边自然一致)
order = call("POST", "/orders", customer, {
    "merchant_id": sid,
    "items": [{"dish_id": main_dish["id"], "quantity": 1}],
    "address": "半径内测试地址", "lat": 30.6927, "lng": 104.0823,
})
assert order["delivery_fee_cents"] == mid["fee_cents"]
assert order["total_cents"] == order["food_cents"] + order["delivery_fee_cents"]
if mid["parts"]["night"]:
    assert "夜间配送" in order["promo_note"]
call("POST", f"/orders/{order['order_no']}/transition", customer, {"to_status": "cancelled"})
print("✓ 下单实收配送费与预览一致(已取消清场)")

# 平台起送价下限:低于 ¥15 的购物车不接单
cheap = call("POST", "/merchants/me/dishes", merchant,
             {"name": "起送价测试豆浆", "price_cents": 600, "stock": 10})
err = call("POST", "/orders", customer, {
    "merchant_id": sid,
    "items": [{"dish_id": cheap["id"], "quantity": 1}],
    "address": "测试地址", "lat": 30.6612, "lng": 104.0823,
}, expect_error=True)
assert err["_error"] == 409 and "起送价" in err["detail"]
call("PATCH", f"/merchants/me/dishes/{cheap['id']}", merchant, {"is_on_sale": False})
print("✓ 平台起送价下限 ¥15:小单被拒(佣金连支付通道费都不够的单不接)")

# ---------- 营业时间自动开关店 ----------
call("PATCH", "/merchants/me", merchant, {"open_time": "08:00", "close_time": "22:00"})
err = call("PATCH", "/merchants/me", merchant, {"open_time": "25:99"}, expect_error=True)
assert err["_error"] == 422
print("✓ 营业时间格式校验(25:99 被拒)")


async def hours_flow():
    # 到打烊时刻 → 自动歇业
    fake_close = datetime.now(BEIJING).replace(hour=22, minute=0, second=30)
    await sync_business_hours(fake_close)
    assert call("GET", "/merchants/me", merchant)["is_open"] is False
    print("✓ 22:00 到点自动打烊")

    # 非边界时刻手动开店,不被清扫任务干扰
    call("PATCH", "/merchants/me", merchant, {"is_open": True})
    midday = datetime.now(BEIJING).replace(hour=15, minute=0, second=30)
    await sync_business_hours(midday)
    assert call("GET", "/merchants/me", merchant)["is_open"] is True
    print("✓ 非边界时刻不干扰手动开关")

    # 到开店时刻 → 自动营业
    call("PATCH", "/merchants/me", merchant, {"is_open": False})
    fake_open = datetime.now(BEIJING).replace(hour=8, minute=0, second=30)
    await sync_business_hours(fake_open)
    assert call("GET", "/merchants/me", merchant)["is_open"] is True
    print("✓ 08:00 到点自动开店")


asyncio.run(hours_flow())

# 清场:恢复纯手动 + 营业中
call("PATCH", "/merchants/me", merchant, {"open_time": "", "close_time": ""})
call("PATCH", "/merchants/me", merchant, {"is_open": True})

print("\n配送费计价 + 营业时间验证通过 🎉")
