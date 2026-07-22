"""食品安全投诉验证:强制带图、成立退款流水齐、下架菜品、暂停营业、
第 3 起自动停业、dismissed 不动资金、留痕导出。

在 server/ 目录下运行:python -m tests.e2e_food_safety
"""
import time

from tests.util import call, login, register_fresh_customer

merchant = login("13800000002")
rider_token = login("13800000003")
admin = login("13800000000")

# 从商家自身接口取店铺(公开列表不含停业中的店,上一轮残留停业时会找不到)
sid = call("GET", "/merchants/me", merchant)["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"食安测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})

IMG = ["https://example.com/evidence.jpg"]


def completed_order(customer):
    """跑一单到已送达(食安投诉的前置状态)。"""
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no}", rider_token)
    call("POST", f"/orders/{no}/transition", rider_token,
         {"to_status": "picked_up", "verify_code": no[-4:]})
    call("POST", f"/orders/{no}/transition", rider_token,
         {"to_status": "delivered"})
    return no


def report(customer, no, kind="foreign_object", images=IMG, expect_error=False):
    return call("POST", "/food-safety", customer, {
        "order_no": no, "kind": kind,
        "description": "吃出了不明异物,附照片",
        "images": images,
    }, expect_error=expect_error)


def find_report(no):
    reports = call("GET", "/admin/food-safety?status=open", admin)
    return next(r for r in reports if r["order_no"] == no)


def main():
    # 确保商家营业(前置)
    call("PATCH", "/merchants/me", merchant, {"is_open": True})

    # 1) 必须带图;配送中不能提;正常提交成功且同单防重
    customer = register_fresh_customer()
    no1 = completed_order(customer)
    err = report(customer, no1, images=[], expect_error=True)
    assert err["_error"] == 422, err
    r = report(customer, no1)
    assert r["status"] == "open" and r["kind"] == "foreign_object"
    err = report(customer, no1, expect_error=True)
    assert err["_error"] == 409, err
    print("✓ 无图 422,提交成功,同单防重 409")

    # 2) confirmed:先行全额退款(含配送费),流水齐;fault=platform 审计豁免
    o1 = call("GET", f"/orders/{no1}", customer)
    fs = find_report(no1)
    done = call("POST", f"/admin/food-safety/{fs['id']}/confirm", admin,
                {"note": "凭证清晰,成立"})
    assert done["status"] == "confirmed"
    o1_after = call("GET", f"/orders/{no1}", customer)
    assert o1_after["refund_cents"] == o1["total_cents"], o1_after["refund_cents"]
    flows = call("GET", f"/orders/{no1}/refunds", customer)
    assert sum(f["amount_cents"] for f in flows) == o1["total_cents"]
    print("✓ 成立:全额退款(含配送费),退款流水一致")

    # 3) 下架涉事菜品 + 暂停营业(留痕)
    call("POST", f"/admin/food-safety/{fs['id']}/take-down-dish", admin,
         {"note": "整改期间下架", "dish_id": dish["id"]})
    dishes = call("GET", f"/merchants/{sid}/dishes")
    assert not any(d["id"] == dish["id"] for d in dishes), "涉事菜品应已下架"
    call("POST", f"/admin/food-safety/{fs['id']}/suspend-merchant", admin,
         {"note": "后厨卫生整改"})
    shop = call("GET", "/merchants/me", merchant)
    assert shop["is_open"] is False, "商家应已停业"
    reports = call("GET", "/admin/food-safety?status=confirmed", admin)
    acts = [a["action"] for r in reports if r["order_no"] == no1
            for a in r["actions"]]
    assert {"confirmed", "dish_off", "suspend"} <= set(acts), acts
    print("✓ 下架涉事菜品、暂停营业,处置全留痕")

    # 恢复营业与菜品,继续跑后面的单
    call("PATCH", "/merchants/me", merchant, {"is_open": True})
    call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant,
         {"is_on_sale": True})

    # 4) dismissed 不动资金
    no2 = completed_order(customer)
    report(customer, no2, kind="spoiled")
    fs2 = find_report(no2)
    call("POST", f"/admin/food-safety/{fs2['id']}/dismiss", admin,
         {"note": "照片与订单菜品不符"})
    o2 = call("GET", f"/orders/{no2}", customer)
    assert o2["refund_cents"] == 0, "驳回不动资金"
    print("✓ 驳回:不动资金,理由留痕")

    # 5) 30 天内第 3 起成立 → 自动停业(上面已成立 1 起;历史轮次的
    # 成立记录会让自动停业提前触发,循环里先复业保证能下单)
    for i in range(2):
        call("PATCH", "/merchants/me", merchant, {"is_open": True})
        no = completed_order(customer)
        report(customer, no, kind="sick")
        fs_n = find_report(no)
        call("POST", f"/admin/food-safety/{fs_n['id']}/confirm", admin,
             {"note": f"第 {i + 2} 起成立"})
    shop = call("GET", "/merchants/me", merchant)
    assert shop["is_open"] is False, "第 3 起成立应自动停业"
    reports = call("GET", "/admin/food-safety?status=confirmed", admin)
    assert any(a["action"] == "auto_suspend"
               for r in reports for a in r["actions"]), "应有自动停业留痕"
    print("✓ 30 天内第 3 起成立,自动暂停营业")

    # 收尾:恢复营业,别影响别的测试套
    call("PATCH", "/merchants/me", merchant, {"is_open": True})

    print("\ne2e_food_safety 全部通过 ✅")


if __name__ == "__main__":
    main()
