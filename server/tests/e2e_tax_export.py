"""税务导出:三份月度 CSV 的表头与金额口径(含冲账抵减),非 admin 403。
造一单完成 + 一笔售后冲账,验证平台收入按净口径、骑手/商家汇总与钱包同源。
在 server/ 目录下运行:python -m tests.e2e_tax_export
"""
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from tests.util import BASE, orderable_dish, call, login

merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")

# 新用户跑售后(演示用户有 30 天 3 次风控上限)
customer = call("POST", "/auth/register",
                body={"phone": f"137{int(time.time()) % 100000000:08d}",
                      "password": "123456", "name": "税表测试用户",
                      "role": "customer"})["token"]

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dishes = call("GET", f"/merchants/{shop['id']}/dishes")
main_dish = orderable_dish(dishes)

now = datetime.now(ZoneInfo("Asia/Shanghai"))
PERIOD = f"{now.year:04d}-{now.month:02d}"


def fetch_csv(kind, token, period=PERIOD):
    req = urllib.request.Request(
        f"{BASE}/admin/tax/{kind}.csv?period={period}",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


# 非 admin 403
status, _ = fetch_csv("platform-income", merchant)
assert status == 403
print("✓ 非管理员无法导出税表(403)")

# 基线
_, csv0 = fetch_csv("platform-income", admin)
base_total = csv0.strip().splitlines()[-1].split(",")[4]

# 完成一单 → 佣金入表;再售后冲账 → 佣金被负数行抵减
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

_, csv1 = fetch_csv("platform-income", admin)
lines = csv1.strip().splitlines()
assert lines[0].lstrip("﻿") == "日期,类型,单号,商家,平台收入(元),备注"
row = next(x for x in lines if no in x)
assert "外卖佣金" in row and f"{paid['commission_cents'] / 100:.2f}" in row
total_after_order = float(lines[-1].split(",")[4])
assert abs(total_after_order - float(base_total)
           - paid["commission_cents"] / 100) < 0.001
print(f"✓ 平台收入明细:该单佣金 {paid['commission_cents'] / 100:.2f} 入表,合计精确增加")

# 售后冲账 → 佣金负数行抵减(净口径)
a = call("POST", f"/orders/{no}/after-sale", customer,
         {"reason": "税表冲账测试", "images": ["/uploads/demo.jpg"]})
call("POST", f"/after-sales/{a['id']}/accept", merchant, {"reply": "退餐费"})
_, csv2 = fetch_csv("platform-income", admin)
lines2 = csv2.strip().splitlines()
assert sum(1 for x in lines2 if no in x) == 2, "冲账负数行也应逐笔可见"
total_after_reversal = float(lines2[-1].split(",")[4])
assert abs(total_after_reversal - float(base_total)) < 0.001, \
    "冲账后该单佣金归零,合计回到基线(净口径)"
print("✓ 售后冲账逐笔可见,合计自动抵减(净口径)")

# 骑手所得汇总:含骑手行,配送费≥该单
_, rcsv = fetch_csv("rider-income", admin)
rlines = rcsv.strip().splitlines()
assert rlines[0].lstrip("﻿") == "骑手,手机号,当月配送费收入(元),完成单数,当月已打款(元)"
rrow = next(x for x in rlines if "13800000003" in x)
assert float(rrow.split(",")[2]) >= paid["delivery_fee_cents"] / 100
print("✓ 骑手所得汇总:按人聚合,配送费口径正确")

# 商家结算汇总:表头 + 含本店行
_, mcsv = fetch_csv("merchant-settlement", admin)
mlines = mcsv.strip().splitlines()
assert mlines[0].lstrip("﻿") == "商家,店主手机号,外卖净额(元),团购净额(元),当月已打款提现(元)"
assert any("张记面馆" in x for x in mlines)
print("✓ 商家结算汇总:按店聚合,含外卖/团购/提现三列")

# 非法月份
status, _ = fetch_csv("platform-income", admin, period="2026-13")
assert status == 422
print("✓ 非法月份 422")

print("\n税务导出验证通过 🎉")

# 佣金开票依据(#48):按商家汇总,与 merchant_earnings 佣金合计一致
import asyncio as _asyncio


async def _check_commission_invoice():
    from sqlalchemy import text as _sql

    from app.db import SessionLocal
    _, ccsv = fetch_csv("commission-invoice", admin)
    clines = ccsv.strip().splitlines()
    assert clines[0].lstrip("﻿") == "商家,外卖佣金(元),团购服务费(元),合计(元),发票抬头,税号"
    crow = next(x for x in clines if "张记面馆" in x)
    csv_commission = float(crow.split(",")[1])
    async with SessionLocal() as db:
        db_commission = (await db.execute(_sql(
            """SELECT coalesce(sum(me.commission_cents), 0)
               FROM merchant_earnings me
               JOIN merchants m ON m.id = me.merchant_id
               WHERE m.name = '张记面馆'
                 AND me.created_at >= date_trunc('month', now() AT TIME ZONE
                     'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'"""
        ))).scalar()
    assert abs(csv_commission - db_commission / 100) < 0.005, \
        (csv_commission, db_commission)


_asyncio.run(_check_commission_invoice())
status, _ = fetch_csv("commission-invoice", merchant)
assert status == 403
print("✓ 佣金开票依据 CSV:与 merchant_earnings 佣金合计一致,非 admin 403")

print("税务口径(#48)验证通过 ✅")
