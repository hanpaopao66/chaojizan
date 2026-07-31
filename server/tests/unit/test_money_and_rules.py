"""单元测试:只挑「算错了会直接变成钱」的地方(#129)。

为什么单独开一层:e2e 慢、要起服务连库、失败时定位成本高,不适合覆盖边界条件。
这一层只测纯函数 —— 不起服务、不连库,必须秒级跑完,慢了就没人跑。

不追求覆盖率数字。选的五类都是出过事或最容易出事的:
配送费分段、阶梯佣金的 5% 承诺上限、风控包围盒、跨零点时间窗、账本哈希稳定性。
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402
from app.services.auto_flow import tier_rate_for  # noqa: E402
from app.services.flags import in_hhmm_range  # noqa: E402
from app.services.ledger import canonical, sha256  # noqa: E402
from app.services.pricing import (delivery_fee_parts, haversine_m,  # noqa: E402
                                  in_delivery_range, is_night)


# ---------------- 配送费:算错就是骑手少拿或用户多付 ----------------
class TestDeliveryFee:
    def test_起步价覆盖基础距离内(self):
        """2km 内都是起步价,不该按距离加钱。"""
        for m in (0, 500, 1999, 2000):
            parts = delivery_fee_parts(m, when=_noon())
            assert parts["base"] == settings.delivery_base_fee_cents, m

    def test_超出部分向上取整加价(self):
        """2.1km 也算超 1km —— 向上取整,不是四舍五入。
        取整方向弄反的话每一单都少给骑手一块钱。"""
        base = settings.delivery_base_fee_cents
        per = settings.delivery_per_km_cents
        assert delivery_fee_parts(2100, when=_noon())["base"] == base + per
        assert delivery_fee_parts(3000, when=_noon())["base"] == base + per
        assert delivery_fee_parts(3001, when=_noon())["base"] == base + 2 * per

    def test_距离部分有封顶(self):
        """封顶是对用户的承诺:再远也不会无限涨。"""
        assert (delivery_fee_parts(100_000, when=_noon())["base"]
                == settings.delivery_max_fee_cents)

    def test_夜间与天气加价分开计且不受封顶影响(self):
        """封顶只管距离部分。夜间/天气是另计的,全额归骑手 ——
        如果被一起封顶,深夜跑远单反而比白天挣得少。"""
        # 夜间窗口按北京时间判定:北京 23:00 = UTC 15:00。
        # 直接写 23:00 UTC 会落到北京早上 7 点(这里第一版就写错了)
        night = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
        parts = delivery_fee_parts(100_000, weather_on=True, when=night)
        assert parts["base"] == settings.delivery_max_fee_cents
        assert parts["night"] == settings.delivery_night_surcharge_cents
        assert parts["weather"] == settings.delivery_weather_surcharge_cents

    def test_白天不收夜间加价(self):
        assert delivery_fee_parts(1000, when=_noon())["night"] == 0

    def test_配送半径边界(self):
        limit = settings.delivery_max_km * 1000
        assert in_delivery_range(limit - 1)
        assert not in_delivery_range(limit + 1)


def _noon() -> datetime:
    """北京时间正午(UTC+8),确保不落进夜间窗口。"""
    return datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc)


# ---------------- 阶梯佣金:5% 是写进承诺的上限 ----------------
class TestTierCommission:
    def test_按单量降档(self):
        assert tier_rate_for(0) == Decimal("0.050")
        assert tier_rate_for(499) == Decimal("0.050")
        assert tier_rate_for(500) == Decimal("0.045")
        assert tier_rate_for(1000) == Decimal("0.040")
        assert tier_rate_for(999_999) == Decimal("0.040")

    def test_任何档都不得高于5个点(self):
        """这是对商家的公开承诺,不是一个可调参数。
        即使配置被改坏,函数也必须把它钳回 5%。"""
        original = settings.commission_tiers
        try:
            settings.commission_tiers = [[0, "0.080"], [500, "0.200"]]
            assert tier_rate_for(0) == Decimal("0.050")
            assert tier_rate_for(9999) == Decimal("0.050")
        finally:
            settings.commission_tiers = original

    def test_负数单量不炸且取最低档(self):
        assert tier_rate_for(-1) == Decimal("0.050")


# ---------------- 时间窗:跨零点是最容易写错的一种 ----------------
class TestHhmmWindow:
    def test_不跨天(self):
        assert in_hhmm_range("09:00-18:00", "12:00")
        assert not in_hhmm_range("09:00-18:00", "08:59")
        assert not in_hhmm_range("09:00-18:00", "18:00")   # 右开区间

    def test_跨零点(self):
        """23:00-05:00 这种宵禁窗口,写成 start<=x<end 会整段失效。"""
        w = "23:00-05:00"
        assert in_hhmm_range(w, "23:30")
        assert in_hhmm_range(w, "00:00")
        assert in_hhmm_range(w, "04:59")
        assert not in_hhmm_range(w, "05:00")
        assert not in_hhmm_range(w, "22:59")

    def test_格式不对时不生效而不是崩(self):
        """配置写错不该让下单整条链路挂掉。"""
        for bad in ("", "乱写", "09:00", "a-b-c"):
            assert in_hhmm_range(bad, "12:00") is False


# ---------------- 风控包围盒:曾让 e2e 时好时坏 ----------------
class TestRiskBox:
    def test_包围盒约65米(self):
        """services/risk.py 用 _DEG=0.0006 的经纬度包围盒近似 65m。
        这个常数一旦改大,正常小区的邻居会被互相判成刷单;
        改小则同一栋楼刷单查不出来。锁住它的实际尺度。"""
        from app.services.risk import _DEG

        lat, lng = 30.66, 104.08
        # 纬度方向:1 度 ≈ 111km,0.0006 度 ≈ 66.6m
        ns = haversine_m(lat, lng, lat + _DEG, lng)
        assert 60 <= ns <= 75, f"南北向 {ns:.1f}m 偏离 65m 量级"
        # 经度方向在该纬度收缩 cos(30.66°)≈0.86
        ew = haversine_m(lat, lng, lat, lng + _DEG)
        assert 50 <= ew <= 70, f"东西向 {ew:.1f}m 偏离预期"

    def test_测试用坐标网格间距大于包围盒(self):
        """tests/util.unique_spot 的网格必须比包围盒宽,
        否则相邻用例会互相判成同址高频(这条真实翻过车)。"""
        # 从 tests.geo 取而不是 tests.util:后者 import 时会调 API,
        # 让这条纯函数测试隐式依赖起着的服务(CI 上就是这么红的)
        from tests.geo import unique_spot

        a = unique_spot("seed-a")
        b = (a[0] + 0.0008, a[1])          # 网格步长
        assert haversine_m(*a, *b) > 70


# ---------------- 账本:哈希链的地基是序列化稳定 ----------------
class TestLedgerCanonical:
    def test_键序不影响输出(self):
        """两端各自序列化后要字节级一致,否则哈希对不上、
        见证节点会把正常账本判成篡改。"""
        assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})

    def test_无多余空白(self):
        assert " " not in canonical({"a": 1, "b": [1, 2]})

    def test_中文不转义(self):
        """转成 \\uXXXX 的话,另一端用不同库序列化就对不上。"""
        assert "商家" in canonical({"k": "商家"})

    def test_同样输入同样哈希(self):
        payload = {"day": "2026-07-30", "rows": [{"s": "abc", "fee": 100}]}
        assert sha256(canonical(payload)) == sha256(canonical(payload))

    def test_内容变了哈希必变(self):
        a = sha256(canonical({"fee": 100}))
        b = sha256(canonical({"fee": 101}))
        assert a != b


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
