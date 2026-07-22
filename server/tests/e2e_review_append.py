"""评价匿名与追评验证:匿名评价对外"匿名用户"、追评 7 天窗口一次、
敏感词拦截、商家回复追评、非本人 404。

在 server/ 目录下运行:python -m tests.e2e_review_append
"""
import asyncio
import random
import time

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import call, login, register_fresh_rider

merchant = login("13800000002")
ts = int(time.time())


def fresh():
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login",
                body={"phone": phone, "code": code})["token"]


async def main():
    customer = fresh()
    rider = await register_fresh_rider("追评测试骑手")
    shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
    sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
    dish = call("POST", "/merchants/me/dishes", merchant,
                {"name": f"追评测试菜-{ts}", "price_cents": 2000, "stock": 20})

    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08})
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})

    # 1) 匿名评价:公开列表与商家侧都是"匿名用户"
    review = call("POST", f"/orders/{no}/review", customer, {
        "merchant_rating": 5, "comment": "味道很好但不想让老板认出我",
        "is_anonymous": True})
    rid = review["id"]
    assert review["customer_name"] == "匿名用户"
    public = call("GET", f"/merchants/{sid}/reviews")
    mine = next(r for r in public if r["id"] == rid)
    assert mine["customer_name"] == "匿名用户" and mine["is_anonymous"]
    print("✓ 匿名评价对外只显示「匿名用户」")

    # 2) 追评:敏感词拦截、成功、只此一次、匿名继承
    err = call("POST", f"/reviews/{rid}/append", customer,
               {"content": "加微信转账便宜点"}, expect_error=True)
    assert err["_error"] == 422
    updated = call("POST", f"/reviews/{rid}/append", customer,
                   {"content": "过了两天再来说:分量也实在"})
    assert updated["append_content"].startswith("过了两天")
    assert updated["customer_name"] == "匿名用户"  # 追评继承匿名
    err = call("POST", f"/reviews/{rid}/append", customer,
               {"content": "再追一条"}, expect_error=True)
    assert err["_error"] == 409
    print("✓ 追评过审核、一单一次、继承匿名")

    # 3) 7 天窗口:backdate 首评时间后追评 409
    customer2 = fresh()
    order2 = call("POST", "/orders", customer2, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08})
    no2 = order2["order_no"]
    call("POST", f"/orders/{no2}/pay/mock", customer2)
    call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no2}", rider)
    call("POST", f"/orders/{no2}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no2}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no2}/transition", customer2,
         {"to_status": "completed"})
    r2 = call("POST", f"/orders/{no2}/review", customer2,
              {"merchant_rating": 4, "comment": "不错"})
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE reviews SET created_at = now() - interval '8 days' "
            "WHERE id = :i"), {"i": r2["id"]})
        await db.commit()
    err = call("POST", f"/reviews/{r2['id']}/append", customer2,
               {"content": "太晚了吧"}, expect_error=True)
    assert err["_error"] == 409 and "7 天" in err["detail"]
    # 非本人 404
    err = call("POST", f"/reviews/{rid}/append", customer2,
               {"content": "蹭一条"}, expect_error=True)
    assert err["_error"] == 404
    print("✓ 首评超 7 天关闭;非本人 404")

    # 4) 商家回复追评;没追评的 409
    replied = call("POST", f"/merchants/me/reviews/{rid}/append-reply",
                   merchant, {"reply": "感谢回头认可,常来!"})
    assert replied["append_reply"].startswith("感谢")
    err = call("POST", f"/merchants/me/reviews/{r2['id']}/append-reply",
               merchant, {"reply": "?"}, expect_error=True)
    assert err["_error"] in (409, 422)
    print("✓ 商家可回复追评;无追评不可回复")

    print("\ne2e_review_append 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
