"""骑手每日保险费(services/insurance.charge_daily_fee)端到端。

账号现造(管理员、店、骑手、顾客),不碰演示号。

1. 骑手上线:当天保障记录登记了,还没扣保费(premium_cents = 0);
2. 当天第一单送到:从这一单的收入里扣 2.5 元,账本流水里单独一行 insurance_fee;
   保障记录写上保费;余额 = 这单收入 − 2.5 元;
3. 同一天第二单送到:不再扣;
4. 审计不报保险费的错(规则 4g)、骑手余额不算错账;
5. 公开账本:保险费在 rider_insurance_rows、不在 rider_rows,合计对得上,见证节点核账通过;
6. 保障金池:登记模式下保费进池子(premium_cents 至少有这一笔)。

在 server/ 目录下运行:python -m tests.e2e_rider_insurance_fee
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
FEE = 250


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


admin, _ = register_user("customer", name="保险费e2e客服")
sql("UPDATE users SET role = 'admin' WHERE id = :id", {"id": me_id(admin)})
boss, _ = register_user("merchant", name="保险费e2e店主")
shop = call("POST", "/merchants", boss, {
    "name": f"保险费测试店-{tag}", "address": "测试路 25 号", "lat": 30.6612, "lng": 104.0823,
    "license_no": f"JYINS{tag}", "license_image_url": "/uploads/license-demo.jpg"})
call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
call("PATCH", "/merchants/me", boss, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", boss, {
    "name": f"保险费测试饭-{tag}", "price_cents": 2200, "stock": 900, "category": "主食"})
rider = _run(register_fresh_rider("保险费e2e骑手"))
cust, _ = register_user("customer", name="保险费e2e顾客")


def go(tok, no, to, **extra):
    return call("POST", f"/orders/{no}/transition", tok, {"to_status": to, **extra})


def deliver() -> str:
    lat, lng = unique_spot()
    o = call("POST", "/orders", cust, {
        "merchant_id": shop["id"], "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": f"保险费测试地址 {tag}", "lat": lat, "lng": lng})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", cust)
    go(boss, no, "accepted")
    call("POST", f"/riders/grab/{no}", rider)
    go(boss, no, "ready")
    go(rider, no, "picked_up")
    go(rider, no, "delivered")
    go(cust, no, "completed")
    return no


def balance() -> int:
    return call("GET", "/riders/wallet", rider)["balance_cents"]


def rows(no) -> list[tuple[str, int]]:
    return sorted((e["kind"], e["amount_cents"])
                  for e in call("GET", "/riders/earnings", rider) if e["order_no"] == no)


def today() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def today_record() -> dict:
    return next(r for r in call("GET", "/riders/insurance", rider) if r["day"] == today())


def main() -> None:
    # ============ 1. 上线:登记当天保障,还没扣 ============
    call("POST", "/riders/online", rider, {"is_online": True})
    rec = today_record()
    assert rec["status"] == "registered" and rec["premium_cents"] == 0, rec
    print("✓ 上线登记当天保障,还没送单不扣保费")

    # ============ 2. 当天第一单:从这单收入里扣 ============
    b0 = balance()
    no1 = deliver()
    r1 = rows(no1)
    earned = sum(a for k, a in r1 if k == "earning")
    assert ("insurance_fee", -FEE) in r1, r1
    assert balance() == b0 + earned - FEE, "余额 = 这单收入 − 保险费"
    assert today_record()["premium_cents"] == FEE
    print(f"✓ 当天第一单送到扣 {FEE / 100:g} 元保险费,流水里单独一行")

    # ============ 3. 同一天第二单不再扣 ============
    b1 = balance()
    no2 = deliver()
    r2 = rows(no2)
    assert not [k for k, _ in r2 if k == "insurance_fee"], r2
    assert balance() == b1 + sum(a for k, a in r2 if k == "earning")
    assert today_record()["premium_cents"] == FEE
    print("✓ 同一天第二单不再扣")

    # ============ 4. 审计 ============
    problems = call("POST", "/admin/audit/run", admin)["detail"]
    bad = [p for p in problems if p.get("check", "").startswith("rider_insurance")
           or p.get("check") in ("rider_balance_negative", "rider_fund_negative")]
    assert not bad, f"审计报错:{bad}"
    print("✓ 审计不报错(规则 4g)")

    # ============ 5. 公开账本、见证节点 ============
    from app.db import SessionLocal
    from app.services.ledger import build_day_payload, hash_no
    from app.services.rider_fault import fund_balance

    async def go_():
        async with SessionLocal() as db:
            return await build_day_payload(db, today()), await fund_balance(db)
    p, fund = _run(go_())
    h1 = hash_no(no1)
    assert not [r for r in p["rider_rows"] if r["kind"] == "insurance_fee"], "保险费不进 rider_rows"
    assert {"o": h1, "amount": -FEE, "kind": "insurance_fee"} in p["rider_insurance_rows"]
    assert p["totals"]["rider_insurance"] == sum(r["amount"] for r in p["rider_insurance_rows"])
    assert verify_rows(p) == [], verify_rows(p)
    print("✓ 公开账本保险费单独成栏,见证节点核账通过")

    # ============ 6. 登记模式下保费进保障金池 ============
    assert fund["premium_cents"] >= FEE, fund
    assert fund["balance_cents"] == (fund["accrued_cents"] + fund["premium_cents"]
                                     - fund["paid_cents"] + fund["returned_cents"]), fund
    print("✓ 没接入保险公司之前,保费进保障金池")

    print("\ne2e_rider_insurance_fee 全部通过 ✅")


if __name__ == "__main__":
    main()
