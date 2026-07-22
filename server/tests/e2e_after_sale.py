"""售后判责体系验证:举证必传、商家责任退餐费、骑手责任平台赔付、
次数风控、恶意售后黑名单。在 server/ 目录下运行:python -m tests.e2e_after_sale
"""
import time

from tests.util import call, login, register_fresh_customer

customer = register_fresh_customer()  # 风控按用户 30 天累计,必须用新账号
merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"售后测试菜-{int(time.time())}", "price_cents": 2000, "stock": 50})

EVIDENCE = ["/uploads/demo-evidence-1.jpg"]


def make_order(token, to_delivered=True):
    order = call("POST", "/orders", token, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", token)
    if to_delivered:
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
        call("POST", f"/riders/grab/{no}", rider)
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
        call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
        call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    return no, order["total_cents"], order["delivery_fee_cents"]


def accept_after_sale(no, reason):
    """申请 + 商家同意,返回订单详情。"""
    call("POST", f"/orders/{no}/after-sale", customer,
         {"reason": reason, "images": EVIDENCE})
    pending = call("GET", "/merchants/me/after-sales?status=pending", merchant)
    target = next(x for x in pending if x["order_no"] == no)
    call("POST", f"/after-sales/{target['id']}/accept", merchant, {"reply": "非常抱歉,退您餐费"})
    return call("GET", f"/orders/{no}", customer)


# 送达前不能申请
no0, _, _ = make_order(customer, to_delivered=False)
err = call("POST", f"/orders/{no0}/after-sale", customer,
           {"reason": "汤洒了一半", "images": EVIDENCE}, expect_error=True)
assert err["_error"] == 409
print(f"✓ 送达前不能申请售后:{err['detail']}")
call("POST", f"/orders/{no0}/transition", customer, {"to_status": "cancelled"})

# 举证必传:没有图片直接 422
no1, total1, fee1 = make_order(customer)
err = call("POST", f"/orders/{no1}/after-sale", customer,
           {"reason": "汤洒了一半,面都坨了"}, expect_error=True)
assert err["_error"] == 422
print("✓ 举证照片必传,无图申请 422")

# 正常申请 → 拒绝(带回复)
a = call("POST", f"/orders/{no1}/after-sale", customer,
         {"reason": "汤洒了一半,面都坨了", "images": EVIDENCE})
assert a["status"] == "pending" and a["images"] == EVIDENCE and a["fault"] == ""
print("✓ 带图申请成功,状态 pending,未判责")

err = call("POST", f"/orders/{no1}/after-sale", customer,
           {"reason": "再来一次", "images": EVIDENCE}, expect_error=True)
assert err["_error"] == 409
print("✓ 一单只能申请一次")

pending = call("GET", "/merchants/me/after-sales?status=pending", merchant)
mine = next(x for x in pending if x["order_no"] == no1)
assert mine["images"] == EVIDENCE, "商家应能看到举证图"
rejected = call("POST", f"/after-sales/{mine['id']}/reject", merchant,
                {"reply": "出餐时完好,建议联系骑手核实"})
assert rejected["status"] == "rejected"
print("✓ 商家可见举证图;拒绝带回复")

# ---- 骑手责任:商家拒绝后,客服仲裁判骑手责 → 平台先行赔付全额(含配送费) ----
admin_list = call("GET", "/admin/after-sales?days=7", admin)
target = next(x for x in admin_list if x["order_no"] == no1)
assert target["images"] == EVIDENCE
r = call("POST", f"/admin/after-sales/{target['id']}/rider-fault", admin,
         {"reason": "举证属实,配送途中餐品受损"})
assert r["refunded_cents"] == total1, "骑手责任应全额赔付(含配送费)"
order1 = call("GET", f"/orders/{no1}", customer)
assert order1["refund_cents"] == total1
assert "平台先行赔付" in order1["refund_note"]
seen = call("GET", f"/orders/{no1}/after-sale", customer)
assert seen["fault"] == "rider" and seen["status"] == "accepted"
print(f"✓ 判骑手责:平台先行赔付全额 ¥{total1/100:.2f}(含配送费 ¥{fee1/100:.2f}),"
      "商家净额与骑手收入不受影响")

# 审计不应对这单报错(商家不冲账是骑手责任单的合法状态)
problems = call("POST", "/admin/audit/run", admin)["detail"]
mine_p = [p for p in problems if no1 in p.get("detail", "")]
assert not mine_p, f"审计对骑手责任单误报:{mine_p}"
print("✓ 审计恒等式对骑手责任单不误报")

# ---- 商家责任:同意 = 退餐费,配送费已履约不退 ----
no2, total2, fee2 = make_order(customer)
call("POST", f"/orders/{no2}/transition", customer, {"to_status": "completed"})
order2 = accept_after_sale(no2, "少送了一份餐具,面里有异物")
assert order2["refund_cents"] == total2 - fee2, (order2["refund_cents"], total2, fee2)
assert "配送费已履约不退" in order2["refund_note"]
print(f"✓ 商家责任:退餐费 ¥{(total2-fee2)/100:.2f},配送费 ¥{fee2/100:.2f} 已履约不退")

# ---- 次数风控:30 天内 3 次成功售后后,新申请被拦 ----
# 已成功 2 次(骑手责任 1 + 商家责任 1),再来 1 次凑满 3 次
no3, _, _ = make_order(customer)
accept_after_sale(no3, "包装破损,汤全洒了")
no4, _, _ = make_order(customer)
err = call("POST", f"/orders/{no4}/after-sale", customer,
           {"reason": "又有问题", "images": EVIDENCE}, expect_error=True)
assert err["_error"] == 409 and "客服" in err["detail"]
print(f"✓ 次数风控:第 4 次申请被拦 → {err['detail']}")

# ---- 恶意售后黑名单 ----
me = call("GET", "/auth/me", customer)
call("POST", f"/admin/users/{me['id']}/after-sale-ban", admin, {"banned": True})
err = call("POST", f"/orders/{no4}/after-sale", customer,
           {"reason": "试试还能不能申请", "images": EVIDENCE}, expect_error=True)
assert err["_error"] == 403
call("POST", f"/admin/users/{me['id']}/after-sale-ban", admin, {"banned": False})
print("✓ 黑名单:禁后自助售后 403(仍可走客服工单),解禁恢复")

# 非商家角色不能处理售后
err = call("GET", "/merchants/me/after-sales", rider, expect_error=True)
assert err["_error"] == 403
print("✓ 非商家角色不能处理售后(403)")

# 清场
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("\n售后判责体系验证通过 🎉")
