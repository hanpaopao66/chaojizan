"""判骑手责任的钱怎么走(services/rider_fault.py)端到端 —— 平台不出钱。

账号现造(管理员、店、骑手、顾客),不碰演示号。池子余额每次都现读(/transparency/funds),
期望值按「先池子、不够骑手出」自己算一遍再比 —— 不断言池子里恰好有多少钱。

1. 配送异常「餐品损坏」裁成退款:顾客全额退款;商家净额照旧;这单骑手收入冲回;
   商家那份餐钱先保障金池(按裁决时的余额)、不够的骑手出;池子余额少了池子出的那部分;
   审计不报错;当天的公开账本 payload 里判责行不在 rider_rows、在 rider_fault_rows,
   池子的支出在 rider_fund.rows,见证节点的逐行核账照样过;
2. 骑手走原通道申诉成立:扣的全部退回、池子出的回池,审计不报错;
3. 售后判骑手责任(大单,池子兜不住):骑手余额变负、可提现 0、提现被挡;
   过了 72 小时走客服工单申诉成立,扣的退回、池子回池,余额回来。

**前提:服务端的信用分起算日至少在 4 天前**(第 3 段要把判责做旧 4 天,同 e2e_credit;CI 设 30 天前)。

在 server/ 目录下运行:python -m tests.e2e_rider_fault
"""
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from tests.util import call, register_fresh_rider, register_user, unique_spot

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "witness"))
from superz_witness import verify_rows  # noqa: E402

tag = str(int(time.time()))
EVIDENCE = "/uploads/demo-evidence-1.jpg"


def _run(coro):
    from app.db import engine

    async def go():
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(go())


async def _sql(stmt: str, params: dict | None = None):
    from app.db import SessionLocal
    async with SessionLocal() as db:
        r = await db.execute(text(stmt), params or {})
        await db.commit()
        try:
            return r.scalar()
        except Exception:
            return None


def sql(stmt: str, params: dict | None = None):
    return _run(_sql(stmt, params))


def me_id(tok) -> int:
    return call("GET", "/auth/me", tok)["id"]


admin, _ = register_user("customer", name="骑手责任e2e客服")
sql("UPDATE users SET role = 'admin' WHERE id = :id", {"id": me_id(admin)})
boss, _ = register_user("merchant", name="骑手责任e2e店主")
shop = call("POST", "/merchants", boss, {
    "name": f"骑手责任测试店-{tag}", "address": "测试路 37 号", "lat": 30.6612, "lng": 104.0823,
    "license_no": f"JYFAULT{tag}", "license_image_url": "/uploads/license-demo.jpg"})
call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
call("PATCH", "/merchants/me", boss, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", boss, {
    "name": f"骑手责任测试饭-{tag}", "price_cents": 2200, "stock": 900, "category": "主食"})
rider = _run(register_fresh_rider("骑手责任e2e骑手"))
cust, _ = register_user("customer", name="骑手责任e2e顾客")
cust2, _ = register_user("customer", name="骑手责任e2e顾客二")


def fund() -> dict:
    return call("GET", "/transparency/funds")["rider_fund"]


def rider_balance() -> int:
    return call("GET", "/riders/wallet", rider)["balance_cents"]


def merchant_earned() -> int:
    return call("GET", "/merchants/me/wallet", boss)["total_earned_cents"]


def place(tok, qty=1) -> str:
    lat, lng = unique_spot()
    o = call("POST", "/orders", tok, {
        "merchant_id": shop["id"], "items": [{"dish_id": dish["id"], "quantity": qty}],
        "address": f"骑手责任测试地址 {tag}", "lat": lat, "lng": lng})
    call("POST", f"/orders/{o['order_no']}/pay/mock", tok)
    return o["order_no"]


def go(tok, no, to):
    return call("POST", f"/orders/{no}/transition", tok, {"to_status": to})


def picked_up(no):
    go(boss, no, "accepted")
    call("POST", f"/riders/grab/{no}", rider)
    go(boss, no, "ready")
    go(rider, no, "picked_up")


def merchant_net(o: dict) -> int:
    return max(o["food_cents"] + o["packing_fee_cents"] - o["discount_cents"], 0) \
        - o["commission_cents"]


def fault_rows(no: str) -> dict:
    return {e["kind"]: e["amount_cents"]
            for e in call("GET", "/riders/earnings", rider) if e["order_no"] == no}


def audit_clean(no: str, why: str):
    problems = call("POST", "/admin/audit/run", admin)["detail"]
    mine = [p for p in problems if no in p.get("detail", "")
            or p.get("check") in ("rider_fund_negative",)]
    assert not mine, f"{why}:审计报错 {mine}"


def today_payload() -> dict:
    from app.db import SessionLocal
    from app.services.ledger import build_day_payload

    async def go_():
        async with SessionLocal() as db:
            return await build_day_payload(
                db, datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    return _run(go_())


def main() -> None:
    per_order = fund()["per_order_cents"]

    # ============ 1. 配送异常判骑手责任 ============
    a = place(cust)
    picked_up(a)
    o = call("GET", f"/orders/{a}", cust)
    m_net = merchant_net(o)
    income = o["delivery_fee_cents"] + o["tip_cents"]
    pool0, r0, mw0 = fund()["balance_cents"], rider_balance(), merchant_earned()
    issue = call("POST", "/riders/issues", rider, {"order_no": a, "kind": "food_damaged",
                                                   "note": "路上摔了,汤洒了", "photo_url": EVIDENCE})
    call("POST", f"/admin/delivery-issues/{issue['id']}/resolve", admin,
         {"action": "refund", "note": "餐损,判骑手责任"})
    # 结算那一刻这单的配送入账也计提了一笔,裁决时池子里多了这一笔
    f1 = min(pool0 + per_order, m_net)
    x1 = m_net - f1
    ob = call("GET", f"/orders/{a}", cust)
    assert ob["status"] == "completed" and ob["refund_cents"] == o["total_cents"], ob
    assert merchant_earned() - mw0 == m_net, "商家无责,这单净额该照旧入账"
    assert rider_balance() - r0 == -x1, \
        f"骑手这单收入冲回、另扣 {x1}:余额应变 {-x1},实际 {rider_balance() - r0}"
    rows = fault_rows(a)
    assert rows.get("earning") == income and rows.get("fault_reversal") == -income, rows
    assert rows.get("fault_charge", 0) == -x1, rows
    pool1 = fund()["balance_cents"]
    assert pool1 == pool0 + per_order - f1, (pool0, per_order, f1, pool1)
    audit_clean(a, "配送异常判骑手责任")
    p = today_payload()
    from app.services.ledger import hash_no
    h = hash_no(a)
    assert not [r for r in p["rider_rows"] if r["kind"].startswith("fault_")], \
        "判责行混进了 rider_rows —— 见证节点会把它当成配送费被冲回"
    mine = {r["kind"]: r["amount"] for r in p["rider_fault_rows"] if r["o"] == h}
    assert mine.get("fault_reversal") == -income and mine.get("fault_charge", 0) == -x1, mine
    fund_rows = {r["kind"]: r["amount"] for r in p["rider_fund"]["rows"] if r["o"] == h}
    assert fund_rows.get("payout", 0) == f1, fund_rows
    assert p["totals"]["rider_fault"] == sum(r["amount"] for r in p["rider_fault_rows"])
    assert verify_rows(p) == [], f"见证节点的逐行核账不过:{verify_rows(p)}"
    print(f"✓ 配送异常判骑手责任:顾客全额退 ¥{o['total_cents'] / 100:.2f},商家净额 ¥{m_net / 100:.2f}"
          f" 照旧;骑手这单收入 ¥{income / 100:.2f} 冲回;商家那份餐钱池子出 ¥{f1 / 100:.2f}、"
          f"骑手另出 ¥{x1 / 100:.2f};审计、公开账本、见证核账都过")

    # ============ 2. 原通道申诉成立:扣的退回、池子回池 ============
    ap = call("POST", "/appeals", rider, {"target_type": "delivery_issue",
                                          "target_id": issue["id"],
                                          "reason": "是路面塌陷,有现场照片"})
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:路面塌陷,非骑手责任"})
    assert rider_balance() - r0 == income, "改判成立:这单收入和另扣的都该退回"
    assert fault_rows(a).get("fault_refund") == income + x1, fault_rows(a)
    assert fund()["balance_cents"] == pool1 + f1, "池子出的那部分该回池"
    audit_clean(a, "配送异常改判")
    print(f"✓ 原通道改判:退回骑手 ¥{(income + x1) / 100:.2f},池子回池 ¥{f1 / 100:.2f},审计不报错")

    # ============ 3. 售后判骑手责任:大单,池子兜不住,骑手余额变负 ============
    b = place(cust2, qty=20)
    picked_up(b)
    go(rider, b, "delivered")
    go(cust2, b, "completed")
    ob = call("GET", f"/orders/{b}", cust2)
    m_net_b = merchant_net(ob)
    income_b = ob["delivery_fee_cents"] + ob["tip_cents"]
    call("POST", f"/orders/{b}/after-sale", cust2,
         {"reason": "餐盒整个翻了,汤洒在袋子里", "images": [EVIDENCE]})
    as_b = next(x["id"] for x in call("GET", "/admin/after-sales?days=7", admin)
                if x["order_no"] == b)
    pool2, r2 = fund()["balance_cents"], rider_balance()
    res = call("POST", f"/admin/after-sales/{as_b}/rider-fault", admin,
               {"reason": "餐盒侧翻,配送责任"})
    f3 = min(pool2, m_net_b)
    x3 = m_net_b - f3
    assert res["refunded_cents"] == ob["total_cents"] and res["fund_cents"] == f3 and \
        res["rider_charge_cents"] == x3 and res["rider_income_cents"] == income_b, (res, f3, x3)
    assert x3 > 0, f"这一单商家那份 {m_net_b} 分,池子只有 {pool2} 分 —— 该有骑手另出的部分"
    w = call("GET", "/riders/wallet", rider)
    assert w["balance_cents"] == r2 - income_b - x3, (w, r2, income_b, x3)
    assert w["balance_cents"] < 0 and w["withdrawable_cents"] == 0, w
    assert fund()["balance_cents"] == pool2 - f3
    audit_clean(b, "售后判骑手责任")
    print(f"✓ 售后判骑手责任(商家那份 ¥{m_net_b / 100:.2f}):池子出 ¥{f3 / 100:.2f},"
          f"骑手另出 ¥{x3 / 100:.2f},余额 ¥{w['balance_cents'] / 100:.2f}、可提现 0")

    # 过了 72 小时:原通道接不上,走客服工单;成立的话扣的退回、池子回池
    sql("UPDATE after_sales SET processed_at = now() - interval '4 days' WHERE id = :i",
        {"i": as_b})
    late = call("POST", "/appeals", rider, {"target_type": "after_sale_rider", "target_id": as_b,
                                            "reason": "取餐时盒子就是裂的"}, expect_error=True)
    assert late["_error"] == 422, late
    t = call("POST", "/credit/me/appeals", rider,
             {"kind": "after_sale_fault", "record_id": as_b, "reason": "取餐时盒子就是裂的,我拍了照"})
    call("POST", f"/admin/credit/appeals/{t['id']}/resolve", admin,
         {"result": "overturned", "note": "取餐照片显示盒子出店前已裂"})
    assert rider_balance() == r2, "工单改判成立:扣的全部退回,余额回到判责之前"
    assert fund()["balance_cents"] == pool2, "池子出的那部分回池"
    a_row = next(x for x in call("GET", "/admin/after-sales?days=7", admin) if x["id"] == as_b)
    assert a_row["fault"] != "rider", a_row
    audit_clean(b, "工单改判")
    print("✓ 过了 72 小时走工单:改判成立,扣的退回、池子回池、判责从骑手转走;审计不报错")

    print("\ne2e_rider_fault 全部通过 ✅")


if __name__ == "__main__":
    main()
