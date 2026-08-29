"""住宿点评:离店可评/在住不可评/超窗拒评/滚动评分聚合(<3 不出分)/追评/商家回复/匿名。

在 server/ 目录下运行:python -m tests.e2e_stays_review
"""
import asyncio
import random
from urllib.parse import quote
from datetime import date, timedelta

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import ADMIN, call, login, register_user

admin_token = login(ADMIN)
today = date.today()

mt, phone = register_user("merchant", "hotel123", prefix="138")
shop = call("POST", "/merchants", token=mt, body={
    "name": f"点评客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST09",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-009",
              "special_license_image_url": "https://example.com/sp.jpg"}})
sid = shop["id"]
call("POST", f"/admin/merchants/{sid}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})
rt = call("POST", "/stays/me/room-types", token=mt,
          body={"name": "点评房", "cancel_policy": "limited_free"})
call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt["id"]], "from_date": str(today),
    "to_date": str(today + timedelta(days=10)),
    "price_cents": 10000, "total_qty": 9})


def guest():
    return register_user("customer", "123456", prefix="137")[0]


def stay_through(t):
    """下单→支付→确认→入住→离店,返回单号。"""
    o = call("POST", "/stays/orders", token=t, body={
        "room_type_id": rt["id"], "checkin_date": str(today + timedelta(days=1)),
        "checkout_date": str(today + timedelta(days=2)), "rooms_qty": 1,
        "guest_name": "点评客", "guest_phone": "13700000008"})
    no = o["order_no"]
    call("POST", f"/stays/orders/{no}/pay/mock", token=t)
    call("POST", f"/stays/me/orders/{no}/confirm", token=mt)
    call("POST", f"/stays/me/orders/{no}/checkin", token=mt)
    call("POST", f"/stays/me/orders/{no}/checkout", token=mt)
    return no


# 1) 在住不可评
t1 = guest()
o = call("POST", "/stays/orders", token=t1, body={
    "room_type_id": rt["id"], "checkin_date": str(today + timedelta(days=3)),
    "checkout_date": str(today + timedelta(days=4)), "rooms_qty": 1,
    "guest_name": "在住客", "guest_phone": "13700000009"})
call("POST", f"/stays/orders/{o['order_no']}/pay/mock", token=t1)
r = call("POST", f"/stays/orders/{o['order_no']}/review", token=t1,
         body={"rating": 5}, expect_error=True)
assert r["_error"] == 409 and "离店" in r["detail"], r
print("OK 未离店不可评")

# 2) 离店可评;一单一评;匿名保护
no1 = stay_through(t1)
rv = call("POST", f"/stays/orders/{no1}/review", token=t1, body={
    "rating": 5, "comment": "床很舒服,前台很热情",
    "tags": ["干净卫生", "服务热情"], "is_anonymous": True})
assert rv["reviewer_name"] == "匿名住客"
r = call("POST", f"/stays/orders/{no1}/review", token=t1,
         body={"rating": 1}, expect_error=True)
assert r["_error"] == 409, "一单一评"
r = call("POST", f"/stays/orders/{no1}/review", token=t1,
         body={"rating": 5, "tags": ["乱写的标签"]}, expect_error=True)
assert r["_error"] in (409, 422)
print("OK 离店可评/一单一评/匿名/标签白名单")

# 3) <3 条不出分;满 3 条出滚动均分
#
# 搜索用**全名**而不是前缀:历次跑动共用同一个店名前缀,而列表封顶 50 条
# 且按评分排序 —— 前缀搜到几十家老店时,新建的这家(还没评分,排最后)
# 会被挤出结果,断言就变成"查无此店"而不是"这家不该出分"
lst = call("GET", f"/stays/hotels?q={quote(shop['name'])}&sort=rating")
mine = next((h for h in lst if h["id"] == sid), None)
assert mine is not None and mine["rating_avg"] is None, "1 条评价不该出分"
t2, t3 = guest(), guest()
call("POST", f"/stays/orders/{stay_through(t2)}/review", token=t2,
     body={"rating": 4})
call("POST", f"/stays/orders/{stay_through(t3)}/review", token=t3,
     body={"rating": 3})
lst = call("GET", f"/stays/hotels?q={quote(shop['name'])}&sort=rating")
mine = next(h for h in lst if h["id"] == sid)
assert mine["rating_avg"] == 4.0 and mine["rating_count"] == 3, mine
d = call("GET", f"/stays/hotels/{sid}")
assert d["rating_avg"] == 4.0
print("OK 评分聚合:<3 不出分,满 3 条滚动均分 4.0")

# 4) 超过 15 天不可评(直连库把 completed_at 挪老)
t4 = guest()
no4 = stay_through(t4)


async def backdate():
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE stay_orders SET completed_at = now() - interval '16 days' "
            "WHERE order_no = :no"), {"no": no4})
        await db.commit()


asyncio.run(backdate())
r = call("POST", f"/stays/orders/{no4}/review", token=t4,
         body={"rating": 5}, expect_error=True)
assert r["_error"] == 409 and "15" in r["detail"], r
print("OK 离店超 15 天评价通道关闭")

# 5) 追评 + 商家回复(首评回复→追评回复)
rv2 = call("POST", f"/stays/reviews/{rv['id']}/append", token=t1,
           body={"content": "第二天退房也很顺利"})
assert rv2["append_content"]
call("POST", f"/stays/me/reviews/{rv['id']}/reply", token=mt,
     body={"reply": "谢谢支持,欢迎再来"})
replied = call("POST", f"/stays/me/reviews/{rv['id']}/reply", token=mt,
               body={"reply": "追评也看到啦"})
assert replied["reply"] == "谢谢支持,欢迎再来"
assert replied["append_reply"] == "追评也看到啦"
# 公开列表匿名可见
pub = call("GET", f"/stays/hotels/{sid}/reviews")
assert any(p["reviewer_name"] == "匿名住客" for p in pub)
# 商家列表带单号
mine_rv = call("GET", "/stays/me/reviews", token=mt)
assert all(p["order_no"] for p in mine_rv)
print("OK 追评/商家两段回复/公开匿名列表")

print("PASS e2e_stays_review")
