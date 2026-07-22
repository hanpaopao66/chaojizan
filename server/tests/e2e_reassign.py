"""管理员改派 + 运力看板验证:释放回池(不计免责)、指定改派、
PICKED_UP 拒改、超上限拒派、看板结构、非 admin 403。

在 server/ 目录下运行:python -m tests.e2e_reassign
"""
import asyncio
import time

from tests.util import call, drain_order_pool, login, register_fresh_rider

customer = login("13800000001")
merchant = login("13800000002")
admin = login("13800000000")

sid = call("GET", "/merchants/me", merchant)["id"]
call("PATCH", "/merchants/me", merchant, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"改派测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})


def make_order():
    o = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    return no


async def main():
    await drain_order_pool()
    r1 = await register_fresh_rider("改派骑手甲")
    r2 = await register_fresh_rider("改派骑手乙")
    call("POST", "/riders/online", r1, {"is_online": True})
    call("POST", "/riders/online", r2, {"is_online": True})
    r2_id = None

    # 1) 释放回池:原骑手转单免责计数不受影响
    no1 = make_order()
    call("POST", f"/riders/grab/{no1}", r1)
    call("POST", f"/admin/orders/{no1}/reassign", admin, {"rider_id": None})
    pool = call("GET", "/riders/available-orders", r2)
    assert no1 in [o["order_no"] for o in pool], "释放后应回池"
    # 转单计数不受影响:此时 r1 正常转一单应仍是当日第 1 次
    no_x = make_order()
    call("POST", f"/riders/grab/{no_x}", r1)
    r = call("POST", f"/riders/transfer/{no_x}", r1, {"reason": "other"})
    assert r["today_count"] == 1, f"改派不计免责次数:{r}"
    print("✓ 释放回池:他人可抢,原骑手免责计数不受影响")

    # 2) 指定改派给在线骑手(User.name 是默认昵称,按 id 对)
    r2_id = call("GET", "/auth/me", r2)["id"]
    board = call("GET", "/admin/dispatch-overview", admin)
    assert any(x["id"] == r2_id for x in board["riders"]), "在线骑手应出现在看板"
    call("POST", f"/admin/orders/{no1}/reassign", admin, {"rider_id": r2_id})
    mine = call("GET", "/orders", r2)
    assert any(o["order_no"] == no1 for o in mine), "指定改派应落到目标骑手"
    print("✓ 指定改派:订单落到目标在线骑手名下")

    # 3) PICKED_UP 拒改;超在途上限拒派
    call("POST", f"/orders/{no1}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no1}/transition", r2,
         {"to_status": "picked_up", "verify_code": no1[-4:]})
    err = call("POST", f"/admin/orders/{no1}/reassign", admin,
               {"rider_id": None}, expect_error=True)
    assert err["_error"] == 409 and "取餐" in err["detail"], err
    for _ in range(2):  # r2 已 1 单(picked_up)+ 再抢 2 单 = 3 单在途
        call("POST", f"/riders/grab/{make_order()}", r2)
    no4 = make_order()
    err = call("POST", f"/admin/orders/{no4}/reassign", admin,
               {"rider_id": r2_id}, expect_error=True)
    assert err["_error"] == 409 and "在途" in err["detail"], err
    print("✓ PICKED_UP 拒改派;目标骑手超上限拒派")

    # 4) 看板结构:统计/骑手/池子/在途/热力齐全
    board = call("GET", "/admin/dispatch-overview", admin)
    assert {"stats", "riders", "pool", "in_flight", "heat"} <= set(board)
    assert board["stats"]["in_flight"] >= 3
    assert any(o["order_no"] == no4 for o in board["pool"])
    flight_nos = [o["order_no"] for o in board["in_flight"]]
    assert no1 in flight_nos
    assert all("wait_minutes" in o for o in board["pool"])
    print("✓ 运力看板结构完整,池子/在途/统计口径正确")

    # 5) 非 admin 403
    err = call("GET", "/admin/dispatch-overview", r1, expect_error=True)
    assert err["_error"] == 403, err
    print("✓ 非 admin 403")

    print("\ne2e_reassign 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
