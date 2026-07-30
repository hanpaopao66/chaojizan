"""酒店搜索/详情/报价:起价聚合、满房标记、排序筛选、取消政策文案。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_stays_search
"""
import random
from datetime import date, timedelta
from urllib.parse import quote

from tests.util import ADMIN, call, login

admin_token = login(ADMIN)
tag = str(random.randint(1000, 9999))
today = date.today()
ci, co = today + timedelta(days=7), today + timedelta(days=9)  # 2 晚


def make_hotel(name, lat, lng, tier):
    phone = "138" + "".join(str(random.randint(0, 9)) for _ in range(8))
    reg = call("POST", "/auth/register",
               body={"phone": phone, "password": "hotel123",
                     "role": "merchant"})
    t = reg["token"]
    shop = call("POST", "/merchants", token=t, body={
        "name": name, "lat": lat, "lng": lng, "biz_type": "hotel",
        "address": f"搜索测试路{tag}号",
        "license_no": "91510100MA6TEST03",
        "license_image_url": "https://example.com/biz.jpg",
        "hotel": {"tier": tier,
                  "special_license_no": "川公治安 2026-003",
                  "special_license_image_url": "https://example.com/sp.jpg"},
    })
    call("POST", f"/admin/merchants/{shop['id']}/approve", token=admin_token)
    call("PATCH", "/merchants/me", token=t, body={"is_open": True})
    return shop["id"], t


def add_room(t, name, price, qty, policy="limited_free", days_n=30):
    rt = call("POST", "/stays/me/room-types", token=t,
              body={"name": name, "cancel_policy": policy})
    call("PUT", "/stays/me/calendar", token=t, body={
        "room_type_ids": [rt["id"]], "from_date": str(today),
        "to_date": str(today + timedelta(days=days_n)),
        "price_cents": price, "total_qty": qty})
    return rt["id"]


# 酒店 A:近、便宜(两房型 300/500);B:远、贵(800);C:满房(关房)
a_id, a_t = make_hotel(f"搜A栈{tag}", 30.6600, 104.0600, "economy")
add_room(a_t, "标准间", 30000, 5)
add_room(a_t, "大床房", 50000, 2, policy="strict")
b_id, b_t = make_hotel(f"搜B栈{tag}", 30.7500, 104.1500, "comfort")
add_room(b_t, "豪华间", 80000, 3)
c_id, c_t = make_hotel(f"搜C栈{tag}", 30.6610, 104.0610, "economy")
rt_c = add_room(c_t, "无货间", 40000, 1)
call("PUT", "/stays/me/calendar", token=c_t, body={
    "room_type_ids": [rt_c], "from_date": str(today),
    "to_date": str(today + timedelta(days=30)), "closed": True})

Q = f"&checkin={ci}&checkout={co}"
mine = lambda lst: [h for h in lst if h["id"] in (a_id, b_id, c_id)]

# 1) 起价 = 可订房型最低区间总价 ÷ 晚数;满房标记
lst = mine(call("GET", f"/stays/hotels?q={quote(tag)}&sort=rating" + Q +
                f"&max_price_cents=999999"))
by_id = {h["id"]: h for h in lst}
assert by_id[a_id]["min_night_price_cents"] == 30000
assert by_id[b_id]["min_night_price_cents"] == 80000
assert c_id not in by_id, "带价格上限筛选时,满房(无价)店应被过滤"
# 不带价格筛选时,满房店应展示且 full=true
lst_all = mine(call("GET", f"/stays/hotels?q={quote(tag)}&sort=rating" + Q))
by_id = {h["id"]: h for h in lst_all}
assert by_id[c_id]["full"] is True and by_id[c_id]["min_night_price_cents"] is None
print("OK 起价聚合与满房标记")

# 2) 排序:price 升序 A(300)→C(满房垫底或不参与价格序)→B(800)
lst = mine(call("GET", f"/stays/hotels?q={quote(tag)}&sort=price" + Q))
ids = [h["id"] for h in lst]
assert ids.index(a_id) < ids.index(b_id), ids
assert ids[-1] == c_id, "满房(无价)应排最后"
# distance:A(近)在 B(远)前
lst = mine(call("GET",
                f"/stays/hotels?lat=30.66&lng=104.06&sort=distance"
                f"&q={quote(tag)}" + Q))
ids = [h["id"] for h in lst]
assert ids.index(a_id) < ids.index(b_id)
assert lst[0]["distance_m"] is not None
print("OK 排序 price/distance")

# 3) 筛选:tier=comfort 只剩 B;价格上限 40000 只剩 A
lst = mine(call("GET", f"/stays/hotels?q={quote(tag)}&tier=comfort"
                f"&sort=rating" + Q))
assert [h["id"] for h in lst] == [b_id]
lst = mine(call("GET", f"/stays/hotels?q={quote(tag)}&sort=rating"
                f"&max_price_cents=40000" + Q))
assert [h["id"] for h in lst] == [a_id]
print("OK 筛选 tier/价格区间")

# 4) 详情报价:每晚明细、总价、仅剩 X 间、取消政策文案
d = call("GET", f"/stays/hotels/{a_id}?checkin={ci}&checkout={co}")
assert d["checkin_from"] == "14:00" and d["tier"] == "economy"
std = next(r for r in d["rooms"] if r["room_type"]["name"] == "标准间")
big = next(r for r in d["rooms"] if r["room_type"]["name"] == "大床房")
assert std["total_cents"] == 60000 and len(std["nightly"]) == 2
assert std["left_qty"] is None, ">3 间不透具体数"
assert big["left_qty"] == 2, "≤3 间要展示仅剩 X 间"
assert "免费取消" in std["cancel_policy_text"]
assert "不可退" in big["cancel_policy_text"]
# 满房店详情:房型展示但不可订
d = call("GET", f"/stays/hotels/{c_id}?checkin={ci}&checkout={co}")
assert d["rooms"][0]["bookable"] is False and d["rooms"][0]["total_cents"] is None
print("OK 详情报价/仅剩X间/取消政策文案")

# 5) 日期校验与外卖频道隔离
r = call("GET", f"/stays/hotels/{a_id}?checkin={today - timedelta(days=1)}",
         expect_error=True)
assert r["_error"] == 422
food = call("GET", "/merchants?lat=30.66&lng=104.06&radius_m=5000")
assert all(m["id"] not in (a_id, b_id, c_id) for m in food)
print("OK 日期校验与频道隔离")

print("PASS e2e_stays_search")
