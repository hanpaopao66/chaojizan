"""拼单车里的规格和备注。

原来拼单车只存「菜 + 份数」:带必选规格的菜加进车里,到结算页一定被
resolve_options 拒(「请选择份量」),客户端只好不列这种菜;备注也没处写。
现在车里的一行 = (人, 菜, 规格, 备注),规格走和普通下单同一套校验,
单价在服务端按规格加价重算;备注下单时并进订单备注。

在 server/ 目录下运行:python -m tests.e2e_group_cart_options
"""
import time

from tests.util import call, demo_shop, login, register_fresh_customer

merchant = login("13800000002")
sid = demo_shop()["id"]


def main() -> None:
    dish = call("POST", "/merchants/me/dishes", merchant, {
        "name": f"拼单规格菜-{int(time.time())}", "price_cents": 2000, "stock": 50,
        "options": [
            {"name": "份量", "required": True, "multi": False,
             "choices": [{"name": "小份", "delta_cents": 0},
                         {"name": "大份", "delta_cents": 300}]},
            {"name": "加料", "required": False, "multi": True,
             "choices": [{"name": "加蛋", "delta_cents": 200}]},
        ]})
    did = dish["id"]
    owner = register_fresh_customer("拼单规格-发起人")
    buddy = register_fresh_customer("拼单规格-同伴")
    order = None
    try:
        code = call("POST", "/group-carts", owner, {"merchant_id": sid})["code"]
        call("POST", f"/group-carts/{code}/join", buddy)

        def put(who, qty, choices=(), note=""):
            return call("POST", f"/group-carts/{code}/items", who, {
                "dish_id": did, "quantity": qty,
                "choices": list(choices), "note": note})

        # 1) 必选组没选 → 和普通下单同一句话拒掉
        err = call("POST", f"/group-carts/{code}/items", buddy,
                   {"dish_id": did, "quantity": 1}, expect_error=True)
        assert err["_error"] == 422 and "份量" in err["detail"], err
        err = call("POST", f"/group-carts/{code}/items", buddy,
                   {"dish_id": did, "quantity": 1, "choices": ["小份", "大份"]},
                   expect_error=True)
        assert err["_error"] == 422, "单选组选了两项应当拒"
        print("✓ 必选组没选、单选组选两项:422(和普通下单同一套校验)")

        # 2) 规格加价服务端算;同一道菜不同规格 / 不同备注是不同的行
        cart = put(buddy, 1, ["大份", "加蛋"], "不要香菜")
        line = cart["items"][0]
        assert line["price_cents"] == 2500, line  # 2000 + 300 + 200
        assert line["name"].endswith("(大份+加蛋)"), line["name"]
        assert line["choices"] == ["大份", "加蛋"] and line["note"] == "不要香菜"
        cart = put(buddy, 2, ["小份"])
        assert len(cart["items"]) == 2 and cart["total_cents"] == 2500 + 4000
        print("✓ 规格加价在服务端算(¥20 + 大份 3 + 加蛋 2 = ¥25);不同规格各占一行")

        # 3) 份数是某一行的绝对值;规格先后顺序不算不同,0 = 删掉这一行
        cart = put(buddy, 0, ["加蛋", "大份"], "不要香菜")
        assert [i["choices"] for i in cart["items"]] == [["小份"]], cart["items"]
        err = call("POST", f"/group-carts/{code}/items", buddy, {
            "dish_id": did, "quantity": 1, "choices": ["小份"], "note": "字" * 31},
            expect_error=True)
        assert err["_error"] == 422 and "备注" in err["detail"], err
        print("✓ 规格顺序不同也认得出是同一行,0 份删掉;备注超过 30 字 422")

        # 整车备注拼起来有上限:下单时它接在用户自己的备注后面放进 200 字的订单备注,
        # 超了在加菜那一下就说,不等下单时悄悄截掉
        put(buddy, 1, ["大份"], "字" * 30)
        err = call("POST", f"/group-carts/{code}/items", owner, {
            "dish_id": did, "quantity": 1, "choices": ["大份", "加蛋"],
            "note": "字" * 30}, expect_error=True)
        assert err["_error"] == 422 and "加起来" in err["detail"], err
        cart = put(buddy, 0, ["大份"], "字" * 30)
        assert all(not i["note"] for i in cart["items"]), cart["items"]
        print("✓ 整车备注加起来超了:加菜那一下 422,不等下单时截断")

        # 4) 锁单下单:订单按规格计价,备注并进订单备注
        put(buddy, 1, ["大份"], "少放葱")
        call("POST", f"/group-carts/{code}/items", owner, {
            "dish_id": did, "quantity": 1, "choices": ["小份"]})
        cart = call("GET", f"/group-carts/{code}", owner)
        assert cart["total_cents"] == 2000 * 3 + 2300, cart["total_cents"]
        call("POST", f"/group-carts/{code}/lock", owner, {"locked": True})
        order = call("POST", "/orders", owner, {
            "merchant_id": sid,
            "items": [
                {"dish_id": did, "quantity": 3, "choices": ["小份"]},
                {"dish_id": did, "quantity": 1, "choices": ["大份"]},
            ],
            "address": "拼单规格测试地址", "lat": 30.66, "lng": 104.08,
            "remark": "放门口", "group_code": code})
        assert order["food_cents"] == cart["total_cents"], (
            f"订单 {order['food_cents']} 和拼单车合计 {cart['total_cents']} 对不上")
        # 用户自己的备注在前,车里的备注接在后面;只写菜和备注,不写是谁点的
        assert order["remark"] == f"放门口 拼单备注 {dish['name']}(大份):少放葱", \
            order["remark"]
        print(f"✓ 下单:金额和车里一致,备注并进订单 —— 「{order['remark']}」")
    finally:
        if order is not None:
            call("POST", f"/orders/{order['order_no']}/transition", owner,
                 {"to_status": "cancelled", "reason": "测试清场"})
        # 测试菜下架,别留在演示店的菜单里
        call("PATCH", f"/merchants/me/dishes/{did}", merchant, {"is_on_sale": False})

    print("\ne2e_group_cart_options 全部通过 ✅")


if __name__ == "__main__":
    main()
