"""拼单验证:两账号同车增删同步、锁后加菜 409、只有发起人能下单、
下单原子关车、过期码 404、满减按合车总额算、备注拼单人数。

在 server/ 目录下运行:python -m tests.e2e_group_cart
"""
import asyncio
import time

from tests.util import call, login, register_fresh_customer

merchant = login("13800000002")
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"拼单测试菜-{int(time.time())}", "price_cents": 2500,
             "stock": 50})


async def main():
    owner = register_fresh_customer()
    buddy = register_fresh_customer()

    # 满减按合车总额:单人 2500 不到门槛,两人 5000 过门槛
    old_rules = call("GET", "/merchants/me", merchant)["promo_rules"]
    call("PATCH", "/merchants/me", merchant, {
        "promo_rules": [{"threshold_cents": 4000, "off_cents": 500}]})
    try:
        # 1) 开车、入车、双方加菜实时同步
        cart = call("POST", "/group-carts", owner, {"merchant_id": sid})
        code = cart["code"]
        assert len(code) == 6 and cart["is_owner"]
        cart = call("POST", f"/group-carts/{code}/join", buddy)
        assert not cart["is_owner"] and len(cart["members"]) == 2
        call("POST", f"/group-carts/{code}/items", owner,
             {"dish_id": dish["id"], "quantity": 1})
        cart = call("POST", f"/group-carts/{code}/items", buddy,
                    {"dish_id": dish["id"], "quantity": 2})
        assert len(cart["items"]) == 2 and cart["total_cents"] == 7500
        # 同伴改自己的份数(绝对值),看到的是同一辆车
        cart = call("POST", f"/group-carts/{code}/items", buddy,
                    {"dish_id": dish["id"], "quantity": 1})
        assert cart["total_cents"] == 5000
        view = call("GET", f"/group-carts/{code}", owner)
        assert {i["by"] for i in view["items"]} == \
            {v for v in view["members"].values()}
        print("✓ 开车/入车/增删同步,按人标记")

        # 2) 非成员 403;锁后加菜 409;非发起人锁 403
        outsider = register_fresh_customer()
        err = call("GET", f"/group-carts/{code}", outsider, expect_error=True)
        assert err["_error"] == 403
        err = call("POST", f"/group-carts/{code}/lock", buddy, {},
                   expect_error=True)
        assert err["_error"] == 403
        call("POST", f"/group-carts/{code}/lock", owner, {"locked": True})
        err = call("POST", f"/group-carts/{code}/items", buddy,
                   {"dish_id": dish["id"], "quantity": 3}, expect_error=True)
        assert err["_error"] == 409 and "锁单" in err["detail"], err
        print("✓ 非成员 403,锁后加菜 409")

        # 3) 只有发起人能用车下单;下单原子关车,满减按合计算
        err = call("POST", "/orders", buddy, {
            "merchant_id": sid,
            "items": [{"dish_id": dish["id"], "quantity": 2}],
            "address": "拼单测试地址", "lat": 30.66, "lng": 104.08,
            "group_code": code}, expect_error=True)
        assert err["_error"] == 403, err
        order = call("POST", "/orders", owner, {
            "merchant_id": sid,
            "items": [{"dish_id": dish["id"], "quantity": 2}],
            "address": "拼单测试地址", "lat": 30.66, "lng": 104.08,
            "group_code": code})
        assert order["food_cents"] == 5000
        assert order["discount_cents"] == 500  # 合车过满减门槛
        assert "拼单×2人" in order["promo_note"], order["promo_note"]
        err = call("GET", f"/group-carts/{code}", owner, expect_error=True)
        assert err["_error"] == 404, "下单后车应已关"
        print("✓ 发起人下单原子关车,满减按合车总额生效,备注带人数")

        # 4) 过期/不存在的码 404
        err = call("POST", "/group-carts/000000/join", buddy,
                   expect_error=True)
        assert err["_error"] == 404
        print("✓ 过期码 404")

        # 清场:关掉未支付的拼单订单
        call("POST", f"/orders/{order['order_no']}/transition", owner,
             {"to_status": "cancelled", "reason": "测试清场"})
    finally:
        call("PATCH", "/merchants/me", merchant, {"promo_rules": old_rules})

    print("\ne2e_group_cart 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
