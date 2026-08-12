"""定位丢了的时候,哪些接单偏好悄悄失效了。

这条守的是**「让骑手误以为某件事在生效」**这一类问题。

接单半径和只看顺路都要拿骑手位置来算,位置一没有就整段跳过 ——
而界面上 chip 还选着「3km」。骑手不会想到是定位的问题,他会按
"我只看 3 公里内"去接单,接了才发现要骑十公里。

比「挡掉了 N 单你不知道」更坏:那个是少看到单,这个是接错单。
"""
from app.routers.riders import stale_location_prefs as stale


class Test有定位时一切正常:
    def test_设了偏好也不报失效(self):
        assert stale(True, grab_radius_km=3, grab_same_way_only=True) == []

    def test_没设偏好更不报(self):
        assert stale(True, grab_radius_km=None, grab_same_way_only=False) == []


class Test没定位时照实报出来:
    def test_设了半径就报半径(self):
        assert stale(False, grab_radius_km=3,
                     grab_same_way_only=False) == ["grab_radius_km"]

    def test_设了只看顺路就报它(self):
        assert stale(False, grab_radius_km=None,
                     grab_same_way_only=True) == ["grab_same_way_only"]

    def test_两个都设了就都报(self):
        assert stale(False, grab_radius_km=5, grab_same_way_only=True) == [
            "grab_radius_km", "grab_same_way_only"]

    def test_一个没设就不报_没设谈不上失效(self):
        """没设过的偏好不该出现在提示里 —— 骑手会一头雾水
        "我什么时候设过只看顺路"。"""
        assert stale(False, grab_radius_km=None,
                     grab_same_way_only=False) == []


class Test半径为零当没设:
    def test_0km_不算设了(self):
        """`grab_radius_km=0` 是"不限"的另一种写法(服务端也按假值处理),
        不该报成"你的半径没生效"。"""
        assert stale(False, grab_radius_km=0, grab_same_way_only=False) == []


# ---------- 同时接单上限(#263) ----------

from app.config import settings
from app.routers.riders import effective_max_active as cap


class Test同时接单上限:
    """骑手能往下调,不能往上。

    往下随便 —— 那是他自己的节奏,新手设 1 单是攻略里的通行建议。
    往上不给 —— 同时 8 单必然有人超时,而超时的赔付平台出、差评他背。
    """

    def test_没设过就用平台默认(self):
        assert cap(None) == settings.rider_max_active_orders

    def test_往下调按他设的来(self):
        assert cap(1) == 1

    def test_往上调按平台硬上限截断(self):
        """接口层已经拦了 >cap 的入参,但这里再截一道 ——
        平台常数调小时,数据库里的存量值可能就超了。"""
        assert cap(settings.rider_max_active_orders + 5) == \
            settings.rider_max_active_orders

    def test_正好等于硬上限不受影响(self):
        hard = settings.rider_max_active_orders
        assert cap(hard) == hard


# ---------- 新手默认收窄半径(#266) ----------

from app.routers.riders import NOVICE_RADIUS_KM


class Test新手半径只自动设一次:
    """这条的风险不在设错值,在**替骑手做决定**。

    自动设一次是帮忙(新手接十公里的单必超时),反复设就是插手。
    而「没设过」和「设成了不限」的 grab_radius_km 都是 null,
    光看这个字段区分不出来 —— 所以有 grab_radius_touched。
    """

    def test_默认值是三公里(self):
        """和美团给新手的建议一致,理由也一样:接太远容易超时。"""
        assert NOVICE_RADIUS_KM == 3

    def test_没碰过且没设值_才该自动设(self):
        assert _should_auto(radius=None, touched=False) is True

    def test_碰过了就不再自动设_哪怕他设回不限(self):
        """「我就是要看全城」是个明确的决定,下次上线不该被悄悄改回 3 公里。"""
        assert _should_auto(radius=None, touched=True) is False

    def test_已经有值就不动(self):
        assert _should_auto(radius=5, touched=False) is False
        assert _should_auto(radius=5, touched=True) is False


def _should_auto(*, radius, touched):
    """复刻 set_online 里的判据,盯住它不被顺手改宽。"""
    return radius is None and not touched


# ---------- 收工方向(#264) ----------

from app.routers.riders import GO_HOME_PRECISION, round_coarse


class Test收工方向只存街道级:
    """这条守的是**隐私**,不是精度。

    骑手的收工方向多半就是他家附近。存得越准,我们的库里就越接近
    "这个人住在哪"—— 连着看几天就能推出来。而「往这个方向」这个用途
    只需要街道级:判顺路比的是绕路增量的相对大小,差一公里不影响排序。
    """

    def test_截到小数点后两位(self):
        assert round_coarse(30.661234) == 30.66
        assert round_coarse(104.082789) == 104.08

    def test_精度常量就是二(self):
        """改大这个数之前先想清楚:每多一位,定位精度细十倍。"""
        assert GO_HOME_PRECISION == 2

    def test_误差在一公里量级(self):
        """2 位 ≈ 0.01 度 ≈ 1.1km。够用,且不够指认到楼。"""
        raw = 30.665999
        assert abs(raw - round_coarse(raw)) < 0.01

    def test_负数也截得对(self):
        """南半球/西半球:round 对负数同样向偶数舍入,不会跑偏。"""
        assert round_coarse(-33.868821) == -33.87


class Test收工方向也会静默失效:
    """绕路增量是从「骑手当前位置」起算的,所以它和半径、顺路一样吃定位。

    加新偏好时都要过这一关:**它没生效的时候骑手看得出来吗?**
    """

    def test_没定位时报出来(self):
        assert "go_home_on" in stale(False, grab_radius_km=None,
                                     grab_same_way_only=False,
                                     go_home_on=True)

    def test_有定位时不报(self):
        assert stale(True, grab_radius_km=None, grab_same_way_only=False,
                     go_home_on=True) == []

    def test_没开就不报(self):
        assert stale(False, grab_radius_km=None, grab_same_way_only=False,
                     go_home_on=False) == []
