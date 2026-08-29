"""公开账本纳入住宿 + 见证节点校验:stay_rows 逐行恒等、篡改示警。

直连数据库把住宿资金时间戳改到昨天,重建昨日锚点(账本未上线,开发库可删),
然后用 witness/superz_witness.py 的 verify_rows 原样校验。
在 server/ 目录下运行:python -m tests.e2e_stays_witness
"""
import asyncio
import copy
import random
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from sqlalchemy import text

from app.db import SessionLocal
from app.services.ledger import build_missing_anchors, hash_no
from tests.util import ADMIN, call, login, register_user

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "witness"))
from superz_witness import verify_rows  # noqa: E402

admin_token = login(ADMIN)
# 必须用北京时间的"今天":账本按北京时区切日(services/ledger._today_beijing),
# 而开发机的本地时区可能落后北京(如 PDT 差 15 小时)。用 date.today() 会
# 把资金时间戳算到前一天,昨日锚点里一行住宿都没有 —— 表现为 KeyError,
# 且只在本地日期与北京日期不同的那段时间里复现,极难排查
today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
yesterday = (today - timedelta(days=1)).isoformat()

# 造两笔住宿资金:离店结算 + 取消扣首晚
mt, phone = register_user("merchant", "hotel123", prefix="138")
shop = call("POST", "/merchants", token=mt, body={
    "name": f"账本客栈{phone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST08",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-008",
              "special_license_image_url": "https://example.com/sp.jpg"}})
call("POST", f"/admin/merchants/{shop['id']}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})
rt = call("POST", "/stays/me/room-types", token=mt,
          body={"name": "账本房", "cancel_policy": "first_night"})
call("PUT", "/stays/me/calendar", token=mt, body={
    "room_type_ids": [rt["id"]], "from_date": str(today),
    "to_date": str(today + timedelta(days=10)),
    "price_cents": 30000, "total_qty": 3})
ct, cphone = register_user("customer", "guest123", prefix="137")
ci, co = today + timedelta(days=2), today + timedelta(days=4)


def book(pay=True):
    o = call("POST", "/stays/orders", token=ct, body={
        "room_type_id": rt["id"], "checkin_date": str(ci),
        "checkout_date": str(co), "rooms_qty": 1,
        "guest_name": "账本客", "guest_phone": "13700000007"})
    call("POST", f"/stays/orders/{o['order_no']}/pay/mock", token=ct)
    return o["order_no"]


no_settle = book()
call("POST", f"/stays/me/orders/{no_settle}/confirm", token=mt)
call("POST", f"/stays/me/orders/{no_settle}/checkin", token=mt)
call("POST", f"/stays/me/orders/{no_settle}/checkout", token=mt)
no_cancel = book()
call("POST", f"/stays/orders/{no_cancel}/cancel", token=ct)


async def main():
    async with SessionLocal() as db:
        # 资金时间戳挪到昨天;删除昨日起的锚点强制重建(账本未上线,仅开发库)
        await db.execute(text(
            "UPDATE stay_orders SET completed_at = now() - interval '1 day' "
            "WHERE order_no = :no"), {"no": no_settle})
        await db.execute(text(
            "UPDATE stay_orders SET cancelled_at = now() - interval '1 day' "
            "WHERE order_no = :no"), {"no": no_cancel})
        await db.execute(text(
            "DELETE FROM ledger_anchors WHERE day >= :d"), {"d": yesterday})
        await db.commit()
        await build_missing_anchors(db)

    payload = call("GET", f"/ledger/days/{yesterday}")["payload"]
    assert payload["stay_rate"] == 0.05
    rows = {r["s"]: r for r in payload["stay_rows"]}
    settle = rows[hash_no(no_settle)]
    cancel = rows[hash_no(no_cancel)]
    assert settle == {"s": hash_no(no_settle), "gross": 60000, "fee": 3000,
                      "net": 57000, "kind": "settle"}
    assert cancel == {"s": hash_no(no_cancel), "gross": 60000, "fee": 0,
                      "net": 30000, "kind": "cancel"}
    # 合计与逐行加总恒等(共享开发库里可能还有其他测试的住宿流水)
    assert payload["totals"]["stay_fee"] == sum(
        r["fee"] for r in payload["stay_rows"])
    print("✓ 昨日锚点含住宿行(settle 5% / cancel 零佣)")

    # 见证节点原样校验通过
    assert verify_rows(payload) == [], verify_rows(payload)
    print("✓ 见证节点校验通过(Python 版,Go 版同一套恒等式已同步)")

    # 篡改示警:佣金超 5% / 取消行收佣 / 净额不平,都要被抓
    bad = copy.deepcopy(payload)
    bad["stay_rows"][[r["s"] for r in bad["stay_rows"]].index(
        hash_no(no_settle))]["fee"] = 9000
    assert any("超过" in p or "净额" in p for p in verify_rows(bad))
    bad2 = copy.deepcopy(payload)
    bad2["stay_rows"][[r["s"] for r in bad2["stay_rows"]].index(
        hash_no(no_cancel))]["fee"] = 100
    assert any("不应产生佣金" in p for p in verify_rows(bad2))
    print("✓ 篡改示警:超佣 5%/取消行收佣都被恒等式拦截")

    # 隐私:住宿行无个人信息
    keys = set()
    for r in payload["stay_rows"]:
        keys |= set(r)
    assert keys <= {"s", "gross", "fee", "net", "kind"}
    print("✓ 住宿行匿名化(仅哈希单号与金额)")

    print("PASS e2e_stays_witness")


asyncio.run(main())
