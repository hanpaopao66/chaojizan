"""平台服务费发票:月度聚合口径(佣金+团购费,冲账抵减)、只开已结束月份、
一月一张、开票回填链接、驳回可重申。
在 server/ 目录下运行:python -m tests.e2e_invoice
"""
import asyncio
from datetime import datetime

from sqlalchemy import text
from zoneinfo import ZoneInfo

from app.db import SessionLocal, engine
from tests.util import orderable_dish, call, login

customer = login("13800000001")
merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dishes = call("GET", f"/merchants/{shop['id']}/dishes")
main_dish = orderable_dish(dishes)

now = datetime.now(ZoneInfo("Asia/Shanghai"))
last = datetime(now.year, now.month - 1, 1) if now.month > 1 \
    else datetime(now.year - 1, 12, 1)
PERIOD = f"{last.year:04d}-{last.month:02d}"
THIS = f"{now.year:04d}-{now.month:02d}"


async def cleanup_and(sql, params=None):
    async with SessionLocal() as db:
        await db.execute(text(sql), params or {})
        await db.commit()
    await engine.dispose()


# 幂等:清掉本店该月的历史申请(测试可重复跑)
asyncio.run(cleanup_and(
    "DELETE FROM invoice_requests WHERE merchant_id = :mid AND period = :p",
    {"mid": shop["id"], "p": PERIOD}))

s0 = call("GET", f"/invoices/summary?period={PERIOD}", merchant)
assert s0["period_ended"] is True and s0["requested"] is False

# 完成一单,把入账行回拨到上个月 → 聚合金额应精确增加该单佣金
order = call("POST", "/orders", customer, {
    "merchant_id": shop["id"],
    "items": [{"dish_id": main_dish["id"], "quantity": 1}],
    "address": "测试地址", "lat": 30.66, "lng": 104.08,
})
no = order["order_no"]
paid = call("POST", f"/orders/{no}/pay/mock", customer)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
call("POST", f"/riders/grab/{no}", rider)
call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
asyncio.run(cleanup_and(
    "UPDATE merchant_earnings SET created_at = "
    f"('{PERIOD}-15 04:00:00'::timestamp AT TIME ZONE 'Asia/Shanghai') "
    "WHERE order_no = :no", {"no": no}))
s1 = call("GET", f"/invoices/summary?period={PERIOD}", merchant)
assert s1["commission_cents"] == s0["commission_cents"] + paid["commission_cents"], (s0, s1)
assert s1["total_cents"] == s1["commission_cents"] + s1["voucher_fee_cents"]
print(f"✓ 月度聚合:上月服务费 +{paid['commission_cents'] / 100:.2f}(该单佣金)")

# 当月不能开
err = call("POST", "/invoices", merchant,
           {"period": THIS, "title": "成都张记面馆餐饮有限公司",
            "tax_no": "91510100MA6C000X0Q", "email": "zhangji@example.com"},
           expect_error=True)
assert err["_error"] == 422 and "已结束" in err["detail"]
print(f"✓ 当月不能开票:{err['detail']}")

# 金额为 0 的远古月份不能开
err = call("POST", "/invoices", merchant,
           {"period": "2020-01", "title": "成都张记面馆餐饮有限公司",
            "tax_no": "91510100MA6C000X0Q", "email": "zhangji@example.com"},
           expect_error=True)
assert err["_error"] == 422 and "0" in err["detail"]

# 正常申请:金额 = 聚合快照,抬头存回商家资料
inv = call("POST", "/invoices", merchant,
           {"period": PERIOD, "title": "成都张记面馆餐饮有限公司",
            "tax_no": "91510100MA6C000X0Q", "email": "zhangji@example.com"})
assert inv["amount_cents"] == s1["total_cents"] and inv["status"] == "pending"
err = call("POST", "/invoices", merchant,
           {"period": PERIOD, "title": "成都张记面馆餐饮有限公司",
            "tax_no": "91510100MA6C000X0Q", "email": "zhangji@example.com"},
           expect_error=True)
assert err["_error"] == 409
s2 = call("GET", f"/invoices/summary?period={PERIOD}", merchant)
assert s2["requested"] is True and s2["title"] == "成都张记面馆餐饮有限公司"
print("✓ 申请成功(金额=系统聚合),重复申请被拒,抬头已存档")

# 管理端开票 → 商家可见下载链接
pending = call("GET", "/admin/invoices?status=pending", admin)
mine = next(x for x in pending if x["id"] == inv["id"])
assert mine["merchant_name"] == "张记面馆"
call("POST", f"/admin/invoices/{inv['id']}/issue", admin,
     {"file_url": "/uploads/invoice-demo.pdf", "note": "电子普票"})
records = call("GET", "/invoices/mine", merchant)
rec = next(x for x in records if x["id"] == inv["id"])
assert rec["status"] == "issued" and rec["file_url"] == "/uploads/invoice-demo.pdf"
print("✓ 开票完成,商家端可见文件链接")

# 已开票不能再处理;驳回路径:重新造一张 → 驳回 → 可重申
err = call("POST", f"/admin/invoices/{inv['id']}/reject", admin,
           {"reason": "重复处理"}, expect_error=True)
assert err["_error"] == 409
asyncio.run(cleanup_and(
    "DELETE FROM invoice_requests WHERE merchant_id = :mid AND period = :p",
    {"mid": shop["id"], "p": PERIOD}))
inv2 = call("POST", "/invoices", merchant,
            {"period": PERIOD, "title": "成都张记面馆餐饮有限公司",
             "tax_no": "91510100MA6C000X0Q", "email": "zhangji@example.com"})
call("POST", f"/admin/invoices/{inv2['id']}/reject", admin,
     {"reason": "税号疑似有误,请核对"})
inv3 = call("POST", "/invoices", merchant,
            {"period": PERIOD, "title": "成都张记面馆餐饮有限公司",
             "tax_no": "91510100MA6C000X0Q", "email": "zhangji@example.com"})
assert inv3["status"] == "pending"
print("✓ 驳回即释放该月名额,商家修正后可重新申请")

print("\n平台服务费发票验证通过 🎉")
