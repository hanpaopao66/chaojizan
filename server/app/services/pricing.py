"""配送费计价:商家→收货地直线距离,阶梯加价 + 夜间/恶劣天气加价。

配送费的每一分(含加价)都归骑手,平台不从中抽取 —— services/audit.py 恒等式校验。
之后接高德路径规划 API 可换成骑行距离,这里的函数签名不变。
"""
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import settings

_EARTH_RADIUS_M = 6371000.0
BEIJING = ZoneInfo("Asia/Shanghai")


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点直线距离(米)。"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def in_delivery_range(distance_m: float) -> bool:
    return distance_m <= settings.delivery_max_km * 1000


def is_night(now: datetime | None = None) -> bool:
    hour = (now or datetime.now(BEIJING)).astimezone(BEIJING).hour
    return hour >= settings.delivery_night_start_hour or hour < settings.delivery_night_end_hour


def delivery_fee_parts(
    distance_m: float,
    *,
    weather_on: bool = False,
    when: datetime | None = None,
) -> dict[str, int]:
    """配送费组成(分)。键固定:base/night/weather,前端与测试按键取用。"""
    extra_km = max(0.0, distance_m / 1000 - settings.delivery_base_km)
    base = settings.delivery_base_fee_cents + math.ceil(extra_km) * settings.delivery_per_km_cents
    return {
        "base": min(base, settings.delivery_max_fee_cents),
        "night": settings.delivery_night_surcharge_cents if is_night(when) else 0,
        "weather": settings.delivery_weather_surcharge_cents if weather_on else 0,
    }


def delivery_fee_cents(
    distance_m: float,
    *,
    weather_on: bool = False,
    when: datetime | None = None,
) -> int:
    return sum(delivery_fee_parts(distance_m, weather_on=weather_on, when=when).values())
