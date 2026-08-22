"""账务自检的覆盖矩阵:每条恒等式都要**真的抓得到人**。

审计是这个平台的资金安全网,而安全网只有一个考核标准:
往里扔一笔坏账,它得叫。全绿本身不是成绩 —— 上一轮审查里
每一个资金 bug 审计都是全绿的,因为错误要么发生在恒等式两边,
要么正好落在排除条件里。

所以这条用例反着写:**故意把账做坏,断言自检报出对应的 check 名**,
然后复原,再断言复原后它不再报。造坏账一律直接改库 ——
经业务接口是造不出来的(接口那边正在被堵),而审计的职责恰恰是
"不管这行数据怎么进来的,对不上就得叫"。

同时钉住两条"不许叫"的:商家余额口径必须和钱包完全一致
(漏住宿净额 / 连锁按店重复扣提现,都会造出永不消失的假红灯)。

在 server/ 目录下运行:python -m tests.e2e_audit_coverage
"""
import asyncio
import re
import time

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import (ADMIN, MERCHANT, call, demo_shop, drain_order_pool,
                        login, register_fresh_customer, register_fresh_rider)

customer = register_fresh_customer()
merchant = login(MERCHANT)
admin = login(ADMIN)

sid = demo_shop()["id"]
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"自检覆盖菜-{int(time.time())}", "price_cents": 4000,
             "stock": 50})


async def db_all(q, **p):
    async with SessionLocal() as db:
        return (await db.execute(text(q), p)).all()


async def db_one(q, **p):
    rows = await db_all(q, **p)
    return rows[0] if rows else None


async def db_exec(q, **p):
    async with SessionLocal() as db:
        await db.execute(text(q), p)
        await db.commit()


def place_paid_order():
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "自检覆盖测试地址", "lat": 30.66, "lng": 104.08})
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    return no


def full_flow(rider):
    no = place_paid_order()
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    return no


def checks_for(problems, needle):
    """detail 里点名了 needle 的那些 check 名。"""
    return {p["check"] for p in problems if needle in p.get("detail", "")}


def count_in(problems, check):
    """聚合类告警文案里的笔数(没报就是 0)。"""
    for p in problems:
        if p["check"] == check:
            m = re.search(r"(\d+) 笔", p["detail"])
            if m:
                return int(m.group(1))
    return 0


async def main():
    from app.services.audit import run_audit

    await drain_order_pool()
    rider = await register_fresh_rider("自检覆盖骑手")
    call("POST", "/riders/online", rider, {"is_online": True})

    done_no = full_flow(rider)
    cancel_no = place_paid_order()
    call("POST", f"/orders/{cancel_no}/transition", customer,
         {"to_status": "cancelled", "reason": "自检覆盖用例"})

    order = await db_one(
        "SELECT id, rider_id, merchant_id, total_cents FROM orders "
        "WHERE order_no = :n", n=done_no)
    cancelled = await db_one(
        "SELECT id, total_cents FROM orders WHERE order_no = :n", n=cancel_no)
    other_shop = (await db_one(
        "SELECT id FROM merchants WHERE id <> :m ORDER BY id LIMIT 1",
        m=order.merchant_id)).id
    other_rider = (await db_one(
        "SELECT id FROM users WHERE role = 'rider' AND id <> :r "
        "ORDER BY id LIMIT 1", r=order.rider_id)).id

    base = await run_audit()
    assert not checks_for(base, done_no), checks_for(base, done_no)
    assert not checks_for(base, cancel_no), checks_for(base, cancel_no)
    print("✓ 基线:本用例造的两笔单账目全平,自检不报")

    # ---- 渠道拒绝的退款:以前是自检的盲区(#33 第 5 节遗留)----
    #
    # services/wechat_pay.py 的 request_refund 注释里写着「审计规则 5c
    # 会把它捞出来要人工介入」,而那条规则一直不存在:渠道拒绝时
    # order.refund_cents 不累计(钱没退出去,账面不能写"已退"),
    # 而恒等式那几条又都用 status != failed 把它排除在 Σ 之外 ——
    # 两边一起躲开,「用户该收到钱、一分没收到」在自检里没有任何痕迹。
    # ⚠️ 用 db_exec 不用 db_one:db_all/db_one 那条路**不 commit**,
    # INSERT 会随 session 关闭一起回滚 —— 造的坏账根本没落库,
    # 而自检当然报不出来(踩过一次,表现是"规则写了却不生效")
    await db_exec(
        "INSERT INTO refunds (biz_type, biz_id, order_id, order_no, "
        "  out_refund_no, amount_cents, reason, status, channel, error, "
        "  created_at) "
        "VALUES ('food', :bid, :bid, :no, :orn, 1234, '自检覆盖用例', "
        "        'failed', 'mock', '渠道拒绝(造的)', "
        "        now() - interval '12 hours')",
        bid=order.id, no=done_no, orn=f"AUDITCOV-F-{order.id}")

    def failed_refund_n(ps):
        # 开发库里本来就躺着历史失败退款,所以看的是**笔数变化**,
        # 不是"这条 check 在不在" —— 后者在干净库上才成立
        for p in ps:
            if p["check"] == "refund_failed":
                return int(re.search(r"拒绝 (\d+) 笔", p["detail"]).group(1))
        return 0

    base_failed = failed_refund_n(base)
    after = await run_audit()
    assert failed_refund_n(after) == base_failed + 1, \
        "渠道拒绝的退款没被自检捞出来 —— 这笔钱既没到用户手上,也不在任何恒等式里"
    print("✓ 渠道拒绝的退款会被自检捞出来(补上了 wechat_pay 注释里承诺的那条)")

    # 人工重发成功之后就不该再报 —— 天天红的告警等于没有告警
    await db_exec(
        "INSERT INTO refunds (biz_type, biz_id, order_id, order_no, "
        "  out_refund_no, amount_cents, reason, status, channel, error, "
        "  created_at) "
        "VALUES ('food', :bid, :bid, :no, :orn, 1234, '自检覆盖用例', "
        "        'success', 'mock', '', now() - interval '1 hour')",
        bid=order.id, no=done_no, orn=f"AUDITCOV-S-{order.id}")
    after2 = await run_audit()
    assert failed_refund_n(after2) == base_failed, \
        "失败后已经人工重发成功了还在报,这条告警迟早被无视"
    print("✓ 失败后有成功重发的不再报")

    await db_exec("DELETE FROM refunds WHERE out_refund_no LIKE 'AUDITCOV-%'")

    # ---- 挑一张已核销团购券 / 一笔已离店住宿,资金落定时刻都在窗内 ----
    voucher = await db_one(
        "SELECT id, purchase_no, net_cents, created_at FROM voucher_purchases "
        "WHERE status = 'redeemed' AND redeemed_at >= now() - interval '20 days' "
        "ORDER BY id DESC LIMIT 1")
    stay = await db_one(
        "SELECT id, order_no, fee_cents, created_at FROM stay_orders "
        "WHERE status = 'completed' AND completed_at >= now() - interval '20 days' "
        "ORDER BY id DESC LIMIT 1")
    stay_closed = await db_one(
        "SELECT id, paid_at FROM stay_orders WHERE status = 'closed' "
        "ORDER BY id DESC LIMIT 1")
    refund_row = await db_one(
        "SELECT id, status, created_at FROM refunds WHERE order_no = :n "
        "ORDER BY id LIMIT 1", n=cancel_no)
    assert voucher and stay and stay_closed and refund_row, "缺造坏账的素材"

    # ---- 券/住宿的退款流水:上一轮审查里这两格是空的 ----
    #
    # 券和住宿的「退款」以前只是改一个状态字段,一条 refunds 流水都不写,
    # 而规则 5(Σ流水 == refund_cents)查的是 orders —— 结构上装不下它们。
    # 素材必须是**真的有流水**的券/住宿:挑不到就说明退款根本没接渠道,
    # 那正是这条覆盖用例要抓的东西,红在这里比红在断言里更早也更清楚。
    refunded_voucher = await db_one(
        "SELECT p.id, p.purchase_no, p.sell_price_cents FROM voucher_purchases p "
        "WHERE p.status = 'refunded' AND p.refunded_at >= now() - interval '20 days' "
        "  AND EXISTS (SELECT 1 FROM refunds r WHERE r.biz_type = 'voucher' "
        "              AND r.biz_id = p.id AND r.status <> 'failed') "
        "ORDER BY p.id DESC LIMIT 1")
    refunded_stay = await db_one(
        "SELECT o.id, o.order_no, o.refund_cents, o.total_cents, o.net_cents "
        "FROM stay_orders o "
        "WHERE o.status IN ('cancelled', 'noshow', 'rejected') "
        "  AND o.refund_cents > 0 AND o.refund_cents <= o.total_cents "
        "  AND o.cancelled_at >= now() - interval '20 days' "
        "  AND EXISTS (SELECT 1 FROM refunds r WHERE r.biz_type = 'stay' "
        "              AND r.biz_id = o.id AND r.status <> 'failed') "
        "ORDER BY o.id DESC LIMIT 1")
    # 到店无房:退款额 = 房费 + 违约金,**本来就超过用户实付**。
    # 它是「上界规则不许叫」的那一侧素材(叫了就是天天报红的假红灯)
    no_room_stay = await db_one(
        "SELECT o.id, o.order_no, o.refund_cents, o.total_cents FROM stay_orders o "
        "JOIN stay_after_sales a ON a.stay_order_id = o.id "
        "WHERE o.refund_cents > o.total_cents AND a.kind = 'no_room' "
        "  AND a.status IN ('accepted', 'auto_accepted') "
        "  AND o.cancelled_at >= now() - interval '20 days' "
        "ORDER BY o.id DESC LIMIT 1")
    assert refunded_voucher, "找不到「已退款且有退款流水」的券 —— 券退款没接渠道"
    assert refunded_stay, "找不到「已退款且有退款流水」的住宿单 —— 住宿退款没接渠道"
    assert no_room_stay, "缺「到店无房」素材(上界规则不许误伤的那一侧)"

    # ---- 商家钱包口径:两个曾经的假红灯场景 ----
    # (a) 纯住宿商家:钱全在 stay_orders.net_cents 里,审计漏算住宿净额的话
    #     一提现就是负数,天天报红
    # 两个素材都要求「店主名下没有在途/已打款的提现」。
    #
    # 下面断言的是「整户口径不会误报余额为负」,那就得挑一个**整户确实
    # 不为负**的店主 —— 否则测的不是口径,是运气。开发库里挣得最多的
    # 那家店(张记面馆)恰好有 850 万分历史提现,余额只剩 106 万,
    # 再注入一笔 956 万的提现,审计报它负数是**对的**,断言反而成了
    # 「要求自检对真负数闭嘴」。挑素材时把已提的钱算进去,断言强度不变
    _NO_DRAW = """
          AND NOT EXISTS (SELECT 1 FROM withdrawals w
                          WHERE w.user_id = m.owner_id AND w.role = 'merchant'
                            AND w.status NOT IN ('rejected', 'failed'))"""
    stay_shop = await db_one("""
        SELECT m.id, m.owner_id, s.net FROM merchants m JOIN LATERAL (
          SELECT coalesce(sum(net_cents), 0) net FROM stay_orders so
          WHERE so.merchant_id = m.id
            AND so.status IN ('completed', 'cancelled', 'noshow')) s ON true
        WHERE s.net > 0
          AND (SELECT count(*) FROM merchants m2
               WHERE m2.owner_id = m.owner_id) = 1
          AND (SELECT coalesce(sum(net_cents), 0) FROM merchant_earnings me
               WHERE me.merchant_id = m.id) = 0""" + _NO_DRAW + """
        ORDER BY s.net DESC LIMIT 1""")
    # (b) 连锁:两家店各自有营收,店主一次提走跨店的总额。审计按店逐个循环、
    #     每家店都减一遍整个店主的提现,就会凭空报两条负余额
    chain = await db_all("""
        SELECT m.id, m.owner_id, x.net FROM merchants m JOIN LATERAL (
          SELECT coalesce(sum(net_cents), 0) net FROM merchant_earnings me
          WHERE me.merchant_id = m.id AND me.settle_mode = 'platform') x ON true
        WHERE x.net > 0""" + _NO_DRAW + """
        ORDER BY x.net DESC LIMIT 2""")
    assert stay_shop and len(chain) == 2, "缺钱包口径用例的素材"
    shop_a, shop_b = chain
    stay_draw = stay_shop.net // 2 + 1          # 只有算上住宿净额才提得出来
    chain_draw = max(shop_a.net, shop_b.net) + 1  # 单店不够、两店合起来够

    async def revert():
        await db_exec("UPDATE merchant_earnings SET merchant_id = :m "
                      "WHERE order_no = :n AND kind = 'earning'",
                      m=order.merchant_id, n=done_no)
        await db_exec("UPDATE rider_earnings SET rider_id = :r "
                      "WHERE order_no = :n AND kind = 'earning'",
                      r=order.rider_id, n=done_no)
        await db_exec("UPDATE orders SET total_cents = :t WHERE id = :i",
                      t=cancelled.total_cents, i=cancelled.id)
        await db_exec("DELETE FROM merchant_earnings WHERE order_id = :i",
                      i=cancelled.id)
        await db_exec("UPDATE refunds SET status = :s, created_at = :c "
                      "WHERE id = :i",
                      s=refund_row.status, c=refund_row.created_at,
                      i=refund_row.id)
        await db_exec("UPDATE stay_orders SET status = 'closed', paid_at = :p "
                      "WHERE id = :i", p=stay_closed.paid_at, i=stay_closed.id)
        await db_exec("UPDATE voucher_purchases SET net_cents = :n, "
                      "created_at = :c WHERE id = :i",
                      n=voucher.net_cents, c=voucher.created_at, i=voucher.id)
        await db_exec("UPDATE stay_orders SET fee_cents = :f, created_at = :c "
                      "WHERE id = :i",
                      f=stay.fee_cents, c=stay.created_at, i=stay.id)
        await db_exec("UPDATE merchants SET owner_id = :o WHERE id = :i",
                      o=shop_b.owner_id, i=shop_b.id)
        await db_exec("DELETE FROM withdrawals WHERE paid_note = :t",
                      t="e2e_audit_coverage")
        await db_exec("UPDATE refunds SET status = 'success' "
                      "WHERE biz_type = 'voucher' AND biz_id = :i",
                      i=refunded_voucher.id)
        await db_exec("UPDATE refunds SET status = 'success' "
                      "WHERE biz_type = 'stay' AND biz_id = :i",
                      i=refunded_stay.id)
        await db_exec("UPDATE stay_orders SET refund_cents = :r, net_cents = :n "
                      "WHERE id = :i", r=refunded_stay.refund_cents,
                      n=refunded_stay.net_cents, i=refunded_stay.id)

    try:
        # 1) 收款方错人:金额两边都对,只是记到了别人头上
        await db_exec("UPDATE merchant_earnings SET merchant_id = :m "
                      "WHERE order_no = :n AND kind = 'earning'",
                      m=other_shop, n=done_no)
        await db_exec("UPDATE rider_earnings SET rider_id = :r "
                      "WHERE order_no = :n AND kind = 'earning'",
                      r=other_rider, n=done_no)
        # 2) 超退:剩余应付被扣成负数(满减按原价退的那个口子,见 e2e_refund_bounds)
        await db_exec("UPDATE orders SET total_cents = -900 WHERE id = :i",
                      i=cancelled.id)
        # 3) 取消单上挂一条来路不明的商家入账
        await db_exec("""
            INSERT INTO merchant_earnings
              (merchant_id, order_id, order_no, food_cents, commission_cents,
               net_cents, kind, settle_mode, note)
            VALUES (:m, :i, :n, 1234, 0, 1234, 'earning', 'platform',
                    '手工塞进来的野账')""",
                      m=order.merchant_id, i=cancelled.id, n=cancel_no)
        # 4) 退款卡在 requested:发起了,渠道没回执
        await db_exec("UPDATE refunds SET status = 'requested', "
                      "created_at = now() - interval '48 hours' WHERE id = :i",
                      i=refund_row.id)
        # 5) 住宿已支付没人确认(清扫对 PAID 没有超时兜底)
        await db_exec("UPDATE stay_orders SET status = 'paid', "
                      "paid_at = now() - interval '48 hours' WHERE id = :i",
                      i=stay_closed.id)
        # 6) 时间窗取错列就看不见的两笔:券按 redeemed_at、住宿按 completed_at。
        #    把 created_at 推到 200 天前 —— 老口径(created_at >= since)下
        #    这两笔一生都不会再被自检看到,把它们做坏了也没人知道
        await db_exec("UPDATE voucher_purchases SET net_cents = net_cents + 1, "
                      "created_at = now() - interval '200 days' WHERE id = :i",
                      i=voucher.id)
        await db_exec("UPDATE stay_orders SET fee_cents = fee_cents + 1, "
                      "created_at = now() - interval '200 days' WHERE id = :i",
                      i=stay.id)
        # 7) 钱包口径的两个"不许叫":住宿净额要算进来、连锁提现只减一次
        await db_exec("UPDATE merchants SET owner_id = :o WHERE id = :i",
                      o=shop_a.owner_id, i=shop_b.id)
        for uid, amount in ((stay_shop.owner_id, stay_draw),
                            (shop_a.owner_id, chain_draw)):
            # reject_reason 是 withdrawals 里唯一「NOT NULL 且没有库级默认值」
            # 的列(其余几列都有 server default),裸 INSERT 必须自己补上 ——
            # 模型上的 default="" 是 Python 侧的,走不到原生 SQL
            await db_exec("""
                INSERT INTO withdrawals
                  (user_id, role, amount_cents, status, channel, paid_note,
                   reject_reason)
                VALUES (:u, 'merchant', :a, 'pending', 'manual',
                        'e2e_audit_coverage', '')""", u=uid, a=amount)
        # 8) 券/住宿的退款流水做坏:把流水置 failed(钱没退出去),
        #    业务表上却依然写着"已退款"。这正是接渠道之前那两条线的形态 ——
        #    状态字段绿着、一分钱没动。规则 5 查的是 orders,看不见它们
        await db_exec("UPDATE refunds SET status = 'failed' "
                      "WHERE biz_type = 'voucher' AND biz_id = :i",
                      i=refunded_voucher.id)
        await db_exec("UPDATE refunds SET status = 'failed' "
                      "WHERE biz_type = 'stay' AND biz_id = :i",
                      i=refunded_stay.id)
        # 9) 住宿退超用户实付,且没有「到店无房」那张单子背书 ——
        #    这是真的超退,不是违约金
        await db_exec("UPDATE stay_orders SET refund_cents = total_cents + 1, "
                      "net_cents = -1 WHERE id = :i", i=refunded_stay.id)

        problems = await run_audit()

        got = checks_for(problems, done_no)
        assert "merchant_earning_payee_mismatch" in got, got
        assert "rider_earning_payee_mismatch" in got, got
        print("✓ 收款方错人被抓到(金额恒等式两边全平也没放过)")

        got = checks_for(problems, cancel_no)
        assert "refund_exceeds_total" in got, got
        assert "noncompleted_order_earning" in got, got
        print("✓ 超退(剩余应付为负)、取消单上的野账入账,都报出来了")

        assert count_in(problems, "refund_stuck") >= 1, problems
        print(f"✓ 退款卡在 requested 被报出:"
              f"{count_in(problems, 'refund_stuck')} 笔")

        after_stay = count_in(problems, "stay_paid_stuck")
        before_stay = count_in(base, "stay_paid_stuck")
        assert after_stay > before_stay, (before_stay, after_stay)
        print(f"✓ 住宿 PAID 挂起计入:{before_stay} → {after_stay} 笔")

        got = checks_for(problems, voucher.purchase_no)
        assert "voucher_split_mismatch" in got, got
        got = checks_for(problems, stay.order_no)
        assert "stay_split_mismatch" in got, got
        print("✓ 下单 200 天前、近期才落定的券/住宿依然在自检视野里"
              "(窗口取的是 redeemed_at / completed_at)")

        negative = {p["detail"] for p in problems
                    if p["check"] == "merchant_balance_negative"}
        assert not any(f"#{stay_shop.owner_id}(" in d for d in negative), negative
        assert not any(f"#{shop_a.owner_id}(" in d for d in negative), negative
        # 同一份数据按老口径算就是负的 —— 证明这两条不是"碰巧没报"
        assert 0 - stay_draw < 0                        # 老口径漏住宿净额
        assert shop_a.net - chain_draw < 0              # 老口径按店重复扣提现
        assert shop_b.net - chain_draw < 0
        assert shop_a.net + shop_b.net - chain_draw >= 0  # 整户其实是够的
        print("✓ 商家余额按店主整户核:住宿净额算进来了,"
              "连锁的提现只减一次(两条老假红灯都不再亮)")

        got = checks_for(problems, refunded_voucher.purchase_no)
        assert "voucher_refund_mismatch" in got, got
        got = checks_for(problems, refunded_stay.order_no)
        assert "stay_refund_mismatch" in got, got
        print("✓ 券/住宿标着「已退款」而流水一分没退出去,两条都报出来了")

        assert "stay_refund_exceeds_paid" in got, got
        print("✓ 住宿退款超过用户实付被抓到")

        # "不许叫"的一侧:到店无房本来就退得比实付多(房费+违约金),
        # 报它等于给自检加一盏天天亮的假红灯
        assert "stay_refund_exceeds_paid" not in \
            checks_for(problems, no_room_stay.order_no), \
            f"到店无房的违约金不该被当成超退:{no_room_stay.order_no}"
        print("✓ 到店无房的违约金没被误报成超退")
    finally:
        await revert()

    clean = await run_audit()
    for needle in (done_no, cancel_no, voucher.purchase_no, stay.order_no,
                   refunded_voucher.purchase_no, refunded_stay.order_no):
        assert not checks_for(clean, needle), (needle, checks_for(clean, needle))
    assert count_in(clean, "stay_paid_stuck") == count_in(base, "stay_paid_stuck")
    print("✓ 复原后自检回到基线(既没漏报,也没有赖着不走的告警)")

    # ---- 管理端:列表只是样本,严重程度看总数 ----
    dash = call("GET", "/admin/dashboard", admin)
    assert "audit_alerts_total" in dash and "audit_alert_groups" in dash, dash
    assert dash["audit_alerts_total"] >= len(dash["audit_alerts"]), dash
    assert sum(g["count"] for g in dash["audit_alert_groups"]) \
        == dash["audit_alerts_total"], dash
    print(f"✓ 后台返回告警总数 {dash['audit_alerts_total']} 与按 check 分组"
          f"({len(dash['audit_alert_groups'])} 类),列表 "
          f"{len(dash['audit_alerts'])} 条只作样本")

    # ---- 自检挂掉那天不许被当成干净天:防重键必须撤回 ----
    from datetime import datetime

    from app.redis_client import get_redis
    from app.services import audit as audit_mod
    from app.services import auto_flow
    from app.services.auto_flow import BEIJING, maybe_run_daily_audit

    at_four = datetime.now(BEIJING).replace(hour=4, minute=0, second=10,
                                            microsecond=0)
    key = f"audit:ran:{at_four.date()}"
    redis = get_redis()
    await redis.delete(key)
    original = audit_mod.run_audit

    async def boom():
        raise RuntimeError("自检炸了")

    audit_mod.run_audit = boom
    try:
        try:
            await maybe_run_daily_audit(at_four)
            raise AssertionError("自检抛异常时 maybe_run_daily_audit 必须往上抛")
        except RuntimeError:
            pass
        assert not await redis.get(key), "自检失败后防重键必须撤掉,否则当天不再重跑"
    finally:
        audit_mod.run_audit = original
        await redis.delete(key)
    assert auto_flow  # noqa: B015  (确保拿到的是同一个模块)
    print("✓ 自检抛异常时防重键回滚:当天还能重试,不会被记成没问题的干净天")

    call("POST", "/riders/online", rider, {"is_online": False})
    print("\ne2e_audit_coverage 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
