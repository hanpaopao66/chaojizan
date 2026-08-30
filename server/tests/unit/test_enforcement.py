"""处置目录:同类行为计次,不折算成分数(#306)。

## 为什么不是「超级分」

平台在三处公开承诺过「没有违规积分,任何指标都不折算成分数」。判据是
models.py 里那句:**这个数字会不会影响他能看到的单?会,就是绳索。**

除了承诺,还有三件实际会发生的事:

1. **分数没法申诉。**「我为什么是 72 分」没有答案,只有"这些事加起来"。
   计次是「你 8 月 3 日那单被判虚假出餐」—— 可以逐条推翻。
2. **慢和坏会被折进同一个数轴**,折完就分不出哪部分是能力问题。
3. **一旦有分,行为就为分服务** —— 那正是出餐时长那次拆掉的循环。

## 这组测试守什么

- **级别是算出来的,不是存的。** 这条不变量换来自动归零和申诉自动重算,
  两件计分做不到的事。谁给 Violation 加一列 level,这组会红。
- **不同类不累加。** 两次虚假送达加一次骚扰不等于三次 —— 那就是计分。
- **阈值绑在严重程度上,不绑在端上。** 想给某一端开小灶,得改三端共用的
  SEVERITY,对称因此是结构性的。
- **公示的表就是执行的表。** 规则页从 CATALOG 生成,不可能对不上。
"""
import inspect

import pytest

from app.services import enforcement as E


class Test不做分数:
    def test_没有分数字段(self):
        """目录里出现 score/point 就是走回计分了。"""
        src = inspect.getsource(E)
        body = src[src.index("LEVEL_NONE ="):]
        for bad in ("score", "point", "积分", "扣分"):
            assert bad not in body.lower().replace("不折算成分数", ""), \
                f"处置目录里出现了 {bad}"

    def test_违规事件表没有level列(self):
        """级别必须是算出来的。存下来的话:窗口滚过去它不会自己变,
        申诉推翻一条也不会自己降 —— 那两件事正是计次强于计分的地方。"""
        from app.models import Violation
        cols = {c.name for c in Violation.__table__.columns}
        assert "level" not in cols and "score" not in cols, (
            "级别是算出来的(level_from_counts),不该存。"
            "存了就要自己维护归零和重算,那正是计分制的麻烦")

    def test_不同类不累加(self):
        """两次虚假送达 + 一次别的 ≠ 三次。各类各看各的阈值。"""
        assert E.level_from_counts(
            "rider", {"fake_delivery": 2, "fake_delivery_x": 5}) == E.LEVEL_NONE
        assert E.level_from_counts(
            "rider", {"fake_delivery": 3}) == E.LEVEL_LIMIT


class Test阈值绑在严重程度上:
    def test_严重档只有两个(self):
        """再细分下去「为什么这条三次那条四次」就没法解释了,
        而解释不了的规则等于没有规则。"""
        assert set(E.SEVERITY) == {"severe", "major"}

    def test_每条规则都引用严重档不自带阈值(self):
        """自带阈值 = 可以给某一端偷偷开小灶。"""
        for r in E.CATALOG:
            assert r.severity in E.SEVERITY
            for f in ("times", "window_days", "level"):
                assert not hasattr(r, f), f"Rule 不该自带 {f}"

    def test_同名行为三端同一档(self):
        """骚扰在三端是同一件事,阈值和后果必须一样 ——
        「一方能做另一方不能做」的反面。"""
        by_kind = {}
        for r in E.CATALOG:
            by_kind.setdefault(r.kind, set()).add(r.severity)
        for kind, sevs in by_kind.items():
            assert len(sevs) == 1, f"{kind} 在不同端用了不同的严重档:{sevs}"

    def test_骚扰三端都有(self):
        """这一条是对称性的样本:三端都能骚扰对方,三端都该被同样处置。"""
        ends = {r.audience for r in E.CATALOG if r.kind == "harassment"}
        assert ends == {"customer", "merchant", "rider"}


class Test三端都有内容:
    @pytest.mark.parametrize("a", ["customer", "merchant", "rider"])
    def test_每端至少两条(self, a):
        """结构对称不等于内容空 —— 每端都得说清楚什么算破坏规则。"""
        assert len(E.rules_of(a)) >= 2

    @pytest.mark.parametrize("a", ["customer", "merchant", "rider"])
    def test_每端都有严重档和一般档(self, a):
        """只有一般档 = 再恶劣也只到「限制」;只有严重档 = 一次就冻结,
        没有中间地带。两档都要有。"""
        sevs = {r.severity for r in E.rules_of(a)}
        assert sevs == {"severe", "major"}, (a, sevs)

    def test_只列故意破坏规则不列做得不好(self):
        """慢、少、晚是能力和条件的问题,不该出现在处置目录里。"""
        labels = " ".join(r.label for r in E.CATALOG)
        for bad in ("慢", "超时", "差评", "评分", "接单率"):
            assert bad not in labels, f"目录里出现了「{bad}」—— 那是能力不是作恶"


class Test公示的表就是执行的表:
    def test_规则页从目录生成(self):
        from app.services import rules
        src = inspect.getsource(rules._risk_section)
        assert "public_table(audience)" in src, (
            "规则页另写一份行为清单 = 公示的和执行的可能对不上")

    @pytest.mark.parametrize("a", ["customer", "merchant", "rider"])
    def test_公示表每行都说清了判据和后果(self, a):
        for row in E.public_table(a):
            assert row["label"] and row["when"] and row["level_label"]
            assert row["decided"] in ("auto", "manual")


class Test级别取最强:
    def test_多类同时触发取最强那档(self):
        assert E.level_from_counts(
            "rider", {"fake_delivery": 3, "theft": 1}) == E.LEVEL_FROZEN

    def test_人工通道与目录取强者(self):
        """保留 User.risk_level 那条人工直接处置的口子(反作弊命中、
        紧急情况),但它和目录算出来的取强者 —— 两条通道的可见性
        和申诉资格完全一样,只是认定路径不同。"""
        src = inspect.getsource(E.level_for)
        assert "user.risk_level" in src and "strongest" in src
