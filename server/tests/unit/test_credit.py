"""信用分(services/credit.py):顾客、商家、骑手三种角色,同一套机制。

## 这组测试守什么

1. **公式本身**:起始分、每一项的分值、封顶、上下限、时间窗边界、等级 —— 全在纯函数 compute 里;
2. **新来的不吃亏**:没有扣分项的人一定在最高一档,新老都一样;
3. **公示和计算是同一份**:透明中心 / 规则页的数字从常量来,改常量公示跟着变,
   拿公示的数字自己算一遍和 compute 的结果对得上 —— 三种角色都是;
4. **三种角色同一套机制**:公式、窗口、等级、申诉规矩、可见范围的结构一模一样,
   只有「什么算扣分」「什么不扣分」按角色不同;
5. **申诉入口**:接得上原通道的走原通道(改判连钱和记录一起改),接不上的走工单;
6. **谁能看到**:接单之后、只在这一单上、只给这一单的交易对方;
7. **不许拿它派单、定价、排序、曝光、处置**:那些模块里按语法树找,不许出现它;
   它进响应体只有两个口子;
8. **缓存失效的调用点**都在,而且都在 commit 之后。

分数进了派单、排序、定价、处置就成了绳索(models.py 那句判据)。这类退化不报错 —— 所以用源码守着。
"""
import ast
import asyncio
import importlib
import inspect
import textwrap
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import UserRole
from app.services import credit as cc
from app.state_machine import OrderStatus

NOW = datetime(2026, 9, 14, 4, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _起算日拨到很久以前(monkeypatch):
    """起算日(config.credit_count_from)默认 2026-09-15,比这里的 NOW 还晚 —— 不拨开的话,
    下面每一条带扣分项的用例都会被起算日挡掉,测的就不是它们自己那件事了。
    专门验起算日的 Test起算日 自己再设。"""
    monkeypatch.setattr(cc.settings, "credit_count_from", date(2000, 1, 1))


def fault(i=1, days_ago=1, kind=None):
    return cc.Fact(kind or cc.KIND_DELIVERY, i, NOW - timedelta(days=days_ago),
                   -cc.FAULT_POINTS, "判为你的责任")


def violation(i=1, severity="major", days_ago=1):
    return cc.Fact(cc.KIND_VIOLATION, i, NOW - timedelta(days=days_ago),
                   -cc.violation_points(severity), "违规成立")


class Test公式:
    def test_没有任何记录就是起始分(self):
        s = cc.compute(0, [], NOW)
        assert s.score == cc.BASE
        assert (s.plus, s.minus, s.orders_in_window) == (0, 0, 0)

    def test_完成订单每单加分(self):
        s = cc.compute(3, [], NOW)
        assert s.score == cc.BASE + 3 * cc.ORDER_POINTS
        assert s.plus == 3 * cc.ORDER_POINTS

    def test_完成订单加分封顶(self):
        n = cc.ORDER_CAP // cc.ORDER_POINTS + 7
        s = cc.compute(n, [], NOW)
        assert s.plus == cc.ORDER_CAP
        assert s.orders_in_window == n, "窗口内单数照实给,只是加分封顶"
        assert s.score == min(cc.CEIL, cc.BASE + cc.ORDER_CAP)

    def test_判为你的责任每次扣分(self):
        s = cc.compute(1, [fault(1), fault(2, kind=cc.KIND_AFTER_SALE)], NOW)
        assert s.minus == 2 * cc.FAULT_POINTS
        assert s.score == cc.BASE + cc.ORDER_POINTS - 2 * cc.FAULT_POINTS

    def test_违规按严重程度扣分(self):
        s = cc.compute(0, [violation(1, "severe"), violation(2, "major")], NOW)
        assert s.minus == cc.VIOLATION_POINTS["severe"] + cc.VIOLATION_POINTS["major"]
        assert cc.VIOLATION_POINTS["severe"] > cc.VIOLATION_POINTS["major"]

    def test_下限是0(self):
        s = cc.compute(0, [violation(i, "severe") for i in range(20)], NOW)
        assert s.score == cc.FLOOR
        assert s.minus == 20 * cc.VIOLATION_POINTS["severe"], "扣分合计照实给,只是结果不低于下限"

    def test_上限是100(self):
        assert cc.BASE + cc.ORDER_CAP <= cc.CEIL, "起始分加满加分项不该超过上限"
        assert cc.compute(50, [], NOW).score <= cc.CEIL

    def test_明细加起来就是分数(self):
        """「为什么是 72 分」必须答得出来:起始分 + 加分 − 扣分,不在上下限外时逐项相加就是分数。"""
        s = cc.compute(2, [fault(3), violation(4, "major")], NOW)
        assert s.score == s.base + s.plus - s.minus

    def test_扣分项新的在前(self):
        s = cc.compute(0, [fault(1, days_ago=30), fault(2, days_ago=2),
                           violation(3, days_ago=10)], NOW)
        assert [f.record_id for f in s.deductions] == [2, 3, 1]

    def test_加分项混进扣分列表也不会被当成扣分(self):
        plus = cc.Fact(cc.KIND_ORDER, 9, NOW, cc.ORDER_POINTS)
        assert cc.compute(0, [plus], NOW).minus == 0


class Test时间窗:
    def test_窗口内计分窗口外不计(self):
        s = cc.compute(0, [fault(1, cc.WINDOW_DAYS - 1), fault(2, cc.WINDOW_DAYS + 1)], NOW)
        assert [f.record_id for f in s.deductions] == [1]

    def test_边界那一刻还算_过一秒就不算(self):
        edge = NOW - timedelta(days=cc.WINDOW_DAYS)
        assert cc.in_window(edge, NOW)
        assert not cc.in_window(edge, NOW + timedelta(seconds=1))

    def test_到期时刻和窗口互为反面(self):
        """明细页上写「到 X 日不再计分」,那个 X 必须就是窗口滚过去的那一刻。"""
        at = NOW - timedelta(days=17)
        exp = cc.expires_at(at)
        assert cc.in_window(at, exp - timedelta(seconds=1))
        assert not cc.in_window(at, exp + timedelta(seconds=1))

    def test_数据库里取出来的无时区时间按UTC算(self):
        naive = (NOW - timedelta(days=cc.WINDOW_DAYS - 1)).replace(tzinfo=None)
        assert cc.in_window(naive, NOW)


class Test起算日:
    """旧裁决不算:扣分只算起算日(北京日期,含这一天)之后的裁决和判定;加分不跟着它走。"""

    CF = date(2026, 9, 15)

    @pytest.fixture(autouse=True)
    def _默认的起算日(self, monkeypatch):
        monkeypatch.setattr(cc.settings, "credit_count_from", self.CF)

    def test_默认是2026年9月15日(self):
        from app.config import Settings
        assert Settings.model_fields["credit_count_from"].default == self.CF

    def test_按北京日期的零点算(self):
        assert cc.count_from() == datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)
        assert cc.count_from_label() == "2026-09-15"

    def test_起算日之前的不算_当天零点起就算(self):
        edge = cc.count_from()
        now = edge + timedelta(days=30)
        facts = [
            cc.Fact(cc.KIND_DELIVERY, 1, edge - timedelta(seconds=1), -cc.FAULT_POINTS),
            cc.Fact(cc.KIND_AFTER_SALE, 2, edge, -cc.FAULT_POINTS),
            cc.Fact(cc.KIND_VIOLATION, 3, edge - timedelta(days=3),
                    -cc.violation_points("severe")),
            cc.Fact(cc.KIND_VIOLATION, 4, edge + timedelta(days=1),
                    -cc.violation_points("major")),
        ]
        s = cc.compute(0, facts, now)
        assert [f.record_id for f in s.deductions] == [4, 2]
        assert s.minus == cc.FAULT_POINTS + cc.violation_points("major")
        assert not cc.counts(edge - timedelta(seconds=1), now)
        assert cc.counts(edge, now)

    def test_无时区的时间按UTC比(self):
        edge = cc.count_from()
        assert cc.counts(edge.replace(tzinfo=None), edge + timedelta(days=1))
        assert not cc.counts((edge - timedelta(minutes=1)).replace(tzinfo=None),
                             edge + timedelta(days=1))

    def test_加分不跟着起算日走(self):
        """完成订单照常看时间窗:起算日只是说旧裁决不算,不把谁清回起始分。"""
        now = cc.count_from() + timedelta(days=1)
        assert cc.compute(7, [], now).plus == 7 * cc.ORDER_POINTS
        src = _src(cc, "_order_rows") + _src(cc, "_recent_orders")
        assert "count_from" not in src and "deduction_since" not in src

    def test_查询的下沿和compute同一个口径(self):
        edge = cc.count_from()
        assert cc.deduction_since(edge + timedelta(days=10)) == edge
        far = edge + timedelta(days=cc.WINDOW_DAYS + 10)
        assert cc.deduction_since(far) == cc.window_start(far), \
            "起算日落到时间窗外之后就不再起作用"
        assert "deduction_since(now)" in _src(cc, "load_facts"), "扣分项的查询没按起算日取下沿"
        assert "deduction_since(now)" in _src(cc, "_excluded")

    def test_工单申诉按同一个口径认记录(self):
        """起算日之前的那一条不计分,也就不需要申诉(404),和明细页一致。"""
        assert "counts(f.at, now)" in _src(cc, "submit_ticket_appeal")

    def test_公示写明起算日和理由_改配置公示跟着变(self, monkeypatch):
        monkeypatch.setattr(cc.settings, "credit_count_from", date(2026, 10, 1))
        for role in cc.ROLES:
            spec = cc.public_spec(role)
            assert spec["count_from"] == "2026-10-01", role
            assert "2026-10-01" in spec["formula"], role
            assert "2026-10-01" in spec["count_from_why"] and "加分" in spec["count_from_why"]
            assert any("2026-10-01" in line for line in cc.rules_lines(role)), role
        assert cc.count_from() == datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)

    def test_缓存键升了版本(self):
        """口径变了(v3 起扣分只算起算日之后的):部署之后不能拿旧口径算好的缓存回答。"""
        assert cc.FORMULA_VERSION >= 3


class Test新来的不吃亏:
    def test_最高一档的下沿就是起始分(self):
        assert cc.LEVELS[0].floor == cc.BASE, (
            "新来的起步就该在最高一档 —— 不然一个没有任何问题的人,"
            "只因为是新来的就被标成低一档,交易对方会对他另眼相看")

    @pytest.mark.parametrize("n", [0, 1, 5, 10, 30])
    def test_没有扣分项的人一定是最高一档(self, n):
        s = cc.compute(n, [], NOW)
        assert s.level == cc.LEVELS[0], (n, s.score)

    def test_一条扣分就看得出来(self):
        assert cc.compute(0, [fault(1)], NOW).level != cc.LEVELS[0]

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
    @pytest.mark.parametrize("role", cc.ROLES)
    def test_每种角色的每一类违规都有分值(self, role):
        from app.services.enforcement import rules_of
        rules = rules_of(role)
        assert rules, f"处置目录里没有{role}的违规类别了?"
        for r in rules:
            assert cc.violation_points(r.severity) > 0, (role, r.kind)

    def test_没配分值的档直接报错不许默认成0(self):
        with pytest.raises(KeyError):
            cc.violation_points("没有这一档")

    def test_处置目录的每一档都配了分值(self):
        from app.services.enforcement import SEVERITY
        assert set(SEVERITY) == set(cc.VIOLATION_POINTS)

    def test_三种角色正好是处置目录里的三种人(self):
        from app.services.enforcement import CATALOG
        assert set(cc.ROLES) == {r.audience for r in CATALOG}


def _by_hand(spec: dict, orders: int, faults: dict[str, int], sevs: list[str]) -> int:
    """照着公示的数算:起始分 + min(单数 × 每单分, 封顶) + 各项扣分,夹在范围里。"""
    plus = spec["plus"][0]
    minus = {m["key"]: m for m in spec["minus"]}
    sev = {r["severity"]: -r["points"] for r in minus[cc.KIND_VIOLATION]["items"]}
    s = (spec["base"] + min(orders * plus["points"], plus["cap"])
         + sum(n * minus[k]["points"] for k, n in faults.items())
         - sum(sev[x] for x in sevs))
    return max(spec["range"]["min"], min(spec["range"]["max"], s))


class Test公示和计算是同一份:
    @pytest.mark.parametrize("role", cc.ROLES)
    def test_公示的数字就是常量(self, role):
        spec = cc.public_spec(role)
        assert spec["role"] == role and spec["base"] == cc.BASE
        assert spec["window_days"] == cc.WINDOW_DAYS
        assert spec["range"] == {"min": cc.FLOOR, "max": cc.CEIL}
        plus = spec["plus"][0]
        assert (plus["points"], plus["cap"]) == (cc.ORDER_POINTS, cc.ORDER_CAP)
        for m in spec["minus"]:
            if m["key"] == cc.KIND_VIOLATION:
                for row in m["items"]:
                    assert row["points"] == -cc.VIOLATION_POINTS[row["severity"]]
            else:
                assert m["points"] == -cc.FAULT_POINTS, m["key"]
        assert [lv["min"] for lv in spec["levels"]] == [lv.floor for lv in cc.LEVELS]

    def test_公示的扣分项就是能申诉的那几种(self):
        """公示里列了什么扣分项,本人就能申诉什么 —— 少一项就是有扣分没申诉口。"""
        for role in cc.ROLES:
            keys = tuple(m["key"] for m in cc.public_spec(role)["minus"])
            assert set(keys) == set(cc.APPEALABLE_KINDS[role]), role

    def test_改常量公示跟着变(self, monkeypatch):
        """真·同源检验:抄一份字面量的实现过不了这条。三种角色都要跟着变。"""
        monkeypatch.setattr(cc, "BASE", 77)
        monkeypatch.setattr(cc, "FAULT_POINTS", 13)
        monkeypatch.setattr(cc, "ORDER_CAP", 9)
        for role in cc.ROLES:
            spec = cc.public_spec(role)
            assert spec["base"] == 77 and "77" in spec["formula"], role
            assert all(m["points"] == -13 for m in spec["minus"]
                       if m["key"] != cc.KIND_VIOLATION), role
            assert spec["plus"][0]["cap"] == 9, role
            assert any("13" in line for line in cc.rules_lines(role)), role

    @pytest.mark.parametrize("role", cc.ROLES)
    def test_照着公示自己算一遍和compute一样(self, role):
        """透明中心那一份是给人照着算的:拿公示里的数自己算,必须和系统算的一致。"""
        spec = cc.public_spec(role)
        fault_kinds = [m["key"] for m in spec["minus"] if m["key"] != cc.KIND_VIOLATION]
        for orders, nf, sevs in [(0, 0, []), (3, 1, ["major"]), (14, 2, ["severe"]),
                                 (1, 9, ["severe", "severe", "major"])]:
            faults = {k: nf for k in fault_kinds}
            facts = ([fault(100 + i + 20 * j, kind=k) for j, k in enumerate(fault_kinds)
                      for i in range(nf)]
                     + [violation(200 + i, s) for i, s in enumerate(sevs)])
            assert cc.compute(orders, facts, NOW).score == _by_hand(spec, orders, faults, sevs), \
                (role, orders, nf, sevs)

    def test_三种角色的机制一模一样(self):
        """同一套机制:公式、起始分、窗口、等级、上下限、申诉规矩、刷新口径都一字不差 ——
        只有「什么算扣分」「什么不扣分」「谁看得到」按角色不同。"""
        same = ("version", "range", "base", "window_days", "formula", "levels",
                "minus_cap", "appeal", "count_from", "count_from_why")
        specs = [cc.public_spec(r) for r in cc.ROLES]
        for k in same:
            assert len({repr(s[k]) for s in specs}) == 1, f"「{k}」三种角色不一样"
        assert len({repr(set(s)) for s in specs}) == 1, "三种角色公示的字段不一样"

    @pytest.mark.parametrize("role", cc.ROLES)
    def test_起始分的理由写在公示里(self, role):
        spec = cc.public_spec(role)
        assert str(cc.BASE) in spec["base_why"] and cc.LEVELS[0].label in spec["base_why"]

    def test_公示写明不能用来做什么(self):
        must = {"customer": ("拒单", "派单", "价格"),
                "merchant": ("排序", "曝光", "搜索", "骑手", "处置"),
                "rider": ("派单", "配送费", "处置", "服务分")}
        for role, words in must.items():
            never = "".join(cc.public_spec(role)["never_used_for"])
            for w in words:
                assert w in never, f"{role} 的公示里没说不用它{w}"

    def test_公示写明谁能看到什么时候看到(self):
        others = {"customer": ("商家", "骑手"), "merchant": ("顾客", "骑手"),
                  "rider": ("顾客", "商家")}
        for role, whos in others.items():
            vis = {v["who"]: v["what"] for v in cc.public_spec(role)["visibility"]}
            for who in whos:
                assert "之后" in vis[who] and "看不到明细" in vis[who], (role, who)
            assert "看不到" in vis["其他人"], role

    def test_公示写明权利不扣分(self):
        must = {"customer": ("取消", "售后", "差评"),
                "merchant": ("拒单", "同意的售后", "出餐慢", "差评", "接单后取消"),
                "rider": ("转单", "下线", "差评", "上报配送异常", "送得慢")}
        for role, words in must.items():
            not_counted = "".join(x["what"] for x in cc.public_spec(role)["not_counted"])
            for w in words:
                assert w in not_counted, f"{role}:没写明「{w}」不扣分"

    def test_商家自己同意的退款写明不算(self):
        m = {x["key"]: x for x in cc.public_spec("merchant")["minus"]}
        assert "同意" in m[cc.KIND_AFTER_SALE]["counts"]

    def test_规则页三种角色同一个结构(self):
        """「一方能做另一方不能做」的反面:三种角色的「信用分」一节一样长、同一个顺序,
        「交易对方的信用分」一节也一样。"""
        own = [cc.rules_lines(r) for r in cc.ROLES]
        assert len({len(x) for x in own}) == 1
        for lines in own:
            assert str(cc.BASE) in lines[1] and "申诉" in lines[-1]
        other = [cc.counterpart_lines(r) for r in cc.ROLES]
        assert len({len(x) for x in other}) == 1
        assert len({x[-1] for x in other}) == 1, "公式在哪那一句三种角色该一字不差"
        for r in ("merchant", "rider"):
            assert any("看不到" in line for line in cc.counterpart_lines(r)), r


class Test申诉入口:
    def test_原通道都是真的申诉类型(self):
        """声称有的通道必须真的存在:原通道的 target_type 必须是 appeals 收的值。"""
        from typing import get_args

        from app.routers.appeals import AppealIn
        allowed = set(get_args(AppealIn.model_fields["target_type"].annotation))
        for (role, kind), channel in cc.ORIGINAL_CHANNEL.items():
            assert channel in allowed, (role, kind, channel)
            assert kind in cc.APPEALABLE_KINDS[role], (role, kind)

    def test_工单申诉收的种类覆盖三种角色(self):
        from typing import get_args

        from app.routers.credit import CreditAppealIn
        allowed = set(get_args(CreditAppealIn.model_fields["kind"].annotation))
        for role, kinds in cc.APPEALABLE_KINDS.items():
            assert set(kinds) <= allowed, role

    @pytest.mark.parametrize("role,kind,channel", [
        ("customer", cc.KIND_DELIVERY, "delivery_issue"),
        ("rider", cc.KIND_DELIVERY, "delivery_issue"),
        ("merchant", cc.KIND_AFTER_SALE, "after_sale"),
    ])
    def test_72小时内走原通道(self, role, kind, channel):
        f = fault(7, days_ago=1, kind=kind)
        a = cc.appeal_state(role, f, original=None, ticket=None, now=NOW)
        assert a["via"] == "appeal"
        assert (a["target_type"], a["target_id"]) == (channel, 7)
        assert a["deadline"] and "不再计分" in a["confirm"]

    @pytest.mark.parametrize("role,kind", [
        ("customer", cc.KIND_DELIVERY), ("rider", cc.KIND_DELIVERY),
        ("merchant", cc.KIND_AFTER_SALE)])
    def test_过了72小时走工单(self, role, kind):
        a = cc.appeal_state(role, fault(7, days_ago=4, kind=kind), original=None, ticket=None,
                            now=NOW)
        assert a["via"] == "ticket"

    def test_骑手的售后判责没有原通道_直接走工单(self):
        a = cc.appeal_state("rider", fault(7, kind=cc.KIND_AFTER_SALE), original=None,
                            ticket=None, now=NOW)
        assert a["via"] == "ticket" and a["target_type"] == ""

    def test_原通道申诉中不给第二个入口(self):
        a = cc.appeal_state("rider", fault(7), original="open", ticket=None, now=NOW)
        assert a["via"] == "" and a["state"] == "open"

    def test_原通道维持原判之后还能走一次工单(self):
        """维持原判的推送里写着「如有新证据可通过客服工单反馈」—— 那就得真有这个口子。"""
        a = cc.appeal_state("merchant", fault(7, kind=cc.KIND_AFTER_SALE), original="upheld",
                            ticket=None, original_note="照片看得出盒子是破的", now=NOW)
        assert a["via"] == "ticket" and a["state"] == "upheld"
        assert a["note"] == "照片看得出盒子是破的"

    @pytest.mark.parametrize("role", cc.ROLES)
    def test_工单申诉过一次就没有第二次(self, role):
        for state in ("open", "upheld"):
            a = cc.appeal_state(role, violation(3), original=None, ticket=state, now=NOW)
            assert a["via"] == "" and a["state"] == state

    @pytest.mark.parametrize("role", cc.ROLES)
    def test_违规没有原通道走工单(self, role):
        a = cc.appeal_state(role, violation(3), original=None, ticket=None, now=NOW)
        assert a["via"] == "ticket" and a["confirm"]

    def test_每个入口都写明申诉成立后不再计分(self):
        for role, kinds in cc.APPEALABLE_KINDS.items():
            for kind in kinds:
                f = violation(2) if kind == cc.KIND_VIOLATION else fault(1, kind=kind)
                a = cc.appeal_state(role, f, original=None, ticket=None, now=NOW)
                assert "不再计分" in a["after"] and "不再计分" in a["confirm"], (role, kind)


def _order(status, *, accepted=True, rider_id=None, customer_id=9, kind="food"):
    return SimpleNamespace(id=1, status=status, customer_id=customer_id, rider_id=rider_id,
                           merchant_id=3, order_kind=kind,
                           accepted_at=NOW if accepted else None)


def _user(role, uid=5):
    return SimpleNamespace(id=uid, role=role)


ONGOING = [OrderStatus.ACCEPTED, OrderStatus.READY, OrderStatus.PICKED_UP,
           OrderStatus.DELIVERED, OrderStatus.COMPLETED]


class Test谁能看到:
    merchant = _user(UserRole.merchant)
    rider = _user(UserRole.rider, uid=42)
    customer = _user(UserRole.customer, uid=9)

    def see(self, order, viewer):
        return cc.visible_parties(order, viewer)

    def test_接单之前谁都看不到(self):
        for st in (OrderStatus.PAID, OrderStatus.PENDING_PAYMENT):
            o = _order(st, accepted=False)
            for v in (self.merchant, self.rider, self.customer):
                assert self.see(o, v) == frozenset(), (st, v.role)

    @pytest.mark.parametrize("st", ONGOING)
    def test_商家接单之后_看得到顾客的_骑手接单后才看得到骑手的(self, st):
        assert self.see(_order(st), self.merchant) == {"customer"}
        assert self.see(_order(st, rider_id=42), self.merchant) == {"customer", "rider"}

    @pytest.mark.parametrize("st", ONGOING)
    def test_顾客在商家接单之后看得到商家的_骑手接单后看得到骑手的(self, st):
        assert self.see(_order(st), self.customer) == {"merchant"}
        assert self.see(_order(st, rider_id=42), self.customer) == {"merchant", "rider"}

    def test_接到这一单的骑手看得到顾客和商家的(self):
        for st in (OrderStatus.READY, OrderStatus.PICKED_UP, OrderStatus.COMPLETED):
            assert self.see(_order(st, rider_id=42), self.rider) == {"customer", "merchant"}

    def test_取消了的单不给(self):
        o = _order(OrderStatus.CANCELLED, rider_id=42)
        for v in (self.merchant, self.rider, self.customer):
            assert self.see(o, v) == frozenset()

    def test_抢单大厅里的单骑手看不到(self):
        """池子里的单 rider_id 是空的 —— 谁都不是它的骑手。"""
        assert self.see(_order(OrderStatus.ACCEPTED), self.rider) == frozenset()
        assert self.see(_order(OrderStatus.READY), self.rider) == frozenset()

    def test_别人的单看不到(self):
        assert self.see(_order(OrderStatus.READY, rider_id=7), self.rider) == frozenset()
        assert self.see(_order(OrderStatus.READY, customer_id=10), self.customer) == frozenset()

    def test_跑腿单没有商家(self):
        """跑腿单挂的是每城一个的虚拟服务主体:没有「商家接单」这一步,也没有商家的分可给。"""
        o = _order(OrderStatus.PICKED_UP, rider_id=42, accepted=False, kind="errand_buy")
        assert self.see(o, self.customer) == {"rider"}
        assert self.see(o, self.rider) == {"customer"}
        assert self.see(o, self.merchant) == frozenset()
        # 就算哪天跑腿单也记了 accepted_at,商家那一方照样不给
        o2 = _order(OrderStatus.PICKED_UP, rider_id=42, kind="errand_send")
        assert "merchant" not in self.see(o2, self.customer)
        assert "merchant" not in self.see(o2, self.rider)

    def test_其他角色不走这条(self):
        assert self.see(_order(OrderStatus.ACCEPTED, rider_id=42),
                        _user(UserRole.admin)) == frozenset()
        assert self.see(_order(OrderStatus.ACCEPTED), None) == frozenset()

    def test_交易对方只拿到分数和等级(self):
        b = cc.brief_of(cc.compute(1, [fault(1)], NOW))
        assert set(b) == {"score", "level", "level_label"}, "给交易对方的不许带明细"

    def test_看得到的状态就是接单之后没取消的那几个(self):
        assert set(cc.COUNTERPART_STATUS_VALUES) == {s.value for s in ONGOING}


# ---------------------------------------------------------------------------
# 源码守卫
# ---------------------------------------------------------------------------


def _src(module, name=None):
    obj = getattr(module, name) if name else module
    return inspect.getsource(obj)


def _calls(source: str) -> list[tuple[str, str, int]]:
    """源码里**真的调用**了什么:(对象名, 方法名, 行号)。

    按 AST 找,不按文本找 —— 注释、字符串里写着 `invalidate(` 也算数的话,
    把调用注释掉守卫照样绿(试过:把失效那一行改成注释,文本版的守卫没红)。
    """
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


#: 信用分的模块、给交易对方的三个字段、只有信用分才有的名字
_CREDIT_MODULES = {"credit", "customer_credit"}
_CREDIT_FIELDS = {"customer_credit", "merchant_credit", "rider_credit"}
_CREDIT_NAMES = {"CreditBriefOut", "briefs_for", "visible_parties", "CreditAppeal"}


def _credit_refs(source: str) -> list[str]:
    """源码里**真的引用**了信用分的地方(按 AST):import 了信用分模块、读写那三个字段、
    用了只有信用分才有的名字、按字符串 getattr 那三个字段。注释和文档里提到不算。"""
    hits = []
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[-1]
            names = {a.name for a in node.names}
            if mod in _CREDIT_MODULES or names & (_CREDIT_MODULES | _CREDIT_NAMES):
                hits.append(f"第 {node.lineno} 行 from {node.module} import {sorted(names)}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[-1] in _CREDIT_MODULES:
                    hits.append(f"第 {node.lineno} 行 import {a.name}")
        elif isinstance(node, ast.Attribute) and node.attr in _CREDIT_FIELDS | _CREDIT_NAMES:
            hits.append(f"第 {node.lineno} 行 .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in _CREDIT_FIELDS | _CREDIT_NAMES:
            hits.append(f"第 {node.lineno} 行 {node.id}")
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and node.value in _CREDIT_FIELDS):
            hits.append(f"第 {getattr(node, 'lineno', '?')} 行 '{node.value}'")
    return hits


class Test守卫自己认得出引用:
    """守卫要是一直返回空,等于没有守卫 —— 先证明它认得出每一种写法。"""

    @pytest.mark.parametrize("snippet", [
        "from ..services import credit",
        "from .credit import briefs_for",
        "from ..services.credit import visible_parties",
        "import app.services.credit",
        "from ..services import customer_credit",
        "x = out.rider_credit",
        "getattr(o, 'merchant_credit')",
        "w = CreditBriefOut(score=1, level='good', level_label='良好')",
    ])
    def test_认得出(self, snippet):
        assert _credit_refs(snippet), snippet

    @pytest.mark.parametrize("snippet", [
        "# 这里不许读 credit.briefs_for",
        "'''merchant_credit 只在订单详情里有'''",
        "from .settlement import credit_merchant_for_order",
        "credit_merchant_for_order(order)",
    ])
    def test_不误报(self, snippet):
        assert not _credit_refs(snippet), snippet


class Test不许拿它派单定价排序处置:
    """分数一旦进了派单、定价、店铺排序、曝光、搜索、处置,就成了绳索。
    这类退化不报错,只能按源码守。"""

    @pytest.mark.parametrize("mod", [
        "app.services.dispatch",       # 派单、抢单池排序
        "app.services.pricing",        # 配送费、定价
        "app.services.eta",            # 送达时间、超时判赔
        "app.services.payment_core",   # 支付、自动接单
        "app.services.settlement",     # 结算、分账
        "app.services.enforcement",    # 处置:照旧按违规计次,和分数无关
        "app.services.push",           # 新单推送、状态推送
        "app.services.routing",        # 距离、路线
        "app.services.hardship",       # 地址难度补时补钱:反馈的权重不看人
        "app.routers.open_api",        # 开放接口(POS)
        "app.ws",                      # WebSocket
    ])
    def test_这些模块不认识它(self, mod):
        hits = _credit_refs(inspect.getsource(importlib.import_module(mod)))
        assert not hits, f"{mod} 引用了信用分 —— 它会变成派单、定价、处置的依据:{hits}"

    @pytest.mark.parametrize("mod,fn", [
        ("app.routers.riders", "available_orders"),   # 抢单大厅
        ("app.routers.riders", "grab_order"),         # 抢单回执
        ("app.routers.merchants", "list_merchants"),  # 店铺列表、排序、曝光
        ("app.routers.merchants", "search_merchants"),
        ("app.routers.merchants", "search_suggest"),
        ("app.routers.merchants", "merchant_detail"),  # 店铺页
        ("app.routers.merchants", "merchant_by_code"),
        ("app.routers.merchants", "menu"),
        ("app.routers.orders", "create_order"),       # 下单:不许按分拒单、改价
        ("app.routers.orders", "order_out"),          # 抢单池、回执、开放接口共用
        ("app.routers.orders", "orders_out"),
    ])
    def test_这些口子不带它(self, mod, fn):
        hits = _credit_refs(_src(importlib.import_module(mod), fn))
        assert not hits, f"{mod}.{fn} 引用了信用分:{hits}"

    def test_店铺出参里没有它(self):
        from app.schemas import MerchantOut
        assert not set(MerchantOut.model_fields) & (_CREDIT_FIELDS | {"credit"})

    def test_进响应体只有两个口子(self):
        """全仓只在 orders.my_orders 和 orders.get_order 里调 attach。"""
        root = Path(cc.__file__).resolve().parents[1]
        hits = []
        for p in sorted(root.rglob("*.py")):
            n = sum(1 for owner, name, _ in _calls(p.read_text(encoding="utf-8"))
                    if name == "attach" and owner in ("credit", "customer_credit", "cc"))
            if n:
                hits.append((p.relative_to(root).as_posix(), n))
        assert hits == [("routers/orders.py", 2)], hits
        from app.routers import orders
        for fn in ("my_orders", "get_order"):
            assert ("credit", "attach") in {(o, n) for o, n, _ in _calls(_src(orders, fn))}, fn

    def test_字段只有attach写(self):
        """那三个字段在服务端只有 credit.attach 一处赋值(setattr 按角色拼名字)。"""
        root = Path(cc.__file__).resolve().parents[1]
        writers = []
        for p in sorted(root.rglob("*.py")):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        if isinstance(t, ast.Attribute) and t.attr in _CREDIT_FIELDS:
                            writers.append(p.relative_to(root).as_posix())
        assert writers == [], f"有地方直接给信用分字段赋值:{writers}"

    def test_默认是空的(self):
        from app.schemas import OrderOut
        for f in _CREDIT_FIELDS:
            assert OrderOut.model_fields[f].default is None, f


class Test缓存:
    def test_键带公式版本和角色(self):
        assert f"v{cc.FORMULA_VERSION}" in cc._CACHE_PREFIX
        keys = {cc._key(r, 7) for r in cc.ROLES}
        assert len(keys) == 3, "三种角色的键不能撞"

    def test_读用mget写用pipeline(self):
        src = _src(cc, "briefs_for")
        assert "mget" in src, "十几个人逐个 GET 就是十几次往返"
        assert "_put_cache" in src and "pipeline" in _src(cc, "_put_cache")

    def test_只补差集(self):
        src = _src(cc, "briefs_for")
        assert "ids = [i for i in ids if i not in cached]" in src
        assert "if not ids:\n        return cached" in src

    def test_打缓存三种角色的键一起打(self, monkeypatch):
        """调用方只知道 user_id,不一定知道他是什么角色 —— 打的时候三种角色的键都删。"""
        deleted = []

        class FakeRedis:
            async def delete(self, *keys):
                deleted.extend(keys)

        monkeypatch.setattr(cc, "get_redis", lambda: FakeRedis())
        asyncio.run(cc.invalidate(7, None, 8))
        assert set(deleted) == {cc._key(r, u) for r in cc.ROLES for u in (7, 8)}

    @pytest.mark.parametrize("module,fn", [
        ("app.routers.orders", "transition"),
        ("app.routers.orders", "pickup_verify"),
        ("app.routers.admin", "resolve_delivery_issue"),
        ("app.routers.admin", "after_sale_rider_fault"),
        ("app.routers.admin", "record_violation"),
        ("app.routers.admin", "overturn_violation"),
        ("app.routers.admin", "risk_verdict"),
        ("app.routers.appeals", "resolve_appeal"),
        ("app.services.auto_flow", "sweep_once"),
        ("app.routers.credit", "resolve_credit_appeal"),
        ("app.routers.credit", "submit_credit_appeal"),
    ])
    def test_事实变了的地方都打缓存_而且在提交之后(self, module, fn):
        """订单完成、裁决、判责、违规判定、申诉改判 —— 漏一处,交易对方看到的分数就晚 TTL 那么久。
        提交之前打的话,别的请求可能正好按旧数据算一遍又写回去。"""
        calls = _calls(inspect.getsource(getattr(importlib.import_module(module), fn)))
        inv = [line for _, name, line in calls
               if name in ("invalidate", "invalidate_order", "invalidate_orders")]
        com = [line for _, name, line in calls if name == "commit"]
        assert inv, f"{module}.{fn} 改了计分的事实却没打缓存"
        assert com and min(com) < min(inv), f"{module}.{fn} 在提交之前就打了缓存"

    @pytest.mark.parametrize("module,fn", [
        ("app.routers.orders", "transition"),
        ("app.routers.orders", "pickup_verify"),
        ("app.routers.admin", "resolve_delivery_issue"),
        ("app.routers.admin", "risk_verdict"),
        ("app.services.auto_flow", "sweep_once"),
    ])
    def test_订单完成的地方三方一起打(self, module, fn):
        """完成一单,顾客、店主、骑手三方的加分都变了 —— 只打顾客那一个就是漏两个。"""
        names = {name for _, name, _ in
                 _calls(inspect.getsource(getattr(importlib.import_module(module), fn)))}
        assert names & {"invalidate_order", "invalidate_orders"}, f"{module}.{fn} 只打了一方"


class Test隐私政策两份一致:
    """隐私政策有两份:App 内的 packages/shared/lib/src/legal.dart 和网页上的
    server/static/legal-privacy.html。信用分那一条(第一节第 18 条)和「共享」第 1 条里
    交易对方能看到分数的那一句,两份必须一字不差(Dart 里的 ** 就是网页上的 <strong>)——
    改了一份忘了另一份,App 里和网页上说的就是两回事。"""

    @staticmethod
    def _lines(key: str) -> tuple[str, str]:
        import re
        root = Path(__file__).resolve().parents[3]
        html = (root / "server/static/legal-privacy.html").read_text(encoding="utf-8")
        dart = (root / "packages/shared/lib/src/legal.dart").read_text(encoding="utf-8")
        h = next(line for line in html.splitlines() if key in line)
        h = re.sub(r"^<p>", "", h).removesuffix("<br>").removesuffix("</p>")
        h = h.replace("<strong>", "**").replace("</strong>", "**")
        d = next(line for line in dart.splitlines() if line.startswith(key))
        return h, d

    @pytest.mark.parametrize("key", ["18. 信用分", "1. 为完成配送"])
    def test_两份一字不差(self, key):
        h, d = self._lines(key)
        assert h == d, f"两份隐私政策「{key}」那一条不一样"

    def test_写的是三种角色_交易对方接单之后才看得到(self):
        item18, _ = self._lines("18. 信用分")
        for word in ("顾客", "商家", "骑手", "接单之后", "看不到明细", "申诉"):
            assert word in item18, f"隐私政策第 18 条没写到「{word}」"
