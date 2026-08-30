"""真实出餐时刻:用骑手的时钟校准商家的申报(#303)。

## 这组测试守什么

「出餐时长」原先是 `accepted → ready`,**两个端点都是商家在自己 App 上
点的一下**。而算出来的 P80 直接变成骑手抢单卡上的「预计等餐 X 分钟」,
骑手照着它决定接不接单 —— 到店干等的那段时间没有任何补偿
(`flags.wait_comp_on` 现阶段是关的)。

也就是说:**骑手在用一个由对方单方面生成的数,做一个后果全由自己
承担的决定。** 这是这次改动要修的东西,不是"让统计更准"这么轻。

而这不是假想:`OUTLIER_MIN_MINUTES` 那段注释记着实测观察 ——
"很多店接单后先点出餐、等真做好了再叫骑手"。当时只能把小于 1 分钟的
样本丢掉,而一家真要 25 分钟、却在第 5 分钟点出餐的店,完整穿过那道过滤。

## 边界在哪:诚实的店必须一分不吃亏

这条是整件事的前提,也是最容易做坏的地方。**校准只能在有证据时收紧,
不能在没证据时瞎猜。** 三种情形各有各的判法(见 true_ready_at),
其中两种都取商家的申报值 —— 只有"说好了却还要等"那一种才改。

订正一次口径:早先设想的一行公式 `max(ready, picked_up − 交接)` 是错的。
骑手来晚了的单会被它算成商家慢 —— 那正好是"没证据也收紧"。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import prep_time
from app.services.prep_time import HANDOVER_SECONDS, true_ready_at

T0 = datetime(2026, 8, 30, 11, 0, tzinfo=timezone.utc)


def m(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def 出餐分钟(declared, arrived, picked) -> float:
    """从接单(T0)算起的真实出餐时长。"""
    return (true_ready_at(declared, arrived, picked) - T0).total_seconds() / 60


class Test诚实的商家一分不吃亏:
    def test_骑手来早了商家在真做好时点出餐(self):
        """骑手 5 分钟就到了,餐确实要做到 30 分钟。商家在第 30 分钟
        如实点了出餐、31 分钟交接完成 —— 结果就该是 30,不是 29.5。

        这是规则里那个 `max` 的全部意义:**它保护的是诚实的商家**,
        不是保险丝。"""
        assert 出餐分钟(m(30), arrived=m(5), picked=m(31)) == 30

    def test_餐早好了骑手却磨蹭_已知的不精确(self):
        """骑手到店后去买瓶水再回来。这一单会被算成商家慢。

        **明知不精确也这么定**,理由是替代方案更坏:一旦"商家在骑手
        到店后点的就信它",提前点的最优时机就挪到"骑手到店那一刻",
        洞原样还在(见 true_ready_at 的 ⚠️ 那段)。
        而磨蹭少见、损己不利己,30 天 P80 摊得掉。"""
        got = 出餐分钟(m(15), arrived=m(10), picked=m(40))
        assert got == pytest.approx(40 - HANDOVER_SECONDS / 60)


class Test情形二_商家先点了而骑手到店即取:
    def test_申报属实取申报值(self):
        """诚实的店一分不吃亏 —— 这是整件事的前提。"""
        assert 出餐分钟(m(12), arrived=m(18), picked=m(19)) == 12

    def test_骑手来晚多久都不影响商家(self):
        """**这条最要紧。** 骑手晚到一小时,商家的出餐时长还是 12 分钟。
        早先设想的 max(ready, picked−交接) 会在这里算出 71 分钟,
        把骑手的迟到记到商家账上 —— 那是没有证据的收紧。"""
        assert 出餐分钟(m(12), arrived=m(70), picked=m(71)) == 12

    def test_交接耗时以内都算餐已好(self):
        """边界:等待正好等于交接耗时,仍算「到店即取」。
        宁可把边缘情形算成餐已好,也不要把一次正常交接读成商家的慢。"""
        picked = m(18) + timedelta(seconds=HANDOVER_SECONDS)
        assert 出餐分钟(m(12), arrived=m(18), picked=picked) == 12


class Test情形三_说好了却还要等:
    def test_等待原样加回去(self):
        """接单就点出餐,骑手 10 分钟后到店、又等到第 40 分钟才取到 ——
        真实出餐 = 40 − 交接耗时。"""
        got = 出餐分钟(m(0.5), arrived=m(10), picked=m(40))
        assert got == pytest.approx(40 - HANDOVER_SECONDS / 60)

    def test_提前点没有任何收益(self):
        """同一单,商家把「已出餐」从第 15 分钟提前到第 1 分钟点。
        名义出餐从 15 掉到 1,**真实出餐一分不变** ——
        因为餐真正到手的时刻没变。"""
        晚点点 = 出餐分钟(m(15), arrived=m(10), picked=m(40))
        提前点 = 出餐分钟(m(1),  arrived=m(10), picked=m(40))
        assert 晚点点 == 提前点 == pytest.approx(40 - HANDOVER_SECONDS / 60)

    def test_越提前点等待越长而总数不变(self):
        """把「提前点出餐」这件事的收益锁死在 0:
        无论在第几分钟点,只要餐没好,真实出餐时长恒等。"""
        # 10 和 10.1 是**踩过的洞**:旧规则在"骑手到店那一刻点"能拿 10 分
        vals = {出餐分钟(m(t), arrived=m(10), picked=m(40))
                for t in (0.2, 1, 3, 5, 9, 10, 10.1, 20, 35)}
        assert len(vals) == 1, f"提前点竟然改变了结果:{vals}"


class Test没有骑手环节的单:
    @pytest.mark.parametrize("arrived,picked", [
        (None, None),            # 自取 / 商家自送
        (m(10), None),           # 到了店但没取成(转单/取消)
        (None, m(10)),           # 数据不全
    ])
    def test_只能取申报值且不报错(self, arrived, picked):
        """拿不到第二方的时刻就没有校准依据。**不猜** ——
        没证据时保持原样,是这套校准可信的前提。"""
        assert 出餐分钟(m(14), arrived, picked) == 14


class Test这个数不用来罚谁:
    def test_函数结构上就碰不到钱和状态(self):
        """君子协定:不罚款、不扣分、不动任何一方的钱。

        用签名来证明而不是扫关键词 —— 扫源码会连注释里的"不罚谁"
        一起命中(踩过)。三个时刻进、一个时刻出的纯函数,
        既拿不到 db 也拿不到 settings,想碰钱也碰不到。"""
        import inspect
        sig = inspect.signature(true_ready_at)
        assert list(sig.parameters) == [
            "declared_ready", "arrived_shop_at", "picked_up_at"]
        assert sig.return_annotation == "datetime"
        body = inspect.getsource(true_ready_at)
        body = body[body.index('"""', body.index('"""') + 3) + 3:]
        for 外部 in ("db", "settings", "await", "import"):
            assert 外部 not in body, f"函数体里出现了 {外部} —— 它该是纯函数"

    def test_出餐时长仍然不进排序(self):
        """`_SORTS` 一旦多出出餐相关的键,就是把美团那个
        「出餐快→曝光高」的齿轮装了回来。"""
        from app.routers.merchants import _SORTS
        assert set(_SORTS) == {"distance", "rating", "sales"}


class Test统计口径接上了校准:
    def test_stats_for_用的是true_ready_at(self):
        import inspect
        src = inspect.getsource(prep_time.stats_for)
        assert "true_ready_at(" in src, "统计还在直接用商家申报的 ready"
        assert "arrived_shop_at" in src and "picked_up_at" in src, \
            "没把骑手的两个时刻取回来,校准无从谈起"


class Test这条规则做不到的事:
    """**别把它当成滴水不漏的。** 写下来免得后来的人误以为已经封死。"""

    def test_骑手来得比餐好还晚时无从校准(self):
        """商家接单就点出餐(第 1 分钟),餐其实第 65 分钟才好,
        而骑手第 70 分钟才到、到店即取 —— 这一单会被记成 1 分钟。

        没有任何证据能反驳那个申报:我们只知道"餐在骑手到店前已经好了"。
        要收紧就只能拿 arrived 当出餐时刻,而那等于**把骑手的迟到记到
        商家账上** —— 那是 test_骑手来晚多久都不影响商家 明确禁止的。

        兜底靠两处:一是这种单越多,骑手来早的单就越会把真相顶出来;
        二是申报值小于 OUTLIER_MIN_MINUTES 的整条丢掉,最露骨的那档进不来。
        """
        assert 出餐分钟(m(1), arrived=m(70), picked=m(71)) == 1

    def test_只在有证据时收紧(self):
        """整条规则的取舍写在这里:**没有证据就不动申报值。**

        宁可漏掉一些不诚实,也不能冤枉诚实的 —— 因为这个数会
        影响骑手接不接这家店的单,而商家没有申辩的通道
        (君子协定里也不该有:一旦要申辩,就得有人裁决,就有了权力)。
        """
        无证据 = [
            (m(5), None, None),          # 没有骑手环节
            (m(5), m(20), m(20.5)),      # 到店即取
            (m(5), m(90), m(91)),        # 骑手来得很晚
        ]
        for declared, arrived, picked in 无证据:
            assert 出餐分钟(declared, arrived, picked) == 5

