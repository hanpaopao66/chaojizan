"""住宿售后:到店无房(全额退+30%首晚违约金/商家拒绝/超时自动成立)、
协商退(strict 档商家定金额)、账本违约金负行、审计恒等。

在 server/ 目录下运行:python -m tests.e2e_stays_aftersale
"""
import asyncio
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from app.services.ledger import build_missing_anchors, hash_no
from tests.util import ADMIN, call, login

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "witness"))
from superz_witness import verify_rows  # noqa: E402

admin_token = login(ADMIN)
today = date.today()

phone = "138" + "".join(str(random.randint(0, 9)) for _ in range(8))
mt = call("POST", "/auth/register",
          body={"phone": phone, "password": "hotel123",
                "role": "merchant"})["token"]
shop = call("POST", "/merchants", token=mt, body={
    "name": f"售后客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST10",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-010",
              "special_license_image_url": "https://example.com/sp.jpg"}})
sid = shop["id"]
call("POST", f"/admin/merchants/{sid}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})
rt_free = call("POST", "/stays/me/room-types", token=mt,
               body={"name": "普通房", "cancel_policy": "limited_free"})
rt_strict = call("POST", "/stays/me/room-types", token=mt,
                 body={"name": "特价房", "cancel_policy": "strict"})
call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt_free["id"], rt_strict["id"]],
    "from_date": str(today), "to_date": str(today + timedelta(days=10)),
    "price_cents": 20000, "total_qty": 5})

cphone = "137" + "".join(str(random.randint(0, 9)) for _ in range(8))
ct = call("POST", "/auth/register",
          body={"phone": cphone, "password": "guest123",
                "role": "customer"})["token"]


def book(rt_id, ci_off=0, nights=2, confirm=True):
    o = call("POST", "/stays/orders", token=ct, body={
        "room_type_id": rt_id, "checkin_date": str(today + timedelta(days=ci_off)),
        "checkout_date": str(today + timedelta(days=ci_off + nights)),
        "rooms_qty": 1, "guest_name": "售后客", "guest_phone": "13700000010"})
    no = o["order_no"]
    call("POST", f"/stays/orders/{no}/pay/mock", token=ct)
    if confirm:
        call("POST", f"/stays/me/orders/{no}/confirm", token=mt)
    return no


# 1) 到店无房:未到入住日不能发起;到店后发起 → 商家拒绝 → 再发起 → 商家认罚
no_future = book(rt_free["id"], ci_off=3)
r = call("POST", f"/stays/orders/{no_future}/aftersale", token=ct,
         body={"kind": "no_room", "note": "还没到"}, expect_error=True)
assert r["_error"] == 409 and "入住日" in r["detail"], r

no1 = book(rt_free["id"], ci_off=0)  # 今天入住,2 晚 40000,首晚 20000
a1 = call("POST", f"/stays/orders/{no1}/aftersale", token=ct,
          body={"kind": "no_room", "note": "前台说满房了"})
# 重复发起被拒
r = call("POST", f"/stays/orders/{no1}/aftersale", token=ct,
         body={"kind": "no_room"}, expect_error=True)
assert r["_error"] == 409
# 商家拒绝 → 订单不动
rej = call("POST", f"/stays/me/aftersales/{a1['id']}/respond", token=mt,
           body={"accept": False, "note": "有房,可能客人走错了"})
assert rej["status"] == "rejected"
o = call("GET", f"/stays/orders/{no1}", token=ct)
assert o["status"] == "confirmed"
# 再次发起 → 商家认罚:全额退 40000 + 违约金 6000(首晚 20000×30%)
a2 = call("POST", f"/stays/orders/{no1}/aftersale", token=ct,
          body={"kind": "no_room", "note": "确实没房"})
acc = call("POST", f"/stays/me/aftersales/{a2['id']}/respond", token=mt,
           body={"accept": True, "note": "抱歉,超售了"})
assert acc["status"] == "accepted"
assert acc["refund_cents"] == 46000 and acc["penalty_cents"] == 6000, acc
o = call("GET", f"/stays/orders/{no1}", token=ct)
assert o["status"] == "cancelled" and o["refund_cents"] == 46000
assert o["fee_cents"] == 0 and o["net_cents"] == -6000
print("OK 到店无房:拒绝可留证,认罚 = 全额退+30%首晚违约金(商家 -6000,平台 0)")

# 2) 钱包:违约金从商家余额扣(负余额允许)
w = call("GET", "/merchants/me/wallet", token=mt)
assert w["balance_cents"] == -6000, w
print("OK 商家余额扣违约金:", w["balance_cents"])

async def main():
    # 3) 超时自动成立:商家 2 小时未响应
    no2 = book(rt_free["id"], ci_off=0)
    a3 = call("POST", f"/stays/orders/{no2}/aftersale", token=ct,
              body={"kind": "no_room", "note": "又没房"})
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE stay_after_sales SET created_at = now() - interval "
            "'3 hours' WHERE id = :i"), {"i": a3["id"]})
        await db.commit()
    await sweep_once()
    o = call("GET", f"/stays/orders/{no2}", token=ct)
    assert o["status"] == "cancelled" and o["net_cents"] == -6000, o["status"]
    a = call("GET", f"/stays/orders/{no2}/aftersale", token=ct)
    assert a["status"] == "auto_accepted"
    print("OK 商家 2 小时未响应 → 自动成立")

    # 4) 协商退:可退房型被引导走取消;strict 档商家定金额
    no3 = book(rt_free["id"], ci_off=5, confirm=False)
    r = call("POST", f"/stays/orders/{no3}/aftersale", token=ct,
             body={"kind": "nego_refund"}, expect_error=True)
    assert r["_error"] == 409 and "直接取消" in r["detail"], r
    no4 = book(rt_strict["id"], ci_off=5, confirm=False)
    a4 = call("POST", f"/stays/orders/{no4}/aftersale", token=ct,
              body={"kind": "nego_refund", "note": "行程有变,求通融"})
    r = call("POST", f"/stays/me/aftersales/{a4['id']}/respond", token=mt,
             body={"accept": True}, expect_error=True)
    assert r["_error"] == 422, "同意协商退必须带金额"
    acc = call("POST", f"/stays/me/aftersales/{a4['id']}/respond", token=mt,
               body={"accept": True, "refund_cents": 20000, "note": "退一半"})
    assert acc["refund_cents"] == 20000
    o = call("GET", f"/stays/orders/{no4}", token=ct)
    assert o["status"] == "cancelled" and o["refund_cents"] == 20000
    assert o["net_cents"] == 20000 and o["fee_cents"] == 0
    print("OK 协商退:strict 档商家定金额,平台只留证不抽佣")

    # 5) 账本违约金负行(kind=penalty)+ 见证器恒等式
    yesterday = (today - timedelta(days=1)).isoformat()
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE stay_orders SET cancelled_at = now() - interval '1 day' "
            "WHERE order_no = :no"), {"no": no1})
        await db.execute(text(
            "DELETE FROM ledger_anchors WHERE day >= :d"), {"d": yesterday})
        await db.commit()
        await build_missing_anchors(db)
    payload = call("GET", f"/ledger/days/{yesterday}")["payload"]
    row = next(r for r in payload["stay_rows"] if r["s"] == hash_no(no1))
    assert row["kind"] == "penalty" and row["net"] == -6000 and row["fee"] == 0
    assert verify_rows(payload) == [], verify_rows(payload)
    print("OK 账本违约金负行 + 见证器绿")

    # 6) 审计恒等式(net+refund==total 对赔付单依然成立)
    result = call("POST", "/admin/audit/run", token=admin_token)
    bad = [p for p in result["detail"]
           if p.get("check") == "stay_split_mismatch"]
    assert not bad, bad
    print("OK 审计恒等式绿(赔付单 net+refund==total)")

    print("PASS e2e_stays_aftersale")


asyncio.run(main())
