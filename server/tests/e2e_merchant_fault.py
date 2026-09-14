"""判商家责任的钱怎么走(services/merchant_fault.py)端到端 —— 2026-09-15 定:商家有责任,
商家连配送费和小费一起出,顾客拿回全款;平台不贴钱。

账号现造(管理员、店、骑手、顾客),不碰演示号。每一段逐方核实际金额:顾客一共退了多少、
商家这单的入账 / 冲回 / 另出的那行、骑手拿多少、平台这单收的佣金和净留存;审计不报错;
当天的公开账本里另出的那行在 merchant_fault_rows、不在 merchant_rows,见证节点核账照过。

1. 商家同意售后(送达、顾客还没确认收货,带小费):先按完成结算再冲 —— 原来这种单冲不到账,
   等自动完成时商家照常入账,这笔退款就成了平台出的;
2. 顾客对「售后被拒」申诉、改判成立;
3. 骑手到店未出餐,平台裁成退款;
4. 食安投诉核实成立;
5. 用了停发之前的平台券:退的是顾客真付的钱,券那截不退现金、回平台;
6. 商家自配送:配送费本来就在商家入账里,冲回净额就一起退了,不另出;
7. 商家余额因此为负:可提现 0、提现被挡;审计不当错账报(提走的没超过挣到的)。

在 server/ 目录下运行:python -m tests.e2e_merchant_fault
"""
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from tests.util import (call, grant_legacy_platform_coupon, register_fresh_rider,
                        register_user, unique_spot)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "witness"))
from superz_witness import verify_rows  # noqa: E402

tag = str(int(time.time()))
EVIDENCE = "/uploads/demo-evidence-1.jpg"
TIP = 300


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


admin, _ = register_user("customer", name="商家责任e2e客服")
sql("UPDATE users SET role = 'admin' WHERE id = :id", {"id": me_id(admin)})
boss, _ = register_user("merchant", name="商家责任e2e店主")
BOSS_ID = me_id(boss)
shop = call("POST", "/merchants", boss, {
    "name": f"商家责任测试店-{tag}", "address": "测试路 38 号", "lat": 30.6612, "lng": 104.0823,
    "license_no": f"JYMFAULT{tag}", "license_image_url": "/uploads/license-demo.jpg"})
call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
call("PATCH", "/merchants/me", boss, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", boss, {
    "name": f"商家责任测试饭-{tag}", "price_cents": 2200, "stock": 900, "category": "主食"})
rider = _run(register_fresh_rider("商家责任e2e骑手"))


def new_customer():
    tok, phone = register_user("customer", name="商家责任e2e顾客")
    return tok, phone


def place(tok, *, tip=TIP, coupon_id=None) -> str:
    lat, lng = unique_spot()
    body = {"merchant_id": shop["id"], "items": [{"dish_id": dish["id"], "quantity": 1}],
            "address": f"商家责任测试地址 {tag}", "lat": lat, "lng": lng, "tip_cents": tip}
    if coupon_id:
        body["coupon_id"] = coupon_id
    o = call("POST", "/orders", tok, body)
    call("POST", f"/orders/{o['order_no']}/pay/mock", tok)
    return o["order_no"]


def go(tok, no, to):
    return call("POST", f"/orders/{no}/transition", tok, {"to_status": to})


def delivered(no):
    go(boss, no, "accepted")
    call("POST", f"/riders/grab/{no}", rider)
    go(boss, no, "ready")
    go(rider, no, "picked_up")
    go(rider, no, "delivered")


def merchant_rows(no) -> dict:
    """这单商家账本上的行:{kind: 净额},顺带核对账明细给每一行都标了名字"""
    day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    rows = [r for r in call("GET", f"/merchants/me/finance/orders?day={day}", boss)
            if r["order_no"] == no]
    assert all(r.get("kind_label") for r in rows), rows
    return {r["kind"]: r["net_cents"] for r in rows}


def rider_rows(no) -> dict:
    return {e["kind"]: e["amount_cents"]
            for e in call("GET", "/riders/earnings", rider) if e["order_no"] == no}


def commission_of(no) -> int:
    return int(sql("SELECT coalesce(sum(commission_cents), 0) FROM merchant_earnings "
                   "WHERE order_no = :no", {"no": no}) or 0)


def audit_clean(no: str, why: str):
    problems = call("POST", "/admin/audit/run", admin)["detail"]
    mine = [p for p in problems if no in p.get("detail", "")
            or (p.get("check") == "merchant_balance_negative" and f"#{BOSS_ID}" in p["detail"])]
    assert not mine, f"{why}:审计报错 {mine}"


def today_payload() -> dict:
    from app.db import SessionLocal
    from app.services.ledger import build_day_payload

    async def go_():
        async with SessionLocal() as db:
            return await build_day_payload(
                db, datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    return _run(go_())


def check_merchant_fault(no, cust, *, why, self_delivery=False) -> dict:
    """逐方核这一单:顾客拿回全款、商家净额冲回并另出骑手那份、骑手照拿、平台这单 0。"""
    from app.services.ledger import hash_no

    o = call("GET", f"/orders/{no}", cust)
    assert o["status"] == "completed", (why, o["status"])
    share = 0 if self_delivery else o["delivery_fee_cents"] + o["tip_cents"]
    # 顾客:实付一分不少退回(这些单没有扣实付的缺货 / 改地址退款)
    assert o["refund_cents"] == o["total_cents"], \
        f"{why}:顾客该拿回全款 {o['total_cents']},实际退 {o['refund_cents']}"
    flows = call("GET", f"/orders/{no}/refunds", cust)
    assert sum(f["amount_cents"] for f in flows if f["status"] != "failed") == o["refund_cents"]
    # 商家:入账 N、冲回 −N、另出 −(配送费 + 小费)
    m = merchant_rows(no)
    net = m.get("earning")
    assert net is not None and m.get("reversal") == -net, (why, m)
    if self_delivery:
        assert "fault_charge" not in m, f"{why}:自配送的配送费在入账里,冲回就退了,不该再另出:{m}"
    else:
        assert m.get("fault_charge") == -share, f"{why}:商家该另出 {share}:{m}"
    # 骑手:配送费和小费照拿,没有判责行
    r = rider_rows(no)
    if self_delivery:
        assert r == {}, (why, r)
    else:
        assert r == {"earning": share}, f"{why}:骑手该照拿 {share}:{r}"
    # 平台:佣金冲掉了;收顾客的 − 退顾客的 − 给骑手的 − 给商家的 = 0
    assert commission_of(no) == 0, why
    platform = o["total_cents"] - o["refund_cents"] - sum(r.values()) - sum(m.values())
    assert platform == 0, f"{why}:平台这单留了 {platform} 分(负数就是平台在贴钱)"
    audit_clean(no, why)
    p = today_payload()
    h = hash_no(no)
    assert not [x for x in p["merchant_rows"] if x["kind"].startswith("fault_")], \
        "判商家责任的行混进了 merchant_rows"
    mine = [x for x in p["merchant_fault_rows"] if x["o"] == h]
    assert mine == ([] if self_delivery else [{"o": h, "amount": -share, "kind": "fault_charge"}]), mine
    assert p["totals"]["merchant_fault"] == sum(x["amount"] for x in p["merchant_fault_rows"])
    assert verify_rows(p) == [], f"见证节点的逐行核账不过:{verify_rows(p)}"
    return {"total": o["total_cents"], "net": net, "share": share}


def after_sale_id(no) -> int:
    return next(a["id"] for a in call("GET", "/merchants/me/after-sales", boss)
                if a["order_no"] == no)


def main() -> None:
    w_start = call("GET", "/merchants/me/wallet", boss)

    # ============ 1. 商家同意售后(送达、顾客还没确认收货)============
    c1, _ = new_customer()
    a = place(c1)
    delivered(a)
    assert call("GET", f"/orders/{a}", c1)["status"] == "delivered"
    call("POST", f"/orders/{a}/after-sale", c1, {"reason": "面里吃出一根头发", "images": [EVIDENCE]})
    call("POST", f"/after-sales/{after_sale_id(a)}/accept", boss, {"reply": "抱歉,全额退您"})
    r1 = check_merchant_fault(a, c1, why="商家同意售后")
    print(f"✓ 商家同意售后:顾客拿回全款 ¥{r1['total'] / 100:.2f}(含配送费和小费);商家净额 "
          f"¥{r1['net'] / 100:.2f} 冲回、另出骑手那份 ¥{r1['share'] / 100:.2f};骑手照拿;"
          "平台这单 0;没确认收货的先结算再冲;审计、公开账本、见证核账都过")

    # ============ 2. 售后被拒,顾客申诉改判成立 ============
    c2, _ = new_customer()
    b = place(c2)
    delivered(b)
    go(c2, b, "completed")
    call("POST", f"/orders/{b}/after-sale", c2, {"reason": "少了一份米饭", "images": [EVIDENCE]})
    call("POST", f"/after-sales/{after_sale_id(b)}/reject", boss, {"reply": "出餐时是齐的"})
    ap = call("POST", "/appeals", c2, {"target_type": "after_sale_rejected",
                                       "target_id": after_sale_id(b),
                                       "reason": "打开袋子就少了一份,有照片"})
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "照片可证少了一份"})
    r2 = check_merchant_fault(b, c2, why="售后被拒改判")
    seen = call("GET", f"/orders/{b}/after-sale", c2)
    assert seen["status"] == "accepted" and seen["fault"] == "merchant", seen
    print(f"✓ 售后被拒改判成立:顾客拿回全款 ¥{r2['total'] / 100:.2f},商家另出 "
          f"¥{r2['share'] / 100:.2f};判商家责任")

    # ============ 3. 骑手到店未出餐,平台裁成退款 ============
    c3, _ = new_customer()
    c = place(c3)
    go(boss, c, "accepted")
    call("POST", f"/riders/grab/{c}", rider)
    issue = call("POST", "/riders/issues", rider,
                 {"order_no": c, "kind": "not_ready", "note": "到店等了 20 分钟还没出餐"})
    preview = next(i for i in call("GET", "/admin/delivery-issues?status=open", admin)
                   if i["id"] == issue["id"])
    oc = call("GET", f"/orders/{c}", c3)
    assert preview["refund_preview_cents"] == oc["total_cents"], preview
    assert preview["merchant_charge_preview_cents"] == oc["delivery_fee_cents"] + TIP, preview
    call("POST", f"/admin/delivery-issues/{issue['id']}/resolve", admin,
         {"action": "refund", "note": "商家没出餐,判商家责任"})
    r3 = check_merchant_fault(c, c3, why="到店未出餐")
    print(f"✓ 到店未出餐判商家责任:仲裁前就看到退 ¥{r3['total'] / 100:.2f}、商家另出 "
          f"¥{r3['share'] / 100:.2f};裁完各方金额同上")

    # ============ 4. 食安投诉核实成立 ============
    c4, _ = new_customer()
    d = place(c4)
    delivered(d)
    call("POST", "/food-safety", c4, {"order_no": d, "kind": "foreign_object",
                                      "description": "吃出一块塑料片,附照片",
                                      "images": ["https://example.com/evidence.jpg"]})
    fs = next(x for x in call("GET", "/admin/food-safety?status=open", admin)
              if x["order_no"] == d)
    call("POST", f"/admin/food-safety/{fs['id']}/confirm", admin, {"note": "凭证清晰,成立"})
    r4 = check_merchant_fault(d, c4, why="食安投诉成立")
    print(f"✓ 食安投诉成立:顾客拿回全款 ¥{r4['total'] / 100:.2f},商家另出 ¥{r4['share'] / 100:.2f}")

    # ============ 5. 用了停发之前的平台券 ============
    c5, phone5 = new_customer()
    cid = _run(grant_legacy_platform_coupon(phone5, 300, source=f"legacy:mfault:{tag}"))
    e = place(c5, coupon_id=cid)
    oe = call("GET", f"/orders/{e}", c5)
    assert oe["subsidy_cents"] == 300, oe["subsidy_cents"]
    delivered(e)
    go(c5, e, "completed")
    call("POST", f"/orders/{e}/after-sale", c5, {"reason": "菜是凉的,还有异味", "images": [EVIDENCE]})
    call("POST", f"/after-sales/{after_sale_id(e)}/accept", boss, {"reply": "抱歉,全额退您"})
    r5 = check_merchant_fault(e, c5, why="用了平台券")
    # 商家那份应收里含着平台券的 300(平台替顾客付给商家的),冲回之后这 300 回到平台自己手里
    assert r5["net"] == oe["food_cents"] + oe["packing_fee_cents"] - oe["discount_cents"] \
        - oe["commission_cents"], (r5, oe)
    print(f"✓ 用了平台券:顾客退他真付的 ¥{r5['total'] / 100:.2f},券那 ¥3.00 不退现金、回平台")

    # ============ 6. 商家自配送 ============
    call("PATCH", "/merchants/me", boss, {"self_delivery": True})
    try:
        c6, _ = new_customer()
        f = place(c6, tip=0)
        go(boss, f, "accepted")
        go(boss, f, "ready")
        go(boss, f, "picked_up")
        go(boss, f, "delivered")
    finally:
        call("PATCH", "/merchants/me", boss, {"self_delivery": False})
    call("POST", f"/orders/{f}/after-sale", c6, {"reason": "送到的时候汤洒了一半", "images": [EVIDENCE]})
    call("POST", f"/after-sales/{after_sale_id(f)}/accept", boss, {"reply": "抱歉,全额退您"})
    r6 = check_merchant_fault(f, c6, why="商家自配送", self_delivery=True)
    print(f"✓ 商家自配送:顾客拿回全款 ¥{r6['total'] / 100:.2f}(配送费在商家入账里,"
          "冲回净额就一起退了,没有另出的那行)")

    # ============ 7. 商家余额为负:可提现 0、提现被挡,审计不当错账报 ============
    w = call("GET", "/merchants/me/wallet", boss)
    owed = r1["share"] + r2["share"] + r3["share"] + r4["share"] + r5["share"]
    assert w["balance_cents"] == w_start["balance_cents"] - owed, (w, w_start, owed)
    assert w["balance_cents"] < 0 and w["withdrawable_cents"] == 0, w
    call("PUT", "/payout-account", boss, {"kind": "bank_corporate", "holder_name": "商家责任测试店",
                                          "account_no": "6222020200112233999",
                                          "bank_name": "工商银行测试支行"})
    err = call("POST", "/merchants/me/withdrawals", boss, {"amount_cents": 1000},
               expect_error=True)
    assert err["_error"] == 409 and "可提现" in err["detail"], err
    audit_clean(f, "余额为负")
    print(f"✓ 商家余额 ¥{w['balance_cents'] / 100:.2f}(这几单另出的 ¥{owed / 100:.2f}):"
          "可提现 0、提现被挡;之后的收入先抵;审计不当错账报")

    print("\ne2e_merchant_fault 全部通过 ✅")


if __name__ == "__main__":
    main()
