"""埋点收口:**白名单、逐键过滤、默认丢弃**(#311)。

## 为什么开源项目更需要这一层

`analytics.dart` 和本文件的上游都写着「只收产品行为、不收设备指纹」。
但在这一层落地之前,服务端做的是:

    db.add(AppEvent(event=e.name[:50], props=e.props))

**任何事件名、任何 props、无大小限制。** 也就是说那句原则只写在注释里,
代码里没有任何东西拦得住它。

对闭源产品这叫"靠自觉";**对开源项目这是自相矛盾的公开代码** ——
policy 写在注释里,enforcement 是空的。任何人 fork 之后加一行
`Analytics.track('device', {'imei': ...})` 就能收上来,
而声明的原则一个字都拦不住。

这个仓库解决过一模一样的形状 —— 助手令牌的能力范围
(`security.AGENT_ALLOWED`):**白名单、全匹配、默认拒绝**,
并且有测试钉着"写操作只有一条"。埋点用同一套。

## 为什么是丢弃而不是报错

老版本 App 里可能有这里没列的事件名。回 400 会让整批上报失败,
而埋点**永远不该影响用户体验**。所以未知的静默丢掉,
但把丢掉的条数回给客户端 —— 丢了多少要看得见,否则这层就成了黑洞。
"""
import logging

logger = logging.getLogger("superz.events")

#: 搜索词长度上限。搜索词是这套埋点里**最敏感的一个字段** ——
#: 用户可能搜的是地址、人名,或者暴露健康状况的词(「无糖」「孕妇餐」)。
#:
#: 留着它是有理由的:「哪些词搜不到东西」直接决定招商方向。
#: 但没有任何分析需要 40 个字的搜索词 —— 那种长度的输入多半是
#: 整段地址粘贴进来的。超长直接截断,不是拒绝整条。
SEARCH_Q_MAX = 20

#: 事件白名单:事件名 → 允许的 props 键。
#:
#: **这张表就是隐私政策里那句「我们收什么」的唯一事实来源。**
#: 加一个事件就要在这里加一行,而这一行是能被 review 的 ——
#: 这正是它存在的意义。
ALLOWED: dict[str, frozenset[str]] = {
    # 商家曝光。喂商家漏斗(曝光→进店→结算→下单),而那个漏斗是
    # 「不做竞价排名」的正面替代:不卖曝光位,但把真实漏斗给商家看
    "impression_shop": frozenset({"merchant_id"}),
    "view_menu": frozenset({"merchant_id"}),
    "checkout_view": frozenset({"merchant_id"}),
    # 搜索:hits=0 的词就是招商线索
    "search": frozenset({"q", "hits"}),
    # 分享:kind 区分邀请/店铺,不带被分享到哪个平台
    "share": frozenset({"kind"}),
    # 透明中心/信任页的浏览量。**只有事件名,没有 props** ——
    # 要回答的问题只是"有没有人看",不需要知道是谁看了哪一段
    "view_transparency": frozenset(),
    "view_trust": frozenset(),
}

#: 单条 props 的键数上限。白名单已经限死了键名,这条是防御性的
MAX_PROPS_KEYS = 8
#: 单个字符串值的长度上限(搜索词另有更严的 SEARCH_Q_MAX)
MAX_VALUE_LEN = 100


def clean(name: str, props: dict | None) -> tuple[str, dict] | None:
    """过一条埋点。返回 (事件名, 干净的 props);不在白名单就返回 None。

    纯函数 —— 单测直接喂它,不用起服务。
    """
    if name not in ALLOWED:
        return None
    allowed_keys = ALLOWED[name]
    out: dict = {}
    for k, v in (props or {}).items():
        if k not in allowed_keys:
            continue        # 白名单外的键直接丢,不报错
        if isinstance(v, str):
            limit = SEARCH_Q_MAX if (name == "search" and k == "q") \
                else MAX_VALUE_LEN
            v = v[:limit]
        elif isinstance(v, bool):
            pass
        elif isinstance(v, (int, float)):
            pass
        else:
            # 嵌套对象/数组一律不收:它们是"以后想放什么都行"的口子,
            # 而白名单的意义就是不留这种口子
            continue
        out[k] = v
        if len(out) >= MAX_PROPS_KEYS:
            break
    return name, out
