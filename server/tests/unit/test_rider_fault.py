"""判骑手责任的钱怎么走(services/rider_fault.py):平台不出钱。

1. 缺口怎么分:先池子(不超过余额),不够的骑手出 —— 纯函数;
2. 两条判骑手责任的路(配送异常裁成退款、售后仲裁)真的在走它;三条改判的路
   (原通道两种 + 客服工单)真的在退;
3. 公开账本:判责行不进 rider_rows(见证节点按「配送费只进不冲」核),单独进 rider_fault_rows,
   池子的支出和回池逐笔进 rider_fund.rows;见证节点的逐行核账认得出新字段的对错;
4. 核账:判骑手责任的恒等式、池子不许为负、提现不许超过挣到的钱;
5. 说法:推送、公示、规则页不再说「平台先行赔付」「不扣你的钱」。

这类退化不报错(平台悄悄又开始出钱、骑手被多扣),所以一半按源码守,行为由 e2e_rider_fault 核。
"""
import ast
import inspect
import sys
import textwrap
from pathlib import Path

import pytest

from app.models import EarningKind
from app.services import rider_fault as rf

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "witness"))
import superz_witness as w  # noqa: E402


class Test缺口怎么分:
    @pytest.mark.parametrize("gap,pool,fund,rider", [
        (2090, 10_000, 2090, 0),      # 池子够:全由池子出
        (2090, 920, 920, 1170),       # 池子不够:池子出光,剩下骑手出
        (2090, 0, 0, 2090),           # 池子空了:骑手出
        (2090, -50, 0, 2090),         # 池子是负的(不该出现):当 0,绝不透支
        (0, 5000, 0, 0),              # 跑腿单没有商家那份
        (-300, 5000, 0, 0),           # 满减大过餐费:净额为负也不出
    ])
    def test_先池子后骑手(self, gap, pool, fund, rider):
        assert rf.split_gap(gap, pool) == (fund, rider)

    def test_两边加起来正好是缺口_平台一分不出(self):
        for gap in (0, 1, 999, 20900):
            for pool in (0, 1, 500, 20900, 99999):
                f, r = rf.split_gap(gap, pool)
                assert f + r == gap and f <= max(pool, 0) and f >= 0 and r >= 0

    def test_没有封顶(self):
        """拍板时没说封顶,不自己加:骑手出的部分可以很大(要不要封顶待定)。"""
        assert rf.split_gap(1_000_000, 0) == (0, 1_000_000)

    def test_推送把几个数都照实说(self):
        s = rf.Split(income=600, merchant=2090, fund=920, rider=1170, fund_before=920)
        text = rf.rider_push_text(s)
        for part in ("6.00", "20.90", "9.20", "11.70", "之后的收入先抵"):
            assert part in text, (part, text)
        assert s.rider_total == 1770


class Test账本行的种类:
    def test_三种骑手判责行(self):
        assert {k.value for k in rf.FAULT_KINDS} == {
            "fault_reversal", "fault_charge", "fault_refund"}
        assert all(isinstance(k, EarningKind) for k in rf.FAULT_KINDS)

    def test_公开账本和核账认的是同一组(self):
        from app.services import audit, ledger
        assert set(ledger.RIDER_FAULT_KINDS) == {k.value for k in rf.FAULT_KINDS}
        assert set(audit._RIDER_FAULT_KINDS) == set(rf.FAULT_KINDS)

    def test_判责行不进rider_rows(self):
        src = inspect.getsource(__import__("app.services.ledger", fromlist=["x"]).build_day_payload)
        assert "kind NOT IN ({faults})" in src and "rider_fault_rows" in src
        assert '"paid_cents"' in src and '"rows": fund_rows' in src, "池子的支出没进公开账本"


def _calls(fn) -> set[tuple[str, str]]:
    out = set()
    for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(fn)))):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                out.add((f.value.id if isinstance(f.value, ast.Name) else "", f.attr))
            elif isinstance(f, ast.Name):
                out.add(("", f.id))
    return out


class Test两条判责的路都走它:
    def test_配送异常裁成退款(self):
        from app.routers import admin
        assert ("rider_fault", "apply") in _calls(admin.resolve_delivery_issue)

    def test_售后仲裁判骑手责任(self):
        from app.routers import admin
        calls = _calls(admin.after_sale_rider_fault)
        assert ("rider_fault", "apply") in calls
        assert ("", "settle_order") in calls, "还没确认收货的单要先结算再冲,不然之后入账就成了平台出的钱"

    def test_三条改判的路都退(self):
        from app.routers import appeals
        from app.services import credit
        src = inspect.getsource(appeals._overturn)
        assert src.count("_undo_rider_fault(") >= 2, "原通道两种骑手申诉改判都要退钱"
        assert ("", "_undo_rider_fault") in _calls(credit.resolve_ticket_appeal), \
            "骑手走客服工单申诉成立也要退(原通道 72 小时 + 工单都算数)"
        assert ("rider_fault", "undo") in _calls(credit._undo_rider_fault)
        assert ("rider_fault", "undo") in _calls(appeals._undo_rider_fault)

    def test_池子的读和写在同一把锁里(self):
        for fn in (rf.apply, rf.undo):
            assert "pg_advisory_xact_lock" in inspect.getsource(fn), fn.__name__


class Test核账:
    def test_判责恒等式和池子余额都在核(self):
        from app.services import audit
        src = inspect.getsource(audit.run_audit)
        assert "_rider_fault_problems" in src
        checks = inspect.getsource(audit._rider_fault_problems)
        assert '"rider_fault_split"' in checks and '"rider_fund_negative"' in checks

    def test_余额为负不是错账_提走的比挣到的多才是(self):
        from app.services import audit
        src = inspect.getsource(audit.run_audit)
        assert "RiderEarning.kind.notin_(_RIDER_FAULT_KINDS)" in src


def _payload(**extra) -> dict:
    base = {"schema": 1, "day": "2026-09-20", "commission_rate_max": 0.05,
            "voucher_rate": 0.02, "stay_rate": 0.05, "merchant_rows": [],
            "rider_rows": [{"o": "a" * 24, "amount": 600, "kind": "earning"}],
            "voucher_rows": [], "stay_rows": [],
            "totals": {"rider_amount": 600}}
    base.update(extra)
    return base


class Test见证节点认得出新字段:
    def test_正常的判责行和池子行不报(self):
        p = _payload(
            rider_fault_rows=[{"o": "a" * 24, "amount": -600, "kind": "fault_reversal"},
                              {"o": "a" * 24, "amount": -1170, "kind": "fault_charge"},
                              {"o": "b" * 24, "amount": 900, "kind": "fault_refund"}],
            rider_fund={"per_order_cents": 20, "orders": 1, "accrued_cents": 20,
                        "paid_cents": 920, "returned_cents": 0,
                        "rows": [{"o": "a" * 24, "amount": 920, "kind": "payout"}]})
        p["totals"]["rider_fault"] = -600 - 1170 + 900
        assert w.verify_rows(p) == []

    def test_符号不对的报(self):
        p = _payload(rider_fault_rows=[{"o": "a" * 24, "amount": 600,
                                        "kind": "fault_reversal"}])
        assert any("符号不对" in x for x in w.verify_rows(p))

    def test_没见过的种类报(self):
        p = _payload(rider_fault_rows=[{"o": "a" * 24, "amount": -1, "kind": "fine"}])
        assert any("未知类型" in x for x in w.verify_rows(p))

    def test_池子行不许是负数(self):
        p = _payload(rider_fund={"rows": [{"o": "a" * 24, "amount": -5, "kind": "payout"}]})
        assert any("保障金池行" in x for x in w.verify_rows(p))

    def test_判责行混进rider_rows照样报(self):
        """rider_rows 的规矩没变:判责行混进来,见证节点照旧当成配送费被冲回。"""
        p = _payload(rider_rows=[{"o": "a" * 24, "amount": -600, "kind": "fault_reversal"}])
        assert w.verify_rows(p), "rider_rows 里出现负数行却没报"


class Test说法:
    def test_骑手的公示说清楚钱怎么走(self):
        from app.services import credit
        m = {x["key"]: x for x in credit.public_spec("rider")["minus"]}
        for key in (credit.KIND_DELIVERY, credit.KIND_AFTER_SALE):
            text = m[key]["counts"]
            assert "从你的收入里扣" in text and "保障金池" in text, (key, text)
            assert "不扣你的钱" not in text and "先行赔付" not in text, (key, text)

    def test_规则页骑手那一节写了(self):
        import asyncio

        from app.services import rules

        async def flag(_db):
            return False
        import app.services.flags as flags
        old = flags.wait_comp_on
        flags.wait_comp_on = flag
        try:
            r = asyncio.run(rules.rules_for("rider", object()))
        finally:
            flags.wait_comp_on = old
        money = next(s for s in r["sections"] if s["title"] == "钱")["items"]
        assert any("保障金池" in i and "申诉" in i for i in money), money

    def test_推送不再说平台先行赔付(self):
        from app.routers import admin
        for fn in (admin.resolve_delivery_issue, admin.after_sale_rider_fault):
            src = inspect.getsource(fn)
            assert "不扣你的工资" not in src and "不扣你的钱" not in src, fn.__name__
            assert '"配送异常,平台先行赔付"' not in src, fn.__name__
