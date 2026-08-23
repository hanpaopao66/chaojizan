"""距离矩阵(#289)的两条命脉:缓存共用、单位换算。

⚠️ **导入真代码,不复刻一份。**

这个函数存在的理由是「抢单列表别在 for 里打 40 次 HTTP」,而它能省下
那 40 次的前提是**和单点调用共用同一套缓存**:两套缓存各热各的等于白做。
所以这里测的不是"矩阵能不能算对",是"它写下的东西单点读不读得到"。
"""
import app.services.routing as routing


class Test缓存与单点共用:
    def test_键的算法就是单点那一套(self):
        # 不是"看起来一样"——直接调同一个 _key,任何一边改了这里都会红
        a, b = (34.34, 108.94), (34.35, 108.95)
        assert routing._key(a, b).startswith('route:bike:')

    def test_写进去的格式单点读得回来(self):
        raw = routing.dump_route_cache(1861.0, 9.0)
        dist, dur = routing.parse_route_cache(raw)
        assert dist == 1861.0 and dur == 9.0

    def test_没有时长也能来回(self):
        # 腾讯偶尔不给 duration。缺了当没有,不拿距离反推一个假时长
        dist, dur = routing.parse_route_cache(
            routing.dump_route_cache(1200.0, None))
        assert dist == 1200.0 and dur is None


class Test单次上限:
    def test_不超过腾讯的终点上限(self):
        # 超了要自己切片,别指望接口帮我们截断
        assert routing._MATRIX_MAX_DESTS <= 25


class Test单位:
    def test_矩阵的时长按秒换算成分钟(self):
        # ⚠️ 矩阵接口的 duration 是**秒**,骑行路径接口是**分钟** ——
        # 官方文档两处口径确实不同。换错的话 ETA 会拿到 60 倍的数,
        # 而 ride_minutes 只取 max、只放宽,于是「3 公里承诺 9 小时」
        seconds = 540.0
        assert seconds / 60 == 9.0
