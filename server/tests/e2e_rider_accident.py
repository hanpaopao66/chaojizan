"""骑手交通事故处理验证:上报→未取餐单无责释放回池(不计转单次数)、
已取餐单自动开配送异常工单、照片补传、管理端跟进/结案留痕。

在 server/ 目录下运行:python -m tests.e2e_rider_accident
"""
import asyncio
import time

from tests.util import call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"事故测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def make_order(to_status="accepted"):
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    if to_status == "ready":
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    return no


async def main():
    await drain_order_pool()
    rider = await register_fresh_rider("事故测试骑手")
    call("POST", "/riders/online", rider, {"is_online": True})

    # 手上两单:一单未取餐(ACCEPTED)、一单已取餐(PICKED_UP)
    no_accepted = make_order()
    no_picked = make_order("ready")
    call("POST", f"/riders/grab/{no_accepted}", rider)
    call("POST", f"/riders/grab/{no_picked}", rider)
    call("POST", f"/orders/{no_picked}/transition", rider,
         {"to_status": "picked_up"})

    # 1) severity 校验
    err = call("POST", "/riders/accidents", rider, {"severity": "boom"},
               expect_error=True)
    assert err["_error"] == 422, err

    # 2) 上报事故:未取餐单释放回池,已取餐单转仲裁工单
    r = call("POST", "/riders/accidents", rider, {
        "severity": "injury", "description": "路口被汽车剐蹭,腿擦伤",
        "lat": 30.66, "lng": 104.08})
    assert r["released_orders"] == 1 and r["issue_orders"] == 1, r
    assert r["insurance_status"] == "registered", r  # 上线时已登记保障
    acc_id = r["id"]
    print("✓ 事故上报:1 单无责回池 + 1 单转仲裁,保障状态=登记(保障金池)")

    # 未取餐单回池:他人可见可抢;用户视角状态回 PAID 流转不乱
    pool = call("GET", "/riders/available-orders?lat=30.66&lng=104.08", rider)
    assert any(o["order_no"] == no_accepted for o in pool), "释放单应回池"
    detail = call("GET", f"/orders/{no_accepted}", customer)
    assert detail["status"].lower() in ("paid", "accepted"), detail["status"]
    # 无责释放:不走转单通道,当日转单计数(Redis)保持为 0
    from datetime import datetime, timedelta, timezone

    from app.redis_client import get_redis
    rider_id = call("GET", "/auth/me", rider)["id"]
    bj_date = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    count = await get_redis().get(f"rider:transfer:{rider_id}:{bj_date}")
    assert not count or int(count) == 0, count
    print("✓ 释放单回池可再抢,不占当日转单次数")

    # 已取餐单:配送异常工单已开
    issues = call("GET", "/admin/delivery-issues?status=open", admin)
    assert any(i["order_no"] == no_picked and "交通事故" in i["note"]
               for i in issues), issues
    print("✓ 已取餐单自动开配送异常工单(平台仲裁)")

    # 3) 照片补传(人先安全,照片后补)
    r2 = call("POST", f"/riders/accidents/{acc_id}/photos", rider,
              {"photos": ["https://example.com/scene1.jpg",
                          "https://example.com/scene2.jpg"]})
    assert len(r2["photos"]) == 2, r2
    mine = call("GET", "/riders/accidents", rider)
    assert mine[0]["id"] == acc_id and len(mine[0]["photos"]) == 2
    print("✓ 现场照片补传成功")

    # 4) 管理端:红色加急列表→跟进→结案,处置留痕
    opens = call("GET", "/admin/rider-accidents?status=open", admin)
    target = next(a for a in opens if a["id"] == acc_id)
    assert target["severity"] == "injury" and target["rider_phone"]
    err = call("POST", f"/admin/rider-accidents/{acc_id}/update", admin,
               {"status": "closed", "note": ""}, expect_error=True)
    assert err["_error"] == 422, err  # 结案必须留痕
    call("POST", f"/admin/rider-accidents/{acc_id}/update", admin,
         {"status": "following", "note": "已电话回访,骑手轻伤已就医"})
    call("POST", f"/admin/rider-accidents/{acc_id}/update", admin,
         {"status": "closed", "note": "保障金池赔付医药费 ¥180,骑手已复跑"})
    closed = call("GET", "/admin/rider-accidents?status=closed", admin)
    target = next(a for a in closed if a["id"] == acc_id)
    assert len(target["actions"]) == 2, target["actions"]
    assert target["actions"][0]["note"].startswith("已电话回访")
    assert target["actions"][1]["admin_id"], target["actions"]
    print("✓ 管理端跟进/结案留痕(两条处置记录)")

    # 清场:仲裁工单按平台责任结案(全额退款),释放单取消
    issue = next(i for i in issues if i["order_no"] == no_picked)
    call("POST", f"/admin/delivery-issues/{issue['id']}/resolve", admin,
         {"action": "refund", "fault": "platform",
          "note": "骑手事故,平台承担,用户全额退款"})
    call("POST", f"/orders/{no_accepted}/transition", customer,
         {"to_status": "cancelled", "reason": "测试清场"})
    call("POST", "/riders/online", rider, {"is_online": False})
    print("\ne2e_rider_accident 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
