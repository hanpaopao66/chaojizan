"""云端购物车持久化 + 我常买(清单#56)。

再来一单已是客户端行为(读历史单重建),这里验证服务端两块:
购物车跨 token 续用 + 常买聚合(近90天≥2单出现的在售菜)。
"""
import random
import time

from tests.util import call, login


def sms_login(phone):
    """同一手机号可反复登录拿新 token(模拟换设备)。"""
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login",
                body={"phone": phone, "code": code})["token"]

merchant = login("13800000002")
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
ts = int(time.time())
d1 = call("POST", "/merchants/me/dishes", merchant,
          {"name": f"常买主菜-{ts}", "price_cents": 2000, "stock": 200})
d2 = call("POST", "/merchants/me/dishes", merchant,
          {"name": f"偶买菜-{ts}", "price_cents": 1500, "stock": 200})

# 新注册用户,避开风控与历史脏数据
phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
customer = sms_login(phone)  # 首次登录即注册

# ---- 云端购物车:存 → 换 token 取仍在 ----
call("PUT", f"/cart/{shop['id']}", customer, {"items": [
    {"dish_id": d1["id"], "quantity": 2, "choices": []},
    {"dish_id": d2["id"], "quantity": 1, "choices": []},
]})
customer2 = call("POST", "/auth/refresh", customer)["token"]  # 换设备=新会话 token
got = call("GET", f"/cart/{shop['id']}", customer2)
assert len(got["items"]) == 2
assert {it["dish_id"] for it in got["items"]} == {d1["id"], d2["id"]}
print("✓ 购物车云端持久化:换 token 仍能取回")

# 清空
call("PUT", f"/cart/{shop['id']}", customer2, {"items": []})
assert call("GET", f"/cart/{shop['id']}", customer2)["items"] == []
print("✓ 清空购物车(空 items 删除该店车)")

# 不存在商家 404
err = call("PUT", "/cart/99999999", customer2,
           {"items": [{"dish_id": d1["id"], "quantity": 1}]},
           expect_error=True)
assert err["_error"] == 404
print("✓ 保存到不存在商家 404")

# ---- 我常买:近90天完成单出现≥2次的在售菜 ----
addr = {"address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "测试", "contact_phone": phone}


def complete_order(dish_id):
    o = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish_id, "quantity": 1}], **addr})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    for st in ("accepted", "ready"):
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": st})
    rider = login("13800000003")
    call("POST", f"/riders/grab/{no}", rider)
    for st in ("picked_up", "delivered"):
        call("POST", f"/orders/{no}/transition", rider, {"to_status": st})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})


# d1 买两单(达常买阈值),d2 只买一单(不达)
complete_order(d1["id"])
freq = call("GET", f"/merchants/{shop['id']}/frequent-dishes", customer)
assert all(d["id"] != d1["id"] for d in freq), "只买过 1 单不该进常买"
complete_order(d1["id"])
freq = call("GET", f"/merchants/{shop['id']}/frequent-dishes", customer)
assert any(d["id"] == d1["id"] for d in freq), "买过 2 单应进常买"
assert all(d["id"] != d2["id"] for d in freq), "只买 1 单的不进"
print("✓ 我常买:≥2 单出现才入常买,1 单的不入")

# 下架后常买自动消失(只回在售)
call("PATCH", f"/merchants/me/dishes/{d1['id']}", merchant, {"is_on_sale": False})
freq = call("GET", f"/merchants/{shop['id']}/frequent-dishes", customer)
assert all(d["id"] != d1["id"] for d in freq), "下架的菜不该出现在常买"
print("✓ 下架菜自动从常买消失(只回在售)")

call("PATCH", f"/merchants/me/dishes/{d2['id']}", merchant, {"is_on_sale": False})
print("\n云端购物车 + 我常买验证通过 🎉")
