"""转单的钱(services/rider_transfer.py)端到端 —— 要么就接,接了就送。

账号现造(管理员、店、两个骑手、顾客),不碰演示号。

1. 骑手 A 接了又转出:立刻扣 10 元(余额少 10、返回 fee_cents);
   抢单大厅里这单挂着「转单加钱 10 元」;骑手 B 接手送到、顾客确认完成,B 多拿 10 元;
1b. 另外自定义加钱(谁转单谁出):A 转出时另加 5 元,立刻扣 15 元,B 送到拿 15 元;
   超过上限的 422,一分不扣;
2. A 又接一单再转出,扣 10 元;这单后来被商家取消,没人送到 → 10 元退回给 A;
3. 无责转单(过了预计出餐时间、上报未出餐满 10 分钟)不扣;
4. 账本页本日「转单扣」= 25 元(第 1 单 10 + 第 1b 单 15,第 2 单退回的抵掉);
5. 审计规则 4f 不报错;公开账本里转单行在 rider_transfer_rows、不在 rider_rows,
   见证节点逐行核账照样过。

在 server/ 目录下运行:python -m tests.e2e_rider_transfer_fee
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


admin, _ = register_user("customer", name="转单扣款e2e客服")
sql("UPDATE users SET role = 'admin' WHERE id = :id", {"id": me_id(admin)})
boss, _ = register_user("merchant", name="转单扣款e2e店主")
shop = call("POST", "/merchants", boss, {
    "name": f"转单扣款测试店-{tag}", "address": "测试路 38 号", "lat": 30.6612, "lng": 104.0823,
    "license_no": f"JYXFER{tag}", "license_image_url": "/uploads/license-demo.jpg"})
call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
call("PATCH", "/merchants/me", boss, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", boss, {
    "name": f"转单扣款测试饭-{tag}", "price_cents": 2200, "stock": 900, "category": "主食"})
rider_a = _run(register_fresh_rider("转单扣款e2e骑手A"))
rider_b = _run(register_fresh_rider("转单扣款e2e骑手B"))
cust, _ = register_user("customer", name="转单扣款e2e顾客")


def place() -> str:
    lat, lng = unique_spot()
    o = call("POST", "/orders", cust, {
        "merchant_id": shop["id"], "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": f"转单扣款测试地址 {tag}", "lat": lat, "lng": lng})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", cust)
    go(boss, no, "accepted")
    return no


def go(tok, no, to, **extra):
    return call("POST", f"/orders/{no}/transition", tok, {"to_status": to, **extra})


def balance(tok) -> int:
    return call("GET", "/riders/wallet", tok)["balance_cents"]


def rows(tok, no) -> list[tuple[str, int]]:
    return sorted((e["kind"], e["amount_cents"])
                  for e in call("GET", "/riders/earnings", tok) if e["order_no"] == no)


def today_payload() -> dict:
    from app.db import SessionLocal
    from app.services.ledger import build_day_payload, hash_no

    async def go_():
        async with SessionLocal() as db:
            return await build_day_payload(
                db, datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    p = _run(go_())
    return p, hash_no


def main() -> None:
    fee = call("GET", "/riders/discipline", rider_a)["transfer_fee_cents"]
    assert fee == 1000, f"默认扣 10 元:{fee}"

    # ============ 1. 接了不送:立刻扣,钱给送到的人 ============
    no1 = place()
    a0, b0 = balance(rider_a), balance(rider_b)
    call("POST", f"/riders/grab/{no1}", rider_a)
    r = call("POST", f"/riders/transfer/{no1}", rider_a, {"reason": "other"})
    assert r["fee_cents"] == fee and not r["waited_free"], r
    assert balance(rider_a) == a0 - fee, "转出立刻扣"
    card = [o for o in call("GET", "/riders/available-orders", rider_b)
            if o["order_no"] == no1]
    assert card and card[0]["transfer_bonus_cents"] == fee, card
    mine = call("GET", f"/orders/{no1}", cust)
    assert mine.get("transfer_bonus_cents", 0) == 0, "顾客看不到骑手之间的钱"
    call("POST", f"/riders/grab/{no1}", rider_b)
    go(boss, no1, "ready")
    go(rider_b, no1, "picked_up")
    go(rider_b, no1, "delivered")
    go(cust, no1, "completed")
    assert ("transfer_bonus", fee) in rows(rider_b, no1), rows(rider_b, no1)
    earned = sum(a for k, a in rows(rider_b, no1) if k == "earning")
    assert balance(rider_b) == b0 + earned + fee, "送到的人多拿转单扣的钱"
    print(f"✓ 接了不送立刻扣 {fee / 100:g} 元;接手送到的骑手完成时多拿这笔")

    # ============ 1b. 另外自定义加钱:谁转单谁出 ============
    extra = 500
    no4 = place()
    a3, b3 = balance(rider_a), balance(rider_b)
    call("POST", f"/riders/grab/{no4}", rider_a)
    err = call("POST", f"/riders/transfer/{no4}", rider_a,
               {"reason": "other", "extra_cents": 10 ** 6}, expect_error=True)
    assert err["_error"] == 422, err
    assert balance(rider_a) == a3, "加钱超上限被拒,一分不扣"
    r = call("POST", f"/riders/transfer/{no4}", rider_a,
             {"reason": "other", "extra_cents": extra})
    assert r["fee_cents"] == fee and r["extra_cents"] == extra, r
    assert r["bonus_cents"] == fee + extra, r
    assert balance(rider_a) == a3 - fee - extra, "另加的钱也是转单的人立刻出"
    card = [o for o in call("GET", "/riders/available-orders", rider_b)
            if o["order_no"] == no4]
    assert card and card[0]["transfer_bonus_cents"] == fee + extra, card
    call("POST", f"/riders/grab/{no4}", rider_b)
    go(boss, no4, "ready")
    go(rider_b, no4, "picked_up")
    go(rider_b, no4, "delivered")
    go(cust, no4, "completed")
    assert ("transfer_bonus", fee + extra) in rows(rider_b, no4), rows(rider_b, no4)
    earned = sum(a for k, a in rows(rider_b, no4) if k == "earning")
    assert balance(rider_b) == b3 + earned + fee + extra
    print(f"✓ 另外加 {extra / 100:g} 元:转单的人连同 {fee / 100:g} 元一起出,送到的人全拿")

    # ============ 2. 转出后订单取消:退回 ============
    no2 = place()
    a1 = balance(rider_a)
    call("POST", f"/riders/grab/{no2}", rider_a)
    call("POST", f"/riders/transfer/{no2}", rider_a, {"reason": "unwell"})
    assert balance(rider_a) == a1 - fee
    go(boss, no2, "cancelled", reason="食材用完了")
    assert rows(rider_a, no2) == sorted([("transfer_fee", -fee), ("transfer_refund", fee)]), \
        rows(rider_a, no2)
    assert balance(rider_a) == a1, "没人送到就退回"
    print("✓ 转出后订单取消:没有接手送到的人,扣的钱退回")

    # ============ 3. 无责转单不扣 ============
    no3 = place()
    a2 = balance(rider_a)
    call("POST", f"/riders/grab/{no3}", rider_a)
    call("POST", "/riders/issues", rider_a,
         {"order_no": no3, "kind": "not_ready", "note": "等了很久"})
    sql("UPDATE delivery_issues SET created_at = now() - interval '11 minutes' "
        "WHERE order_no = :no", {"no": no3})
    sql("UPDATE orders SET accepted_at = now() - interval '2 hours' "
        "WHERE order_no = :no", {"no": no3})
    r = call("POST", f"/riders/transfer/{no3}", rider_a, {"reason": "other"})
    assert r["waited_free"] and r["fee_cents"] == 0, r
    assert balance(rider_a) == a2 and rows(rider_a, no3) == [], "无责转单不扣"
    print("✓ 过了出餐时间商家还没出餐的无责转单:不扣钱")

    # ============ 4. 账本页:本日转单扣 ============
    w = call("GET", "/riders/me/worklog", rider_a)
    assert w["today_transfer_fee_cents"] == fee * 2 + extra, w
    print(f"✓ 账本页本日「转单扣」{(fee * 2 + extra) / 100:g} 元(取消退回的抵掉)")

    # ============ 5. 审计、公开账本、见证节点 ============
    problems = call("POST", "/admin/audit/run", admin)["detail"]
    bad = [p for p in problems if p.get("check", "").startswith("rider_transfer")
           or p.get("check") == "rider_balance_negative"]
    assert not bad, f"审计报错:{bad}"
    p, hash_no = today_payload()
    h1, h2 = hash_no(no1), hash_no(no2)
    assert not [r for r in p["rider_rows"] if r["o"] in (h1, h2)
                and r["kind"].startswith("transfer")], "转单行不进 rider_rows"
    mine = sorted((r["kind"], r["amount"]) for r in p["rider_transfer_rows"]
                  if r["o"] in (h1, h2))
    assert mine == sorted([("transfer_fee", -fee), ("transfer_bonus", fee),
                           ("transfer_fee", -fee), ("transfer_refund", fee)]), mine
    assert p["totals"]["rider_transfer"] == sum(
        r["amount"] for r in p["rider_transfer_rows"])
    assert verify_rows(p) == [], verify_rows(p)
    print("✓ 审计不报错;公开账本转单行单独成栏,见证节点核账通过")

    print("\ne2e_rider_transfer_fee 全部通过 ✅")


if __name__ == "__main__":
    main()
