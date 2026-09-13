"""公开大屏(/screen/stats、/screen/orders/latest)的口径。

## 跑腿服务主体不是商家

跑腿单挂在本城一个 biz_type='errand' 的 Merchant 上 —— 平台自己建的占位,
状态直接是 approved、坐标 (0, 0)、名字「某某市跑腿服务」。大屏原来三处被它带偏,
全都不报错:

- 「商家入驻数」「服务 N 商家」把它数成一家店;
- 城市坐标取「订单所挂商家的坐标均值」,跑腿单越多,城市点越往 (0, 0) 拽;
- 播报写成「在「西安市跑腿服务」下单」,涟漪画在经纬度 (0, 0)。

这一类错的形状是「判据用错」:SQL 跑得通、数也像样,只是数的东西不对。
所以这里直接盯 SQL 的判据,再用假会话把整个接口跑一遍,看返回的形状。

## 团购、跑腿的今日数

大屏地图底下那一行要「团购今日核销 N 张」「跑腿今日 N 单」,原来接口里没有。
新加的两个数只出张数/单数,不出金额,也不含任何个人信息。
"""
import asyncio
from datetime import date, datetime, timezone

import pytest

from app.routers import screen


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def one(self):
        return self.rows[0]

    def all(self):
        return self.rows


class FakeDB:
    """按语句里的特征片段分流的假会话。每条执行过的 SQL 都记下来,
    判据类断言直接查这份记录。"""

    def __init__(self, *, merchants=(4011, 3), cities=None, latest=None,
                 vouchers_today=37, errands_today=22):
        self.sql: list[str] = []
        self.merchants = merchants
        self.cities = cities if cities is not None else [
            ("西安市", 18426, 4930000, 34.3412, 108.9398)]
        self.latest = latest or []
        self.vouchers_today = vouchers_today
        self.errands_today = errands_today

    async def get(self, model, pk):
        return None  # 没有开关行:GMV 默认展示、开城清单没配

    async def execute(self, stmt, params=None):
        s = str(stmt)
        self.sql.append(s)
        today = date(2026, 9, 13)
        if "FROM users" in s and "JOIN" not in s:
            return _Result([(12846, 128, 3470, 41, 36)])
        if "FROM merchants" in s:
            return _Result([self.merchants])
        if "GROUP BY m.city" in s:
            return _Result(self.cities)
        if "JOIN users u" in s:
            return _Result(self.latest)
        if "::date AS d" in s:
            return _Result([(today, 168, 493200)])
        if "is_today" in s:
            return _Result([(True, 12, 26), (False, 12, 22)])
        if "SELECT status, count(*)" in s:
            return _Result([("completed", 104), ("picked_up", 31)])
        if "FROM merchant_earnings" in s:
            return _Result([(1000000, 47200)])
        if "least(floor" in s:
            return _Result([(1, 61)])
        if "ready_late" in s:
            return _Result([(3, 88)])
        if "FROM stay_orders" in s:
            return _Result([(14, 19, 0, 0)])
        if "FROM orders WHERE" in s:
            return _Result([(48219, 150000000, 168, 493200, self.errands_today)])
        raise AssertionError(f"没料到的查询:{s[:120]}")

    async def scalar(self, stmt):
        s = str(stmt)
        self.sql.append(s)
        if "avg(extract(epoch" in s:
            return 28.4
        if "count(DISTINCT city)" in s:
            return 10
        if "remark LIKE" in s:
            return 54
        if "checked_in" in s:
            return 11
        if "voucher_purchases" in s:
            return self.vouchers_today
        raise AssertionError(f"没料到的查询:{s[:120]}")


@pytest.fixture(autouse=True)
def _no_guard_no_cache(monkeypatch):
    async def _ok(request):
        return None
    monkeypatch.setattr(screen, "_guard", _ok)
    monkeypatch.setattr(screen.settings, "public_cache_max_seconds", 0)
    monkeypatch.setattr(screen.settings, "screen_demo", False)
    screen._cache.clear()


def _stats(db):
    return asyncio.run(screen.screen_stats(request=None, db=db))


def _latest(db, limit=20):
    return asyncio.run(screen.screen_latest_orders(request=None, limit=limit, db=db))


class Test跑腿服务主体不算商家:
    def test_数商家的每一条语句都排除了跑腿主体(self):
        db = FakeDB()
        _stats(db)
        counted = [s for s in db.sql if "FROM merchants" in s]
        assert len(counted) >= 2, "商家数和开城兜底两处都该查到"
        for s in counted:
            assert "biz_type <> 'errand'" in s, (
                "数商家的语句没排除跑腿服务主体 —— 每开一城跑腿,"
                "「商家入驻数」就平白多一家:\n" + s)

    def test_城市坐标不取跑腿主体的零点(self):
        db = FakeDB()
        _stats(db)
        (s,) = [s for s in db.sql if "GROUP BY m.city" in s]
        assert "avg(m.lat) FILTER (WHERE m.biz_type <> 'errand')" in s
        assert "avg(m.lng) FILTER (WHERE m.biz_type <> 'errand')" in s
        # 单量照算:跑腿单也是这座城的单,只是不参与取坐标
        assert "count(*)" in s and "WHERE o.status NOT IN" in s

    def test_只有跑腿单的城市给空坐标而不是零(self):
        """坐标全被 FILTER 掉时 avg 是 NULL。round(None) 会让整个接口 500,
        给 0 又会把点画到几内亚湾 —— 只能是 None,前端不画点。"""
        db = FakeDB(cities=[("西安市", 180, 0, 34.3412, 108.9398),
                            ("铜川市", 12, 0, None, None)])
        data = _stats(db)
        tong = next(c for c in data["cities"] if c["city"] == "铜川市")
        assert tong["lat"] is None and tong["lng"] is None
        assert tong["orders"] == 12, "没坐标也照样上 TOP10,单量不能丢"
        xian = next(c for c in data["cities"] if c["city"] == "西安市")
        assert (xian["lat"], xian["lng"]) == (34.34, 108.94), "坐标只到城市级两位小数"

    def test_服务商家数和入驻数是同一个数(self):
        data = _stats(FakeDB(merchants=(1204, 9)))
        assert data["registrations"]["merchants"] == {"total": 1204, "today": 9}
        assert data["coverage"]["merchants"] == 1204


class Test团购跑腿今日数:
    def test_两个新数都在返回里(self):
        data = _stats(FakeDB(vouchers_today=37, errands_today=22))
        assert data["vouchers"] == {"today_redeemed": 37}
        assert data["errands"] == {"today_orders": 22}

    def test_团购按核销时刻数已核销的券(self):
        db = FakeDB()
        _stats(db)
        (s,) = [s for s in db.sql if "voucher_purchases" in s]
        assert "status = 'redeemed'" in s and "redeemed_at >=" in s, (
            "团购的钱在核销那一刻才分,按购买时刻数会把没核销、还能退的券算进去")

    def test_跑腿按有效订单口径数(self):
        """和「今日 N 单」同一口径(付了钱、没取消),所以跑腿数 ≤ 今日单数。"""
        db = FakeDB()
        _stats(db)
        (s,) = [s for s in db.sql if "order_kind IN" in s]
        assert "status NOT IN ('pending_payment','cancelled')" in s
        assert "('errand_send', 'errand_buy')" in s

    def test_新数不带金额也不受_GMV_开关管(self):
        data = _stats(FakeDB())
        for k in ("vouchers", "errands"):
            assert not any("cents" in f for f in data[k]), f"{k} 不该出金额"


def _row(**kw):
    base = dict(id=9, order_no="SZ2026091300001", status="picked_up",
                total_cents=2600, created_at=datetime(2026, 9, 13, 4, 1, tzinfo=timezone.utc),
                name="张记面馆", city="西安市", lat=34.26113, lng=108.94264,
                phone="13800006421", kind="food")
    base.update(kw)
    return (base["id"], base["order_no"], base["status"], base["total_cents"],
            base["created_at"], base["name"], base["city"], base["lat"],
            base["lng"], base["phone"], base["kind"])


class Test播报:
    def test_外卖单照旧(self):
        item = screen.ticker_item(_row(), show_gmv=True)
        assert item["merchant"] == "张记面馆"
        assert (item["lat"], item["lng"]) == (34.26, 108.94)
        assert item["phone"] == "138****6421"
        assert item["order_no_tail"] == "300001"
        assert item["status_label"] == "配送中"

    @pytest.mark.parametrize("kind,label", [("errand_send", "帮我送"),
                                            ("errand_buy", "帮我买")])
    def test_跑腿单写频道名_不给坐标(self, kind, label):
        item = screen.ticker_item(
            _row(kind=kind, name="西安市跑腿服务", lat=0.0, lng=0.0), show_gmv=True)
        assert item["merchant"] == label, "跑腿服务主体不是店"
        assert item["lat"] is None and item["lng"] is None, (
            "服务主体的 (0, 0) 是占位,涟漪会画到几内亚湾;"
            "取件点是用户自己的地址,也不能拿来顶")
        assert item["city"] == "西安市"

    def test_GMV_关掉时不出金额(self):
        assert screen.ticker_item(_row(), show_gmv=False)["amount_cents"] is None

    def test_接口整条跑通(self):
        db = FakeDB(latest=[_row(), _row(id=8, kind="errand_buy", name="西安市跑腿服务",
                                         lat=0.0, lng=0.0)])
        data = _latest(db)
        assert [i["merchant"] for i in data["items"]] == ["张记面馆", "帮我买"]
        (s,) = [s for s in db.sql if "JOIN users u" in s]
        assert "o.order_kind" in s
