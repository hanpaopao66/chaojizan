"""满赠全链路:配置校验 → 达标出赠品行(0 元,不计佣) → 缺货自动失效 → 赠品行不可退。"""
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
addr = {"address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "测试", "contact_phone": "13800000001"}

ts = int(time.time())
main = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"满赠主菜-{ts}", "price_cents": 2000, "stock": 50})
cola = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"满赠可乐-{ts}", "price_cents": 300, "stock": 50})

# 赠品必须是本店在售菜品:瞎填 id 被拒
err = call("PATCH", "/merchants/me", merchant, {
    "gift_rules": [{"threshold_cents": 3000, "dish_id": 99999999}],
}, expect_error=True)
assert err["_error"] == 422
me = call("PATCH", "/merchants/me", merchant, {
    "gift_rules": [{"threshold_cents": 3000, "dish_id": cola["id"]}],
})
assert me["gift_rules"][0]["name"] == cola["name"], "名字快照应以库里为准"
print(f"✓ 满赠配置成功(满30赠{cola['name']}),乱填赠品被拒")

# 不满门槛:没有赠品行
o1 = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": main["id"], "quantity": 1}], **addr})
assert all(i["price_cents"] > 0 for i in o1["items"])
print("✓ 未达门槛无赠品行")

# 达标:出现 0 元赠品行,food/total/佣金全不含赠品
o2 = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": main["id"], "quantity": 2}], **addr})
gift_lines = [i for i in o2["items"] if i["price_cents"] == 0]
assert len(gift_lines) == 1
assert gift_lines[0]["name"] == f"[赠]{cola['name']}"
assert gift_lines[0]["quantity"] == 1
assert o2["food_cents"] == 4000, "菜品金额不含赠品"
assert o2["total_cents"] == (o2["food_cents"] + o2["packing_fee_cents"]
                             - o2["discount_cents"] - o2["subsidy_cents"]
                             + o2["delivery_fee_cents"])
assert f"赠{cola['name']}" in o2["promo_note"]
print(f"✓ 满 30 出赠品行 [赠]{cola['name']} ¥0,金额口径零影响")

# 赠品照常扣库存
stock_after = next(d for d in call("GET", "/merchants/me/dishes", merchant)
                   if d["id"] == cola["id"])["stock"]
assert stock_after == 49, f"赠品应扣库存,实际 {stock_after}"
print("✓ 赠品扣库存(50→49)")

# 赠品行不可缺货退款(0 元无款可退)
call("POST", f"/orders/{o2['order_no']}/pay/mock", customer)
err = call("POST", f"/orders/{o2['order_no']}/refund-item", merchant,
           {"dish_id": cola["id"], "quantity": 1}, expect_error=True)
assert err["_error"] == 422
print(f"✓ 赠品行不可缺货退款:{err['detail']}")

# 付费菜全退光 = 整单取消,赠品库存一并回补
done = call("POST", f"/orders/{o2['order_no']}/refund-item", merchant,
            {"dish_id": main["id"], "quantity": 2})
assert done["status"] == "cancelled"
assert done["refund_cents"] > 0
stock_back = next(d for d in call("GET", "/merchants/me/dishes", merchant)
                  if d["id"] == cola["id"])["stock"]
assert stock_back == 50, f"整单取消赠品应回补,实际 {stock_back}"
print("✓ 付费菜退光整单取消,赠品库存回补(49→50)")

# 赠品没库存:下单照常成功,只是没有赠品行,promo_note 注明
call("PATCH", f"/merchants/me/dishes/{cola['id']}", merchant, {"stock": 0})
o3 = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": main["id"], "quantity": 2}], **addr})
assert all(i["price_cents"] > 0 for i in o3["items"])
assert "已送完" in o3["promo_note"]
print("✓ 赠品无库存不拦下单,自动跳过并注明已送完")

# 两档取最高:再加一档满 60 赠主菜,买 4 份(80 元)应赠主菜而非可乐
call("PATCH", f"/merchants/me/dishes/{cola['id']}", merchant, {"stock": 10})
call("PATCH", "/merchants/me", merchant, {
    "gift_rules": [
        {"threshold_cents": 3000, "dish_id": cola["id"]},
        {"threshold_cents": 6000, "dish_id": main["id"]},
    ],
})
o4 = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": main["id"], "quantity": 4}], **addr})
gifts = [i for i in o4["items"] if i["price_cents"] == 0]
assert len(gifts) == 1 and gifts[0]["name"] == f"[赠]{main['name']}"
print("✓ 两档只取满足门槛的最高一档")

# 清理:关活动、下架测试菜
call("PATCH", "/merchants/me", merchant, {"gift_rules": []})
call("PATCH", f"/merchants/me/dishes/{main['id']}", merchant, {"is_on_sale": False})
call("PATCH", f"/merchants/me/dishes/{cola['id']}", merchant, {"is_on_sale": False})
print("\n满赠活动验证通过 🎉")
