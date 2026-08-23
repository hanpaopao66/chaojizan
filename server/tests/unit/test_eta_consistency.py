"""结算页的「预计送达」必须和下单后的是同一个数(#295)。

## 这组测试在防什么

结算页原来自己算:直线距离 × 一个常量速度。下单成功后订单上的
`eta_at` 是服务端算的(腾讯骑行路网 + 商家实测出餐 + 忙碌模式)。
于是同一件事在同一分钟内有两个答案 —— 结算页 30 分钟,付完款 42 分钟。

新用户不会想到这是两套算法。他只会记住这个 App 说话不算数。

修法是让结算页去问服务端(`/orders/delivery-fee` 的 `eta_minutes`),
走 `compute_eta_async` —— 和 `payment_core` 下单时**同一个函数**。

⚠️ 这里的风险是"悄悄走偏":有人为了让预估"更准"给它传上
`prep_minutes`(商家实测分位数),看着是优化,实际又把两个数拉开了 ——
因为下单那条路径**没传**。所以下面第一组直接对着 payment_core 的
调用形态测,而不是测某个具体分钟数。
"""
import inspect
from types import SimpleNamespace

from app.services import eta as eta_mod


def _probe(lat=34.35, lng=108.95, **kw):
    """结算页预估用的轻量对象,字段和 orders.preview_delivery_fee 里一致。"""
    base = dict(pickup=False, parent_order_no="", scheduled_at=None,
                lat=lat, lng=lng)
    base.update(kw)
    return SimpleNamespace(**base)


def _shop(lat=34.34, lng=108.94, **kw):
    return SimpleNamespace(lat=lat, lng=lng, **kw)


class Test预估和下单同源:
    def test_下单路径没有传prep(self):
        """守住"两边参数一致"这件事本身。

        `payment_core` 是 `compute_eta_async(order, merchant)` —— 光秃秃两个位置参数。
        哪天它开始传 prep_minutes 了,结算页那边也必须跟着传,
        否则又是两个数。这条测试就是那时候的闹钟。
        """
        src = inspect.getsource(
            __import__('app.services.payment_core', fromlist=['x']))
        call = [ln for ln in src.splitlines() if 'compute_eta_async(' in ln]
        assert call, '找不到 compute_eta_async 调用,payment_core 改结构了'
        assert all('prep_minutes' not in ln for ln in call), (
            'payment_core 开始传 prep_minutes 了 —— '
            'orders.preview_delivery_fee 里的预估必须同步改,否则结算页和订单又对不上')

    def test_预估用的字段compute_eta都读得到(self):
        """轻量对象少给一个字段,就会在预估里静默走成另一个分支。"""
        got = eta_mod.compute_eta(_probe(), _shop())
        assert got is not None

    def test_同样的输入给同一个数(self):
        """预估的 probe 和真订单,喂进去结果必须一样。"""
        order = SimpleNamespace(pickup=False, parent_order_no="",
                                scheduled_at=None, lat=34.35, lng=108.95,
                                floor=None, has_elevator=None,
                                order_no="X1", status=None)
        a = eta_mod.compute_eta(_probe(), _shop())
        b = eta_mod.compute_eta(order, _shop())
        # 两次调用相差几微秒,比到分钟
        assert a.replace(second=0, microsecond=0) == \
            b.replace(second=0, microsecond=0)


class Test爬楼要算进预估:
    def test_高层无电梯比一层久(self):
        """结算页选的地址带楼层,预估就得含爬楼 ——
        否则用户在结算页看到的是"不含爬楼"的数,下单后变长。"""
        low = eta_mod.compute_eta(
            _probe(floor=1, has_elevator=True), _shop())
        high = eta_mod.compute_eta(
            _probe(floor=6, has_elevator=False), _shop())
        assert high > low

    def test_没填楼层不猜(self):
        no_info = eta_mod.compute_eta(
            _probe(floor=None, has_elevator=None), _shop())
        one = eta_mod.compute_eta(_probe(floor=1, has_elevator=True), _shop())
        assert no_info.replace(second=0, microsecond=0) == \
            one.replace(second=0, microsecond=0)


class Test自取和追加单不给预估:
    def test_自取返回None(self):
        """自取没有配送,给个"预计送达"是无中生有。"""
        assert eta_mod.compute_eta(_probe(pickup=True), _shop()) is None

    def test_追加单返回None(self):
        assert eta_mod.compute_eta(
            _probe(parent_order_no="A100"), _shop()) is None


class Test客户端常量对齐服务端:
    def test_出餐兜底是20分钟(self):
        """`coord_utils.dart` 的 etaMinutes 里写死了同一个 20。

        两边不一致时,商家列表页会系统性地比结算页乐观 ——
        每一单都差那几分钟。改这里就得改那里。
        """
        assert eta_mod.ETA_PREP_MINUTES == 20


class Test券名要认得出:
    """#296:用户被赔的是"安抚券",订单上就不能只写"平台券"。"""

    def test_超时赔付叫安抚券(self):
        from app.routers.orders import _coupon_label
        assert _coupon_label("eta:A20260823001") == "超时安抚券"

    def test_各来源各有名字(self):
        from app.routers.orders import _coupon_label
        assert _coupon_label("favorite:12:34") == "收藏有礼券"
        assert _coupon_label("batch:7:34") == "平台活动券"
        assert _coupon_label("shop:7:34:1") == "店铺券"

    def test_没见过的来源不瞎猜(self):
        from app.routers.orders import _coupon_label
        assert _coupon_label("newthing:1") == "平台券"
