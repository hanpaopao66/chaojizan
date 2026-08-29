"""劳动者保护(#144)。

这一组测试守的是一条**不可协商的原则**:

> 任何由骑手实际表现算出来的统计量,都不得用于收紧对骑手的要求。

为什么必须有测试:这条原则违反起来是"无声"的 ——
某天有人为了让 ETA "更准"接上实测数据,时限就悄悄收紧了,
代码评审时看起来还像个优化。有测试挡着,想收紧就必须显式删测试,
而删测试会在评审里被看见。
"""
import pytest

from app.services import labor_guard as lg
from app.services import weather as w


class TestETA只许放宽不许收紧:
    def test_建议值更宽时采纳(self):
        """路况差、天气恶劣 → 该放宽就放宽。"""
        assert lg.clamp_eta_minutes(40, 30) == 40

    def test_建议值更紧时不采纳(self):
        """**核心**:任何想缩短时限的建议一律被挡回保底值。"""
        assert lg.clamp_eta_minutes(20, 30) == 30

    def test_骑手跑得再快也不会被加码(self):
        """模拟自我收紧循环:实测越来越快,ETA 不许跟着变紧。"""
        baseline = lg.ride_minutes(4000)
        for measured in (30, 25, 20, 15, 10, 5):
            assert lg.clamp_eta_minutes(measured, baseline) >= baseline

    def test_相等时不变(self):
        assert lg.clamp_eta_minutes(30, 30) == 30


class Test骑行速度是常量:
    def test_取值保守(self):
        """电动车空载能跑 25,但配送含等红灯、找楼栋、爬楼。
        按巡航速度算 ETA 等于默认一路绿灯且送到楼下就完事。"""
        assert lg.RIDE_SPEED_KMH <= 18

    def test_恶劣天气更慢(self):
        """下雨路滑视线差,慢是应该的 —— 与加价配套。"""
        assert lg.RIDE_SPEED_KMH_SEVERE < lg.RIDE_SPEED_KMH

    def test_恶劣天气骑行时间更长(self):
        normal = lg.ride_minutes(3000)
        severe = lg.ride_minutes(3000, severe_weather=True)
        assert severe > normal

    def test_距离越远时间越长(self):
        assert lg.ride_minutes(1000) < lg.ride_minutes(4000)


class Test疲劳保护不断人收入:
    def test_分级(self):
        assert lg.fatigue_level(60) == "none"
        assert lg.fatigue_level(5 * 60) == "remind"
        assert lg.fatigue_level(9 * 60) == "throttle"

    def test_提醒有话说(self):
        assert lg.fatigue_message("remind", 5 * 60)
        assert lg.fatigue_message("throttle", 9 * 60)
        assert lg.fatigue_message("none", 60) is None

    def test_最高等级也只是降频不是禁止(self):
        """一刀切断收入是另一种不尊重 —— 骑手要吃饭。"""
        msg = lg.fatigue_message("throttle", 9 * 60)
        assert "接单照常" in msg
        spec = lg.public_spec()
        assert "不禁止接单" in spec["fatigue"]["what_throttle_means"]


class Test承诺可验证:
    def test_承诺列表非空且具体(self):
        for p in lg.LABOR_PROMISES:
            assert len(p) > 15, p

    def test_关键承诺在列(self):
        blob = "".join(lg.LABOR_PROMISES)
        assert "不会因为你跑得快而变紧" in blob
        assert "出餐慢" in blob
        assert "断你的单" in blob

    def test_公开说明讲了机制而不只是口号(self):
        spec = lg.public_spec()
        assert "自我收紧" in spec["why"]
        assert spec["ride_speed"]["why"]


class Test恶劣天气判定:
    def test_大雨触发(self):
        assert w.is_severe(61, w.RAIN_MM, 0)

    def test_大风触发(self):
        assert w.is_severe(0, 0, w.WIND_KMH)

    def test_雪触发(self):
        assert w.is_severe(73, 0, 0)

    def test_晴天不触发(self):
        assert not w.is_severe(0, 0.0, 5.0)

    def test_毛毛雨不触发(self):
        """把飘点雨也算恶劣,会让加价变常态,真正恶劣时反而失去信号。"""
        assert not w.is_severe(51, 0.1, 5.0)

    def test_三条判据取或不取与(self):
        """要求同时满足等于永远不触发。"""
        assert w.is_severe(0, w.RAIN_MM, 0)      # 只有雨
        assert w.is_severe(0, 0, w.WIND_KMH)     # 只有风

    def test_阈值公开且与常量同源(self):
        spec = w.public_spec()
        by = {t["key"]: t for t in spec["thresholds"]}
        assert str(w.RAIN_MM) in by["rain"]["value"]
        assert str(w.WIND_KMH) in by["wind"]["value"]

    @pytest.mark.parametrize("key", ["rain", "wind", "code"])
    def test_每条阈值都讲了理由(self, key):
        by = {t["key"]: t for t in w.public_spec()["thresholds"]}
        assert len(by[key]["why"]) > 20

    def test_恶劣时必须同时放宽时限(self):
        """只加价不放宽时限,等于用钱买骑手冒险。"""
        blob = "".join(w.public_spec()["on_severe"])
        assert "放宽" in blob

    def test_查不到时维持现状而不是关掉加价(self):
        """正在下雨时因为查不到而关掉加价,是最坏的结果。"""
        assert "维持当前状态" in w.public_spec()["degradation"]


class TestETA接线后仍不收紧:
    """clamp 写在 labor_guard 里没用,得确认 compute_eta 真的调了它。"""

    @staticmethod
    def _mins(**kw):
        from datetime import datetime, timezone
        from types import SimpleNamespace as NS
        from app.services.eta import compute_eta
        order = NS(pickup=False, parent_order_no="", scheduled_at=None,
                   lat=30.6700, lng=104.0800)
        shop = NS(lat=30.6600, lng=104.0800)
        t = compute_eta(order, shop, **kw)
        return (t - datetime.now(timezone.utc)).total_seconds() / 60

    def test_出餐快不缩短ETA(self):
        """出餐快是商家的功劳,不该变成骑手的压力。"""
        base = self._mins()
        assert self._mins(prep_minutes=1) >= base - 0.1
        assert self._mins(prep_minutes=5) >= base - 0.1

    def test_出餐慢会放宽ETA(self):
        assert self._mins(prep_minutes=40) > self._mins()

    def test_恶劣天气不缩短(self):
        """恶劣天气只会更慢,绝不会更快。"""
        assert self._mins(severe_weather=True) >= self._mins() - 0.1

    def test_任意实测值都不会低于保底(self):
        base = self._mins()
        for p in (0, 0.5, 1, 3, 8, 12, 19):
            assert self._mins(prep_minutes=p) >= base - 0.1, p


class Test天气开关的语义:
    """e2e 里那条断言因为依赖真实天气被放松了,机制在这里用确定性测试守住。"""

    def test_强制开优先于自动判定(self):
        """管理员强制开时,不管天气如何都加价 —— 自动判定漏了要能救。"""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app.services import flags

        async def go():
            db = AsyncMock()
            db.get.return_value = type("F", (), {"value": "on"})()
            # 天气服务即便返回"晴天",强制开也必须生效
            with patch("app.services.weather.current",
                       new=AsyncMock(return_value={"severe": False})):
                return await flags.weather_surcharge_on(db, 30.66, 104.08)

        assert asyncio.run(go()) is True

    def test_没有强制关这条路(self):
        """天气恶劣却关掉加价,没有正当理由 —— 所以只有「强制开」没有「强制关」。

        ⚠️ 这条的语义 2026-08-29 变过一次(#307)。原先是
        「关了开关,下雨照样加价」—— 自动判定直接生效。
        现在自动判定**只提请审核**,人点头才加价:
        加价是用户实付的钱,误报(格点漂移、一阵过云雨)会让他凭空多花,
        而他看不到那一刻的气象数据、也不知道找谁申诉。

        所以这里断言的是**下雨也不直接加价,但会留下一张待审单** ——
        「宁可漏加,不可错收」。
        """
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app.services import flags

        async def go(severe):
            db = AsyncMock()
            db.get.return_value = type("F", (), {"value": "off"})()
            with patch("app.services.weather.current",
                       new=AsyncMock(return_value={"severe": severe})), \
                 patch("app.services.geo_city.district_of",
                       new=AsyncMock(return_value=("成都市", "锦江区"))), \
                 patch("app.services.weather_zone.active_alert",
                       new=AsyncMock(return_value=None)), \
                 patch("app.services.weather_zone.request_if_severe",
                       new=AsyncMock(return_value=severe)) as req:
                got = await flags.weather_surcharge_on(db, 30.66, 104.08)
                return got, req.await_count

        on_rain, asked_rain = asyncio.run(go(True))
        assert on_rain is False, "自动判定直接加价了 —— 那审核就是摆设"
        assert asked_rain == 1, "下雨了却没提请审核 —— 那这条路永远走不通"

        on_sun, _ = asyncio.run(go(False))
        assert on_sun is False

    def test_有生效的审核单才加价(self):
        """人点头之后才是真加价。这条和上一条合起来才是完整语义。"""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app.services import flags

        async def go():
            db = AsyncMock()
            db.get.return_value = type("F", (), {"value": "off"})()
            with patch("app.services.geo_city.district_of",
                       new=AsyncMock(return_value=("成都市", "锦江区"))), \
                 patch("app.services.weather_zone.active_alert",
                       new=AsyncMock(return_value=object())):
                return await flags.weather_surcharge_on(db, 30.66, 104.08)

        assert asyncio.run(go()) is True

    def test_查不到天气时不加价但也不报错(self):
        """None 表示「不知道」,不是「天气很好」——
        真正的降级语义是:已加价的订单不会被追溯撤销。"""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app.services import flags

        async def go():
            db = AsyncMock()
            db.get.return_value = type("F", (), {"value": "off"})()
            with patch("app.services.weather.current",
                       new=AsyncMock(return_value=None)), \
                 patch("app.services.geo_city.district_of",
                       new=AsyncMock(return_value=("成都市", "锦江区"))), \
                 patch("app.services.weather_zone.active_alert",
                       new=AsyncMock(return_value=None)):
                return await flags.weather_surcharge_on(db, 30.66, 104.08)

        assert asyncio.run(go()) is False


class Test骑手评价不得变成评分体系:
    """#148 最容易滑向段位体系,边界在这里钉死。

    判断标准:**这个数字会不会影响他能看到的单?**
    会,就是绳索;不会,才是反馈。
    """

    def test_公开承诺里明确不按评分差别对待(self):
        from app.services import dispatch as d
        never = "".join(d.public_spec()["never_do"])
        assert "评分" in never or "等级" in never

    def test_排序权重里没有任何评分项(self):
        """只要评分进了综合分,它就成了绳索 —— 用权重表逐项确认。"""
        from app.services import dispatch as d
        keys = {w["key"] for w in d.public_spec()["weights"]}
        for banned in ("rating", "score", "level", "rank", "tier", "star"):
            assert banned not in keys, f"排序权重里出现了 {banned}"

    def test_Candidate里没有评分字段(self):
        """从数据结构上堵死:评分进不了打分函数的入参,就不可能影响排序。"""
        from app.services import dispatch as d
        fields = set(d.Candidate.__dataclass_fields__)
        for banned in ("rating", "score", "level", "rank", "tier"):
            assert not any(banned in f for f in fields), \
                f"Candidate 里出现了含 {banned} 的字段"


# ---------- 路线级余量(#268) ----------

class Test路网时长只放宽不收紧:
    """常量速度是一个平均值拍在所有路线上 —— 市区过 8 个红灯和郊区
    一条直路拿的是同一份余量。腾讯路网时长补的就是这个差。

    **方向不能反**:路网算的是纯骑行,不含取餐、找楼栋、爬楼、
    打电话找不到门牌。照它给 ETA 就是把这些时间从骑手身上抠掉。
    """

    def test_不传路网时长_行为和以前完全一样(self):
        """老调用方一个字不用改。"""
        assert lg.ride_minutes(3000) == 3000 / 1000 / lg.RIDE_SPEED_KMH * 60

    def test_路网更长时用路网_市区多红灯(self):
        base = lg.ride_minutes(3000)
        assert lg.ride_minutes(3000, route_minutes=base + 6) == base + 6

    def test_路网更短时用常量_绝不收紧(self):
        """这条是红线。路网说 5 分钟能到,不代表骑手 5 分钟能送到。"""
        base = lg.ride_minutes(3000)
        assert lg.ride_minutes(3000, route_minutes=1.0) == base

    def test_恶劣天气也取_max_不开例外(self):
        """恶劣天气用更慢的常量(11km/h),多数情况下它已经比路网长。

        但**万一路网更长**(暴雨天的市区高峰),还是该用路网 ——
        「只放宽」这条规则不该因为天气就开个例外。

        第一版这里写的是「恶劣天气一律不吃路网」,理由是"路网算的是
        平常路况,用它会收紧"。那个理由只成立于路网**更短**的时候,
        我把它错误地推广到了更长的情况 —— 那样反而是拿天气当借口收紧。
        """
        severe = lg.ride_minutes(3000, severe_weather=True)
        # 更短:用常量(这部分原来就对)
        assert lg.ride_minutes(3000, severe_weather=True,
                               route_minutes=1.0) == severe
        # 更长:用路网。上界按恶劣天气的常量算,severe+5 在界内
        assert lg.ride_minutes(3000, severe_weather=True,
                               route_minutes=severe + 5) == severe + 5

    def test_异常值当没有(self):
        base = lg.ride_minutes(3000)
        assert lg.ride_minutes(3000, route_minutes=None) == base
        assert lg.ride_minutes(3000, route_minutes=0) == base
        assert lg.ride_minutes(3000, route_minutes=-3) == base

    def test_任何路网值都不会让结果变小(self):
        """穷举一遍:这条改动不可能让任何一单的 ETA 变短。

        含上界截断之后仍然成立 —— 截断是防离谱,不是收紧。
        天气两档都过一遍:恶劣天气不该成为收紧的例外。
        """
        for severe in (False, True):
            base = lg.ride_minutes(3000, severe_weather=severe)
            for rm in [None, 0, -1, 0.5, 1, base - 0.01, base, base + 0.01,
                       base * lg.ROUTE_MINUTES_MAX_FACTOR,
                       base * lg.ROUTE_MINUTES_MAX_FACTOR + 1, 999, 1e9]:
                got = lg.ride_minutes(3000, severe_weather=severe,
                                      route_minutes=rm)
                assert got >= base, f"severe={severe} route={rm} 收紧了"

    def test_任何路网值都不会离谱地放宽(self):
        """另一头也要有界:放宽是好事,放宽到 4 小时就是把单送不出去。"""
        for severe in (False, True):
            base = lg.ride_minutes(3000, severe_weather=severe)
            ceiling = base * lg.ROUTE_MINUTES_MAX_FACTOR
            for rm in [base * 3, 999, 1e9]:
                assert lg.ride_minutes(3000, severe_weather=severe,
                                       route_minutes=rm) == ceiling


class Test路网时长的上界:
    """路网时长是**外部数据**,而 clamp_eta_minutes 只挡收紧不挡放宽 ——
    一个离谱的值会直接变成给顾客的承诺。3 公里承诺 4 小时,顾客不会等,
    他会取消,而取消的锅落在商家和骑手头上。
    """

    def test_超过上界就截断(self):
        base = lg.ride_minutes(3000)
        absurd = base * 10
        got = lg.ride_minutes(3000, route_minutes=absurd)
        assert got == base * lg.ROUTE_MINUTES_MAX_FACTOR
        assert got < absurd

    def test_上界之内照常用(self):
        base = lg.ride_minutes(3000)
        ok = base * 1.4          # 市区多灯的合理范围
        assert lg.ride_minutes(3000, route_minutes=ok) == ok

    def test_正好等于上界不截(self):
        base = lg.ride_minutes(3000)
        edge = base * lg.ROUTE_MINUTES_MAX_FACTOR
        assert lg.ride_minutes(3000, route_minutes=edge) == edge

    def test_截断后仍然不小于常量(self):
        """截断是防离谱,不是收紧。"""
        base = lg.ride_minutes(3000)
        assert lg.ride_minutes(3000, route_minutes=base * 99) >= base
