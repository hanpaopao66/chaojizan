"""库存每日回满 + 菜品估清:估清打标/文案区分/撤销恢复/每日任务两类恢复+幂等。"""
import asyncio
import time

from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
ts = int(time.time())

# A:启用每日回满(30);B:普通菜(20,不启用)
dish_a = call("POST", "/merchants/me/dishes", merchant,
              {"name": f"回满菜-{ts}", "price_cents": 2000, "stock": 30,
               "daily_stock": 30})
assert dish_a["daily_stock"] == 30
dish_b = call("POST", "/merchants/me/dishes", merchant,
              {"name": f"估清菜-{ts}", "price_cents": 2000, "stock": 20})
addr = {"address": "测试地址1号", "lat": 30.6612, "lng": 104.0823,
        "contact_name": "测试", "contact_phone": "13800000001"}

# 估清 B:库存清零 + 打标;重复估清 409
b = call("POST", f"/merchants/me/dishes/{dish_b['id']}/sell-out", merchant)
assert b["stock"] == 0 and b["sold_out_today"] is True
err = call("POST", f"/merchants/me/dishes/{dish_b['id']}/sell-out", merchant,
           expect_error=True)
assert err["_error"] == 409
print("✓ 一键估清:库存清零打标,重复估清被拒")

# 下单文案:估清 → 今日已售罄
err = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish_b["id"], "quantity": 1}], **addr,
}, expect_error=True)
assert err["_error"] == 409 and "今日已售罄" in err["detail"], err
print(f"✓ 估清后下单文案:{err['detail']}")

# 撤销估清:恢复估清前库存
b = call("POST", f"/merchants/me/dishes/{dish_b['id']}/sell-out/cancel", merchant)
assert b["stock"] == 20 and b["sold_out_today"] is False
print("✓ 撤销估清:库存恢复到估清前(20)")

# 文案:下架 vs 库存不足
call("PATCH", f"/merchants/me/dishes/{dish_b['id']}", merchant,
     {"is_on_sale": False})
err = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish_b["id"], "quantity": 1}], **addr,
}, expect_error=True)
assert "已下架" in err["detail"], err
call("PATCH", f"/merchants/me/dishes/{dish_b['id']}", merchant,
     {"is_on_sale": True})
err = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish_b["id"], "quantity": 99}], **addr,
}, expect_error=True)
assert "库存不足" in err["detail"], err
print("✓ 下单 409 文案三分:今日已售罄 / 已下架 / 库存不足")

# 手动补库存自动解除估清态
call("POST", f"/merchants/me/dishes/{dish_b['id']}/sell-out", merchant)
b = call("PATCH", f"/merchants/me/dishes/{dish_b['id']}", merchant, {"stock": 15})
assert b["sold_out_today"] is False and b["stock"] == 15
print("✓ 估清后手动补货,估清态自动解除")

# 造场景跑每日任务:A 卖掉 1 份(29),B 再估清(0)
order = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": dish_a["id"], "quantity": 1}], **addr,
})
call("POST", f"/merchants/me/dishes/{dish_b['id']}/sell-out", merchant)


def run_reset() -> tuple:
    async def _run():
        from app.db import SessionLocal, engine
        from app.services.auto_flow import reset_daily_stock
        async with SessionLocal() as db:
            result = await reset_daily_stock(db)
        await engine.dispose()
        return result
    return asyncio.run(_run())


run_reset()
dishes = {d["id"]: d for d in call("GET", "/merchants/me/dishes", merchant)}
a2, b2 = dishes[dish_a["id"]], dishes[dish_b["id"]]
assert a2["stock"] == 30, f"每日回满应到 30,实际 {a2['stock']}"
assert b2["stock"] == 15 and b2["sold_out_today"] is False, \
    f"估清恢复应回 15,实际 {b2['stock']}/{b2['sold_out_today']}"
print("✓ 每日任务:daily_stock 回满(29→30),估清菜恢复估清前值(0→15)")

# 幂等:再跑一次结果不变
run_reset()
dishes = {d["id"]: d for d in call("GET", "/merchants/me/dishes", merchant)}
assert dishes[dish_a["id"]]["stock"] == 30
assert dishes[dish_b["id"]]["stock"] == 15
print("✓ 每日任务连续两次幂等")

# 收尾
call("POST", f"/orders/{order['order_no']}/pay/mock", customer)
call("POST", f"/orders/{order['order_no']}/transition", merchant,
     {"to_status": "cancelled", "reason": "测试收尾"})
for d in (dish_a, dish_b):
    call("PATCH", f"/merchants/me/dishes/{d['id']}", merchant,
         {"is_on_sale": False, "daily_stock": None})
print("\n库存每日回满 + 估清验证通过 🎉")
