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


def door_fee_cents(floor: int | None, has_elevator: bool | None,
                   to_door: bool = True) -> int:
    """上门难度费(分)。**顾客付,全额归骑手。**

    ## 为什么只算无电梯

    等电梯的时间已经在 ETA 里补过(labor_guard.floor_minutes),再收一笔
    就是同一件事收两次钱。真正吃力气的是**背着餐爬楼梯**,
    而骑手的原话是:爬 1–4 楼勉强能被派费覆盖,**从 5 楼开始就不合理了**。

    ## 为什么按声明的楼层算,不按实际爬了几层

    事后按实际结算需要骑手举证 —— 那又回到"让在马路上跑车的人
    收集材料"的坑里。按下单时声明的楼层计费;声明错了(填 1 楼实际 6 楼)
    走骑手的异常上报通道,那一单**送到楼下即算完成**。

    ## 顾客选了「送到楼下」就不收

    不收这笔钱,骑手也没有义务上楼。这一条必须同时写进骑手端和规则页,
    否则这笔费用就是白收的。
    """
    if not to_door or has_elevator or not floor:
        return 0
    over = floor - settings.door_fee_free_floor
    if over <= 0:
        return 0
    return min(over * settings.door_fee_per_floor_cents,
               settings.door_fee_max_cents)


def delivery_fee_parts(
    distance_m: float,
    *,
    weather_on: bool = False,
    when: datetime | None = None,
    floor: int | None = None,
    has_elevator: bool | None = None,
    to_door: bool = True,
) -> dict[str, int]:
    """配送费组成(分)。键固定:base/night/weather/door,前端与测试按键取用。

    **这份拆分要一路带到订单里**(Order.fee_parts),不是只在预览时露一次。
    顾客要知道 8 块钱花在哪、骑手要在**接单前**就知道这单为什么值 8 块。
    """
    extra_km = max(0.0, distance_m / 1000 - settings.delivery_base_km)
    base = settings.delivery_base_fee_cents + math.ceil(extra_km) * settings.delivery_per_km_cents
    return {
        "base": min(base, settings.delivery_max_fee_cents),
        "night": settings.delivery_night_surcharge_cents if is_night(when) else 0,
        "weather": settings.delivery_weather_surcharge_cents if weather_on else 0,
        # 上门难度:无电梯高楼层。有电梯不收(等电梯已在 ETA 里补过)
        "door": door_fee_cents(floor, has_elevator, to_door),
    }


def wait_compensation_cents(wait_minutes: float) -> int:
    """等餐超时补偿(分)。**平台承担,不转嫁商家或用户。**

    骑手到店后餐没好,那段时间他没有任何收入 —— 而这不是他的问题。
    原先这段时间是完全白等的。

    为什么由平台承担:转嫁给商家会让商家宁可晚点按「出餐」(数据失真),
    转嫁给用户则是让用户为商家的慢买单。平台承担的同时,
    出餐时长统计(services/prep_time.py)会把慢出餐商家显出来 ——
    治理靠数据,不靠罚钱。

    注:这属于**履约成本**,不是营销补贴 —— 与"平台不做补贴烧钱"不冲突。
    """
    from ..config import settings

    free = settings.delivery_wait_free_minutes
    if wait_minutes <= free:
        return 0
    extra = math.ceil(wait_minutes - free)
    return min(extra * settings.delivery_wait_per_min_cents,
               settings.delivery_wait_max_cents)


def delivery_fee_cents(
    distance_m: float,
    *,
    weather_on: bool = False,
    when: datetime | None = None,
    wait_minutes: float = 0.0,
) -> int:
    total = sum(delivery_fee_parts(
        distance_m, weather_on=weather_on, when=when).values())
    return total + wait_compensation_cents(wait_minutes)
