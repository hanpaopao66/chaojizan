"""派单算法(#140/#141)。

守两件事:
1. **算法本身讲道理** —— 顺路要真的影响排序,加成要有上限,反例要排在后面;
2. **公开的和跑的是同一份** —— /transparency/dispatch 返回的权重必须来自
   代码常量。抄一份的话迟早对不上,那时公开的就是假的,比不公开更坏。
"""
import re

from app.services import dispatch as d


def cand(**kw):
    base = dict(to_pickup_m=1000.0, trip_m=1000.0, wait_minutes=0.0,
                tip_yuan=0.0, same_shop=False, detour_m=None)
    base.update(kw)
    return d.Candidate(**base)


class Test顺路真的影响排序:
    def test_强顺路排在普通单前面(self):
        """旧算法的核心缺陷:same_way 算出来只用于 UI 打标,不进综合分。"""
        normal = d.score(cand())
        good = d.score(cand(detour_m=200.0))
        assert good.score < normal.score
        assert good.same_way_level == "strong"

    def test_绕路越多优势越小(self):
        strong = d.score(cand(detour_m=200.0)).score
        weak = d.score(cand(detour_m=1000.0)).score
        none = d.score(cand(detour_m=5000.0)).score
        assert strong < weak < none

    def test_绕路太多就不算顺路(self):
        """反例:送达点相邻但取餐点在反方向 3km,实际多跑近 6 公里。"""
        assert d.same_way_level(5982.0) == "none"

    def test_手头没单时不声称顺路(self):
        """没有基准就不该说顺路。"""
        assert d.same_way_level(None) == "none"

    def test_同商家比顺路权重更高(self):
        """同店多取一单,取餐环节几乎零成本,比路线接近值钱。"""
        assert d.SAME_SHOP_BONUS_M > d.SAME_WAY_STRONG_BONUS_M


class Test加成有上限:
    def test_等待加成封顶(self):
        """不封顶的话等 30 分钟能抵消 4500m —— 超过整个 4km 配送半径。"""
        long_wait = d.score(cand(wait_minutes=600))
        assert -long_wait.breakdown["wait_bonus_m"] == d.WAIT_BONUS_MAX_M

    def test_小费加成封顶(self):
        """这是「钱能买多靠前」的定价。不封顶 = 出得起钱的永远排最前。"""
        rich = d.score(cand(tip_yuan=999))
        assert -rich.breakdown["tip_bonus_m"] == d.TIP_BONUS_MAX_M

    def test_巨额小费买不过强顺路加同店(self):
        """钱可以买靠前,但买不过真实的效率优势 —— 否则就是纯竞价。"""
        rich = d.score(cand(tip_yuan=999)).score
        efficient = d.score(cand(same_shop=True, detour_m=100.0)).score
        assert efficient < rich


class Test整单划算度:
    def test_送程进入排序(self):
        """旧算法只看「到取餐点多远」:同店的 220m 单和 4km 单同分。"""
        near = d.score(cand(trip_m=220.0)).score
        far = d.score(cand(trip_m=4000.0)).score
        assert near < far

    def test_送程权重低于到店(self):
        """送程有配送费覆盖,去取餐的路是白跑的 —— 白跑的更该被惩罚。"""
        assert 0 < d.TRIP_WEIGHT < 1


class Test公开的就是跑的:
    """公开算法的意义全在这里:接口里的数必须是真在用的那个。"""

    def test_权重取值与常量一致(self):
        spec = d.public_spec()
        by_key = {w["key"]: w for w in spec["weights"]}

        def num(s: str) -> float:
            # 取**最后一个**数字:文案形如「每 1 分钟 ≈ 靠近 150 米」,
            # 抓第一个会拿到「1」而不是权重值
            return float(re.findall(r"[\d.]+", s)[-1])

        assert num(by_key["wait"]["value"]) == d.WAIT_WEIGHT_M_PER_MIN
        assert num(by_key["wait"]["cap"]) == d.WAIT_BONUS_MAX_M
        assert num(by_key["tip"]["value"]) == d.TIP_WEIGHT_M_PER_YUAN
        assert num(by_key["tip"]["cap"]) == d.TIP_BONUS_MAX_M
        assert num(by_key["same_shop"]["value"]) == d.SAME_SHOP_BONUS_M
        assert num(by_key["trip"]["value"]) == d.TRIP_WEIGHT

    def test_改了常量公开值跟着变(self, monkeypatch):
        """真·同源检验:抄一份字面量的实现过不了这条。"""
        monkeypatch.setattr(d, "TIP_WEIGHT_M_PER_YUAN", 42.0)
        spec = d.public_spec()
        tip = next(w for w in spec["weights"] if w["key"] == "tip")
        assert "42" in tip["value"]

    def test_每个权重都讲了理由(self):
        """讲不出道理的数字不配公开 —— 公开一堆没解释的数等于没公开。"""
        for w in d.public_spec()["weights"]:
            assert w.get("why"), f"{w['key']} 没写为什么是这个数"
            assert len(w["why"]) > 20

    def test_承诺不做的事必须在列(self):
        """承诺不做的事和承诺做的事一样重要 —— 这几条正是资本平台被骂最多的。"""
        never = "".join(d.public_spec()["never_do"])
        assert "强制派单" in never
        assert "评分" in never or "等级" in never
        assert "拒" in never

    def test_有变更历史(self):
        """算法可以改,但不能悄悄改 —— 悄悄改等于从没公开过。"""
        log = d.public_spec()["changelog"]
        assert log
        for e in log:
            assert e.get("date") and e.get("what") and e.get("why")

    def test_顺路定义公开了几何式子(self):
        sw = d.public_spec()["same_way_definition"]
        assert "绕路增量" in sw["formula"]
        assert sw.get("why")

    def test_距离口径写明来源与降级(self):
        dist = d.public_spec()["distance"]
        assert "骑行" in dist["source"] and "直线" in dist["source"]
