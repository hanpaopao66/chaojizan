"""食品安全投诉验证:强制带图、成立退款流水齐、下架菜品、暂停营业、
第 3 起自动停业、dismissed 不动资金、留痕导出。

2026-09-14 起投诉成立**由商家承担退款**(原来平台先垫全额、不冲商家账):
退的是餐费(实付 − 配送费 − 小费,配送费、小费已付给骑手),这单商家净额冲回;
记一条售后判商家责任、扣店主信用分;商家 72 小时内可以申诉,改判成立只撤销判责、钱不动,
这一起也不再计入自动停业的计数。还没确认收货的单先按完成结算再冲。账务自检全绿。

在 server/ 目录下运行:python -m tests.e2e_food_safety
"""
import asyncio
import time

from app.db import engine
from tests.util import (audit_new_problems, audit_snapshot, call, login,
                        register_fresh_customer)

merchant = login("13800000002")
rider_token = login("13800000003")
admin = login("13800000000")

# 从商家自身接口取店铺(公开列表不含停业中的店,上一轮残留停业时会找不到)
sid = call("GET", "/merchants/me", merchant)["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"食安测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})

IMG = ["https://example.com/evidence.jpg"]


def run_async(make):
    """这个用例是同步的:每次 asyncio.run 之后把连接池放掉,不然下一次换了事件循环会串台。"""
    async def _go():
        try:
            return await make()
        finally:
            await engine.dispose()
    return asyncio.run(_go())


def clear_food_safety_hold():
    """清掉可能残留的食安停业闸门。

    这条闸门是「暂停营业待人工复核」的执行机制:置位后商家自己开不回来,
    只能由平台复核解除。所以本套件里每次要复业之前都得先解一次 ——
    上一轮跑挂了留下的闸门,也会让这次从第一步就 403。
    """
    shop_id = call("GET", "/merchants/me", merchant)["id"]
    call("POST", f"/admin/merchants/{shop_id}/food-safety-hold/release",
         admin, {"note": "测试复业"}, expect_error=True)


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
    clear_food_safety_hold()   # 上一轮跑挂留下的闸门会让这次从头 403
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

    # 2) confirmed:商家承担餐费退款(配送费、小费归骑手不退),这单净额冲回、记商家责任。
    #    这一单还没确认收货(送达就提的投诉):先按完成结算再冲,平台一分不出
    audit_before = run_async(audit_snapshot)
    o1 = call("GET", f"/orders/{no1}", customer)
    assert o1["status"] == "delivered", o1["status"]
    w0 = call("GET", "/merchants/me/wallet", merchant)
    fs = find_report(no1)
    done = call("POST", f"/admin/food-safety/{fs['id']}/confirm", admin,
                {"note": "凭证清晰,成立"})
    assert done["status"] == "confirmed"
    o1_after = call("GET", f"/orders/{no1}", customer)
    food_part = o1["total_cents"] - o1["delivery_fee_cents"] - o1["tip_cents"]
    assert o1_after["refund_cents"] == food_part, (o1_after["refund_cents"], food_part)
    assert o1_after["status"] == "completed", o1_after["status"]
    flows = call("GET", f"/orders/{no1}/refunds", customer)
    assert sum(f["amount_cents"] for f in flows) == food_part
    w1 = call("GET", "/merchants/me/wallet", merchant)
    assert w1["total_earned_cents"] == w0["total_earned_cents"], \
        f"商家这单的净额没冲回(平台在出钱):{w0['total_earned_cents']} → {w1['total_earned_cents']}"
    a1 = next(a for a in call("GET", "/merchants/me/after-sales", merchant)
              if a["order_no"] == no1)
    assert a1["status"] == "accepted" and a1["fault"] == "merchant", a1
    problems = run_async(lambda: audit_new_problems(audit_before, no1))
    assert not problems, problems
    print(f"✓ 成立:退餐费 {food_part} 分(配送费、小费归骑手不退),商家承担(结算后冲回),"
          "记商家责任;账务自检全绿")

    # 店主信用分记一条「食安投诉成立」;商家可以申诉,改判只撤销判责、钱不动
    got = call("GET", "/credit/me", merchant)
    row = next((d for d in got["deductions"]
                if d["kind"] == "after_sale_fault" and d["record_id"] == a1["id"]), None)
    assert row and "食品安全" in row["title"], got["deductions"]
    assert row["appeal"]["target_type"] == "after_sale", row["appeal"]
    ap = call("POST", "/appeals", merchant,
              {"target_type": "after_sale", "target_id": a1["id"],
               "reason": "后厨监控显示出餐时没有异物(申诉测试)"})
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:监控可证出餐无异物"})
    w2 = call("GET", "/merchants/me/wallet", merchant)
    assert w2["total_earned_cents"] == w1["total_earned_cents"], "改判又补回了净额(平台出钱)"
    a1b = next(a for a in call("GET", "/merchants/me/after-sales", merchant)
               if a["order_no"] == no1)
    assert a1b["fault"] == "cleared", a1b
    got = call("GET", "/credit/me", merchant)
    assert not any(d["kind"] == "after_sale_fault" and d["record_id"] == a1["id"]
                   for d in got["deductions"]), "改判成立了还在扣分"
    print("✓ 店主信用分记了这一条;商家申诉改判成立:判责撤销、不再扣分,净额不补回")

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

    # 恢复营业与菜品,继续跑后面的单。
    # **必须先由平台解除食安闸门** —— 停业期间商家自己开不回来,
    # 这正是"暂停营业待人工复核"的执行机制(见 merchants.update_my_shop)
    err = call("PATCH", "/merchants/me", merchant, {"is_open": True},
               expect_error=True)
    assert err["_error"] == 403 and "食品安全" in err["detail"], err
    print(f"✓ 停业期间商家自己开不回来:{err['detail']}")
    call("POST", f"/admin/merchants/{shop['id']}/food-safety-hold/release",
         admin, {"note": "整改材料已核验"})
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

    # 5) 30 天内第 3 起成立 → 自动停业。上面那一起被商家申诉改判了,**不算** ——
    #    再成立 3 起才停业。历史轮次的成立记录会让自动停业提前触发,循环里先复业保证能下单
    from datetime import datetime, timedelta, timezone
    month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    counted_before = sum(
        1 for r in call("GET", "/admin/food-safety?status=confirmed", admin)
        if r["merchant_id"] == sid
        and datetime.fromisoformat(r["created_at"]) > month_ago
        and not any(a["action"] == "appeal_overturned" for a in r["actions"]))
    for i in range(3):
        # 前一轮可能已触发自动停业:闸门不解,商家自己开不回来
        clear_food_safety_hold()
        call("PATCH", "/merchants/me", merchant, {"is_open": True})
        no = completed_order(customer)
        report(customer, no, kind="sick")
        fs_n = find_report(no)
        call("POST", f"/admin/food-safety/{fs_n['id']}/confirm", admin,
             {"note": f"第 {i + 1} 起成立"})
        if i == 1 and counted_before == 0:
            shop = call("GET", "/merchants/me", merchant)
            assert shop["is_open"] is True, \
                "改判成立的那一起还算进了自动停业的计数(只成立了 2 起就停业了)"
    shop = call("GET", "/merchants/me", merchant)
    assert shop["is_open"] is False, "第 3 起成立应自动停业"
    reports = call("GET", "/admin/food-safety?status=confirmed", admin)
    assert any(a["action"] == "auto_suspend"
               for r in reports for a in r["actions"]), "应有自动停业留痕"
    print("✓ 30 天内第 3 起成立,自动暂停营业")

    # 收尾:解闸门 + 恢复营业,别影响别的测试套
    clear_food_safety_hold()
    call("PATCH", "/merchants/me", merchant, {"is_open": True})

    print("\ne2e_food_safety 全部通过 ✅")


if __name__ == "__main__":
    main()
