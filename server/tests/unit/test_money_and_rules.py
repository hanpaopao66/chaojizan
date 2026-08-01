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


class Test住宿清扫的顺序:
    """有挂起售后的订单不能被判「未入住」。

    这个顺序错了会**把责任判反**:客人提的是「到店无房」——
    他没入住恰恰是因为商家没房。而 noshow 分支会扣他首晚房费归商家,
    等于商家的过失让客人买单。

    而且判了 noshow 之后,售后自动成立会撞状态机
    (未入住 → 已取消不是合法转换)并抛异常,**整轮清扫就地中断** ——
    后面所有订单的退款和离店结算全都不执行。一笔卡住的售后能让所有人拿不到钱。
    """

    def test_noshow_查询排除了挂起售后(self):
        import inspect

        from app.services import auto_flow
        src = inspect.getsource(auto_flow._sweep_stays)
        # noshow 那段必须带上"排除有挂起售后的订单"这个条件
        assert "notin_(pending_as_orders)" in src or \
               "not_in(pending_as_orders)" in src, \
            "未入住的筛选没有排除有挂起售后的订单 —— 会把商家的过失算到客人头上"

    def test_单条售后失败不拖垮整轮(self):
        import inspect

        from app.services import auto_flow
        src = inspect.getsource(auto_flow._sweep_stays)
        assert "except Exception" in src and "continue" in src, \
            "一笔处理不了的售后不该让其余订单的退款全部停摆"
        # 但不能静默吞掉
        assert "logger.exception" in src, "跳过要留 error 日志,否则永远发现不了"

    def test_未入住到已取消不是合法转换(self):
        """钉住这个前提 —— 上面两条的必要性建立在它之上。"""
        from app.state_machine import STAY_TRANSITIONS, StayOrderStatus
        assert (StayOrderStatus.NOSHOW,
                StayOrderStatus.CANCELLED) not in STAY_TRANSITIONS


class Test订单信息法定留存:
    """《网络餐饮服务经营者落实食品安全主体责任监督管理规定》
    (总局令第 123 号,2026-06-01 施行)第十五条:

    > 平台提供者……应当如实记录并保存网络餐饮服务的订单信息……
    > **保存时间自交易完成之日起不少于三年。**

    注意这比旧规(36 号令的六个月)长得多。旧口径下写的任何"清理历史订单"
    的想法,现在都是违规的。
    """

    def test_法定要记录的五项都有落点(self):
        """食品名称、下单时间、送餐人员、送达时间、收货地址。"""
        from app.models import Order
        for field in ("items", "created_at", "rider_id",
                      "delivered_at", "address"):
            assert hasattr(Order, field), f"法定记录项缺字段:{field}"

    def test_送达时间有独立列而不是只靠事件表(self):
        """order_events 是流水:查一单的送达时间要 join + 过滤,
        而且**直接落库的订单没有对应事件** —— 实测 35042 单已送达/完成,
        delivered 事件只有 2055 条。法定要记录的字段就该有自己的列。
        """
        from app.models import Order
        assert hasattr(Order, "delivered_at")
        assert hasattr(Order, "completed_at")

    def test_没有任何地方删订单(self):
        """保存期是**三年**,而这套代码的清理逻辑一律只碰缓存和会话。

        这条测试是给未来的人看的:想加"清理历史订单"之前先看这里 ——
        三年内删一条都是违规。
        """
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[2] / "app"
        bad = []
        for f in root.rglob("*.py"):
            src = f.read_text(encoding="utf-8")
            for m in re.finditer(
                    r"(delete\(\s*Order\s*\)|DELETE\s+FROM\s+orders\b)", src):
                bad.append(f"{f.name}:{src[:m.start()].count(chr(10)) + 1}")
        assert not bad, f"有地方在删订单,而法定保存期是三年:{bad}"

    def test_注销账号不删订单只匿名化(self):
        """个保法第四十七条把"法律、行政法规规定的保存期限未届满"
        列为删除义务的例外。订单要留三年,所以注销是匿名化用户,不是删单。
        """
        import inspect

        from app.routers import auth
        src = inspect.getsource(auth)
        assert "已注销用户" in src, "注销应当匿名化"
        assert "delete(Order)" not in src and "DELETE FROM orders" not in src


class Test明厨亮灶标识是法定要求:
    """总局令第 123 号第十三条:平台应当"根据入网餐饮服务提供者是否实施
    「互联网+明厨亮灶」,在入网餐饮服务提供者列表页面展示
    「无明厨亮灶」、「有明厨亮灶」标识"。

    要标的是**两种**,而且是**每一个商家列表**。
    """

    def test_列表返回体带标识且两种都有(self):
        from app.schemas import MerchantOut
        for f in ("kitchen_cam", "kitchen_cam_label"):
            assert f in MerchantOut.model_fields, f"列表返回体缺 {f}"

    def test_标识挂在模型属性上而不是逐端点填(self):
        """商家列表不止一个(首页、搜索、收藏、附近……)。
        逐个端点填一定会漏,漏掉的那个列表就是个合规缺口。
        挂在模型属性上,from_attributes 会自动带出去。
        """
        from app.models import Merchant
        assert isinstance(
            Merchant.__dict__.get("kitchen_cam"), property), \
            "kitchen_cam 应当是模型属性,这样新加的列表天然带上"

    def test_只认在线可看(self):
        """待核验、掉线一律算「无」—— 标识和实际能不能看必须是同一件事。
        行业乱象正是"标着明厨亮灶却黑屏"。
        """
        from app.services import kitchen_cam as kc
        assert kc.LISTED_AS_HAS == (kc.STATUS_ACTIVE,)
        for s in (kc.STATUS_PENDING, kc.STATUS_DEGRADED, kc.STATUS_NONE):
            assert kc.listed_label(s) == "无明厨亮灶", s

    def test_降级要迟钝恢复要灵敏(self):
        """一次失败就降级会让商家疲于奔命,最后没人愿意装 ——
        而我们要的是更多人装。修好了则要让他快点回来。
        """
        from app.services import kitchen_cam as kc
        assert kc.FAIL_STREAK_TO_DEGRADE >= 2
        assert kc.OK_STREAK_TO_RECOVER <= kc.FAIL_STREAK_TO_DEGRADE

    def test_不给明厨亮灶加权排序(self):
        """一旦标识能换流量,就会有人对着天花板装一个来骗标识。"""
        from app.services import kitchen_cam as kc
        blob = " ".join(kc.NEVER_DO)
        assert "加权排序" in blob or "流量倾斜" in blob


class Test健康证按城市:
    """国家层面不要求送餐员持健康证(不属于"直接接触入口食品的人员",
    四川已明确取消),但地方可能另有规章 —— 做成城市级清单。
    """

    def test_默认不要求(self):
        from app.schemas import RiderProfileIn
        assert not RiderProfileIn.model_fields[
            "health_cert_photo_url"].is_required()

    def test_城市清单默认为空(self):
        """**默认空 = 都不要求。** 加城市的判据是"查到了本地条文",
        不是"别的平台都要" —— 跟着行业惯性加门槛正是原来那个毛病。
        """
        import inspect

        from app.services import flags
        src = inspect.getsource(flags.health_cert_cities)
        assert "return []" in src, "未配置时必须返回空清单(= 不要求)"

    def test_档案接口提前告知本市要不要(self):
        """等到上线被拦才发现,那时候他人已经在路上了。"""
        from app.schemas import RiderProfileOut
        assert "health_cert_required" in RiderProfileOut.model_fields
        assert "city" in RiderProfileOut.model_fields


class Test地图选点的周边地点:
    """地图选点页下方的周边列表(#170)。

    光给一个图钉 + 反查出来的一行地址,用户很难确认"这就是我家" ——
    反查给的往往是路名,而他要的是「XX 小区 10 号楼」。
    """

    def test_一次调用拿全不额外打周边搜索(self):
        """腾讯的逆地理编码带 get_poi=1 时会一并返回周边 POI 与距离。
        少一次调用就少一份配额和延迟。"""
        import inspect

        from app.routers import geo
        src = inspect.getsource(geo.poi_around)
        assert "REVERSE_URL" in src, "应复用逆地理编码,不另打周边搜索接口"
        assert '"get_poi": 1' in src

    def test_没坐标的地点要过滤掉(self):
        """选了也没用 —— 骑手送不到。"""
        import inspect

        from app.routers import geo
        src = inspect.getsource(geo.poi_around)
        assert "continue" in src and "lat" in src

    def test_按距离排序(self):
        import inspect

        from app.routers import geo
        assert 'sort(key=lambda x: x["distance_m"])' in \
            inspect.getsource(geo.poi_around)

    def test_未配置key时给演示数据而不是报错(self):
        """开发环境没配 key 也要能把流程走完。"""
        import inspect

        from app.routers import geo
        src = inspect.getsource(geo.poi_around)
        assert "if not settings.tencent_map_key" in src


class Test核账要随单量增长仍能跑:
    """每日自动核账用的是 `order_id.in_(...)`。

    如果传的是 **Python 列表**,SQLAlchemy 会给每个 id 绑一个占位符,
    而 PostgreSQL 单条语句的参数上限是 **32767** —— 一个月完成单超过这个数,
    核账就直接抛 `the number of query arguments cannot exceed 32767` 挂掉。

    后果不是"少一条告警",是**整个核账不再运行** ——
    而这套东西的全部意义就是"差一分钱系统报警"。
    它必须随单量增长而继续能跑,不能到某个量级就自己停了。
    """

    def test_用子查询而不是id列表(self):
        import inspect

        from app.services import audit
        src = inspect.getsource(audit.run_audit)
        assert "completed_ids = select(Order.id)" in src, \
            "应当用子查询,不要把 id 列表逐个绑成参数"
        # 旧写法的痕迹不能残留
        assert "order_ids = [o.id for o in completed]" not in src

    def test_三处入账查询都走子查询(self):
        import inspect

        from app.services import audit
        src = inspect.getsource(audit.run_audit)
        # 商家入账 / 商家冲账 / 骑手入账 / 售后判责,四处都要走子查询 ——
        # 漏一处,核账照样会在那个量级挂掉
        assert src.count(".in_(completed_ids)") >= 4, \
            "四处按订单 id 查的地方都要走子查询"
