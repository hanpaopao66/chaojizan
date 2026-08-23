"""骑手现场难度反馈(#301)。

## 这一组守的是「群众至上,尊重劳动者」

那不是一句口号,是几条能被测试挡住的规则。这个功能有一个很具体的
失败方式:它会被"优化"成对平台更划算的样子,而每一步看起来都合理 ——

- 「补贴成本高,把门槛从 2 条提到 5 条」→ 机制事实上停摆;
- 「这个地址大家都说难,说明难是常态,不该额外给钱」→ 自我收紧;
- 「反馈多的骑手是不是在刷?给他降降权重」→ 反馈从此有了代价;
- 「按最难的那次给太贵,按最轻的那次给」→ 多数人的体验被丢掉。

所以下面每一条都对着一种具体的走歪方式。想违反就必须显式删测试,
而删测试会在评审里被看见(和 test_labor_guard 同一个思路)。
"""
import pytest

from app.services import hardship as hs


class Test只加不减:
    def test_没勾任何项不给钱(self):
        assert hs.comp_cents([], None, None) == 0

    def test_永远不为负(self):
        """没有任何一条路径允许"骑手反馈之后钱变少了"。"""
        for kinds in ([], ["other"], ["no_elevator"], ["walk_in"],
                      ["no_elevator", "walk_in", "no_vehicle", "gate_hard"]):
            for floors in (None, 0, 1, 4, 6, 99):
                for walk in (None, 0, 50, 100, 3000):
                    assert hs.comp_cents(kinds, floors, walk) >= 0

    def test_勾得越多不会变少(self):
        base = hs.comp_cents(["no_elevator"], 6, None)
        more = hs.comp_cents(["no_elevator", "gate_hard"], 6, None)
        assert more >= base


class Test口径和现有上门费一致:
    def test_四楼及以下不算爬楼(self):
        """和 pricing.door_fee_cents 同一条线:1–4 楼派费覆盖得住。"""
        assert hs.comp_cents(["no_elevator"], 4, None) == 0
        assert hs.comp_cents(["no_elevator"], 5, None) == 100

    def test_爬楼封顶(self):
        assert hs.comp_cents(["no_elevator"], 99, None) == \
            hs.NO_ELEVATOR_MAX_CENTS

    def test_百米内不算步行进小区(self):
        assert hs.comp_cents(["walk_in"], None, 100) == 0
        assert hs.comp_cents(["walk_in"], None, 200) == 50

    def test_步行封顶(self):
        assert hs.comp_cents(["walk_in"], None, 3000) == hs.WALK_IN_MAX_CENTS

    def test_单笔有上限(self):
        """防滥用,不是防骑手 —— 上限要在"正常情况够用"的水平之上。"""
        worst = hs.comp_cents(
            ["no_elevator", "walk_in", "no_vehicle", "gate_hard"], 99, 3000)
        assert worst <= hs.MAX_COMP_CENTS
        # 最难的一单真实值应当**够得着**:上限不能低到把正常情况也砍了
        real_worst = (hs.NO_ELEVATOR_MAX_CENTS + hs.WALK_IN_MAX_CENTS
                      + hs.NO_VEHICLE_CENTS + hs.GATE_HARD_CENTS)
        assert hs.MAX_COMP_CENTS >= real_worst, \
            "上限低于最难那一单的真实值 —— 最该被补偿的人反而被砍了"


class Test说不清的不自动给钱:
    def test_other不自动补(self):
        """「其他」进人工看。自动给钱会变成一个无门槛的口子,
        而堵这个口子的办法通常是收紧全部 —— 伤的是老实反馈的人。"""
        assert hs.comp_cents(["other"], None, None) == 0

    def test_other也要有回执(self):
        assert hs.explain(["other"], None, None), "填了却什么都不说,等于石沉大海"


class Test钱要摊开给人看:
    def test_每一项一行(self):
        lines = hs.explain(["no_elevator", "gate_hard"], 6, None)
        assert len(lines) == 2
        assert any("6 楼" in ln for ln in lines)
        assert all("¥" in ln for ln in lines)

    def test_没触发的项不出现(self):
        """4 楼无电梯不收钱,就不该在明细里写一行 ——
        列一行 ¥0 只会让人以为被收了钱。"""
        assert hs.explain(["no_elevator"], 4, None) == []


class Test共识按不同骑手算:
    def test_同一个人说十遍不算数(self):
        rows = [{"kinds": ["no_elevator"], "floors": 6, "rider_id": 7}
                for _ in range(10)]
        got = hs.consensus(rows)
        assert got["kinds"] == [], "一个人刷十条就转正了"
        assert got["samples"] == 1, "样本数报的该是有多少个人,不是多少条"

    def test_两个人说同一件事才转正(self):
        rows = [{"kinds": ["no_elevator"], "floors": 6, "rider_id": 7},
                {"kinds": ["no_elevator"], "floors": 7, "rider_id": 8}]
        assert hs.consensus(rows)["kinds"] == ["no_elevator"]

    def test_只有一个人说的项不转正(self):
        """一次误报不该让一个地址永久涨价。"""
        rows = [{"kinds": ["no_elevator", "no_vehicle"], "floors": 6,
                 "rider_id": 7},
                {"kinds": ["no_elevator"], "floors": 6, "rider_id": 8}]
        assert hs.consensus(rows)["kinds"] == ["no_elevator"]

    def test_取中位数不取最大值(self):
        """取最大值等于让最夸张的那次定价;中位数是多数人的实际体验 ——
        这就是"群众至上"在这里的字面意思。"""
        rows = [{"kinds": ["no_elevator"], "floors": 6, "rider_id": 1},
                {"kinds": ["no_elevator"], "floors": 6, "rider_id": 2},
                {"kinds": ["no_elevator"], "floors": 30, "rider_id": 3}]
        assert hs.consensus(rows)["floors"] == 6

    def test_空输入不炸(self):
        assert hs.consensus([])["samples"] == 0


class Test不做的事:
    def test_没有信用分没有评分(self):
        """沉淀的是**地址的属性**,不是人的行为。

        一旦有了"骑手可信度",这个功能就从"帮我们了解这个地址"
        变成了"考核骑手",而反馈从此有了代价 —— 有代价就没人说了。
        """
        import inspect
        # 只看**代码**不看注释:模块开头正是在说明"不做信用分",
        # 连注释一起扫的话,越是把理由写清楚的文件越容易被判违规
        skips = ("#", chr(34) * 3, chr(39) * 3)
        src = "\n".join(
            ln for ln in inspect.getsource(hs).splitlines()
            if not ln.lstrip().startswith(skips))
        for token in ("credit_score", "reliability", "rider_score",
                      "trust_level"):
            assert token not in src, f"出现了 {token} —— 这是在给骑手打分"

    def test_模型里没有评价字段(self):
        from app.models import RiderHardship
        cols = set(RiderHardship.__table__.columns.keys())
        assert not (cols & {"score", "rating", "credit", "weight"}), cols


class Test门槛不能悄悄抬高:
    def test_两条就转正(self):
        """门槛是权衡:1 条太容易被一次误报永久涨价,3 条在单量不大的
        城市可能几个月都攒不齐 —— 攒不齐就等于这个机制不存在。

        调高它是"降低补贴成本"最省事的办法,也是最隐蔽的一种停摆。
        """
        assert hs.CONSENSUS_MIN == 2


class Test地址键:
    def test_同一栋楼同一层归一类(self):
        assert hs.addr_key(30.66123, 104.08234, 6) == \
            hs.addr_key(30.66127, 104.08236, 6)

    def test_不同楼层分开(self):
        """同一栋楼 2 楼和 12 楼不是一回事。"""
        assert hs.addr_key(30.6612, 104.0823, 2) != \
            hs.addr_key(30.6612, 104.0823, 12)

    def test_没填楼层归一类(self):
        """那一类里的共识只对"这栋楼周边"成立(车进不去、门禁难),
        不会误伤具体楼层。"""
        assert hs.addr_key(30.6612, 104.0823, None) == \
            hs.addr_key(30.6612, 104.0823, 0)
