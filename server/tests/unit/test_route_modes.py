"""按出行方式算路径(#298)。

## 这组测试守什么

**同样 800 米,骑过去和走过去是两种体感。** 自取的人是走过去的,
订酒店的人多半开车。给错方式的距离,是让人按错误的前提做决定。

三件事最容易在后续改动里悄悄坏掉,所以都锁住:

1. **缓存键必须带 mode**。不带的话,步行查询会读到骑行缓存 ——
   不报错,只是数不对,而且一周内都不会自愈(TTL 七天);
2. **矩阵接口的 mode 取值和路径规划不同名**(bicycling / driving 对
   bike / drive),写混了腾讯会当参数错处理,静默回退直线;
3. **duration 的单位体检**。腾讯各接口单位不统一 —— 路径规划是分钟,
   距离矩阵是秒(#289 踩过)。单位错了不报错,只会把「走 12 分钟」
   显示成「走 720 分钟」。
"""
import app.services.routing as routing


class Test缓存键按方式分开:
    def test_三种方式三个键(self):
        a, b = (34.34, 108.94), (34.35, 108.95)
        keys = {routing._key(a, b, m) for m in ("bike", "walk", "drive")}
        assert len(keys) == 3, "键没带 mode,步行会读到骑行的缓存"

    def test_默认仍是bike(self):
        """默认值**不能改**:距离矩阵(#289)写进去的是这个键,
        单点调用要读得到它写的,前缀一变两套缓存各热各的。"""
        a, b = (34.34, 108.94), (34.35, 108.95)
        assert routing._key(a, b) == routing._key(a, b, "bike")
        assert routing._key(a, b).startswith("route:bike:")


class Test矩阵的方式取值:
    def test_和路径规划不同名(self):
        assert routing._MODE_MATRIX["bike"] == "bicycling"
        assert routing._MODE_MATRIX["drive"] == "driving"
        assert routing._MODE_MATRIX["walk"] == "walking"

    def test_三个方式都有对应接口和系数(self):
        for m in ("bike", "walk", "drive"):
            assert m in routing._MODE_API
            assert m in routing._MODE_FALLBACK
            assert m in routing._MODE_MATRIX
            assert m in routing._MODE_SPEED_RANGE


class Test兜底系数按方式区分:
    def test_步行比骑行短驾车比骑行长(self):
        """人能穿小区走天桥,车要绕单行道和高架。
        一个系数拍在三种方式上,等于承认我们没在区分。"""
        f = routing._MODE_FALLBACK
        assert f["walk"] < f["bike"] < f["drive"]


class Test速度区间体检:
    def test_步行区间不接受骑行速度(self):
        lo, hi = routing._MODE_SPEED_RANGE["walk"]
        assert lo <= 4.5 <= hi, "正常步行速度该被接受"
        assert not (lo <= 20 <= hi), "20km/h 的『步行』该被当成单位错"

    def test_把分钟当秒会被挡下(self):
        """真实故障形态:5000 米、实际 75 分钟,若被当成 75 秒,
        算出来是 240km/h —— 必须落在区间外。"""
        lo, hi = routing._MODE_SPEED_RANGE["walk"]
        kmh_wrong = (5000 / 1000) / (75 / 3600)
        assert not (lo <= kmh_wrong <= hi)


class Test限流和真配额耗尽要分开:
    def test_每秒上限是可重试的(self):
        """status=120 是『每秒请求量已达上限』,等一下就好;
        真的配额烧完了重试只是多烧一次,所以只有 120 在重试名单里。"""
        assert 120 in routing._RATE_LIMIT_STATUS
        assert routing._RATE_LIMIT_PAUSE > 0


class Test同格去重的前提:
    """矩阵按缓存格去重(50 家酒店常常只剩三四个真正要问的点)。

    去重成立的前提是「同一格里的点共用一个答案」——
    这个前提要是不成立,去重就是在给不同的地方发同一个距离。
    """

    def test_几十米内的点落在同一格(self):
        me = (30.6598, 104.0810)
        # 同一栋楼里的两家酒店(约 20m)
        a, b = (30.6927, 104.0823), (30.69272, 104.08232)
        assert routing._key(me, a, "drive") == routing._key(me, b, "drive"), \
            "同格前提不成立,去重会把不同地方给成同一个距离"

    def test_街对面不算同一格(self):
        """格子 0.001° ≈ 111m。再粗就会把街对面算成同一点 ——
        对步行来说,街对面和这边差一个红绿灯。"""
        me = (30.6598, 104.0810)
        a, b = (30.6927, 104.0823), (30.6940, 104.0840)
        assert routing._key(me, a, "walk") != routing._key(me, b, "walk")
