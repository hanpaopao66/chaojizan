"""埋点白名单(#311)。

## 这一组守的是一句话:**声明的原则必须由代码强制**

`analytics.dart` 和 `routers/platform.py` 的文件头都写着
「只收登录用户的产品行为,不收设备指纹」。在白名单落地之前,
服务端做的是 `props=e.props` —— 任何键、任何值、照单全收。

对闭源产品这叫"靠自觉"。**对开源项目这是自相矛盾的公开代码**:
policy 写在注释里,enforcement 是空的。任何人 fork 之后加一行
`Analytics.track('device', {'imei': ...})` 就能收上来。

所以这里的判据不是「过滤逻辑对不对」,是
**「那句公开的承诺,在代码里拦得住吗」**。
"""
import pytest

from app.services.events import (ALLOWED, MAX_PROPS_KEYS, MAX_VALUE_LEN,
                                 SEARCH_Q_MAX, clean)


class Test默认拒绝:
    def test_不在白名单的事件整条丢掉(self):
        assert clean("device_info", {"imei": "8613800000000"}) is None
        assert clean("gps", {"lat": 30.66, "lng": 104.08}) is None
        assert clean("", {}) is None

    def test_白名单外的键逐个丢掉(self):
        """事件名对,但夹带了别的东西 —— 这是最可能真实发生的形状:
        某次改动顺手往现有事件里多塞一个字段。"""
        name, props = clean("view_menu",
                            {"merchant_id": 1, "lat": 30.66, "imei": "x"})
        assert props == {"merchant_id": 1}, f"夹带的键进来了:{props}"

    def test_嵌套对象和数组一律不收(self):
        """它们是「以后想放什么都行」的口子,而白名单的意义就是不留口子。"""
        _, props = clean("view_menu",
                         {"merchant_id": {"nested": "x"}})
        assert props == {}
        _, props = clean("search", {"q": ["a", "b"], "hits": 1})
        assert props == {"hits": 1}


class Test设备指纹这句承诺:
    @pytest.mark.parametrize("key", [
        "imei", "idfa", "oaid", "android_id", "mac", "ip", "ua",
        "device_id", "serial", "lat", "lng", "location",
    ])
    def test_没有任何事件允许设备或位置类字段(self, key):
        """逐个点名。加事件的人要往白名单里加键,这条会当场红。"""
        for event, keys in ALLOWED.items():
            assert key not in keys, (
                f"事件 {event} 允许了 {key} —— "
                f"「不收设备指纹」这句话就不成立了")


class Test搜索词:
    def test_超长截断而不是拒绝整条(self):
        """搜索词是这套埋点里最敏感的字段:可能是地址、人名,
        或者暴露健康状况的词。但没有任何分析需要 40 个字的搜索词 ——
        那种长度多半是整段地址粘贴进来的。"""
        _, props = clean("search", {"q": "成都市锦江区某某路" * 5, "hits": 0})
        assert len(props["q"]) == SEARCH_Q_MAX
        assert props["hits"] == 0, "截断搜索词不该把别的字段一起丢掉"

    def test_搜索词的限长比普通字段更严(self):
        assert SEARCH_Q_MAX < MAX_VALUE_LEN


class Test白名单本身:
    def test_浏览类事件不带任何_props(self):
        """透明中心/信任页要回答的问题只是「有没有人看」,
        不需要知道是谁看了哪一段。"""
        assert ALLOWED["view_transparency"] == frozenset()
        assert ALLOWED["view_trust"] == frozenset()

    def test_事件数量钉住(self):
        """加事件不是坏事,但**必须是有意的**。这个数字变了就要改这条,
        而改它的人会被迫看一眼上面那句「这张表就是隐私政策的事实来源」。"""
        assert len(ALLOWED) == 7, (
            f"埋点事件从 7 个变成了 {len(ALLOWED)} 个 —— "
            f"确认新增的那个真的需要收,并同步隐私政策")

    def test_键数上限存在(self):
        big = {f"k{i}": i for i in range(50)}
        _, props = clean("search", big)
        assert len(props) <= MAX_PROPS_KEYS
