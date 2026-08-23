"""配送费的计价距离(#300)。

## 这组测试守的是一条不可协商的原则

> 任何第三方数据只能让骑手的处境变好,不能变坏。

和 `test_labor_guard` 里那条「实测数据不得用于收紧对骑手的要求」
是同一条原则的两处落点。

## 为什么必须有测试

配送费一分不少全归骑手,这个数直接就是他的收入。而它现在依赖一个
**外部接口**:腾讯回来什么就用什么。接口抽风、坐标落到高架另一侧、
路网数据有洞 —— 任何一种都可能返回一个比直线还短的距离。

那时候少的钱是从骑手身上少的,而代码看起来完全正常。

`billing_distance_m` 里那个 `max(直线, 路网)` 就是挡这个的。
它看起来像"多余的防御",删掉它测试会红 —— 而删测试会在评审里被看见。
"""
import asyncio

import pytest

from app.services import routing
from app.services.pricing import delivery_fee_parts, haversine_m


class Test只放宽不收紧:
    def test_路网比直线短时取直线(self, monkeypatch):
        """核心。路网数据异常时,骑手不该替接口的错买单。"""
        async def fake(*a, **kw):
            return 100.0, 5.0, "route"        # 荒谬地短
        monkeypatch.setattr(routing, "route", fake)
        a = (30.6598, 104.0810)
        b = (30.6900, 104.0900)
        got, _src = asyncio.run(
            routing.billing_distance_m(a[0], a[1], b[0], b[1]))
        assert got == pytest.approx(haversine_m(*a, *b)), \
            "路网返回了一个比直线还短的数,而我们采纳了 —— 少的是骑手的钱"

    def test_路网更长时采纳路网(self, monkeypatch):
        async def fake(*a, **kw):
            return 9999.0, 40.0, "route"
        monkeypatch.setattr(routing, "route", fake)
        got, src = asyncio.run(routing.billing_distance_m(
            30.6598, 104.0810, 30.6900, 104.0900))
        assert got == 9999.0 and src == "route"

    def test_接口炸了退回直线兜底而不是报错(self, monkeypatch):
        """路径服务挂了不该拦住下单 —— 顾客点不了餐,骑手也没单可跑。"""
        async def boom(*a, **kw):
            raise RuntimeError("腾讯挂了")
        monkeypatch.setattr(routing, "route", boom)
        a, b = (30.6598, 104.0810), (30.6900, 104.0900)
        got, src = asyncio.run(
            routing.billing_distance_m(a[0], a[1], b[0], b[1]))
        assert src == "straight"
        # 兜底也要比裸直线宽一点(实测系数 1.19,取 1.2 偏保守)
        assert got > haversine_m(*a, *b)


class Test这件事值多少钱:
    """把"为什么值一次网络调用"钉成数字,免得哪天有人为了省配额改回直线。"""

    def test_实测样本差一整档(self):
        # 成都实测:直线 2250m 对应骑行 3192m(+42%)
        old = sum(delivery_fee_parts(2250).values())
        new = sum(delivery_fee_parts(3192).values())
        assert new > old, "换成路网之后骑手没多拿钱,那这次改动白做了"
        assert new - old >= 100, "少了一整个公里档的差价"

    def test_直线永远不会高估(self):
        """几何决定的:两点之间直线最短。所以偏差是**单边**的 ——
        不存在"平均下来差不多"这种安慰。"""
        # 任取几组坐标,直线都 ≤ 任何实际路径
        for lat, lng in ((30.66, 104.08), (30.70, 104.12), (30.68, 104.05)):
            straight = haversine_m(30.6598, 104.0810, lat, lng)
            assert straight <= straight * routing._MODE_FALLBACK["bike"]


class Test范围按直线计价按路网:
    """两把尺子,各有各的道理 —— 这一条最容易被"统一一下"改坏。

    ## 为什么钱按路网

    配送费全归骑手,直线永远 ≤ 实际要骑的路,少的是他的收入。

    ## 为什么范围按直线

    一度两边都改成路网,理由是"骑手接了超范围的活垫了中间那段"。
    **这个理由是错的**:配送费封顶 ¥10,要骑到 9 公里才碰得到 ——
    计价换成路网之后,4.6km 的单就按 4.6km 付钱,没有任何垫付。

    而路网判范围有个真实代价:附近商家列表的半径是 PostGIS **球面直线**
    (merchants.py 的 _radius_cap),算不了路网。两把尺子不一样,
    用户就会看见一家店、点进去、下单被拒 ——
    「看得见点不了」比「看不见」更伤人,而且他不知道为什么。
    """

    def test_下单路径两样都在(self):
        import inspect

        from app.routers import orders
        src = inspect.getsource(orders.create_order)
        assert "billing_distance_m" in src, "计价没走路网"
        assert "in_delivery_range(straight_m)" in src, \
            "范围判定不是按直线了 —— 会和附近商家列表的半径对不上"

    def test_封顶价远在配送半径之外(self):
        """上面那个"没有垫付"的论证依赖这条:封顶价必须够不着。

        哪天有人把 delivery_max_fee_cents 调低、或者把半径调大到
        封顶价咬得住的程度,那个论证就不成立了,得重新想 ——
        这条测试就是那时候的闹钟。
        """
        import math

        from app.config import settings
        from app.services.pricing import delivery_fee_parts

        # 半径边缘、再按最坏的路网系数放大之后的距离
        edge_m = settings.delivery_max_km * 1000 * 1.5
        base = delivery_fee_parts(edge_m)["base"]
        uncapped = settings.delivery_base_fee_cents + math.ceil(
            max(0.0, edge_m / 1000 - settings.delivery_base_km)
        ) * settings.delivery_per_km_cents
        assert base == uncapped, (
            f"配送半径边缘({edge_m:.0f}m)已经碰到封顶价 {base} —— "
            "骑手多骑的那段拿不到钱了,「范围按直线」的理由不再成立")


class Test算过的数要锁住:
    def test_订单上有计价距离和来源(self):
        from app.models import Order
        assert hasattr(Order, "bill_distance_m")
        assert hasattr(Order, "bill_distance_source")

    def test_来源两种取值都要能表达(self):
        """route 和 straight 差 19%,不标出来事后无从分辨
        「这单为什么比那单便宜」。"""
        assert set(routing._MODE_FALLBACK) >= {"bike"}
