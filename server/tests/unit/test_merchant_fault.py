"""判商家责任的钱怎么走(services/merchant_fault.py)。2026-09-15 定:商家有责任,商家连配送费和小费
一起出,顾客拿回全款。

1. 骑手那份:平台骑手送的单是配送费 + 小费,自配送、自取为 0(那两种的配送费本来就在商家入账里);
2. 四条判商家责任的路(商家同意售后、售后被拒改判、到店未出餐 / 餐品不齐、食安投诉成立)
   都走 merchant_fault.apply、都退全款;
3. 另出的那行:负数、佣金 0、行内 net == food − commission、记在平台代收口径上、只出一次;
4. 公开账本:这两种行不进 merchant_rows,单独进 merchant_fault_rows;见证节点认得出对错;
5. 核账:另出的 == 骑手那份、净额冲回了、顾客全款退了;商家余额为负不是错账,提走的比挣到的多才是;
6. 对账单、逐单明细、税务导出认得这几种行;
7. 反查(规则 4e):新规则生效之后判了商家责任的单,必须有另出的那一行 —— 起算点是迁移 0141
   在升级那一刻记进库里的,之前按旧规则判的单不报;起算点没了要报。

这类退化不报错(平台悄悄又开始贴钱、商家被多扣),一半按源码守,行为由 e2e_merchant_fault 核。
"""
import ast
import inspect
import sys
import textwrap
from datetime import datetime, timedelta, timezone
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


class Test改判平台补回:
    """2026-09-15 定:平台判错了,平台自己认 —— 商家售后判责改判成立,冲回的净额和另出的那行都补回。"""

    def test_补回两行_形状和冲账对称(self):
        src = inspect.getsource(mf.undo)
        assert "food_cents=reversed_net, commission_cents=0, net_cents=reversed_net" in src, \
            "补回净额的调整行:food == net、佣金 0(和 2026-09-14 之前改判补的同一个形状)"
        assert "kind=EarningKind.adjustment" in src and "kind=EarningKind.fault_refund" in src
        assert "EarningKind.adjustment not in rows" in src \
            and "EarningKind.fault_refund not in rows" in src, "补过的不许再补"
        assert src.count('settle_mode="platform"') == 2, "平台补给商家的钱走平台侧余额"

    def test_申诉改判那一支用它_判责记platform(self):
        from app.routers import appeals
        branch = inspect.getsource(appeals._overturn).split(
            'elif appeal.target_type == "after_sale_rider"')[0]
        assert "merchant_fault.undo(" in branch and 'a.fault = "platform"' in branch
        assert "平台判错了" in branch


def _ledger_payload():
    return {
        "merchant_rows": [{"o": "a", "food": 2090, "commission": 0, "net": 2090,
                           "kind": "adjustment"},
                          {"o": "b", "food": 900, "commission": 45, "net": 855,
                           "kind": "earning"}],
        "merchant_fault_rows": [{"o": "a", "amount": 800, "kind": "fault_refund"},
                                {"o": "c", "amount": -500, "kind": "fault_charge"}],
        "rider_fault_rows": [{"o": "d", "amount": 1770, "kind": "fault_refund"},
                             {"o": "e", "amount": -600, "kind": "fault_reversal"}],
        "appeal_refund_rows": [{"o": "f", "amount": 1800}],
    }


class Test平台纠错的钱进公开账本:
    def test_合计的式子服务端和见证节点一样(self):
        from app.services import ledger
        p = _ledger_payload()
        expect = 2090 + 800 + 1770 + 1800
        assert ledger.platform_correction(p["merchant_rows"], p["merchant_fault_rows"],
                                          p["rider_fault_rows"], p["appeal_refund_rows"]) == expect
        assert w.platform_correction(p) == expect

    def test_见证节点核合计和顾客改判退款行(self):
        extra = _ledger_payload()
        p = _payload(merchant_fault_rows=extra["merchant_fault_rows"],
                     rider_fault_rows=extra["rider_fault_rows"],
                     appeal_refund_rows=extra["appeal_refund_rows"])
        p["merchant_rows"] = p["merchant_rows"] + [extra["merchant_rows"][0]]
        p["totals"].update(merchant_fault=300, rider_fault=1170, appeal_refund=1800,
                           platform_correction=2090 + 800 + 1770 + 1800)
        assert w.verify_rows(p) == [], w.verify_rows(p)
        p["totals"]["platform_correction"] -= 1
        assert any("平台纠错" in x for x in w.verify_rows(p))
        p = _payload(appeal_refund_rows=[{"o": "f", "amount": 0}])
        assert any("申诉改判退款行" in x for x in w.verify_rows(p))

    def test_账本里有顾客改判退款行和合计(self):
        from app.services import ledger
        src = inspect.getsource(ledger.build_day_payload)
        assert '"appeal_refund_rows": appeal_refund_rows' in src
        assert "APPEAL_REFUND_NOTES" in src and "status <> 'failed'" in src, \
            "按平台发起的那一天记、渠道拒了的不算(微信要等回调才转成功,按成功取数会漏)"
        assert '"platform_correction": platform_correction(' in src


class Test透明中心的申诉改判只放纠错的钱:
    def test_四项进申诉改判_难度反馈进补贴(self):
        from app.routers import transparency
        src = inspect.getsource(transparency.funds_public)
        assert "adjustments = merchant_restore + merchant_fault_back + fault_back + appeal_refunds" \
            in src
        assert "subsidy = order_subsidy + hardship" in src
        for key in ("merchant_restore_cents", "merchant_fault_refund_cents",
                    "rider_fault_refund_cents", "appeal_refund_cents", "rider_hardship_cents"):
            assert f'"{key}"' in src, key

    def test_赔付记录有申诉改判(self):
        from app.routers import transparency
        src = inspect.getsource(transparency.compensation_public)
        assert '"appeal_corrections"' in src
        assert "kind IN ('adjustment', 'fault_refund')" in src

    def test_顾客改判退款的原因新老两种都认(self):
        from app.routers import appeals
        assert appeals.APPEAL_REFUND_NOTE in appeals.APPEAL_REFUND_NOTES
        assert "平台判错了,平台自己认" in appeals.APPEAL_REFUND_NOTE
        assert "申诉改判:平台承担,原路退回" in appeals.APPEAL_REFUND_NOTES, "历史流水照认"


# ---------------- 规则 4e:判了商家责任,就必须有另出的那一行 ----------------

T0 = datetime(2026, 9, 15, 2, 0, tzinfo=timezone.utc)      # 新规则在这个库上生效的时刻
MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / \
    "0141_merchant_fault_charge_since.py"


class _AuditDB:
    """_merchant_fault_charge_missing 用到的两个方法:get 读起算点,execute 回事先摆好的行并记下语句。"""

    def __init__(self, flag_value, rows=()):
        self.flag_value, self.rows, self.stmts = flag_value, list(rows), []

    async def get(self, model, key):
        assert key == mf.CHARGE_SINCE_FLAG, key
        return None if self.flag_value is None else SimpleNamespace(key=key, value=self.flag_value)

    async def execute(self, stmt, *a, **k):
        self.stmts.append(stmt)
        return SimpleNamespace(all=lambda: self.rows)


def _sql(stmt):
    from sqlalchemy.dialects import postgresql
    c = stmt.compile(dialect=postgresql.dialect())
    return str(c), c.params


def _judged(**kw):
    base = dict(id=1, order_no="f" * 20, rider_id=7, delivery_fee_cents=500, tip_cents=300,
                order_kind="food")
    base.update(kw)
    return SimpleNamespace(**base)


def _run4e(db, since=T0 - timedelta(days=30)):
    import asyncio

    from app.services import audit
    return asyncio.run(audit._merchant_fault_charge_missing(db, since))


class Test反查判了商家责任就得有另出的那行:
    """规则 4e(services/audit._merchant_fault_charge_missing):4d 只核写了另出那一行的单,
    绕开 merchant_fault.apply、一行都没写的它看不见。从判责的记录反过来找;起算点是迁移 0141 记进库里的
    「新规则生效时刻」,之前按旧规则判的单不报。行为(删掉那一行就报、老单不报)由 e2e_merchant_fault 第 10 段核。"""

    def test_接进了每日核账_跟在4d后面(self):
        from app.services import audit
        src = inspect.getsource(audit.run_audit)
        assert "_merchant_fault_charge_missing(db, since)" in src
        assert src.index("_merchant_fault_problems(db, since)") \
            < src.index("_merchant_fault_charge_missing(db, since)")

    def test_四条路的记录都认_判给别人的不算(self):
        from app.services.delivery_fault import MERCHANT_KINDS
        sql, params = _sql(mf.judged_query(T0))
        # ① 售后判商家责任(商家同意、售后被拒改判;配送异常、食安成立也会补一条)
        assert "after_sales.fault = %(fault_1)s" in sql and params["fault_1"] == "merchant"
        # ② 到店未出餐、餐品不齐裁成退款
        assert "delivery_issues.resolution = %(resolution_1)s" in sql \
            and params["resolution_1"] == "refund"
        assert list(params["kind_1"]) == list(MERCHANT_KINDS)
        # ③ 食安投诉成立
        assert "food_safety_reports.status = %(status_1)s" in sql \
            and params["status_1"] == "confirmed"
        # 售后判给了别人(骑手责任、商家申诉改判成立)的,②③ 不算
        assert sql.count("NOT IN (SELECT after_sales.order_id") == 2
        assert list(params["fault_2"]) == ["rider", "platform"]
        # 三处都只看起算点之后的,一单取最后一次
        assert sum(1 for v in params.values() if v == T0) == 3, params
        assert "max(" in sql and "GROUP BY" in sql

    def test_起算点没了要报_不能悄悄不查(self):
        for broken in (None, "", "不是时间"):
            out = _run4e(_AuditDB(broken))
            assert [p["check"] for p in out] == ["merchant_fault_charge_missing"], out
            assert "起算点" in out[0]["detail"] and mf.CHARGE_SINCE_FLAG in out[0]["detail"]

    def test_平台骑手送的没有那一行就报_自配送自取跑腿不报(self):
        at = T0 + timedelta(hours=3)
        rows = [(_judged(), at),
                (_judged(id=2, order_no="e" * 20, rider_id=None), at),              # 自配送 / 自取
                (_judged(id=3, order_no="d" * 20, delivery_fee_cents=0, tip_cents=0), at),
                (_judged(id=4, order_no="c" * 20, order_kind="errand_send"), at)]  # 跑腿没有商家
        db = _AuditDB(T0.isoformat(), rows)
        out = _run4e(db)
        assert len(out) == 1 and out[0]["check"] == "merchant_fault_charge_missing", out
        assert "f" * 20 in out[0]["detail"] and "800 分" in out[0]["detail"], out
        sql, params = _sql(db.stmts[0])
        # 只捞没有 fault_charge 那一行的单(有了的,金额对不对归 4d)
        assert "NOT (EXISTS (SELECT *" in sql and "merchant_earnings.kind" in sql
        assert EarningKind.fault_charge in params.values()

    def test_起算点取近30天和生效时刻里晚的那个(self):
        for since, expect in ((T0 - timedelta(days=30), T0),                   # 刚上线:从生效那一刻起
                              (T0 + timedelta(days=5), T0 + timedelta(days=5))):  # 上线一个多月后:近 30 天
            db = _AuditDB(T0.isoformat())
            _run4e(db, since=since)
            _, params = _sql(db.stmts[0])
            floors = {v for v in params.values() if isinstance(v, datetime)}
            assert floors == {expect}, (since, floors)

    def test_起算点读库(self):
        import asyncio

        def read(value):
            return asyncio.run(mf.charge_since(_AuditDB(value)))

        assert read(T0.isoformat()) == T0
        assert read("2026-09-15T02:00:00") == T0, "没带时区的当 UTC"
        assert read(None) is None and read("  ") is None and read("2026-13-45") is None

    def test_迁移在升级那一刻记进库里_接在0140后面(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("m0141", MIGRATION)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        assert (m.revision, m.down_revision) == ("0141", "0140")
        assert m.KEY == mf.CHARGE_SINCE_FLAG
        src = MIGRATION.read_text(encoding="utf-8")
        assert "ON CONFLICT (key) DO NOTHING" in src, "重跑不许把起算点往后挪"
        assert "datetime.now(timezone.utc).isoformat()" in src
        code = "\n".join(ln.split("#", 1)[0] for ln in
                         src.split('"""', 2)[2].splitlines())       # 去掉文档串和注释
        assert "flag_history" not in code, "它不是开关,不进透明中心的开关时间线"
        others = [p.name for p in MIGRATION.parent.glob("*.py")
                  if p != MIGRATION and "down_revision = '0141'" in p.read_text(encoding="utf-8")]
        assert not others, f"0141 后面还接了迁移,记得把这条测试的「接在 0140 后面」一起看:{others}"

    def test_不是开关_后台看不到改不了_不进开关时间线(self):
        from app.routers import admin, transparency
        assert mf.CHARGE_SINCE_FLAG not in admin._KNOWN_FLAGS, "进了后台「平台开关」页就能被人改掉"
        assert mf.CHARGE_SINCE_FLAG not in transparency._PUBLIC_FLAGS
        assert "if key not in _KNOWN_FLAGS" in inspect.getsource(admin.set_flag)
