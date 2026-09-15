"""可下发文案的登记表(#122):后台「文案」页列的就是这些 —— 每个位置都能**改字**,能藏的还能**显示 / 隐藏**。

每条写清楚**出现在哪**、客户端自带的**默认值**、**最多几个字**、**能不能藏**(不能藏的写明为什么)。
客户端每个 `RemoteCopy.text(key, 默认值)` / `RemoteCopy.shown(key)` 的调用点都要在这里登记:没登记的 key 后台改不了
(PUT 回 422)—— 免得运营写出一个客户端根本不读的 key,以为改了其实没生效。
默认值要和客户端里写的一字不差,单测(tests/unit/test_copy_registry.py)对着 Dart 源码逐条核。

承诺类(pledge.*)不在这里:它们由服务端按真实费率算(platform._pledge_copy),后台只能看、不能改。

改完什么时候生效:客户端启动时拉 /config,拉到就刷新界面(底部菜单当场变);没联网就用上次缓存的,再没有就用默认值。
**已经装在手机上、还不认识某个 key 的老版本不受影响** —— 它们照旧显示写死在老版本里的字。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CopyKey:
    group: str          # 后台页上的分组
    where: str          # 出现在哪(给运营看的)
    default: str        # 客户端自带的默认值(和 Dart 源码一字不差)
    max_len: int = 200  # 最多几个字
    hideable: bool = True
    #: 不能在这一页藏的原因,或者「显示 / 隐藏在别处管」的指路(比如首页业务在「平台开关」)
    hide_note: str = ""


#: 底部菜单一格放得下的字数:再长就挤掉图标下面的字、或者折行
NAV_MAX = 4
#: 首页业务入口卡的标题(入口卡上只有字块和标题,副标题没有地方显示,所以不登记)
CHANNEL_NAME_MAX = 6

_NAV_KEEP = "藏了就进不去设置、登录不了,这一格不许藏"
_CHANNEL_HIDE = "显示 / 隐藏在「平台开关 → 首页显示哪些业务」里改(那边会说清藏了之后用户进不去)"

COPY_KEYS: dict[str, CopyKey] = {
    "nav.home": CopyKey("底部菜单", "用户端底部菜单 · 第一格(首页)", "首页", NAV_MAX, False, _NAV_KEEP),
    "nav.video": CopyKey("底部菜单", "用户端底部菜单 · 视频;藏了之后视频页就没有入口", "视频", NAV_MAX),
    "nav.chat": CopyKey("底部菜单", "用户端底部菜单 · 聊天。聊天页顶上的标题、「聊天设置」「聊天与隐私」的页名、"
                        "几处操作说明跟着它变;用户协议和隐私政策里写的是「聊天」,不跟着变,要改得发条款新版。"
                        "藏了之后只能从通知点进会话",
                        "聊天", NAV_MAX),
    "nav.me": CopyKey("底部菜单", "用户端底部菜单 · 最后一格(我的)", "我的", NAV_MAX, False, _NAV_KEEP),

    "channel.food.name": CopyKey("首页业务", "首页业务入口 · 外卖的标题", "点外卖", CHANNEL_NAME_MAX, False, _CHANNEL_HIDE),
    "channel.retail.name": CopyKey("首页业务", "首页业务入口 · 超市水果的标题", "买菜买水果", CHANNEL_NAME_MAX, False,
                                   _CHANNEL_HIDE),
    "channel.stay.name": CopyKey("首页业务", "首页业务入口 · 住宿的标题", "住宿", CHANNEL_NAME_MAX, False, _CHANNEL_HIDE),
    "channel.voucher.name": CopyKey("首页业务", "首页业务入口 · 团购的标题", "超值团购", CHANNEL_NAME_MAX, False,
                                    _CHANNEL_HIDE),
    "channel.errand.name": CopyKey("首页业务", "首页业务入口 · 跑腿的标题", "帮我送", CHANNEL_NAME_MAX, False,
                                   _CHANNEL_HIDE),

    "home.category_vacancy": CopyKey(
        "说明文字", "用户端首页 · 某个品类还没有商家时的空状态",
        "该品类商家入驻中\n总负担 5% 封顶 · 入驻免费 · 没有竞价排名", 200, False,
        "空状态总得有一句话;不想要这段就改成别的字"),
    "about.tagline": CopyKey(
        "说明文字", "用户端「设置 → 关于我们」· 顶上的一句话介绍",
        "低抽成、账目透明的本地生活服务平台\n外卖 5% 封顶 · 配送费 100% 归骑手 · 每一单资金流向可查"),
}
