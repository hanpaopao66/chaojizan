"""平台运行时开关读取(写入在 routers/admin.py,仅管理员)。"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PlatformFlag

logger = logging.getLogger("superz.flags")


async def weather_surcharge_on(
    db: AsyncSession,
    lat: float | None = None,
    lng: float | None = None,
) -> bool:
    """恶劣天气配送加价是否开启(加价全归骑手)。

    ## 从「手动全局开关」改为「按坐标自动判定」(#146)

    原先是管理员手动开、而且是**全局**的 —— 成都下暴雨,北京的骑手也拿加价;
    北京下雪没人开开关,骑手就白挨冻。实测同一时刻成都锦江区降水 0.2mm、
    双流区 0.1mm、北京朝阳 0.0mm,**区县级差异真实存在**。

    ## 再从「判定即生效」改为「判定后提请审核」(#307)

    自动判定**不再直接加价**,只负责给该区县提请一张审核单
    (services/weather_zone.py),人点头之后才生效、且限时。

    为什么:这笔钱是用户实付的。误报(气象格点漂移、一阵过云雨、
    传感器异常)的代价是用户凭空多花钱,而他看不到那一刻的气象数据、
    也不知道找谁申诉。**宁可漏加,不可错收** —— 漏加平台可以事后
    补给骑手,错收是从用户口袋里拿了不该拿的钱。

    管理员保留**强制开**的能力 —— 自动判定漏了也能救。
    但**不保留强制关**:天气恶劣却关掉加价,没有正当理由。
    """
    flag = await db.get(PlatformFlag, "weather_surcharge")
    forced_on = flag is not None and flag.value == "on"
    if forced_on:
        return True
    if lat is None or lng is None:
        return False

    from .geo_city import district_of
    from .weather_zone import active_alert, request_if_severe

    city, district = await district_of(lat, lng)
    if city and await active_alert(db, city, district) is not None:
        return True
    # 没有生效单:顺手看一眼天气,该提请就提请。
    # **提请不影响本单** —— 这一单不加价,审批通过后的单才加。
    # 放在这里而不是定时任务:有人下单的区域才值得查天气,
    # 没有单的区县查了也没用,还白烧配额
    try:
        await request_if_severe(db, lat, lng)
    except Exception:
        # 提请失败绝不能挡住下单 —— 它只是一条运营线索
        logger.warning("恶劣天气提请失败 (%.4f,%.4f)", lat, lng, exc_info=True)
    return False


async def night_curfew_window(db: AsyncSession) -> str | None:
    """平台深夜保护窗:开启时返回 "HH:MM-HH:MM" 时段,关闭返回 None。

    窗口内全平台停止接新单(已有订单正常履约),为夜间运力与安全兜底。
    默认关;时段没配时用 01:00-06:00。
    """
    flag = await db.get(PlatformFlag, "night_curfew")
    if flag is None or flag.value != "on":
        return None
    hours = await db.get(PlatformFlag, "night_curfew_hours")
    return hours.value if hours is not None and hours.value else "01:00-06:00"


async def wait_comp_on(db: AsyncSession) -> bool:
    """等餐补偿(平台承担)是否开启。**默认关 —— 平台现阶段没有这笔预算。**

    机制、计算、审计口径全部保留(pricing.wait_compensation_cents /
    settlement / e2e_wait_comp_audit),等餐时长照常落库(骑手申诉的
    证据链不受影响)—— 关掉的只是「折成钱」这一步。
    以后有预算了,后台把开关拨开即恢复,不用发版。

    对外承诺的文案(派单公示、商家承诺页)都读这个开关:
    **关着的时候不许说「有补偿」** —— 公开的数字对不上,比不公开更坏。
    """
    flag = await db.get(PlatformFlag, "wait_comp")
    return flag is not None and flag.value == "on"


async def weather_shutdown_on(db: AsyncSession) -> bool:
    """极端天气临时停运:开启时全平台停止接新单(已有订单尽力履约),
    无人接单兜底的取消线同步缩短——别让用户在暴雨里干等。"""
    flag = await db.get(PlatformFlag, "weather_shutdown")
    return flag is not None and flag.value == "on"


async def alcohol_curfew_window(db: AsyncSession) -> str | None:
    """酒类禁售时段:开启时返回 "HH:MM-HH:MM",关闭返回 None。

    默认关;时段没配时用 22:00-08:00(参照部分地区夜间禁售惯例)。
    窗口内含酒订单拒单,非酒商品不受影响。
    """
    flag = await db.get(PlatformFlag, "alcohol_curfew")
    if flag is None or flag.value != "on":
        return None
    hours = await db.get(PlatformFlag, "alcohol_curfew_hours")
    return hours.value if hours is not None and hours.value else "22:00-08:00"


def in_hhmm_range(window: str, hhmm: str) -> bool:
    """"01:00-06:00" 是否覆盖 hhmm;支持跨天(如 23:00-05:00)。"""
    try:
        start, end = window.split("-")
    except ValueError:
        return False
    if start <= end:
        return start <= hhmm < end
    return hhmm >= start or hhmm < end


async def open_cities(db: AsyncSession) -> list[str] | None:
    """开城清单(逗号分隔城市名)。未配置/留空返回 None = 不限制。"""
    flag = await db.get(PlatformFlag, "open_cities")
    if flag is None or not flag.value.strip():
        return None
    return [c.strip() for c in flag.value.split(",") if c.strip()]


async def marketing_on(db: AsyncSession) -> bool:
    """营销总开关(默认关):新客券/邀请有礼/生日券/复购提醒/上新推送
    全部受控。没有补贴预算时保持关闭,代码与后台配置原样保留,
    开预算后 POST /admin/flags/marketing on 即可整体启用。"""
    flag = await db.get(PlatformFlag, "marketing")
    return flag is not None and flag.value == "on"


async def health_cert_cities(db: AsyncSession) -> list[str]:
    """要求骑手持健康证的城市清单(逗号分隔)。**默认空 = 都不要求。**

    国家层面并不要求送餐员持健康证:《网络餐饮服务食品安全监督管理办法》
    要求餐食封装、避免送餐人员直接接触食品,送餐员因此不属于
    「直接接触入口食品的人员」,不在预防性健康检查范围内。
    **四川已明确取消。**

    但杭州等地有地方性的网络餐饮配送监管办法,可能另有要求 ——
    所以不能一刀切说"全国都不要",做成城市级清单:
    **默认不要求,只有明确查证过本地有规定的城市才加进来。**

    加城市的判据是"查到了本地的规章条文",不是"别的平台都要"。
    跟着行业惯性加门槛,就是我们原来那个毛病。
    """
    flag = await db.get(PlatformFlag, "health_cert_cities")
    if flag is None or not flag.value.strip():
        return []
    return [c.strip() for c in flag.value.split(",") if c.strip()]


#: 频道开关的 flag 键。值是逗号分隔的 key 列表,如 "food,voucher"。
CHANNELS_FLAG = "channels_enabled"

#: 配不出来时的兜底。**保守取值** —— 读不到配置时宁可少显示,
#: 不能把已经决定隐藏的业务露出来。
#:
#: 「读不到就显示全部」看着更友好,实际是把故障变成事故:
#: 网络抖一下,下架的业务就在首页复活了。
CHANNELS_FALLBACK = ("food", "voucher")


async def enabled_channels(db: AsyncSession) -> list[str]:
    """哪些频道对用户可见。管理员在后台改,**立即生效,不用发版**。

    ## 为什么不做成编译期常量

    项目里本来有一个 `feature_flags.dart` 的编译期开关(应用商店审核用)。
    但「这次先只上外卖和团购」这种决定会反复变 —— 每变一次发一版 App,
    等审核三天,这不是开关该有的成本。

    ## 空值的含义

    从来没配过(查不到这一行)= 用兜底;配成空串 = **一个频道都不显示**。
    这两件事不一样,所以判据是「有没有这一行」,不是「值是不是空的」——
    否则管理员想全关的时候会得到兜底那两个,而他以为自己关掉了。
    """
    flag = await db.get(PlatformFlag, CHANNELS_FLAG)
    if flag is None:
        return list(CHANNELS_FALLBACK)
    return [k.strip() for k in flag.value.split(",") if k.strip()]
