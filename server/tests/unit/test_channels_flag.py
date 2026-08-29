"""首页显示哪些频道:后台配,读不到时**取保守值**。

## 这一组守什么

「这次先只上外卖和团购」这种决定会反复变。做成编译期常量意味着每变一次
发一版 App、等审核三天 —— 那不是开关该有的成本,所以做成后台配置。

而配置一旦可以读不到,就要回答「读不到时显示什么」。**答案必须是保守值**:
「读不到就显示全部」看着友好,实际是把一次网络抖动变成
「已经决定下架的业务在首页复活了」。
"""
import pytest

from app.services.flags import CHANNELS_FALLBACK, CHANNELS_FLAG

#: 客户端注册表里现有的全部频道(packages/shared/lib/src/channels.dart)
ALL_KEYS = {"food", "stay", "voucher", "errand"}


class Test兜底取保守值:
    def test_兜底不是全部频道(self):
        assert set(CHANNELS_FALLBACK) < ALL_KEYS, (
            "兜底把所有频道都放出来了 —— 那么一次网络抖动就会让"
            "已经决定下架的业务在首页复活")

    def test_兜底里的都是真频道(self):
        assert set(CHANNELS_FALLBACK) <= ALL_KEYS, (
            f"兜底里有不认识的 key:{set(CHANNELS_FALLBACK) - ALL_KEYS}")

    def test_兜底不是空的(self):
        """空首页比多显示一个频道更糟 —— 用户以为 App 坏了。"""
        assert CHANNELS_FALLBACK


class Test管理端只收已注册的频道:
    """打错一个字的后果是那个频道从首页消失,而后台显示得好好的 ——
    这种错没人查得出来,所以在入口就拦。"""

    def test_flag_键在白名单里(self):
        from app.routers.admin import _KNOWN_FLAGS
        assert CHANNELS_FLAG in _KNOWN_FLAGS

    def test_写入会校验频道名(self):
        import inspect
        import re
        from app.routers import admin
        src = inspect.getsource(admin.set_flag)
        src = re.sub(r'"""(?:.|\n)*?"""', "", src)
        assert CHANNELS_FLAG in src, (
            "set_flag 里没有针对频道开关的校验分支 —— "
            "管理员打错一个 key,那个频道就静默消失")


class Test没配和配成空是两件事:
    """从来没配过 = 用兜底;配成空串 = 一个频道都不显示。

    判据必须是「有没有这一行」,不是「值是不是空的」——
    否则管理员想全关的时候会得到兜底那两个,而他以为自己关掉了。
    """

    def test_判据是行的有无(self):
        import inspect
        import re
        from app.services import flags
        src = inspect.getsource(flags.enabled_channels)
        src = re.sub(r'"""(?:.|\n)*?"""', "", src)
        assert "is None" in src, (
            "没用「查不到这一行」当判据 —— 那么『全部关掉』这个意图"
            "会被当成『没配过』,回落到兜底")
        assert "not flag.value" not in src and "if not flag" not in src.replace(
            "if flag is None", ""), "用了值的真假当判据"
