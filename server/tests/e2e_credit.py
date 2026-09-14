"""顾客信用分(services/customer_credit.py)端到端。

账号和数据都现造:一个管理员(注册后直连库改角色)、一家店、两个骑手、两个顾客,
不碰演示号 —— 演示号的历史订单会让分数的每一个断言都变成「在测库里攒下来的东西」。

**每一个分数都用 /transparency/credit 公示的数自己算一遍再比** —— 透明中心那一份
和系统算分用的必须是同一份,公示的公式对不上系统的分数,这个公示就是假的。

1. 新顾客:起始分、没有明细,在最高一档;
2. 看得到看不到:商家接单前(列表、详情)看不到、接单后看得到;骑手在抢单大厅、
   接单前的详情里看不到,接到之后看得到,别的骑手看不到;取消的单看不到;
3. 完成一单 +1,**交易对方看到的分数也跟着变**(缓存在完成那一刻真的失效了);
4. 配送时联系不上、平台判为顾客原因 −10,明细指得出是哪一单;这一单之后完成也不加分;
5. 走原来的申诉通道 → 改判 → 分数回来(交易对方看到的也回来),改判的那条列在「不再计分」里;
6. 违规 −10 / −20;走客服工单申诉 → 改判 → 回来、违规被推翻、工单有回复;
   维持原判的不回来、不能再申诉;工单申诉没下结论前工单关不掉;
7. 配送异常过了 72 小时:原通道接不上、工单申诉成立后不再计分;
8. 满 180 天的扣分自动不算;加分封顶、追加单和刷单确认的单不算;
9. 规则页三端都有这一节,商家端规则中心也有。

在 server/ 目录下运行:python -m tests.e2e_credit
"""
import asyncio
import time

from sqlalchemy import text

from tests.util import (call, drain_order_pool, register_fresh_rider, register_user,
                        unique_spot)

tag = str(int(time.time()))


def _run(coro):
    """跑完就 dispose 引擎:连接绑在创建它的事件循环上,跨 asyncio.run 复用会报错。"""
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


# ---------------- 造人造店 ----------------

admin, _ = register_user("customer", name="信用分e2e客服")
admin_id = call("GET", "/auth/me", admin)["id"]
# 管理员不开放注册:注册一个号再直连库改角色(require_role 每次请求都回库读角色)
sql("UPDATE users SET role = 'admin' WHERE id = :id", {"id": admin_id})

boss, _ = register_user("merchant", name="信用分e2e老板")
shop = call("POST", "/merchants", boss, {
    "name": f"信用分测试店-{tag}", "address": "测试路 35 号",
    "lat": 30.6612, "lng": 104.0823,
    "license_no": f"JYCREDIT{tag}", "license_image_url": "/uploads/license-demo.jpg"})
sid = shop["id"]
call("POST", f"/admin/merchants/{sid}/approve", admin)
call("PATCH", "/merchants/me", boss, {"is_open": True})
dish = call("POST", "/merchants/me/dishes", boss, {
    "name": f"信用分测试饭-{tag}", "price_cents": 2200, "stock": 500, "category": "主食"})

rider = _run(register_fresh_rider("信用分骑手"))
rider2 = _run(register_fresh_rider("路过的骑手"))

cust, _ = register_user("customer", name="信用分顾客")
cid = call("GET", "/auth/me", cust)["id"]

SPEC = call("GET", "/transparency/credit")
PLUS = SPEC["plus"][0]
MINUS = {m["key"]: m for m in SPEC["minus"]}
VIOL = {r["kind"]: r["points"] for r in MINUS["violation"]["items"]}


def by_spec(orders: int, deductions: list[int]) -> int:
    """照着公示的数算:起始分 + min(单数 × 每单分, 封顶) + 扣分(负数),夹在范围里。"""
    s = SPEC["base"] + min(orders * PLUS["points"], PLUS["cap"]) + sum(deductions)
    return max(SPEC["range"]["min"], min(SPEC["range"]["max"], s))


def level_label(score: int) -> str:
    return next(lv["label"] for lv in SPEC["levels"] if score >= lv["min"])


def mine(tok=None) -> dict:
    return call("GET", "/credit/me", tok or cust)


def expect(orders: int, deductions: list[int], why: str, tok=None) -> dict:
    want = by_spec(orders, deductions)
    got = mine(tok)
    assert got["score"] == want, f"{why}:公示算出 {want},系统给的 {got['score']}\n{got}"
    assert got["level_label"] == level_label(want), (got["level_label"], want)
    assert got["orders"]["count"] == orders, (why, got["orders"])
    assert sorted(d["points"] for d in got["deductions"]) == sorted(deductions), \
        (why, got["deductions"])
    brief = call("GET", "/credit/me/brief", tok or cust)
    assert brief["score"] == want, f"{why}:「我的」页那一行和明细页对不上:{brief}"
    return got


def find(rows, no):
    return next((o for o in rows if o["order_no"] == no), None)


def credit_seen_by(tok, no, *, detail=True):
    """这一单在这个人的订单列表(和详情)里带不带顾客信用分。"""
    row = find(call("GET", "/orders?limit=50", tok), no)
    seen = row.get("customer_credit") if row else None
    if detail:
        d = call("GET", f"/orders/{no}", tok)
        assert d.get("customer_credit") == seen, (no, d.get("customer_credit"), seen)
    return seen


def place(tok=None) -> str:
    lat, lng = unique_spot()
    o = call("POST", "/orders", tok or cust, {
        "merchant_id": sid, "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": f"信用分测试地址 {tag}", "lat": lat, "lng": lng})
    call("POST", f"/orders/{o['order_no']}/pay/mock", tok or cust)
    return o["order_no"]


def go(tok, no, to):
    return call("POST", f"/orders/{no}/transition", tok, {"to_status": to})


def to_picked_up(no: str):
    go(boss, no, "accepted")
    call("POST", f"/riders/grab/{no}", rider)
    go(boss, no, "ready")
    go(rider, no, "picked_up")


def customer_fault(no: str) -> int:
    """骑手报「联系不上顾客」,平台判为顾客原因(按送达处理)。返回异常工单 id。"""
    issue = call("POST", "/riders/issues", rider,
                 {"order_no": no, "kind": "cannot_contact", "note": "打了三次电话没人接"})
    call("POST", f"/admin/delivery-issues/{issue['id']}/resolve", admin,
         {"action": "mark_delivered", "note": "骑手有通话记录,判顾客原因"})
    return issue["id"]


def violation(kind: str, order_no: str | None, note: str) -> int:
    # 没有订单号就**别传这个键**:后台接口按 str(payload.get("order_no", "")) 取,
    # 传 null 会被存成字面的 "None"
    body = {"kind": kind, "subject_id": cid, "note": note}
    if order_no:
        body["order_no"] = order_no
    call("POST", "/admin/violations", admin, body)
    rows = call("GET", f"/admin/violations?subject_id={cid}", admin)["items"]
    return next(v["id"] for v in rows if v["kind"] == kind and v["order_no"] == order_no)


def ded(got: dict, kind: str, record_id: int) -> dict | None:
    return next((d for d in got["deductions"]
                 if d["kind"] == kind and d["record_id"] == record_id), None)


def main() -> None:
    fault_pts = MINUS["delivery_fault"]["points"]

    # ============ 1. 新顾客 ============
    got = expect(0, [], "新顾客")
    assert got["score"] == SPEC["base"] and got["level"] == SPEC["levels"][0]["key"], got
    assert got["deductions"] == [] and got["excluded"] == [], got
    assert got["rules"] == SPEC, "明细页带的公式和透明中心不是同一份"
    print(f"✓ 新顾客 {got['score']} 分「{got['level_label']}」,和没有问题的老用户同一档;"
          "明细页的公式就是透明中心那一份")

    # ============ 2. 看得到、看不到 ============
    _run(drain_order_pool())       # 抢单池只回前 50 条,先清场再下探针单
    a = place()
    assert credit_seen_by(boss, a) is None, "待接单(新单提醒 / 新单详情)不许看到顾客信用分"
    paid = call("GET", "/orders?status=paid&limit=50", boss)
    assert find(paid, a) and all(o.get("customer_credit") is None for o in paid)
    print("✓ 商家接单之前:列表、待接单筛选、详情里都没有顾客信用分")

    go(boss, a, "accepted")
    seen = credit_seen_by(boss, a)
    assert seen == {"score": SPEC["base"], "level": SPEC["levels"][0]["key"],
                    "level_label": SPEC["levels"][0]["label"]}, seen
    print(f"✓ 商家接单之后看得到:{seen['score']} 分「{seen['level_label']}」,只有分数和等级")

    pool = call("GET", "/riders/available-orders", rider)
    in_pool = find(pool, a)
    assert in_pool is not None, "探针单不在抢单池里,下面这条断言就是空的"
    assert in_pool.get("customer_credit") is None, "抢单大厅里不许出现顾客信用分"
    assert call("GET", f"/orders/{a}", rider, expect_error=True)["_error"] == 404
    assert find(call("GET", "/orders?limit=50", rider), a) is None
    print("✓ 骑手接单之前:抢单大厅里没有,详情 404,自己的订单列表里也没有这一单")

    call("POST", f"/riders/grab/{a}", rider)
    assert credit_seen_by(rider, a) == seen, "接到单的骑手应当看得到"
    assert call("GET", f"/orders/{a}", rider2, expect_error=True)["_error"] == 404
    assert call("GET", f"/orders/{a}", cust).get("customer_credit") is None, \
        "顾客自己的订单详情不带这一项(本人看明细页)"
    print("✓ 接到这一单的骑手看得到;别的骑手 404;顾客自己的订单详情里不带")

    go(boss, a, "ready")
    go(rider, a, "picked_up")
    go(rider, a, "delivered")
    go(cust, a, "completed")

    # ============ 3. 完成一单 +1,交易对方看到的也跟着变 ============
    # ⚠️ 先看交易对方、再看本人:本人的明细页每次现算并**顺手刷新缓存**,
    # 先调它的话,缓存漏打了也会被它补上,这几条断言就成了空的
    assert credit_seen_by(boss, a)["score"] == by_spec(1, []), \
        "商家那边还是接单时缓存的旧分 —— 订单完成时缓存没失效"
    assert credit_seen_by(rider, a)["score"] == by_spec(1, [])
    expect(1, [], "完成一单")
    print(f"✓ 完成一单 +{PLUS['points']} → {by_spec(1, [])},商家和骑手看到的同一时刻跟着变")

    # 取消的单不给
    d = place()
    go(boss, d, "accepted")
    go(cust, d, "cancelled")        # 接单后 2 分钟内,顾客的权利
    assert credit_seen_by(boss, d) is None, "取消了的单交易已经结束,不给"
    expect(1, [], "接单后 2 分钟内取消是权利,不扣分")
    print("✓ 取消了的单商家看不到;接单后 2 分钟内取消不扣分")

    # ============ 4. 配送时联系不上,判为顾客原因 ============
    b = place()
    to_picked_up(b)
    issue_b = customer_fault(b)
    assert credit_seen_by(boss, a)["score"] == by_spec(1, [fault_pts]), \
        "裁决之后商家看到的还是旧分 —— 裁决时缓存没失效"
    got = expect(1, [fault_pts], "配送判为顾客原因")
    row = ded(got, "delivery_fault", issue_b)
    assert row and row["order_no"] == b and row["points"] == fault_pts, got["deductions"]
    assert row["appeal"]["via"] == "appeal" and \
        row["appeal"]["target_type"] == "delivery_issue" and \
        row["appeal"]["target_id"] == issue_b, row["appeal"]
    assert "不再计分" in row["appeal"]["after"] and row["expires_at"], row
    print(f"✓ 联系不上判为顾客原因 {fault_pts} → {got['score']}「{got['level_label']}」;"
          f"明细指得出是异常工单 #{issue_b}(订单 {b[-6:]}),申诉走原通道")

    go(cust, b, "completed")
    expect(1, [fault_pts], "判为顾客原因的那一单完成了也不加分")
    print("✓ 那一单后来完成了也不算「完成一单」")

    # ============ 5. 原通道申诉 → 改判 → 分数回来 ============
    err = call("POST", "/credit/me/appeals", cust,
               {"kind": "delivery_fault", "record_id": issue_b,
                "reason": "我一直在家,电话也没响过"}, expect_error=True)
    assert err["_error"] == 409 and "72 小时" in err["detail"], err
    ap = call("POST", "/appeals", cust, {"target_type": "delivery_issue",
                                         "target_id": issue_b,
                                         "reason": "我一直在家,电话也没响过"})
    row = ded(mine(), "delivery_fault", issue_b)
    assert row["appeal"]["state"] == "open" and row["appeal"]["via"] == "", row["appeal"]
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:骑手拨的是旧号码"})
    assert credit_seen_by(boss, a)["score"] == by_spec(1, []), \
        "改判之后商家看到的没回来 —— 申诉改判时缓存没失效"
    got = expect(1, [], "原通道申诉改判")
    assert any(x["kind"] == "delivery_fault" and x["record_id"] == issue_b
               for x in got["excluded"]), got["excluded"]
    print("✓ 72 小时内不收工单(原通道改判连钱一起退);原通道改判后分数回来,"
          "那一条列在「不再计分」里,商家看到的同时回来")

    # ============ 6. 违规 + 走工单申诉 ============
    v_major = violation("malicious_after_sale", a, "同一话术在三家店要求全额退款")
    v_severe = violation("harassment", None, "在订单群里辱骂骑手")
    assert credit_seen_by(boss, a)["score"] == \
        by_spec(1, [VIOL["malicious_after_sale"], VIOL["harassment"]]), \
        "违规判定之后商家看到的还是旧分 —— 判定时缓存没失效"
    got = expect(1, [VIOL["malicious_after_sale"], VIOL["harassment"]], "两条违规")
    for vid in (v_major, v_severe):
        r = ded(got, "violation", vid)
        assert r and r["appeal"]["via"] == "ticket", (vid, got["deductions"])
    print(f"✓ 违规 {VIOL['malicious_after_sale']} / {VIOL['harassment']} → {got['score']}"
          f"「{got['level_label']}」,每条都指得出是哪条违规记录,申诉走客服工单")

    r = call("POST", "/credit/me/appeals", cust,
             {"kind": "violation", "record_id": v_severe,
              "reason": "那天骂人的是我朋友拿我手机发的,我可以当面说明"})
    tk = next(t for t in call("GET", "/tickets/mine", cust) if t["id"] == r["ticket_id"])
    assert tk["content"].startswith("【信用分申诉】"), tk
    assert ded(mine(), "violation", v_severe)["appeal"]["state"] == "open"
    dup = call("POST", "/credit/me/appeals", cust,
               {"kind": "violation", "record_id": v_severe, "reason": "再申诉一次试试"},
               expect_error=True)
    assert dup["_error"] == 409, dup
    other = call("POST", "/credit/me/appeals", register_user("customer")[0],
                 {"kind": "violation", "record_id": v_major, "reason": "不是我的记录我也来申诉"},
                 expect_error=True)
    assert other["_error"] == 404, other
    print(f"✓ 工单申诉提交(工单 #{r['ticket_id']});同一条不能提第二次,别人的记录 404")

    t_admin = next(t for t in call("GET", "/admin/tickets", admin) if t["id"] == r["ticket_id"])
    assert t_admin["credit_appeal"]["status"] == "open" and \
        t_admin["credit_appeal"]["record_id"] == v_severe, t_admin
    shut = call("POST", f"/admin/tickets/{r['ticket_id']}/close", admin, expect_error=True)
    assert shut["_error"] == 409, "信用分申诉没下结论,工单不许先关"
    call("POST", f"/admin/credit/appeals/{r['id']}/resolve", admin,
         {"result": "overturned", "note": "核实是他人借用手机"})
    assert credit_seen_by(boss, a)["score"] == by_spec(1, [VIOL["malicious_after_sale"]]), \
        "工单申诉成立之后商家看到的没回来 —— 缓存没失效"
    got = expect(1, [VIOL["malicious_after_sale"]], "工单申诉改判")
    assert any(x["kind"] == "violation" and x["record_id"] == v_severe
               for x in got["excluded"]), got["excluded"]
    vrow = next(v for v in call("GET", f"/admin/violations?subject_id={cid}", admin)["items"]
                if v["id"] == v_severe)
    assert vrow["overturned_at"], "申诉成立了违规记录却没被推翻 —— 处置级别不会跟着重算"
    tk = next(t for t in call("GET", "/tickets/mine", cust) if t["id"] == r["ticket_id"])
    assert tk["reply"].startswith("申诉成立"), tk
    print("✓ 工单申诉成立:那一条不再计分、违规记录被推翻、工单里有回复,商家看到的同时回来")

    r2 = call("POST", "/credit/me/appeals", cust,
              {"kind": "violation", "record_id": v_major, "reason": "我只是要回我该退的钱"})
    call("POST", f"/admin/credit/appeals/{r2['id']}/resolve", admin,
         {"result": "upheld", "note": "三家店的记录话术一致"})
    got = expect(1, [VIOL["malicious_after_sale"]], "维持原判")
    a2 = ded(got, "violation", v_major)["appeal"]
    assert a2["state"] == "upheld" and a2["via"] == "" and a2["note"], a2
    again = call("POST", "/credit/me/appeals", cust,
                 {"kind": "violation", "record_id": v_major, "reason": "再给我复核一次"},
                 expect_error=True)
    assert again["_error"] == 409, again
    print("✓ 维持原判:这一条继续计分,写明复核结论,不能再申诉")

    # ============ 7. 配送异常过了 72 小时:走工单 ============
    c = place()
    to_picked_up(c)
    issue_c = customer_fault(c)
    expect(1, [VIOL["malicious_after_sale"], fault_pts], "又一次判为顾客原因")
    sql("UPDATE delivery_issues SET resolved_at = now() - interval '4 days' WHERE id = :i",
        {"i": issue_c})
    row = ded(mine(), "delivery_fault", issue_c)
    assert row["appeal"]["via"] == "ticket", row["appeal"]
    late = call("POST", "/appeals", cust, {"target_type": "delivery_issue",
                                           "target_id": issue_c, "reason": "我当时在电梯里"},
                expect_error=True)
    assert late["_error"] == 422, late
    r3 = call("POST", "/credit/me/appeals", cust,
              {"kind": "delivery_fault", "record_id": issue_c, "reason": "我当时在电梯里,出来就回电了"})
    call("POST", f"/admin/credit/appeals/{r3['id']}/resolve", admin,
         {"result": "overturned", "note": "通话记录显示一分钟后回拨"})
    expect(1, [VIOL["malicious_after_sale"]], "过了 72 小时的配送异常,工单申诉成立")
    print("✓ 过了 72 小时:原通道 422,明细给的是工单入口;工单申诉成立后这一条不再计分")

    # ============ 8. 时间窗 ============
    v_old = violation("fake_order", c, "和商家串通下单")
    expect(1, [VIOL["malicious_after_sale"], VIOL["fake_order"]], "再记一条违规")
    days = SPEC["window_days"] + 1
    sql(f"UPDATE violations SET created_at = now() - interval '{days} days' WHERE id = :v",
        {"v": v_old})
    got = expect(1, [VIOL["malicious_after_sale"]], f"满 {SPEC['window_days']} 天")
    assert ded(got, "violation", v_old) is None
    print(f"✓ 满 {SPEC['window_days']} 天的扣分自动不算,不用谁去「修复」")

    # 加分封顶、追加单不算、刷单确认的不算、窗口外的不算:直连库给第二个顾客造单
    cust2, _ = register_user("customer", name="信用分老顾客")
    cid2 = call("GET", "/auth/me", cust2)["id"]
    n = PLUS["cap"] // PLUS["points"] + 2

    def seed(prefix, count, *, parent="", flags="NULL", ago="1 day"):
        sql(f"""
            INSERT INTO orders (order_no, customer_id, merchant_id, status, items, food_cents,
                packing_fee_cents, discount_cents, subsidy_cents, promo_note,
                delivery_fee_cents, total_cents, commission_cents, address, lat, lng,
                contact_name, contact_phone, remark, parent_order_no, pickup, pickup_code,
                cancel_reason, ready_alert_stage, ready_late, privacy_phone, refund_cents,
                refund_note, risk_flags, created_at, updated_at, completed_at)
            SELECT :p || lpad(g::text, 4, '0'), :c, :m, 'completed', '[]'::jsonb, 2000,
                0, 0, 0, '', 300, 2300, 100, '信用分造单', 30.66, 104.08, '', '', '',
                :parent, false, '', '', 0, false, '', 0, '', {flags},
                now() - interval '{ago}', now() - interval '{ago}', now() - interval '{ago}'
            FROM generate_series(1, :n) g""",
            {"p": f"cr{prefix}{tag}", "c": cid2, "m": sid, "n": count, "parent": parent})

    seed("ok", n)
    seed("ap", 2, parent="SOMEORIGINAL")
    seed("fk", 2, flags="'{\"hits\": [\"addr_freq\"], \"status\": \"confirmed\"}'::jsonb")
    seed("old", 3, ago=f"{SPEC['window_days'] + 5} days")
    got = expect(n, [], "封顶", tok=cust2)
    assert got["plus"] == PLUS["cap"] and got["score"] == by_spec(n, []), got
    print(f"✓ {n} 单正常完成只加 {PLUS['cap']}(封顶);追加单、刷单确认的单、"
          f"{SPEC['window_days']} 天前的单都不算")

    # ============ 9. 规则页 ============
    rc = call("GET", "/rules/customer")
    sec = next(s for s in rc["sections"] if s["title"] == "信用分")
    assert any(str(SPEC["base"]) in i for i in sec["items"]), sec
    rm = next(s for s in call("GET", "/rules/merchant")["sections"] if s["title"] == "顾客信用分")
    rr = next(s for s in call("GET", "/rules/rider")["sections"] if s["title"] == "顾客信用分")
    assert rm["items"] == rr["items"], "商家和骑手读到的顾客信用分规则不一样"
    mine_rules = call("GET", "/merchants/me/rules", boss)
    assert any(s["title"] == "顾客信用分" for s in mine_rules["sections"]), mine_rules
    never = "".join(SPEC["never_used_for"])
    assert all(w in never for w in ("拒单", "派单", "价格")), never
    print("✓ 规则页:顾客一节讲怎么算,商家、骑手一节一字不差讲能看到什么、不许拿它做什么")

    print("\ne2e_credit 全部通过 ✅")


if __name__ == "__main__":
    main()
