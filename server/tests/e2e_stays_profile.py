"""酒店资料自改(网页工作台):前台电话/入退房时刻/设施可改,证照只读。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_stays_profile
"""
import random
from datetime import date, timedelta

from tests.util import ADMIN, MERCHANT, call, login

admin_token = login(ADMIN)
phone = "138" + "".join(str(random.randint(0, 9)) for _ in range(8))
mt = call("POST", "/auth/register",
          body={"phone": phone, "password": "hotel123",
                "role": "merchant"})["token"]
shop = call("POST", "/merchants", token=mt, body={
    "name": f"资料客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST11",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-011",
              "special_license_image_url": "https://example.com/sp.jpg"}})
call("POST", f"/admin/merchants/{shop['id']}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})

# 1) 读资料
p = call("GET", "/stays/me/profile", token=mt)
assert p["special_license_no"] == "川公治安 2026-011"
assert p["checkin_from"] == "14:00"

# 2) 改前台电话/时刻/设施
call("PATCH", "/stays/me/profile", token=mt, body={
    "front_desk_phone": "02899998888", "checkin_from": "13:00",
    "checkout_until": "12:30", "facilities": ["wifi", "parking", "breakfast"]})
p = call("GET", "/stays/me/profile", token=mt)
assert p["front_desk_phone"] == "02899998888"
assert p["checkin_from"] == "13:00" and p["checkout_until"] == "12:30"
assert p["facilities"] == ["wifi", "parking", "breakfast"]
print("OK 资料自改生效")

# 3) 用户端详情联动(需有可订房型;先建一间)
rt = call("POST", "/stays/me/room-types", token=mt, body={"name": "资料房"})
today = date.today()
call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt["id"]], "from_date": str(today),
    "to_date": str(today + timedelta(days=3)),
    "price_cents": 10000, "total_qty": 1})
d = call("GET", f"/stays/hotels/{shop['id']}")
assert d["front_desk_phone"] == "02899998888" and d["checkin_from"] == "13:00"
print("OK 用户端详情联动新前台电话与时刻")

# 4) 护栏:非法时刻格式;餐饮商家被拦
r = call("PATCH", "/stays/me/profile", token=mt,
         body={"checkin_from": "25:00"}, expect_error=True)
assert r["_error"] == 422
food = login(MERCHANT)
r = call("GET", "/stays/me/profile", token=food, expect_error=True)
assert r["_error"] == 403
print("OK 格式护栏与业态权限")

print("PASS e2e_stays_profile")
