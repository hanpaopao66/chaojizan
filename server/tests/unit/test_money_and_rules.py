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


class Test三条业务线的退款都要落流水:
    """券/住宿的「退款」曾经只是改一个状态字段,一条 refunds 流水都不写。

    模拟支付期这歪打正着地自洽(没收钱也没退钱),真开微信支付那天
    就变成「收了钱、标记已退款、钱没退」。而对账自检看的是流水,
    只改状态字段它永远是绿的 —— 这一类错误没有任何症状。

    下面几条是**源码扫描式的守卫**:它们防的不是今天的 bug(e2e_refund_channels
    已经把行为钉死了),而是"以后有人在退款路径上加一条分支、忘了推渠道"。
    """

    def test_券和住宿的退款路径都调了渠道(self):
        import inspect

        from app.routers import stays, vouchers
        from app.services import auto_flow

        assert "request_voucher_refund" in inspect.getsource(
            vouchers.refund_purchase), "券退款没有推给支付渠道"
        # 住宿有五条落定退款的路:取消/拒单/到店无房/协商退/清扫 noshow。
        # 前四条在 stays,最后一条在清扫里
        for fn in (stays.cancel_stay_order, stays.reject_stay_order,
                   stays.resolve_stay_aftersale):
            assert "refund_to_channel" in inspect.getsource(fn), \
                f"{fn.__name__} 改了 refund_cents 却没推渠道"
        assert "refund_to_channel" in inspect.getsource(
            auto_flow._sweep_stays), "清扫判 noshow 时退的钱没有推渠道"

    def test_能原路退多少只有一个口径(self):
        """写入端和自检端必须共用 channel_refundable_cents。

        两处各写一遍 `min(refund_cents, total_cents)` 的下场,
        这个仓库已经在 _rider_due 和商家钱包上各踩过一次:
        加一笔新钱时只改了一处,另一处就成了长期红灯。
        """
        import inspect

        from app.services import audit
        for fn in (audit.run_audit, audit.backfill_legacy_refund_records):
            assert "channel_refundable_cents" in inspect.getsource(fn), \
                f"{fn.__name__} 要复用同一个口径函数,不能自己再算一遍"

    def test_到店无房的违约金不塞进退款流水(self):
        """`refund_cents = 房费 + 违约金`,**超过用户实付**。

        整笔推给微信会被「退款额 ≤ 原支付额」直接拒掉,而账面写着已退。
        """
        from types import SimpleNamespace

        from app.routers.stays import channel_refundable_cents

        # 到店无房:房费 40000 + 首晚 30% 违约金 6000
        no_room = SimpleNamespace(refund_cents=46000, total_cents=40000)
        assert channel_refundable_cents(no_room) == 40000
        # 其余四条路的退款额本来就不超过实付,原样退
        for refund, total in ((20000, 20000), (10000, 20000), (0, 20000)):
            o = SimpleNamespace(refund_cents=refund, total_cents=total)
            assert channel_refundable_cents(o) == refund

    def test_业务线字面量只定义一次(self):
        """写入按 'voucher' 存、自检按 'voucher' 查,各写各的字符串的话,
        改一处会让另一处**静默查不到数** —— 而查不到数的表现是自检全绿。"""
        import inspect

        from app import models
        from app.services import audit, wechat_pay

        assert models.REFUND_BIZ_FOOD == "food"
        assert models.REFUND_BIZ_VOUCHER == "voucher"
        assert models.REFUND_BIZ_STAY == "stay"
        for mod in (wechat_pay, audit):
            src = inspect.getsource(mod)
            assert "REFUND_BIZ_" in src, f"{mod.__name__} 应当引用常量"
            assert 'biz_type="voucher"' not in src, "别把业务线字面量再抄一遍"
            assert 'biz_type == "stay"' not in src, "别把业务线字面量再抄一遍"


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


class Test堂食标识是法定公示项:
    """总局令第 123 号第十二条(2026-06-01 施行):平台应当在列表页和
    商家主页展示「有堂食」「无堂食」标识。

    这一层守的是**不许给默认值**:布尔字段只能默认"有"或"无",
    两个都是替商家做一次没人核实过的陈述。填错比不填更糟。
    """

    def test_返回体带标识且是三态(self):
        from app.schemas import MerchantOut
        for f in ("dine_in_status", "dine_in_label"):
            assert f in MerchantOut.model_fields, f"列表返回体缺 {f}"
        assert MerchantOut.model_fields["dine_in_status"].default == "unknown"
        assert MerchantOut.model_fields["dine_in_label"].default == "未填报"

    def test_默认未填报而不是有堂食(self):
        """"这是法定公示项,平台猜一个填上去等于拿自己的信用背书。"""
        from app.models import Merchant
        col = Merchant.__table__.c.dine_in_status
        assert col.default.arg == "unknown", "默认必须是未填报"
        assert col.server_default.arg == "unknown", "存量商家也一律未填报"

    def test_标识挂在模型属性上而不是逐端点填(self):
        """理由同明厨亮灶:商家列表不止一个,逐个端点填一定会漏。"""
        from app.models import Merchant
        assert isinstance(Merchant.__dict__.get("dine_in_label"), property)

    def test_三态文案(self):
        from app.models import Merchant
        shop = Merchant()
        for value, label in (("yes", "有堂食"), ("no", "无堂食"),
                             ("unknown", "未填报"), ("", "未填报")):
            shop.dine_in_status = value
            assert shop.dine_in_label == label, value

    def test_只收白名单里的三个值(self):
        """能随手写进任意字符串的话,dine_in_label 会静默退化成「未填报」,
        商家以为填了、用户看到的是没填。"""
        import pytest as _pytest
        from pydantic import ValidationError

        from app.schemas import MerchantIn, MerchantPatch
        for value in ("yes", "no", "unknown"):
            assert MerchantPatch(dine_in_status=value).dine_in_status == value
        with _pytest.raises(ValidationError):
            MerchantPatch(dine_in_status="有堂食")
        assert MerchantIn(name="x", lat=0, lng=0).dine_in_status == "unknown"

    def test_不走资质变更那道闸(self):
        """堂食是对现状的陈述,店里加几张桌子就该能当天改过来 ——
        混进 _LICENSE_FIELDS 会让商家改一次就被要求重审。"""
        import inspect

        from app.routers import merchants as m
        src = inspect.getsource(m.update_my_shop)
        head = src.split("_LICENSE_FIELDS = (")[1].split(")")[0]
        assert "dine_in_status" not in head


class Test餐饮也要公示营业执照:
    """第十一条要求营业执照和食品经营许可证都在主页面显著位置持续展示。
    此前餐饮只公示了后者,酒店那条路径反倒是全的 —— 同一件事两个口径,
    漏的那个就是合规缺口。"""

    def test_餐饮公示两张证(self):
        import inspect

        from app.routers import merchants as m
        src = inspect.getsource(m.merchant_licenses)
        assert '"business_license": "营业执照"' in src
        assert "shop.business_license_no" in src, "营业执照号要真的取出来"

    def test_营业执照没有公示图出口(self):
        """库里只有执照号没有执照图。把它放进放行清单,
        那个**无鉴权**的出图口就会去猜一个不存在的 key。"""
        from app.routers.merchants import _PUBLIC_LICENSE_KINDS
        assert "business_license" not in _PUBLIC_LICENSE_KINDS


class Test列表半径与配送上限同一个数:
    """4–5km 的店此前能进列表、能进店、能加购物车,提交时被
    orders.py 以「超出配送范围」409 打回。用户视角是"这店明明在列表里,
    凭什么不给我送" —— 信任伤害,不是体验瑕疵。"""

    def test_不传就取配送上限(self):
        from app.routers.merchants import _browse_radius_m
        assert _browse_radius_m(None) == int(settings.delivery_max_km * 1000)

    def test_传大了也收敛到上限(self):
        """老客户端(搜索页还挂着「5km 内」)不能靠多传一个数
        把下不了单的店放回列表。"""
        from app.routers.merchants import _browse_radius_m
        cap = int(settings.delivery_max_km * 1000)
        assert _browse_radius_m(50_000) == cap
        assert _browse_radius_m(cap + 1) == cap

    def test_传小了照常生效(self):
        from app.routers.merchants import _browse_radius_m
        assert _browse_radius_m(1000) == 1000

    def test_列表里的店都下得了配送单(self):
        """半径口径与下单校验必须是同一个数,否则这条断言就是空的。"""
        from app.routers.merchants import _browse_radius_m
        assert in_delivery_range(_browse_radius_m(None))

    def test_搜索用同一个口径(self):
        """搜索此前不传 max_distance_m 就完全不限距离,
        搜出来的店比首页还远,一样点进去下不了单。"""
        import inspect

        from app.routers import merchants as m
        src = inspect.getsource(m.search_merchants)
        assert "_browse_radius_m(max_distance_m)" in src


class Test商家列表分页:
    """真实城市第 51 家店起永远看不到(原先硬编码 LIMIT 50)。"""

    def test_有offset且limit封顶(self):
        import inspect

        from app.routers import merchants as m
        params = inspect.signature(m.list_merchants).parameters
        assert "offset" in params and "limit" in params
        assert m._PAGE_MAX == 50

    def test_返回体仍是纯list(self):
        """契约不变:包成 {items,total} 会把所有老调用方一起打断。"""
        import typing

        from app.routers import merchants as m
        from app.schemas import MerchantOut
        hints = typing.get_type_hints(m.list_merchants)
        assert hints  # 签名可解析
        route = next(r for r in m.router.routes
                     if getattr(r, "endpoint", None) is m.list_merchants)
        assert route.response_model == list[MerchantOut]

    def test_排序是全序否则翻页会漏店(self):
        """评分/月售有大量并列,并列组内顺序不定 —— 同一家店会在
        第 1 页和第 2 页各出现一次,而另一家一次都不出现。"""
        from app.routers.merchants import _NEARBY_SQL_TMPL
        assert "ORDER BY {order_by}, m.id" in _NEARBY_SQL_TMPL
        assert "LIMIT :limit OFFSET :offset" in _NEARBY_SQL_TMPL

    def test_无定位兜底也要有稳定排序(self):
        import inspect

        from app.routers import merchants as m
        src = inspect.getsource(m.list_merchants)
        assert "order_by(Merchant.id)" in src, "没有 ORDER BY 时加 offset 会漏店"


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
        # 商家入账 / 商家冲账 / 骑手入账,三处都要走子查询 ——
        # 漏一处,核账照样会在那个量级挂掉
        assert src.count(".in_(completed_ids)") >= 3, \
            "三处按订单 id 查的地方都要走子查询"
        # 第四处「售后判责」搬进了 _reversal_due_ids(规则 6 与历史补录共用
        # 一套口径)。调用点把**同一个子查询**原样传进去,函数里再
        # `.in_(order_ids)` —— 换了个参数名,子查询没变。
        #
        # 只数 run_audit 源码里的 `.in_(completed_ids)` 会漏掉它:
        # 这条断言原来写死 >= 4,搬走那次就红了,而红的是断言不是代码。
        # 源码扫描类的守卫必须跟着代码走,否则它保护的是"别重构"
        assert "_reversal_due_ids(db, completed_ids)" in src, \
            "售后判责要复用同一个子查询,不能在这儿把 id 拉成列表"
        helper = inspect.getsource(audit._reversal_due_ids)
        assert helper.count(".in_(order_ids)") >= 2, \
            "_reversal_due_ids 里的 after_sales / refunds 两处也要走子查询"
        assert "[o.id for o" not in helper and "[a.id for a" not in helper, \
            "_reversal_due_ids 里不能把 id 逐个绑成参数"


class Test城市切换器:
    """地址搜索的城市必须能切(#172)。

    服务端的 POI 搜索用腾讯 `region_fix=1` 把结果**限死在指定城市** ——
    不加的话搜「一号店」会把全国同名地点都返回,用户容易选中外地那个,
    下单后才发现超出配送范围。

    但代价是:**城市选错,用户搜自己家一条都搜不到**。
    实测西安的「紫薇臻品」在 city=成都 时返回 0 条,而客户端此前
    一直传写死的「成都」—— 成都以外的用户根本搜不出自己的地址。
    """

    def test_城市清单来自实际有商家的城市(self):
        """列一个没有商家的城市,用户切过去只会看到空列表。"""
        import inspect

        from app.routers import geo
        src = inspect.getsource(geo.open_city_list)
        assert "status = 'approved'" in src, "应当只数已通过审核的商家"
        assert "open_cities" in src, "配了开城清单时以清单为准"

    def test_开城清单里没商家的城市要标出来(self):
        """开城清单是管理员圈的经营范围,可能有刚开城还没商家的 ——
        用户切过去会看到空列表,得先告诉他。"""
        import inspect

        from app.routers import geo
        src = inspect.getsource(geo.open_city_list)
        assert 'by_name.get(c, 0)' in src, "清单里没商家的城市要给 0 而不是漏掉"

    def test_搜索仍然限定城市(self):
        """限定本身是对的(防止选中外地同名地点),要保留。"""
        import inspect

        from app.routers import geo
        assert '"region_fix": 1' in inspect.getsource(geo.poi_tips)

    def test_城市清单公开不要求登录(self):
        """选城市这一步在登录前就可能发生(先看有没有店再决定注册)。"""
        import inspect

        from app.routers import geo
        sig = inspect.signature(geo.open_city_list)
        assert "user" not in sig.parameters, "选城市不该要求先登录"
