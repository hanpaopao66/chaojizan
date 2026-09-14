"""商家、骑手的信用分(services/credit.py)端到端 —— 和顾客的同一套机制。

账号和数据都现造:一个管理员(注册后直连库改角色)、两家店、三个骑手、两个顾客,
不碰演示号 —— 演示号的历史订单会让每一个分数断言都变成「在测库里攒下来的东西」。

**每一个分数都用 /transparency/credit?role= 公示的数自己算一遍再比**。

1. 新店主、新骑手:起始分、最高一档;没有店的商家号没有这一页;
2. 看得到看不到:顾客在商家接单后看得到商家的、骑手接单后看得到骑手的;商家在骑手接单后
   看得到骑手的;骑手接到单后看得到商家的;接单前、抢单大厅、抢单回执、店铺页、列表、
   搜索、取消的单一律没有;
3. 完成一单:顾客、店主、骑手三方的分同一时刻跟着变(缓存在完成那一刻真的失效了);
4. 权利不扣分:接单前拒单、接单后取消、转单;
5. 配送异常判骑手责任(先行赔付)−10,那一单不算骑手完成一单;72 小时内工单不收,
   走原通道改判后分数回来;
6. 售后判骑手责任 −10,只能走工单申诉,成立后回来;
7. 商家拒绝的售后被顾客申诉改判 −10;商家自己同意的不算;原通道再申诉改判后回来;
   过了 72 小时走工单,维持原判的不回来、不能再申诉;
8. 违规成立按严重程度扣,判定那一刻交易对方看到的就变;工单申诉成立的违规被推翻;
9. 满 180 天的扣分不算;加分封顶;追加单、刷单确认的单不算,没送到的那一单不算骑手的;
10. 规则页三端都有「信用分」「交易对方的信用分」两节;后台看得到三种角色的明细和申诉。

在 server/ 目录下运行:python -m tests.e2e_credit_roles
"""
import asyncio
import json
import time
from urllib.parse import quote

from sqlalchemy import text

from tests.util import (call, drain_order_pool, register_fresh_rider, register_user,
                        unique_spot)

tag = str(int(time.time()))
EVIDENCE = ["/uploads/demo-evidence-1.jpg"]
CREDIT_KEYS = ("customer_credit", "merchant_credit", "rider_credit")


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


def me_id(tok) -> int:
    return call("GET", "/auth/me", tok)["id"]


# ---------------- 造人造店 ----------------

admin, _ = register_user("customer", name="三方信用分e2e客服")
sql("UPDATE users SET role = 'admin' WHERE id = :id", {"id": me_id(admin)})


def open_shop(boss: str, name: str, lat: float, lng: float) -> tuple[int, dict]:
    shop = call("POST", "/merchants", boss, {
        "name": f"{name}-{tag}", "address": "测试路 36 号", "lat": lat, "lng": lng,
        "license_no": f"JYROLE{name[-1]}{tag}", "license_image_url": "/uploads/license-demo.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    call("PATCH", "/merchants/me", boss, {"is_open": True})
    dish = call("POST", "/merchants/me/dishes", boss, {
        "name": f"{name}的饭-{tag}", "price_cents": 2200, "stock": 500, "category": "主食"})
    return shop["id"], dish


boss, _ = register_user("merchant", name="三方信用分店主")
boss_id = me_id(boss)
sid, dish = open_shop(boss, "三方信用分测试店A", 30.6612, 104.0823)

rider = _run(register_fresh_rider("三方信用分骑手"))
rider_id = me_id(rider)
rider2 = _run(register_fresh_rider("路过的骑手"))

cust, _ = register_user("customer", name="三方信用分顾客")
cust2, _ = register_user("customer", name="三方信用分顾客二")

SPEC = {r: call("GET", f"/transparency/credit?role={r}") for r in ("merchant", "rider")}
FAULT = {r: next(m["points"] for m in SPEC[r]["minus"] if m["key"] != "violation")
         for r in SPEC}
VIOL = {r: {it["kind"]: it["points"] for m in SPEC[r]["minus"] if m["key"] == "violation"
            for it in m["items"]} for r in SPEC}


def by_spec(role: str, orders: int, deductions: list[int]) -> int:
    """照着公示的数算:起始分 + min(单数 × 每单分, 封顶) + 扣分(负数),夹在范围里。"""
    s = SPEC[role]
    plus = s["plus"][0]
    v = s["base"] + min(orders * plus["points"], plus["cap"]) + sum(deductions)
    return max(s["range"]["min"], min(s["range"]["max"], v))


def level_label(role: str, score: int) -> str:
    return next(lv["label"] for lv in SPEC[role]["levels"] if score >= lv["min"])


def expect(tok, role: str, orders: int, deductions: list[int], why: str) -> dict:
    want = by_spec(role, orders, deductions)
    got = call("GET", "/credit/me", tok)
    assert got["role"] == role, got
    assert got["score"] == want, f"{why}:公示算出 {want},系统给的 {got['score']}\n{got}"
    assert got["level_label"] == level_label(role, want), (why, got["level_label"], want)
    assert got["orders"]["count"] == orders, (why, got["orders"])
    assert sorted(d["points"] for d in got["deductions"]) == sorted(deductions), \
        (why, got["deductions"])
    brief = call("GET", "/credit/me/brief", tok)
    assert brief["score"] == want, f"{why}:「我的」那一行和明细页对不上:{brief}"
    return got


def find(rows, no):
    return next((o for o in rows if o["order_no"] == no), None)


def view(tok, no) -> dict:
    """这一单在这个人那里的订单详情;列表里也有这一单的话,两处的信用分必须一致。"""
    d = call("GET", f"/orders/{no}", tok)
    row = find(call("GET", "/orders?limit=50", tok), no)
    if row is not None:
        for k in CREDIT_KEYS:
            assert row.get(k) == d.get(k), (no, k, row.get(k), d.get(k))
    return d


def no_credit(obj, where: str) -> None:
    blob = json.dumps(obj, ensure_ascii=False)
    for k in CREDIT_KEYS:
        assert f'"{k}": {{' not in blob, f"{where}里出现了 {k}:{blob[:300]}"


def place(tok=None, shop_id=None, dish_id=None) -> str:
    lat, lng = unique_spot()
    o = call("POST", "/orders", tok or cust, {
        "merchant_id": shop_id or sid,
        "items": [{"dish_id": dish_id or dish["id"], "quantity": 1}],
        "address": f"三方信用分测试地址 {tag}", "lat": lat, "lng": lng})
    call("POST", f"/orders/{o['order_no']}/pay/mock", tok or cust)
    return o["order_no"]


def go(tok, no, to, **extra):
    return call("POST", f"/orders/{no}/transition", tok, {"to_status": to, **extra})


def picked_up(no: str):
    go(boss, no, "accepted")
    call("POST", f"/riders/grab/{no}", rider)
    go(boss, no, "ready")
    go(rider, no, "picked_up")


def completed(tok=None) -> str:
    no = place(tok)
    picked_up(no)
    go(rider, no, "delivered")
    go(tok or cust, no, "completed")
    return no


def ded(got: dict, kind: str, record_id: int) -> dict | None:
    return next((d for d in got["deductions"]
                 if d["kind"] == kind and d["record_id"] == record_id), None)


def excluded(got: dict, kind: str, record_id: int) -> bool:
    return any(x["kind"] == kind and x["record_id"] == record_id for x in got["excluded"])


def after_sale(tok, no) -> int:
    call("POST", f"/orders/{no}/after-sale", tok,
         {"reason": "汤洒了大半,盒子是破的", "images": EVIDENCE})
    return next(a["id"] for a in call("GET", "/admin/after-sales?days=7", admin)
                if a["order_no"] == no)


def merchant_fault(tok, no) -> int:
    """商家拒绝售后 → 顾客申诉 → 平台改判为商家责任。返回售后 id。"""
    aid = after_sale(tok, no)
    call("POST", f"/after-sales/{aid}/reject", boss, {"reply": "出餐时是好的"})
    ap = call("POST", "/appeals", tok, {"target_type": "after_sale_rejected",
                                        "target_id": aid, "reason": "照片可证盒子是破的"})
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:照片可证,该售后应当受理"})
    return aid


def violation(subject_id: int, kind: str, order_no: str | None, note: str) -> int:
    # 没有订单号就**别传这个键**:后台接口按 str(payload.get("order_no", "")) 取
    body = {"kind": kind, "subject_id": subject_id, "note": note}
    if order_no:
        body["order_no"] = order_no
    call("POST", "/admin/violations", admin, body)
    rows = call("GET", f"/admin/violations?subject_id={subject_id}", admin)["items"]
    return next(v["id"] for v in rows if v["kind"] == kind and v["order_no"] == order_no)


def ticket_resolve(appeal_id: int, result: str, note: str):
    return call("POST", f"/admin/credit/appeals/{appeal_id}/resolve", admin,
                {"result": result, "note": note})


def main() -> None:  # noqa: C901 —— 一条用例从头走到尾,拆开了反而看不出因果
    base_m, base_r = SPEC["merchant"]["base"], SPEC["rider"]["base"]
    m_orders, r_orders = 0, 0

    # ============ 1. 新店主、新骑手 ============
    got = expect(boss, "merchant", 0, [], "新店主")
    assert got["rules"] == SPEC["merchant"], "明细页带的公式和透明中心不是同一份"
    assert got["deductions"] == [] and got["excluded"] == [] and got["seen_by"], got
    got = expect(rider, "rider", 0, [], "新骑手")
    assert got["rules"] == SPEC["rider"]
    assert got["level"] == SPEC["rider"]["levels"][0]["key"], got
    nostore, _ = register_user("merchant", name="还没开店的商家号")
    err = call("GET", "/credit/me", nostore, expect_error=True)
    assert err["_error"] == 404 and "店主" in err["detail"], err
    bogus = call("GET", "/transparency/credit?role=nobody", expect_error=True)
    assert bogus["_error"] == 422, bogus
    print(f"✓ 新店主 {base_m}、新骑手 {base_r},都在最高一档;没开店的商家号没有这一页;"
          "明细页的公式就是透明中心那一份")

    # ============ 2. 看得到、看不到 ============
    _run(drain_order_pool())       # 抢单池只回前 50 条,先清场再下探针单
    a = place()
    d = view(cust, a)
    assert all(d.get(k) is None for k in CREDIT_KEYS), f"待接单时顾客看到了分数:{d}"
    go(boss, a, "accepted")
    d = view(cust, a)
    assert d["merchant_credit"] == {"score": base_m, "level": "good",
                                    "level_label": SPEC["merchant"]["levels"][0]["label"]}, d
    assert d["rider_credit"] is None, "还没有骑手接单,顾客不该看到骑手的分"
    assert d["customer_credit"] is None, "顾客自己的订单详情不带自己的分(本人看明细页)"
    assert view(boss, a)["rider_credit"] is None
    print(f"✓ 商家接单之后顾客看得到商家的分({d['merchant_credit']['score']}),只有分数和等级;"
          "骑手接单之前谁都看不到骑手的")

    pool = call("GET", "/riders/available-orders", rider)
    in_pool = find(pool, a)
    assert in_pool is not None, "探针单不在抢单池里,下面这条断言就是空的"
    assert all(in_pool.get(k) is None for k in CREDIT_KEYS), f"抢单大厅里出现了分数:{in_pool}"
    no_credit(pool, "抢单大厅")
    grab = call("POST", f"/riders/grab/{a}", rider)
    assert all(grab.get(k) is None for k in CREDIT_KEYS), "抢单回执里不许带分数"
    assert call("GET", f"/orders/{a}", rider2, expect_error=True)["_error"] == 404
    d = view(cust, a)
    assert d["rider_credit"]["score"] == base_r and d["merchant_credit"]["score"] == base_m, d
    assert view(boss, a)["rider_credit"]["score"] == base_r
    r_view = view(rider, a)
    assert r_view["merchant_credit"]["score"] == base_m and r_view["customer_credit"], r_view
    print("✓ 抢单大厅、抢单回执里没有;骑手接到单之后:顾客、商家看得到骑手的,"
          "骑手看得到商家和顾客的;别的骑手 404")

    shop_page = call("GET", f"/merchants/{sid}")
    assert shop_page["id"] == sid
    no_credit(shop_page, "店铺页")
    no_credit(call("GET", "/merchants?lat=30.6612&lng=104.0823"), "店铺列表")
    hits = call("GET", f"/merchants/search?q={quote(f'三方信用分测试店A-{tag}')}"
                       "&lat=30.6612&lng=104.0823")
    assert any(m["id"] == sid for m in hits), "搜索探针没搜到这家店,下面那条断言就是空的"
    no_credit(hits, "搜索结果")
    ready = go(boss, a, "ready")
    assert all(ready.get(k) is None for k in CREDIT_KEYS), "状态流转回执里不许带分数"
    print("✓ 店铺页、店铺列表、搜索、状态流转回执里都没有信用分")

    go(rider, a, "picked_up")
    go(rider, a, "delivered")
    go(cust, a, "completed")
    m_orders, r_orders = 1, 1
    # ⚠️ 先看交易对方、再看本人:本人的明细页每次现算并**顺手刷新缓存**,
    # 先调它的话缓存漏打了也会被它补上,这几条断言就成了空的
    d = view(cust, a)
    assert d["merchant_credit"]["score"] == by_spec("merchant", 1, []), \
        "顾客看到的还是接单时缓存的商家旧分 —— 订单完成时店主的缓存没失效"
    assert d["rider_credit"]["score"] == by_spec("rider", 1, []), \
        "顾客看到的还是骑手的旧分 —— 订单完成时骑手的缓存没失效"
    assert view(boss, a)["rider_credit"]["score"] == by_spec("rider", 1, [])
    assert view(rider, a)["merchant_credit"]["score"] == by_spec("merchant", 1, [])
    expect(boss, "merchant", 1, [], "完成一单")
    expect(rider, "rider", 1, [], "完成一单")
    print(f"✓ 完成一单:店主、骑手各 +{SPEC['merchant']['plus'][0]['points']},"
          "交易对方同一时刻看到的就是新分")

    c0 = place()
    go(boss, c0, "accepted")
    go(cust, c0, "cancelled")
    assert view(cust, c0)["merchant_credit"] is None, "取消了的单交易已经结束,不给"
    print("✓ 取消了的单顾客看不到商家的分")

    # ============ 3. 权利不扣分 ============
    f = place()
    go(boss, f, "cancelled", reason="今天这道菜卖完了")           # 接单前拒单
    g = place()
    go(boss, g, "accepted")
    call("POST", f"/riders/grab/{g}", rider)
    call("POST", f"/riders/transfer/{g}", rider, {"reason": "vehicle_broken"})   # 转单
    go(boss, g, "cancelled", reason="骑手转单后临时缺货")          # 接单后取消
    expect(boss, "merchant", m_orders, [], "接单前拒单、接单后取消")
    expect(rider, "rider", r_orders, [], "转单")
    print("✓ 接单前拒单、接单后取消(没有被判「私自取消」)、转单:都不扣分")

    # ============ 4. 配送异常判为骑手责任(先行赔付)============
    b = place()
    picked_up(b)
    issue = call("POST", "/riders/issues", rider,
                 {"order_no": b, "kind": "food_damaged", "note": "路上摔了一跤,汤全洒了",
                  "photo_url": EVIDENCE[0]})
    call("POST", f"/admin/delivery-issues/{issue['id']}/resolve", admin,
         {"action": "refund", "note": "餐损,判骑手责任,平台先行赔付"})
    m_orders += 1          # 这一单先行赔付后完成:商家这一环做成了,算商家的
    fp = FAULT["rider"]
    assert view(cust, a)["rider_credit"]["score"] == by_spec("rider", r_orders, [fp]), \
        "裁决之后顾客看到的还是骑手的旧分 —— 裁决时缓存没失效"
    assert view(cust, a)["merchant_credit"]["score"] == by_spec("merchant", m_orders, [])
    got = expect(rider, "rider", r_orders, [fp], "配送异常判为骑手责任")
    row = ded(got, "delivery_fault", issue["id"])
    assert row and row["order_no"] == b and "骑手责任" in row["title"], got["deductions"]
    assert row["appeal"]["via"] == "appeal" and \
        row["appeal"]["target_type"] == "delivery_issue", row["appeal"]
    assert "不再计分" in row["appeal"]["confirm"], row["appeal"]
    expect(boss, "merchant", m_orders, [], "先行赔付的那一单商家照样算完成")
    print(f"✓ 配送异常判骑手责任 {fp} → {got['score']};那一单没送到,不算骑手完成一单,"
          "算商家的;申诉走原通道")

    err = call("POST", "/credit/me/appeals", rider,
               {"kind": "delivery_fault", "record_id": issue["id"],
                "reason": "是顾客家门口的台阶塌了"}, expect_error=True)
    assert err["_error"] == 409 and "72 小时" in err["detail"], err
    ap = call("POST", "/appeals", rider, {"target_type": "delivery_issue",
                                          "target_id": issue["id"],
                                          "reason": "是顾客家门口的台阶塌了,我有照片"})
    assert ded(call("GET", "/credit/me", rider), "delivery_fault",
               issue["id"])["appeal"]["state"] == "open"
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:台阶塌陷,非骑手责任"})
    assert view(cust, a)["rider_credit"]["score"] == by_spec("rider", r_orders, []), \
        "原通道改判之后顾客看到的没回来 —— 申诉改判时缓存没失效"
    got = expect(rider, "rider", r_orders, [], "原通道改判")
    assert excluded(got, "delivery_fault", issue["id"]), got["excluded"]
    print("✓ 72 小时内不收工单;原通道改判后分数回来,那一条列在「不再计分」里")

    # ============ 5. 售后判为骑手责任 ============
    c = completed()
    m_orders += 1
    r_orders += 1
    as_c = after_sale(cust, c)
    call("POST", f"/admin/after-sales/{as_c}/rider-fault", admin,
         {"reason": "餐盒侧翻,配送责任"})
    assert view(boss, c)["rider_credit"]["score"] == by_spec("rider", r_orders, [fp]), \
        "售后判骑手责任之后商家看到的还是旧分 —— 判责时缓存没失效"
    got = expect(rider, "rider", r_orders, [fp], "售后判为骑手责任")
    row = ded(got, "after_sale_fault", as_c)
    assert row and row["order_no"] == c and row["appeal"]["via"] == "ticket", got["deductions"]
    r = call("POST", "/credit/me/appeals", rider,
             {"kind": "after_sale_fault", "record_id": as_c,
              "reason": "取餐时盒子就是裂的,我拍了照"})
    t_admin = next(t for t in call("GET", "/admin/tickets", admin) if t["id"] == r["ticket_id"])
    ca = t_admin["credit_appeal"]
    assert ca["role"] == "rider" and ca["record_id"] == as_c and "骑手" in ca["kind_label"], ca
    assert t_admin["content"].startswith("【信用分申诉】骑手"), t_admin["content"]
    ticket_resolve(r["id"], "overturned", "取餐照片显示餐盒出店前已破")
    got = expect(rider, "rider", r_orders, [], "售后判责工单申诉成立")
    assert excluded(got, "after_sale_fault", as_c), got["excluded"]
    tk = next(t for t in call("GET", "/tickets/mine", rider) if t["id"] == r["ticket_id"])
    assert tk["reply"].startswith("申诉成立"), tk
    print("✓ 售后判骑手责任扣分、交易对方同时看到;没有原通道就走工单,后台看得出是骑手的哪一条;"
          "成立后回来")

    # ============ 6. 商家:拒绝的售后被改判为商家责任 ============
    d2 = completed(cust2)
    m_orders += 1
    r_orders += 1
    as_d2 = merchant_fault(cust2, d2)
    mp = FAULT["merchant"]
    assert view(rider, d2)["merchant_credit"]["score"] == by_spec("merchant", m_orders, [mp]), \
        "改判之后骑手看到的还是商家的旧分 —— 申诉改判时店主的缓存没失效"
    got = expect(boss, "merchant", m_orders, [mp], "售后被改判为商家责任")
    row = ded(got, "after_sale_fault", as_d2)
    assert row and row["order_no"] == d2 and row["note"], got["deductions"]
    assert row["appeal"]["via"] == "appeal" and \
        row["appeal"]["target_type"] == "after_sale", row["appeal"]
    err = call("POST", "/credit/me/appeals", boss,
               {"kind": "after_sale_fault", "record_id": as_d2, "reason": "出餐前拍过照"},
               expect_error=True)
    assert err["_error"] == 409 and "72 小时" in err["detail"], err
    ap = call("POST", "/appeals", boss, {"target_type": "after_sale", "target_id": as_d2,
                                         "reason": "出餐前拍过照,盒子完好"})
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "复核:出餐照完好,系配送途中损坏"})
    got = expect(boss, "merchant", m_orders, [], "商家对改判再申诉成立")
    assert excluded(got, "after_sale_fault", as_d2), got["excluded"]
    print(f"✓ 拒绝的售后被顾客申诉改判 {mp};商家对改判再申诉成立后回来,列在「不再计分」里")

    e = completed()
    m_orders += 1
    r_orders += 1
    as_e = after_sale(cust, e)
    call("POST", f"/after-sales/{as_e}/accept", boss, {"reply": "抱歉,已退款"})
    expect(boss, "merchant", m_orders, [], "商家自己同意的售后")
    print("✓ 商家自己同意的售后退款不扣分")

    h = completed(cust2)
    m_orders += 1
    r_orders += 1
    as_h = merchant_fault(cust2, h)
    sql("UPDATE after_sales SET processed_at = now() - interval '4 days' WHERE id = :i",
        {"i": as_h})
    got = expect(boss, "merchant", m_orders, [mp], "又一条商家责任")
    assert ded(got, "after_sale_fault", as_h)["appeal"]["via"] == "ticket"
    late = call("POST", "/appeals", boss, {"target_type": "after_sale", "target_id": as_h,
                                           "reason": "我不认同这个改判"}, expect_error=True)
    assert late["_error"] == 422, late
    r = call("POST", "/credit/me/appeals", boss,
             {"kind": "after_sale_fault", "record_id": as_h, "reason": "我不认同这个改判"})
    ticket_resolve(r["id"], "upheld", "顾客照片清楚,维持")
    got = expect(boss, "merchant", m_orders, [mp], "工单维持原判")
    a2 = ded(got, "after_sale_fault", as_h)["appeal"]
    assert a2["state"] == "upheld" and a2["via"] == "" and a2["note"], a2
    again = call("POST", "/credit/me/appeals", boss,
                 {"kind": "after_sale_fault", "record_id": as_h, "reason": "再给我复核一次"},
                 expect_error=True)
    assert again["_error"] == 409, again
    print("✓ 过了 72 小时:原通道 422,走工单;维持原判的继续计分、写明结论、不能再申诉")

    # ============ 7. 违规 ============
    v_m = violation(boss_id, "fake_ready", c, "三次到店都还没开始做就点了出餐")
    assert view(cust, a)["merchant_credit"]["score"] == \
        by_spec("merchant", m_orders, [mp, VIOL["merchant"]["fake_ready"]]), \
        "违规判定之后顾客看到的还是商家的旧分 —— 判定时缓存没失效"
    got = expect(boss, "merchant", m_orders, [mp, VIOL["merchant"]["fake_ready"]], "商家违规")
    assert ded(got, "violation", v_m)["appeal"]["via"] == "ticket"
    v_theft = violation(rider_id, "theft", None, "顾客的饮料被喝掉了一半")
    v_fake = violation(rider_id, "fake_delivery", e, "没送到楼下就点了送达")
    got = expect(rider, "rider", r_orders,
                 [VIOL["rider"]["theft"], VIOL["rider"]["fake_delivery"]], "骑手两条违规")
    r = call("POST", "/credit/me/appeals", rider,
             {"kind": "violation", "record_id": v_theft,
              "reason": "那杯饮料是商家没封好,出店时就洒了"})
    ticket_resolve(r["id"], "overturned", "商家承认封口没压好")
    got = expect(rider, "rider", r_orders, [VIOL["rider"]["fake_delivery"]], "违规申诉成立")
    assert excluded(got, "violation", v_theft), got["excluded"]
    vrow = next(v for v in call("GET", f"/admin/violations?subject_id={rider_id}",
                                admin)["items"] if v["id"] == v_theft)
    assert vrow["overturned_at"], "申诉成立了违规记录却没被推翻 —— 处置级别不会跟着重算"
    other = call("POST", "/credit/me/appeals", boss,
                 {"kind": "violation", "record_id": v_fake, "reason": "不是我的记录我也来申诉"},
                 expect_error=True)
    assert other["_error"] == 404, other
    print(f"✓ 违规按严重程度扣({VIOL['rider']['theft']} / {VIOL['rider']['fake_delivery']}),"
          "判定那一刻交易对方看到的就变;工单申诉成立的违规被推翻;别人的记录 404")

    # ============ 8. 时间窗 ============
    days = SPEC["rider"]["window_days"] + 1
    sql(f"UPDATE violations SET created_at = now() - interval '{days} days' WHERE id = :v",
        {"v": v_fake})
    got = expect(rider, "rider", r_orders, [], f"满 {SPEC['rider']['window_days']} 天")
    assert ded(got, "violation", v_fake) is None
    print(f"✓ 满 {SPEC['rider']['window_days']} 天的扣分自动不算")

    # ============ 9. 加分封顶、不算的单 ============
    boss2, _ = register_user("merchant", name="三方信用分老店")
    sid2, _dish2 = open_shop(boss2, "三方信用分测试店B", 30.6630, 104.0850)
    rider3 = _run(register_fresh_rider("三方信用分老骑手"))
    rid3 = me_id(rider3)
    cid = me_id(cust)
    n = SPEC["rider"]["plus"][0]["cap"] // SPEC["rider"]["plus"][0]["points"] + 2

    def seed(prefix, count, *, parent="", flags="NULL", ago="1 day"):
        sql(f"""
            INSERT INTO orders (order_no, customer_id, merchant_id, rider_id, status, items,
                food_cents, packing_fee_cents, discount_cents, subsidy_cents, promo_note,
                delivery_fee_cents, total_cents, commission_cents, address, lat, lng,
                contact_name, contact_phone, remark, parent_order_no, pickup, pickup_code,
                cancel_reason, ready_alert_stage, ready_late, privacy_phone, refund_cents,
                refund_note, risk_flags, created_at, updated_at, completed_at)
            SELECT :p || lpad(g::text, 4, '0'), :c, :m, :r, 'completed', '[]'::jsonb, 2000,
                0, 0, 0, '', 300, 2300, 100, '信用分造单', 30.66, 104.08, '', '', '',
                :parent, false, '', '', 0, false, '', 0, '', {flags},
                now() - interval '{ago}', now() - interval '{ago}', now() - interval '{ago}'
            FROM generate_series(1, :n) g""",
            {"p": f"crr{prefix}{tag}", "c": cid, "m": sid2, "r": rid3, "n": count,
             "parent": parent})

    seed("ok", n)
    seed("ap", 2, parent="SOMEORIGINAL")
    seed("fk", 2, flags="'{\"hits\": [\"addr_freq\"], \"status\": \"confirmed\"}'::jsonb")
    seed("old", 3, ago=f"{SPEC['rider']['window_days'] + 5} days")
    seed("rf", 1)
    sql("""INSERT INTO delivery_issues (order_id, order_no, rider_id, kind, note, photo_url,
               status, resolution, resolve_note, created_at, resolved_at)
           SELECT id, order_no, :r, 'food_damaged', '', '', 'resolved', 'refund', '造单',
               now(), now() FROM orders WHERE order_no = :no""",
        {"r": rid3, "no": f"crrrf{tag}0001"})
    got = expect(boss2, "merchant", n + 1, [], "店主封顶")
    assert got["plus"] == SPEC["merchant"]["plus"][0]["cap"], got
    assert len(got["orders"]["recent"]) == SPEC["merchant"]["plus"][0]["cap"], got["orders"]
    expect(rider3, "rider", n, [FAULT["rider"]], "骑手封顶")
    print(f"✓ {n} 单正常完成只加 {SPEC['rider']['plus'][0]['cap']}(封顶);追加单、刷单确认的单、"
          f"{SPEC['rider']['window_days']} 天前的单都不算;先行赔付的那一单算店主的、不算骑手的")

    # ============ 10. 规则页、后台 ============
    for aud in ("customer", "merchant", "rider"):
        secs = {s["title"]: s["items"] for s in call("GET", f"/rules/{aud}")["sections"]}
        assert "信用分" in secs and "交易对方的信用分" in secs, (aud, list(secs))
        assert any(str(SPEC["merchant"]["base"]) in i for i in secs["信用分"]), secs["信用分"]
    mine_rules = {s["title"] for s in call("GET", "/merchants/me/rules", boss)["sections"]}
    assert {"信用分", "交易对方的信用分"} <= mine_rules, mine_rules
    adm = call("GET", f"/admin/users/{rider_id}/credit", admin)
    assert adm["role"] == "rider" and adm["score"] == call("GET", "/credit/me", rider)["score"]
    adm = call("GET", f"/admin/users/{boss_id}/credit", admin)
    assert adm["role"] == "merchant" and adm["score"] == call("GET", "/credit/me", boss)["score"]
    assert call("GET", f"/admin/users/{me_id(nostore)}/credit", admin,
                expect_error=True)["_error"] == 404
    listed = call("GET", "/admin/credit/appeals?status=upheld", admin)
    assert any(x["role"] == "merchant" and x["record_id"] == as_h for x in listed), listed
    print("✓ 规则页三端都有「信用分」「交易对方的信用分」;后台看得到店主和骑手的明细、"
          "申诉列表带角色")

    print("\ne2e_credit_roles 全部通过 ✅")


if __name__ == "__main__":
    main()
