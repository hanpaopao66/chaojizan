"""订单取消规则分级:接单前随时、接单后 2 分钟反悔、超窗关闭、
预约单放宽到预约前 1 小时、出餐后禁止;取消均全额退款。
在 server/ 目录下运行:python -m tests.e2e_cancel_rules
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import SessionLocal, engine
from tests.util import call, login

merchant = login("13800000002")
customer = call("POST", "/auth/register",
                body={"phone": f"136{int(time.time()) % 100000000:08d}",
                      "password": "123456", "name": "取消规则测试",
                      "role": "customer"})["token"]

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
# 专属菜品:今天的测试把演示菜库存吃光了,自建不受干扰
main_dish = call("POST", "/merchants/me/dishes", merchant,
                 {"name": f"取消规则菜-{int(time.time())}",
                  "price_cents": 2000, "stock": 50})


def make_order(accept=False, scheduled_at=None):
    body = {
        "merchant_id": shop["id"],
        "items": [{"dish_id": main_dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    }
    if scheduled_at:
        body["scheduled_at"] = scheduled_at
    order = call("POST", "/orders", customer, body)
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    if accept:
        call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    return no


async def backdate_accept(no, minutes):
    async with SessionLocal() as db:
        await db.execute(text(
            f"UPDATE orders SET accepted_at = now() - interval '{minutes} minutes' "
            "WHERE order_no = :no"), {"no": no})
        await db.commit()
    await engine.dispose()


def cancel(no, expect_error=False):
    return call("POST", f"/orders/{no}/transition", customer,
                {"to_status": "cancelled", "reason": "点错了/重新下单"},
                expect_error=expect_error)


# 1) 接单前随时可取消,全额退款
no1 = make_order()
o1 = cancel(no1)
assert o1["status"] == "cancelled" and o1["refund_cents"] == o1["total_cents"]
assert o1["cancel_reason"] == "点错了/重新下单"
print("✓ 接单前取消:随时免费,原因落库,全额退款")

# 2) 接单后 2 分钟内可反悔
no2 = make_order(accept=True)
o2 = cancel(no2)
assert o2["status"] == "cancelled" and o2["refund_cents"] == o2["total_cents"]
print("✓ 接单后 2 分钟反悔窗口内取消成功")

# 3) 超过 2 分钟自助取消关闭
no3 = make_order(accept=True)
asyncio.run(backdate_accept(no3, 5))
err = cancel(no3, expect_error=True)
assert err["_error"] == 403 and "备餐" in err["detail"]
print(f"✓ 超窗被拒:{err['detail']}")

# 4) 预约单放宽:预约 3 小时后送达,接单 5 分钟后仍可取消
sched = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
no4 = make_order(accept=True, scheduled_at=sched)
asyncio.run(backdate_accept(no4, 5))
o4 = cancel(no4)
assert o4["status"] == "cancelled"
print("✓ 预约单在预约前 1 小时外可取消(商家还没开始做)")

# 5) 出餐后禁止自助取消(状态机 403)
no5 = make_order(accept=True)
call("POST", f"/orders/{no5}/transition", merchant, {"to_status": "ready"})
err = cancel(no5, expect_error=True)
assert err["_error"] in (403, 409), err  # 状态机不存在该流转(409)
print(f"✓ 出餐后禁止自助取消({err['_error']}):{err['detail']}")

# 退款流水与订单一致(抽查 no3 之外的已取消单)
flows = call("GET", f"/orders/{no2}/refunds", customer)
assert sum(f["amount_cents"] for f in flows) == o2["refund_cents"]
print("✓ 取消退款流水与订单一致")

call("PATCH", f"/merchants/me/dishes/{main_dish['id']}/", merchant, {"is_on_sale": False}) if False else None
call("PATCH", f"/merchants/me/dishes/{main_dish['id']}", merchant, {"is_on_sale": False})
print("\n订单取消规则验证通过 🎉")
