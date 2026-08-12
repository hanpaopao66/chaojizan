"""骑行路径缓存的新旧格式兼容(#268)。

缓存里存的东西从「距离」变成了「距离|时长」,TTL 一周。
**升级之后那一周,缓存里还有一大批旧格式的值** ——
解析不了的话会一路回退到直线兜底,而直线比路网短,
表现出来就是 ETA 莫名其妙变紧了一周。

这里只测解析这一段(纯字符串处理),不打网络。

⚠️ **导入真代码,不复刻一份。** 第一版这里自己写了个 parse 副本 ——
那样真代码改了测试照样绿,等于没测。为此把解析抽成了
`routing.parse_route_cache`。
"""
import pytest

from app.services.routing import dump_route_cache, parse_route_cache as parse


class Test缓存格式兼容:
    def test_新格式_距离和时长都有(self):
        assert parse("1861.0|9.0") == (1861.0, 9.0)

    def test_新格式_腾讯没给时长(self):
        """接口偶尔不返回 duration,存成空 —— 读出来是 None 不是 0。
        0 会被 ride_minutes 当成"路网说 0 分钟",虽然那里也挡了,
        但不该指望下游兜底。"""
        assert parse("1861.0|") == (1861.0, None)

    def test_旧格式_只有距离(self):
        """升级前写进去的值。**必须还能读**,否则那一周全部回退直线。"""
        assert parse("1861.0") == (1861.0, None)

    def test_旧格式整数也认(self):
        assert parse("1861") == (1861.0, None)

    def test_坏值抛出_由外层兜住(self):
        """写坏的缓存不该被当成合法距离。外层 bicycling_route 有
        try/except 包着读缓存那段,抛出去就走正常请求。"""
        with pytest.raises(ValueError):
            parse("garbage")


class Test写读成对:
    """dump 和 parse 是一对,改一个必须改另一个。往返测钉住这件事。"""

    @pytest.mark.parametrize("dist,dur", [
        (1861.0, 9.0),
        (1861.0, None),
        (0.5, 0.5),
        (123456.0, 240.0),
    ])
    def test_写进去再读出来还是原样(self, dist, dur):
        assert parse(dump_route_cache(dist, dur)) == (dist, dur)
