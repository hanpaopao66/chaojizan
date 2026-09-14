"""判商家责任的钱怎么走(services/merchant_fault.py)。2026-09-15 定:商家有责任,商家连配送费和小费
一起出,顾客拿回全款。

1. 骑手那份:平台骑手送的单是配送费 + 小费,自配送、自取为 0(那两种的配送费本来就在商家入账里);
2. 四条判商家责任的路(商家同意售后、售后被拒改判、到店未出餐 / 餐品不齐、食安投诉成立)
   都走 merchant_fault.apply、都退全款;
3. 另出的那行:负数、佣金 0、行内 net == food − commission、记在平台代收口径上、只出一次;
4. 公开账本:这两种行不进 merchant_rows,单独进 merchant_fault_rows;见证节点认得出对错;
5. 核账:另出的 == 骑手那份、净额冲回了、顾客全款退了;商家余额为负不是错账,提走的比挣到的多才是;
6. 对账单、逐单明细、税务导出认得这几种行。

这类退化不报错(平台悄悄又开始贴钱、商家被多扣),一半按源码守,行为由 e2e_merchant_fault 核。
"""
import ast
import inspect
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.models import EarningKind
from app.services import merchant_fault as mf

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "witness"))
import superz_witness as w  # noqa: E402


def _order(**kw):
    base = dict(rider_id=7, delivery_fee_cents=500, tip_cents=300)
    base.update(kw)
    return SimpleNamespace(**base)


class Test骑手那份:
    def test_平台骑手送的单是配送费加小费(self):
        assert mf.rider_share_cents(_order()) == 800

    def test_自配送自取没有(self):
        """自配送的配送费在商家入账里(冲回净额就一起冲回了),自取没有配送费 —— 另出一行就是重复扣"""
        assert mf.rider_share_cents(_order(rider_id=None)) == 0
        assert mf.rider_share_cents(_order(rider_id=None, delivery_fee_cents=0, tip_cents=0)) == 0

    def test_推送把几个数都照实说(self):
        s = mf.Split(reversed_net=2090, charge=800)
        assert s.merchant_total == 2890
        text = mf.merchant_push_text(s, 3100)
        for part in ("31.00", "20.90", "8.00", "之后的收入先抵"):
            assert part in text, (part, text)
        # 自配送:没有另出的那行,就别说
        assert "配送费" not in mf.merchant_push_text(mf.Split(reversed_net=2500, charge=0), 2500)


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


class Test四条路都走它:
    def test_商家同意售后(self):
        from app.routers import after_sales
        calls = _calls(after_sales.accept_after_sale)
        assert ("merchant_fault", "apply") in calls
        assert ("", "merchant_fault_refund_cents") in calls
        assert ("", "reverse_merchant_earning") not in calls, "冲账写在 merchant_fault 里,别在这里另冲一遍"

    def test_售后被拒改判(self):
        from app.routers import appeals
        src = inspect.getsource(appeals._overturn)
        branch = src.split('elif appeal.target_type == "after_sale_rejected":')[1] \
            .split("elif appeal.target_type")[0]
        assert "merchant_fault.apply(" in branch and "merchant_fault_refund_cents(db, order)" in branch
        assert "reverse_merchant_earning(" not in branch

    def test_到店未出餐餐品不齐(self):
        from app.routers import admin
        assert ("merchant_fault_svc", "apply") in _calls(admin.resolve_delivery_issue)

    def test_食安投诉成立(self):
        from app.routers import admin
        calls = _calls(admin.confirm_food_safety)
        assert ("merchant_fault", "apply") in calls
        assert ("", "reverse_merchant_earning") not in calls


class Test另出的那行:
    def test_负数_佣金0_行内恒等_平台代收口径_只出一次(self):
        src = inspect.getsource(mf.apply)
        assert "food_cents=-charge, commission_cents=0, net_cents=-charge" in src
        assert 'settle_mode="platform"' in src, "商家欠平台的钱,要从平台侧余额里扣"
        assert "EarningKind.fault_charge not in rows" in src, "再调一次不许再出一遍"
        assert ("", "reverse_merchant_earning") in _calls(mf.apply)

    def test_没确认收货的先结算再冲(self):
        """原来商家同意售后时单还是「已送达」的话冲不到账(还没入账),等自动完成时商家照常入账 ——
        这笔退款就成了平台出的钱"""
        calls = _calls(mf.apply)
        assert ("", "settle_order") in calls
        assert "OrderStatus.DELIVERED" in inspect.getsource(mf.apply)

    def test_种类(self):
        assert {k.value for k in mf.FAULT_KINDS} == {"fault_charge", "fault_refund"}
        assert all(isinstance(k, EarningKind) for k in mf.FAULT_KINDS)


class Test公开账本:
    def test_不进merchant_rows_单独进merchant_fault_rows(self):
        from app.services import audit, ledger
        assert set(ledger.MERCHANT_FAULT_KINDS) == {k.value for k in mf.FAULT_KINDS}
        assert set(audit._MERCHANT_FAULT_KINDS) == set(mf.FAULT_KINDS)
        src = inspect.getsource(ledger.build_day_payload)
        assert "kind NOT IN ({m_faults})" in src and "kind IN ({m_faults})" in src
        assert '"merchant_fault_rows": merchant_fault_rows' in src
        assert '"merchant_fault": sum(' in src


def _payload(**extra) -> dict:
    base = {"schema": 1, "day": "2026-09-20", "commission_rate_max": 0.05,
            "voucher_rate": 0.02, "stay_rate": 0.05,
            "merchant_rows": [{"o": "a" * 24, "food": 2200, "commission": 110, "net": 2090,
                               "kind": "earning"},
                              {"o": "a" * 24, "food": -2200, "commission": -110, "net": -2090,
                               "kind": "reversal"}],
            "rider_rows": [{"o": "a" * 24, "amount": 800, "kind": "earning"}],
            "voucher_rows": [], "stay_rows": [],
            "totals": {"rider_amount": 800}}
    base.update(extra)
    return base


class Test见证节点认得出新字段:
    def test_正常的判商家责任行不报(self):
        p = _payload(merchant_fault_rows=[{"o": "a" * 24, "amount": -800, "kind": "fault_charge"},
                                          {"o": "b" * 24, "amount": 600, "kind": "fault_refund"}])
        p["totals"]["merchant_fault"] = -200
        assert w.verify_rows(p) == []

    def test_符号不对的报(self):
        p = _payload(merchant_fault_rows=[{"o": "a" * 24, "amount": 800, "kind": "fault_charge"}])
        assert any("符号不对" in x for x in w.verify_rows(p))
        p = _payload(merchant_fault_rows=[{"o": "a" * 24, "amount": -1, "kind": "fault_refund"}])
        assert any("符号不对" in x for x in w.verify_rows(p))

    def test_没见过的种类报(self):
        p = _payload(merchant_fault_rows=[{"o": "a" * 24, "amount": -800, "kind": "fine"}])
        assert any("未知类型" in x for x in w.verify_rows(p))

    def test_合计对不上报(self):
        p = _payload(merchant_fault_rows=[{"o": "a" * 24, "amount": -800, "kind": "fault_charge"}])
        p["totals"]["merchant_fault"] = -700
        assert any("商家判责合计" in x for x in w.verify_rows(p))

    def test_老锚点没有这个字段照过(self):
        assert w.verify_rows(_payload()) == []


class Test核账:
    def test_判商家责任恒等式在核(self):
        from app.services import audit
        assert "_merchant_fault_problems" in inspect.getsource(audit.run_audit)
        checks = inspect.getsource(audit._merchant_fault_problems)
        assert '"merchant_fault_split"' in checks
        assert "rider_kept_cents(o)" in checks, "另出的要对着这单骑手那份核"
        assert "EarningKind.reversal not in r" in checks, "另出了骑手那份,净额也得冲回"
        assert "unrefunded" in checks, "商家有责任时顾客该拿回全款"

    def test_余额为负不是错账_提走的比挣到的多才是(self):
        from app.services import audit
        src = inspect.getsource(audit.run_audit)
        assert "MerchantEarning.kind.in_(_MERCHANT_FAULT_KINDS)" in src
        assert "earned - faults - out < 0" in src


class Test对账单认得这几种行:
    def test_每种商家行都有名字(self):
        for kind in (EarningKind.earning, EarningKind.reversal, EarningKind.adjustment,
                     *mf.FAULT_KINDS):
            label = mf.kind_label(kind)
            assert label and label != kind.value, kind
        assert "你出" in mf.kind_label(EarningKind.fault_charge)

    def test_逐单明细带着种类(self):
        from app.schemas import FinanceOrderOut
        row = SimpleNamespace(id=1, order_no="x", food_cents=-800, commission_cents=0,
                              net_cents=-800, created_at=datetime.now(timezone.utc),
                              kind=EarningKind.fault_charge, note="商家责任")
        out = FinanceOrderOut.model_validate(row).model_dump()
        assert out["kind"] == "fault_charge" and "你出" in out["kind_label"], out

    def test_对账单和税务导出(self):
        from app.routers import merchants, tax
        assert "kind_label(e.kind)" in inspect.getsource(merchants.finance_statement_csv)
        for kind in mf.FAULT_KINDS:
            assert kind in tax._KIND_LABELS, kind
