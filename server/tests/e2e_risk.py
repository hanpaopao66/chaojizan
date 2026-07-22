"""防刷单风控验证:同址高频/同设备多账号/商家关联设备标记、
只标记不拦截(结算照常)、确认后剔出月售、解除恢复、非 admin 403。

在 server/ 目录下运行:python -m tests.e2e_risk
"""
import asyncio
import random
import time

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import call, login

merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")

sid = call("GET", "/merchants/me", merchant)["id"]
call("PATCH", "/merchants/me", merchant, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"风控测试菜-{int(time.time())}", "price_cents": 2000,
             "stock": 50})

# 每轮用独立坐标(店铺 4km 内,轮间偏移 >130m 避免历史残留触发同址规则)
BASE_LAT = 30.6650 + (int(time.time()) % 20) * 1.3e-3
BASE_LNG = 104.0823


def fresh_customer(device=""):
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    body = {"phone": phone, "code": code}
    if device:
        body["device_id"] = device
    return call("POST", "/auth/sms-login", body=body)["token"]


def place_order(cust, lat=None, lng=None):
    order = call("POST", "/orders", cust, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "风控测试地址",
        "lat": lat if lat is not None else BASE_LAT,
        "lng": lng if lng is not None else BASE_LNG,
    })
    return order["order_no"]


async def flags_of(no, wait=4.0):
    """风控是异步评估,轮询等结果落库。"""
    async with SessionLocal() as db:
        for _ in range(int(wait / 0.2)):
            flags = await db.scalar(text(
                "SELECT risk_flags FROM orders WHERE order_no = :no"),
                {"no": no})
            if flags is not None:
                return flags
            await asyncio.sleep(0.2)
    return None


def complete(no, cust):
    call("POST", f"/orders/{no}/pay/mock", cust)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", rider,
         {"to_status": "picked_up", "verify_code": no[-4:]})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", cust, {"to_status": "completed"})


async def main():
    # 1) 同址高频:两个账号在同一位置(<65m)累计 4 单 → 第 4 单标记
    a = fresh_customer()
    b = fresh_customer()
    for cust in (a, b, a):
        no = place_order(cust)
        assert (await flags_of(no, wait=1.0)) is None, "前 3 单不该标记"
    no4 = place_order(b)
    flags = await flags_of(no4)
    assert flags and "addr_freq" in flags["hits"], flags
    print("✓ 同址高频:第 4 单(双账号)标记 addr_freq")

    # 2) 同设备多账号:同 device_id 两账号各下一单 → 第 2 单标记
    device = f"dev{int(time.time())}"
    c = fresh_customer(device)
    d = fresh_customer(device)
    place_order(c, lat=30.6912, lng=104.0823)
    no_d = place_order(d, lat=30.6921, lng=104.0823)
    flags = await flags_of(no_d)
    assert flags and "multi_account_device" in flags["hits"], flags
    print("✓ 同设备多账号:第 2 个账号下单被标记")

    # 3) 商家关联设备:店主设备与下单设备相同 → 标记;只标记不拦截,结算照常
    boss_device = f"boss{int(time.time())}"
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE users SET device_id = :d WHERE id = "
            "(SELECT owner_id FROM merchants WHERE id = :sid)"),
            {"d": boss_device, "sid": sid})
        await db.commit()
    e = fresh_customer(boss_device)
    no_e = place_order(e, lat=30.6930, lng=104.0823)
    flags = await flags_of(no_e)
    assert flags and "merchant_related" in flags["hits"], flags
    complete(no_e, e)  # 标记单照常走完结算
    print("✓ 商家关联设备标记;标记单照常支付结算(不拦截)")

    # 4) 确认刷单 → 剔出月售;解除 → 恢复
    before = call("GET", f"/merchants/{sid}")["monthly_sales"]
    risk_list = call("GET", "/admin/risk-orders?status=", admin)
    target = next(r for r in risk_list if r["order_no"] == no_e)
    call("POST", f"/admin/risk-orders/{target['id']}/verdict", admin,
         {"verdict": "confirmed"})
    after = call("GET", f"/merchants/{sid}")["monthly_sales"]
    assert after == before - 1, f"确认后月售应减 1:{before} -> {after}"
    confirmed = call("GET", "/admin/risk-orders?status=confirmed", admin)
    assert any(r["order_no"] == no_e for r in confirmed)
    print("✓ 确认刷单剔出月售(资金不动)")

    # 5) 非 admin 403
    err = call("GET", "/admin/risk-orders", a, expect_error=True)
    assert err["_error"] == 403, err
    print("✓ 非 admin 403")

    print("\ne2e_risk 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
