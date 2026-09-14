"""顾客信用分(services/customer_credit.py)。

## 这组测试守什么

1. **公式本身**:起始分、每一项的分值、封顶、上下限、时间窗边界、等级 —— 全在纯函数 compute 里;
2. **新用户不吃亏**:没有扣分项的人一定在最高一档,新老用户都一样;
3. **公示和计算是同一份**:透明中心 / 规则页的数字从常量来,改常量公示跟着变,
   拿公示的数字自己算一遍和 compute 的结果对得上;
4. **申诉入口**:接得上原通道的走原通道(改判连钱一起退),接不上的走工单;
5. **谁能看到**:商家接单之后、这一单的骑手才看得到,待接单、抢单大厅看不到;
6. **不许拿它排单、定价**:派单、定价、抢单池的源码里不许出现它;它进响应体只有两个口子;
7. **缓存失效的调用点**都在,而且都在 commit 之后。

分数进了派单或定价就成了绳索(models.py 那句判据)。这类退化不报错 —— 所以用源码守着。
"""
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import UserRole
from app.services import customer_credit as cc
from app.state_machine import OrderStatus

NOW = datetime(2026, 9, 14, 4, 0, tzinfo=timezone.utc)


def order(i=1, days_ago=1):
    return cc.Fact(cc.KIND_ORDER, i, NOW - timedelta(days=days_ago), cc.ORDER_POINTS)


def fault(i=1, days_ago=1):
    return cc.Fact(cc.KIND_DELIVERY, i, NOW - timedelta(days=days_ago),
                   -cc.DELIVERY_FAULT_POINTS, "配送时联系不上")


def violation(i=1, severity="major", days_ago=1):
    return cc.Fact(cc.KIND_VIOLATION, i, NOW - timedelta(days=days_ago),
                   -cc.violation_points(severity), "违规成立")


class Test公式:
    def test_没有任何记录就是起始分(self):
        s = cc.compute([], NOW)
        assert s.score == cc.BASE
        assert (s.plus, s.minus, s.orders_in_window) == (0, 0, 0)

    def test_完成订单每单加分(self):
        s = cc.compute([order(i) for i in range(3)], NOW)
        assert s.score == cc.BASE + 3 * cc.ORDER_POINTS
        assert s.plus == 3 * cc.ORDER_POINTS

    def test_完成订单加分封顶(self):
        n = cc.ORDER_CAP // cc.ORDER_POINTS + 7
        s = cc.compute([order(i) for i in range(n)], NOW)
        assert s.plus == cc.ORDER_CAP
        assert s.orders_in_window == n, "窗口内单数照实给,只是加分封顶"
        assert s.score == min(cc.CEIL, cc.BASE + cc.ORDER_CAP)

    def test_配送判为顾客原因每次扣分(self):
        s = cc.compute([order(1), fault(1), fault(2)], NOW)
        assert s.minus == 2 * cc.DELIVERY_FAULT_POINTS
        assert s.score == cc.BASE + cc.ORDER_POINTS - 2 * cc.DELIVERY_FAULT_POINTS

    def test_违规按严重程度扣分(self):
        s = cc.compute([violation(1, "severe"), violation(2, "major")], NOW)
        assert s.minus == cc.VIOLATION_POINTS["severe"] + cc.VIOLATION_POINTS["major"]
        assert cc.VIOLATION_POINTS["severe"] > cc.VIOLATION_POINTS["major"]

    def test_下限是0(self):
        s = cc.compute([violation(i, "severe") for i in range(20)], NOW)
        assert s.score == cc.FLOOR
        assert s.minus == 20 * cc.VIOLATION_POINTS["severe"], "扣分合计照实给,只是结果不低于下限"

    def test_上限是100(self):
        assert cc.BASE + cc.ORDER_CAP <= cc.CEIL, "起始分加满加分项不该超过上限"
        s = cc.compute([order(i) for i in range(50)], NOW)
        assert s.score <= cc.CEIL

    def test_明细加起来就是分数(self):
        """「为什么是 72 分」必须答得出来:起始分 + 加分 − 扣分,不在上下限外时逐项相加就是分数。"""
        facts = [order(1), order(2), fault(3), violation(4, "major")]
        s = cc.compute(facts, NOW)
        assert s.score == s.base + s.plus - s.minus

    def test_扣分项新的在前(self):
        s = cc.compute([fault(1, days_ago=30), fault(2, days_ago=2), violation(3, days_ago=10)],
                       NOW)
        assert [f.record_id for f in s.deductions] == [2, 3, 1]


class Test时间窗:
    def test_窗口内计分窗口外不计(self):
        inside = cc.WINDOW_DAYS - 1
        outside = cc.WINDOW_DAYS + 1
        s = cc.compute([fault(1, inside), fault(2, outside), order(3, inside),
                        order(4, outside)], NOW)
        assert [f.record_id for f in s.deductions] == [1]
        assert s.orders_in_window == 1

    def test_边界那一刻还算_过一秒就不算(self):
        edge = cc.Fact(cc.KIND_DELIVERY, 1, NOW - timedelta(days=cc.WINDOW_DAYS),
                       -cc.DELIVERY_FAULT_POINTS)
        assert cc.in_window(edge.at, NOW)
        assert not cc.in_window(edge.at, NOW + timedelta(seconds=1))

    def test_到期时刻和窗口互为反面(self):
        """明细页上写「到 X 日不再计分」,那个 X 必须就是窗口滚过去的那一刻。"""
        at = NOW - timedelta(days=17)
        exp = cc.expires_at(at)
        assert cc.in_window(at, exp - timedelta(seconds=1))
        assert not cc.in_window(at, exp + timedelta(seconds=1))

    def test_数据库里取出来的无时区时间按UTC算(self):
        naive = (NOW - timedelta(days=cc.WINDOW_DAYS - 1)).replace(tzinfo=None)
        assert cc.in_window(naive, NOW)


class Test新用户不吃亏:
    def test_最高一档的下沿就是起始分(self):
        assert cc.LEVELS[0].floor == cc.BASE, (
            "新用户起步就该在最高一档 —— 不然一个没有任何问题的人,"
            "只因为是新来的就被标成低一档,接单的人会对他另眼相看")

    @pytest.mark.parametrize("n", [0, 1, 5, 10, 30])
    def test_没有扣分项的人一定是最高一档(self, n):
        s = cc.compute([order(i) for i in range(n)], NOW)
        assert s.level == cc.LEVELS[0], (n, s.score)

    def test_一条扣分就看得出来(self):
        """反过来也要成立:新用户只要有一条计分的扣分项,就不在最高一档。"""
        s = cc.compute([fault(1)], NOW)
        assert s.level != cc.LEVELS[0]

    def test_等级阈值(self):
        top, mid, low = cc.LEVELS
        assert cc.level_of(cc.CEIL) == top
        assert cc.level_of(top.floor) == top
        assert cc.level_of(top.floor - 1) == mid
        assert cc.level_of(mid.floor) == mid
        assert cc.level_of(mid.floor - 1) == low
        assert cc.level_of(cc.FLOOR) == low

    def test_等级从高到低排好(self):
        floors = [lv.floor for lv in cc.LEVELS]
        assert floors == sorted(floors, reverse=True) and floors[-1] == cc.FLOOR


class Test违规分值跟着处置目录走:
    def test_顾客的每一类违规都有分值(self):
        from app.services.enforcement import rules_of
        rules = rules_of("customer")
        assert rules, "处置目录里没有顾客的违规类别了?"
        for r in rules:
            assert cc.violation_points(r.severity) > 0, r.kind

    def test_没配分值的档直接报错不许默认成0(self):
        with pytest.raises(KeyError):
            cc.violation_points("没有这一档")

    def test_处置目录的每一档都配了分值(self):
        from app.services.enforcement import SEVERITY
        assert set(SEVERITY) == set(cc.VIOLATION_POINTS)


class Test公示和计算是同一份:
    def test_公示的数字就是常量(self):
        spec = cc.public_spec()
        assert spec["base"] == cc.BASE
        assert spec["window_days"] == cc.WINDOW_DAYS
        assert spec["range"] == {"min": cc.FLOOR, "max": cc.CEIL}
        plus = spec["plus"][0]
        assert (plus["points"], plus["cap"]) == (cc.ORDER_POINTS, cc.ORDER_CAP)
        minus = {m["key"]: m for m in spec["minus"]}
        assert minus[cc.KIND_DELIVERY]["points"] == -cc.DELIVERY_FAULT_POINTS
        for row in minus[cc.KIND_VIOLATION]["items"]:
            assert row["points"] == -cc.VIOLATION_POINTS[row["severity"]]
        assert [lv["min"] for lv in spec["levels"]] == [lv.floor for lv in cc.LEVELS]

    def test_改常量公示跟着变(self, monkeypatch):
        """真·同源检验:抄一份字面量的实现过不了这条。"""
        monkeypatch.setattr(cc, "BASE", 77)
        monkeypatch.setattr(cc, "DELIVERY_FAULT_POINTS", 13)
        monkeypatch.setattr(cc, "ORDER_CAP", 9)
        spec = cc.public_spec()
        assert spec["base"] == 77 and "77" in spec["formula"]
        assert {m["key"]: m for m in spec["minus"]}[cc.KIND_DELIVERY]["points"] == -13
        assert spec["plus"][0]["cap"] == 9
        assert any("13" in line for line in cc.rules_lines("customer"))

    def test_照着公示自己算一遍和compute一样(self):
        """透明中心那一份是给人照着算的:拿公示里的数自己算,必须和系统算的一致。"""
        spec = cc.public_spec()
        plus_rule = spec["plus"][0]
        minus = {m["key"]: m for m in spec["minus"]}
        sev = {r["severity"]: -r["points"] for r in minus[cc.KIND_VIOLATION]["items"]}
        for n_orders, n_faults, sevs in [(0, 0, []), (3, 1, ["major"]), (14, 2, ["severe"]),
                                         (1, 9, ["severe", "severe", "major"])]:
            by_hand = (spec["base"]
                       + min(n_orders * plus_rule["points"], plus_rule["cap"])
                       + n_faults * minus[cc.KIND_DELIVERY]["points"]
                       - sum(sev[s] for s in sevs))
            by_hand = max(spec["range"]["min"], min(spec["range"]["max"], by_hand))
            facts = ([order(i) for i in range(n_orders)]
                     + [fault(100 + i) for i in range(n_faults)]
                     + [violation(200 + i, s) for i, s in enumerate(sevs)])
            assert cc.compute(facts, NOW).score == by_hand, (n_orders, n_faults, sevs)

    def test_起始分的理由写在公示里(self):
        spec = cc.public_spec()
        assert str(cc.BASE) in spec["base_why"] and cc.LEVELS[0].label in spec["base_why"]

    def test_公示写明不能用来做什么(self):
        never = "".join(cc.public_spec()["never_used_for"])
        for word in ("拒单", "派单", "价格"):
            assert word in never, f"公示里没说不用它{word}"

    def test_公示写明谁能看到什么时候看到(self):
        vis = {v["who"]: v["what"] for v in cc.public_spec()["visibility"]}
        for who in ("商家", "骑手"):
            assert "之后" in vis[who] and "看不到明细" in vis[who], who
        assert "看不到" in vis["其他人"]

    def test_公示写明权利不扣分(self):
        not_counted = "".join(x["what"] for x in cc.public_spec()["not_counted"])
        for word in ("取消", "售后", "差评"):
            assert word in not_counted, f"没写明「{word}」不扣分"

    def test_规则页三端各有一节(self):
        assert any(str(cc.BASE) in line for line in cc.rules_lines("customer"))
        # 商家和骑手是同一件事的两端,措辞一字不差 —— 「一方能做另一方不能做」的反面
        assert cc.rules_lines("merchant") == cc.rules_lines("rider")
        assert any("看不到" in line for line in cc.rules_lines("merchant"))


class Test申诉入口:
    def test_配送异常72小时内走原通道(self):
        f = fault(7, days_ago=1)
        a = cc.appeal_state(f, original=None, ticket=None, now=NOW)
        assert a["via"] == "appeal"
        assert (a["target_type"], a["target_id"]) == ("delivery_issue", 7)
        assert a["deadline"]

    def test_配送异常过了72小时走工单(self):
        a = cc.appeal_state(fault(7, days_ago=4), original=None, ticket=None, now=NOW)
        assert a["via"] == "ticket"

    def test_原通道申诉中不给第二个入口(self):
        a = cc.appeal_state(fault(7), original="open", ticket=None, now=NOW)
        assert a["via"] == "" and a["state"] == "open"

    def test_原通道维持原判之后还能走一次工单(self):
        """维持原判的推送里写着「如有新证据可通过客服工单反馈」—— 那就得真有这个口子。"""
        a = cc.appeal_state(fault(7), original="upheld", ticket=None,
                            original_note="骑手有通话记录", now=NOW)
        assert a["via"] == "ticket" and a["state"] == "upheld"
        assert a["note"] == "骑手有通话记录"

    def test_工单申诉过一次就没有第二次(self):
        for state in ("open", "upheld"):
            a = cc.appeal_state(violation(3), original=None, ticket=state, now=NOW)
            assert a["via"] == "" and a["state"] == state

    def test_违规没有原通道走工单(self):
        a = cc.appeal_state(violation(3), original=None, ticket=None, now=NOW)
        assert a["via"] == "ticket"

    def test_每个入口都写明申诉成立后不再计分(self):
        for a in (cc.appeal_state(fault(1), original=None, ticket=None, now=NOW),
                  cc.appeal_state(violation(2), original=None, ticket=None, now=NOW)):
            assert "不再计分" in a["after"]


def _order(status, *, accepted=True, rider_id=None, customer_id=9):
    return SimpleNamespace(id=1, status=status, customer_id=customer_id, rider_id=rider_id,
                           accepted_at=NOW if accepted else None)


def _user(role, uid=5):
    return SimpleNamespace(id=uid, role=role)


class Test谁能看到:
    merchant = _user(UserRole.merchant)
    rider = _user(UserRole.rider, uid=42)

    def test_商家接单之前看不到(self):
        assert not cc.counterpart_may_see(_order(OrderStatus.PAID, accepted=False),
                                          self.merchant)
        assert not cc.counterpart_may_see(
            _order(OrderStatus.PENDING_PAYMENT, accepted=False), self.merchant)

    @pytest.mark.parametrize("st", [OrderStatus.ACCEPTED, OrderStatus.READY,
                                    OrderStatus.PICKED_UP, OrderStatus.DELIVERED,
                                    OrderStatus.COMPLETED])
    def test_商家接单之后看得到(self, st):
        assert cc.counterpart_may_see(_order(st), self.merchant)

    def test_取消了的单不给(self):
        assert not cc.counterpart_may_see(_order(OrderStatus.CANCELLED), self.merchant)
        assert not cc.counterpart_may_see(_order(OrderStatus.CANCELLED, rider_id=42),
                                          self.rider)

    def test_跑腿单没有商家接单这一步_挂靠主体看不到(self):
        assert not cc.counterpart_may_see(_order(OrderStatus.READY, accepted=False),
                                          self.merchant)

    def test_抢单大厅里的单骑手看不到(self):
        """池子里的单 rider_id 是空的 —— 谁都不是它的骑手。"""
        assert not cc.counterpart_may_see(_order(OrderStatus.ACCEPTED), self.rider)
        assert not cc.counterpart_may_see(_order(OrderStatus.READY), self.rider)

    def test_别人的单骑手看不到(self):
        assert not cc.counterpart_may_see(_order(OrderStatus.READY, rider_id=7), self.rider)

    def test_接到这一单的骑手看得到(self):
        assert cc.counterpart_may_see(_order(OrderStatus.READY, rider_id=42), self.rider)
        assert cc.counterpart_may_see(_order(OrderStatus.PICKED_UP, rider_id=42), self.rider)

    def test_其他角色不走这条(self):
        for role in (UserRole.customer, UserRole.admin):
            assert not cc.counterpart_may_see(_order(OrderStatus.ACCEPTED), _user(role))
        assert not cc.counterpart_may_see(_order(OrderStatus.ACCEPTED), None)

    def test_交易对方只拿到分数和等级(self):
        b = cc.brief_of(cc.compute([fault(1), order(2)], NOW))
        assert set(b) == {"score", "level", "level_label"}, "给交易对方的不许带明细"


def _src(module, name=None):
    obj = getattr(module, name) if name else module
    return inspect.getsource(obj)


def _calls(source: str) -> list[tuple[str, str, int]]:
    """源码里**真的调用**了什么:(对象名, 方法名, 行号)。

    按 AST 找,不按文本找 —— 注释、字符串里写着 `invalidate(` 也算数的话,
    把调用注释掉守卫照样绿(试过:把失效那一行改成注释,文本版的守卫没红)。
    """
    import ast
    import textwrap
    out = []
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute):
            owner = f.value.id if isinstance(f.value, ast.Name) else ""
            out.append((owner, f.attr, node.lineno))
        elif isinstance(f, ast.Name):
            out.append(("", f.id, node.lineno))
    return out


class Test不许拿它排单定价:
    """分数一旦进了派单、排序、定价,就成了绳索。这类退化不报错,只能按源码守。"""

    @pytest.mark.parametrize("mod", ["app.services.dispatch", "app.services.pricing",
                                     "app.services.eta", "app.services.payment_core"])
    def test_派单定价的模块不认识它(self, mod):
        import importlib
        src = inspect.getsource(importlib.import_module(mod))
        assert "customer_credit" not in src and "CustomerCredit" not in src, (
            f"{mod} 读了顾客信用分 —— 它会变成挑单、改价的依据")

    def test_抢单池不带它(self):
        from app.routers import riders
        src = _src(riders, "available_orders")
        assert "customer_credit" not in src and "attach" not in src

    def test_进响应体只有两个口子(self):
        """全仓只在 orders.my_orders 和 orders.get_order 里调 attach。"""
        from pathlib import Path
        root = Path(cc.__file__).resolve().parents[1]
        hits = []
        for p in sorted(root.rglob("*.py")):
            n = sum(1 for owner, name, _ in _calls(p.read_text(encoding="utf-8"))
                    if name == "attach" and owner in ("customer_credit", "cc"))
            if n:
                hits.append((p.relative_to(root).as_posix(), n))
        assert hits == [("routers/orders.py", 2)], hits
        from app.routers import orders
        for fn in ("my_orders", "get_order"):
            assert ("customer_credit", "attach") in {(o, n) for o, n, _ in
                                                     _calls(_src(orders, fn))}, fn

    def test_order_out不带它(self):
        """order_out 被抢单池、抢单回执、状态流转、开放接口共用 —— 放进去就全漏了。"""
        from app.routers import orders
        assert "customer_credit" not in _src(orders, "order_out")
        assert "customer_credit" not in _src(orders, "orders_out")

    def test_默认是空的(self):
        from app.schemas import OrderOut
        assert OrderOut.model_fields["customer_credit"].default is None


class Test缓存:
    def test_键带公式版本(self):
        assert f"v{cc.FORMULA_VERSION}" in cc._CACHE_PREFIX

    def test_读用mget写用pipeline(self):
        src = _src(cc, "briefs_for")
        assert "mget" in src, "十几个顾客逐个 GET 就是十几次往返"
        assert "_put_cache" in src and "pipeline" in _src(cc, "_put_cache")

    def test_只补差集(self):
        src = _src(cc, "briefs_for")
        assert "ids = [i for i in ids if i not in cached]" in src
        assert "if not ids:\n        return cached" in src

    @pytest.mark.parametrize("module,fn", [
        ("app.routers.orders", "transition"),
        ("app.routers.orders", "pickup_verify"),
        ("app.routers.admin", "resolve_delivery_issue"),
        ("app.routers.admin", "record_violation"),
        ("app.routers.admin", "overturn_violation"),
        ("app.routers.admin", "risk_verdict"),
        ("app.routers.appeals", "resolve_appeal"),
        ("app.services.auto_flow", "sweep_once"),
        ("app.routers.customer_credit", "resolve_credit_appeal"),
        ("app.routers.customer_credit", "submit_credit_appeal"),
    ])
    def test_事实变了的地方都打缓存_而且在提交之后(self, module, fn):
        """订单完成、裁决、违规判定、申诉改判 —— 漏一处,交易对方看到的分数就晚 TTL 那么久。
        提交之前打的话,别的请求可能正好按旧数据算一遍又写回去。"""
        import importlib
        calls = _calls(inspect.getsource(getattr(importlib.import_module(module), fn)))
        inv = [line for _, name, line in calls if name == "invalidate"]
        com = [line for _, name, line in calls if name == "commit"]
        assert inv, f"{module}.{fn} 改了计分的事实却没打缓存"
        assert com and min(com) < min(inv), f"{module}.{fn} 在提交之前就打了缓存"
