"""M5b 验证:菜品规格/加料 + 预订单。

  1. 规格定价:服务端按菜品定义重算单价,快照名预合成「菜名(大份+加蛋)」
  2. 校验:凭空选项 422 / 缺必选 422 / 单选组选两项 422
  3. 预订单:30 分钟内拒绝;商家接单超时豁免至预约前 1 小时
在 server/ 目录下运行:python -m tests.e2e_dish_options
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import Order
from tests.util import call, login

tag = str(int(time.time()))
admin = login("13800000000")

boss = call("POST", "/auth/register", body={
    "phone": "135" + tag[-8:], "password": "123456", "name": "规格测试老板",
    "role": "merchant"})["token"]
shop = call("POST", "/merchants", boss, {
    "name": f"规格测试店-{tag}", "address": "测试路 6 号",
    "lat": 30.6612, "lng": 104.0823,
    "license_no": "JY99900011188888",
    "license_image_url": "/uploads/license-demo.jpg"})
call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
call("PATCH", "/merchants/me", boss, {"is_open": True})

dish = call("POST", "/merchants/me/dishes", boss, {
    "name": f"牛肉面-{tag}", "price_cents": 1500, "stock": 100,
    "options": [
        {"name": "份量", "required": True, "multi": False,
         "choices": [{"name": "小份", "delta_cents": 0},
                     {"name": "大份", "delta_cents": 300}]},
        {"name": "加料", "required": False, "multi": True,
         "choices": [{"name": "加蛋", "delta_cents": 200},
                     {"name": "加香菜", "delta_cents": 100}]},
    ]})
assert len(dish["options"]) == 2
print("✓ 规格菜品创建:份量(必选) + 加料(可多选)")

customer = call("POST", "/auth/register", body={
    "phone": "134" + tag[-8:], "password": "123456", "name": "规格测试客",
    "role": "customer"})["token"]


def place(choices, expect_error=False, **extra):
    return call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": dish["id"], "quantity": 2, "choices": choices}],
        "address": "规格验证地址", "lat": 30.6612, "lng": 104.0823,
        **extra,
    }, expect_error=expect_error)


# ---- 定价与快照 ----
order = place(["大份", "加蛋", "加香菜"])
assert order["food_cents"] == (1500 + 300 + 200 + 100) * 2, order["food_cents"]
assert order["items"][0]["name"] == f"牛肉面-{tag}(大份+加蛋+加香菜)"
assert order["items"][0]["price_cents"] == 2100
print(f"✓ 服务端重算单价 21 元(基础15+大份3+蛋2+香菜1),快照名:{order['items'][0]['name']}")

# ---- 校验 ----
err = place(["小份", "巨无霸酱"], expect_error=True)
assert err["_error"] == 422 and "不存在选项" in err["detail"]
print(f"✓ 凭空选项被拒:{err['detail']}")
err = place(["加蛋"], expect_error=True)
assert err["_error"] == 422 and "份量" in err["detail"]
print(f"✓ 缺必选组被拒:{err['detail']}")
err = place(["小份", "大份"], expect_error=True)
assert err["_error"] == 422 and "只能选一项" in err["detail"]
print(f"✓ 单选组选两项被拒:{err['detail']}")

# ---- 预订单 ----
err = place(["小份"], expect_error=True,
            scheduled_at=(datetime.now(timezone.utc)
                          + timedelta(minutes=10)).isoformat())
assert err["_error"] == 422 and "30 分钟" in err["detail"]
print(f"✓ 预约不足 30 分钟被拒:{err['detail']}")

sched = datetime.now(timezone.utc) + timedelta(hours=3)
order2 = place(["小份"], scheduled_at=sched.isoformat())
no = order2["order_no"]
assert order2["scheduled_at"] is not None
call("POST", f"/orders/{no}/pay/mock", customer)
print("✓ 预约单(3 小时后送达)创建并支付")


async def check_exemption():
    """把订单 updated_at 改到远超接单超时,验证清扫豁免;再把预约压进 1 小时窗口,验证会被取消。"""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    from app.services import auto_flow
    # sweep 用的 SessionLocal 绑定全局引擎;这里替换成本测试的引擎防跨事件循环
    async with AsyncSession(engine) as db:
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        await db.execute(update(Order).where(Order.order_no == no)
                         .values(updated_at=stale))
        await db.commit()
    await auto_flow.sweep_once()
    async with AsyncSession(engine) as db:
        o = await db.scalar(select(Order).where(Order.order_no == no))
        status_after_exempt = o.status.value
        # 把预约时间改到 40 分钟后(进入 1 小时兜底窗口)
        await db.execute(update(Order).where(Order.order_no == no).values(
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=40),
            updated_at=stale))
        await db.commit()
    await auto_flow.sweep_once()
    async with AsyncSession(engine) as db:
        o = await db.scalar(select(Order).where(Order.order_no == no))
        status_final = o.status.value
    await engine.dispose()
    return status_after_exempt, status_final


exempt_status, final_status = asyncio.run(check_exemption())
assert exempt_status == "paid", f"预约单不应被超时取消,实际 {exempt_status}"
print("✓ 商家接单超时豁免:预约单超时 2 小时未接仍保持待接单")
assert final_status == "cancelled", f"进入 1 小时窗口应取消,实际 {final_status}"
print("✓ 预约前 1 小时兜底生效:仍未接单则取消退款")

print("\nM5b(菜品规格/加料 + 预订单)验证通过 🎉")
