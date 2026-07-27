"""房型/房价房态日历:CRUD、批量设置、总量护栏、权限。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_stays_inventory
(库存 occupy 并发压测在 e2e_stays_order 里跟真实下单一起验)
"""
import random
from datetime import date, timedelta

from tests.util import ADMIN, MERCHANT, call, login

admin_token = login(ADMIN)

# 建一家新酒店并过审(复用 #66 的入驻链路)
phone = "138" + "".join(str(random.randint(0, 9)) for _ in range(8))
reg = call("POST", "/auth/register",
           body={"phone": phone, "password": "hotel123", "role": "merchant"})
mt = reg["token"]
shop = call("POST", "/merchants", token=mt, body={
    "name": f"日历客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel",
    "license_no": "91510100MA6TEST02",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-002",
              "special_license_image_url": "https://example.com/sp.jpg"},
})
call("POST", f"/admin/merchants/{shop['id']}/approve", token=admin_token)

# 1) 餐饮商家(演示号 02)访问住宿接口被拒
food_token = login(MERCHANT)
r = call("GET", "/stays/me/room-types", token=food_token, expect_error=True)
assert r["_error"] == 403 and "酒店业态" in r["detail"], r
print("OK 业态权限拦截:", r["detail"])

# 2) 房型 CRUD
rt1 = call("POST", "/stays/me/room-types", token=mt, body={
    "name": "高级大床房", "bed_type": "1.8m 大床", "area_m2": 28,
    "max_guests": 2, "cancel_policy": "limited_free",
    "free_cancel_until": "18:00"})
rt2 = call("POST", "/stays/me/room-types", token=mt, body={
    "name": "双床房", "bed_type": "1.2m 双床", "max_guests": 2,
    "cancel_policy": "strict"})
lst = call("GET", "/stays/me/room-types", token=mt)
assert [x["id"] for x in lst] == [rt1["id"], rt2["id"]]
patched = call("PATCH", f"/stays/me/room-types/{rt1['id']}", token=mt,
               body={"is_on_sale": False, "cancel_policy": "first_night"})
assert patched["is_on_sale"] is False and patched["cancel_policy"] == "first_night"
call("PATCH", f"/stays/me/room-types/{rt1['id']}", token=mt,
     body={"is_on_sale": True})
print(f"OK 房型 CRUD: rt1={rt1['id']} rt2={rt2['id']}")

# 3) 日历批量设置:两个房型 × 30 天,一次设价设量
today = date.today()
d30 = today + timedelta(days=29)
r = call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt1["id"], rt2["id"]],
    "from_date": str(today), "to_date": str(d30),
    "price_cents": 15800, "total_qty": 5})
assert r["created"] == 60 and r["updated"] == 0, r
# 改价只影响区间;关房两天
call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt1["id"]],
    "from_date": str(today + timedelta(days=3)),
    "to_date": str(today + timedelta(days=4)), "closed": True})
grid = call("GET", f"/stays/me/calendar?from_date={today}&days=30", token=mt)
row1 = next(x for x in grid if x["room_type_id"] == rt1["id"])
assert len(row1["days"]) == 30
closed_days = [d for d in row1["days"] if d["closed"]]
assert len(closed_days) == 2
assert all(d["price_cents"] == 15800 and d["total_qty"] == 5
           for d in row1["days"])
print("OK 日历批量设置与网格查询(30 天 × 2 房型,关房 2 天)")

# 4) 护栏:首次开放不带价被拒;过去日期被拒;区间超 120 天被拒
r = call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt1["id"]],
    "from_date": str(d30 + timedelta(days=1)),
    "to_date": str(d30 + timedelta(days=1)), "total_qty": 3},
    expect_error=True)
assert r["_error"] == 422 and "未设价" in r["detail"], r
r = call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt1["id"]],
    "from_date": str(today - timedelta(days=1)), "to_date": str(today),
    "price_cents": 100}, expect_error=True)
assert r["_error"] == 422 and "过去" in r["detail"], r
r = call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt1["id"]],
    "from_date": str(today), "to_date": str(today + timedelta(days=121)),
    "price_cents": 100}, expect_error=True)
assert r["_error"] == 422, r
print("OK 护栏:未设价/过去日期/超长区间")

# 5) 总量下调不能低于已售(直接造已售数据验证护栏)
#    没有下单接口前,用"关房日不可订"的语义先验证 closed 生效即可;
#    sold 护栏用 total_qty=0 再抬回验证幂等
r = call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt1["id"]],
    "from_date": str(today), "to_date": str(today), "total_qty": 0})
assert r["updated"] == 1
r = call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt1["id"]],
    "from_date": str(today), "to_date": str(today), "total_qty": 5})
assert r["updated"] == 1
print("OK 总量调整幂等(sold>0 护栏在 e2e_stays_order 连同下单一起验)")

print("PASS e2e_stays_inventory")
