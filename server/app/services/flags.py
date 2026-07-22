"""平台运行时开关读取(写入在 routers/admin.py,仅管理员)。"""
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PlatformFlag


async def weather_surcharge_on(db: AsyncSession) -> bool:
    """恶劣天气配送加价是否开启(加价全归骑手)。"""
    flag = await db.get(PlatformFlag, "weather_surcharge")
    return flag is not None and flag.value == "on"


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
