"""恶劣天气加价的**区县级审核**(自动判定提请 → 人工点头 → 限时生效)。

## 为什么不让自动判定直接生效

加价这笔钱是**用户实付的**。自动判定误报(气象格点漂移、一阵过云雨、
传感器异常)的代价是用户凭空多花几块钱,而他无从申诉 ——
他看不到那一刻的气象数据,也不知道该找谁。

所以判定只负责提请,生效要人点头。代价是响应变慢,这是有意的取舍:
**宁可漏加,不可错收。** 漏加时骑手可以由平台事后补偿,
错收则是从用户口袋里拿了不该拿的钱。

## 三条时间线不能混

- `weather.current()` 的缓存(30 分钟):省 API 配额;
- 审核单的**冷静期**:同一区县刚被驳回,别再反复提请刷屏;
- 审核通过的**有效期**:天气会停,批一次不能收一辈子。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import WeatherAlert, WeatherAlertStatus

logger = logging.getLogger("superz.weather_zone")

#: 审核通过后加价生效多久。2 小时:一场雨的量级。
#: 更长会变成"批一次收一辈子",更短则管理员刚点完就要再点一次
APPROVED_HOURS = 2

#: 被驳回后多久不再对同一区县提请。管理员判了误报,
#: 而天气缓存 30 分钟内不变 —— 不设冷静期就会立刻又提请一模一样的单
REJECT_COOLDOWN_HOURS = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """库里取出来的时间可能是 naive(取决于驱动),统一成 aware 再比较。"""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def active_alert(db: AsyncSession, city: str,
                       district: str) -> WeatherAlert | None:
    """该区县当前**已生效且未过期**的加价单。没有返回 None。"""
    if not city:
        return None
    row = await db.scalar(
        select(WeatherAlert)
        .where(WeatherAlert.city == city,
               WeatherAlert.district == district,
               WeatherAlert.status == WeatherAlertStatus.approved)
        .order_by(WeatherAlert.id.desc())
        .limit(1))
    if row is None:
        return None
    exp = _aware(row.expires_at)
    if exp is not None and exp <= _now():
        # 到期即失效。顺手落库,省得每次算价都要判一遍时间
        row.status = WeatherAlertStatus.expired
        return None
    return row


async def _recent_blocking(db: AsyncSession, city: str,
                           district: str) -> bool:
    """这个区县现在该不该跳过提请:已有待审单,或刚被驳回还在冷静期。"""
    row = await db.scalar(
        select(WeatherAlert)
        .where(WeatherAlert.city == city,
               WeatherAlert.district == district,
               WeatherAlert.status.in_([WeatherAlertStatus.pending,
                                        WeatherAlertStatus.rejected]))
        .order_by(WeatherAlert.id.desc())
        .limit(1))
    if row is None:
        return False
    if row.status == WeatherAlertStatus.pending:
        return True     # 已经提请过了,等人审就是
    decided = _aware(row.decided_at) or _aware(row.created_at)
    if decided is None:
        return False
    return decided + timedelta(hours=REJECT_COOLDOWN_HOURS) > _now()


async def request_if_severe(db: AsyncSession, lat: float, lng: float) -> bool:
    """按坐标看天气;恶劣就为该区县提请一单(已提请/冷静期内则跳过)。

    返回是否**新建**了审核单。这个函数只写 pending,
    **绝不自己置 approved** —— 那就绕过了整个设计。
    """
    from . import weather
    from .geo_city import district_of

    w = await weather.current(lat, lng)
    if not (w and w.get("severe")):
        return False
    city, district = await district_of(lat, lng)
    if not city:
        # 解析不出区县就不提请:审核单落在一个说不清是哪儿的区域上,
        # 管理员没法判,批下去也不知道对谁生效
        logger.warning("恶劣天气但解析不出区县 (%.4f,%.4f),不提请", lat, lng)
        return False
    if await active_alert(db, city, district) is not None:
        return False
    if await _recent_blocking(db, city, district):
        return False
    db.add(WeatherAlert(
        city=city, district=district,
        status=WeatherAlertStatus.pending,
        weather_code=int(w.get("weather_code") or 0),
        precip_mm=float(w.get("precip_mm") or 0),
        wind_kmh=float(w.get("wind_kmh") or 0),
        lat=lat, lng=lng,
    ))
    logger.info("恶劣天气提请审核:%s%s 码=%s 降水=%.1fmm 风=%.1fkm/h",
                city, district, w.get("weather_code"),
                w.get("precip_mm") or 0, w.get("wind_kmh") or 0)
    return True


async def expire_due(db: AsyncSession) -> int:
    """把到期的已生效单置为 expired(auto_flow 定时调)。返回条数。"""
    rows = (await db.scalars(
        select(WeatherAlert).where(
            WeatherAlert.status == WeatherAlertStatus.approved,
            WeatherAlert.expires_at.is_not(None),
            WeatherAlert.expires_at <= _now()))).all()
    for r in rows:
        r.status = WeatherAlertStatus.expired
    return len(rows)


def public_spec() -> dict:
    """审核流程的公开说明。天数从上面的常量读,不另抄一份。"""
    return {
        "flow": [
            "系统按坐标查实时天气,命中阈值(见 /transparency/dispatch)"
            "则为**该区县**提请一张加价审核单",
            "平台人工核对气象快照后决定批或驳 —— "
            "**自动判定不能直接加价**",
            f"批准后该区县加价生效 {APPROVED_HOURS} 小时,到期自动失效;"
            "天气仍恶劣会重新提请",
        ],
        "why_manual": "加价是用户实付的钱。自动判定误报(格点漂移、"
                      "一阵过云雨)会让用户凭空多花钱,而他看不到那一刻的"
                      "气象数据、也不知道找谁申诉。宁可漏加,不可错收 —— "
                      "漏加平台可以事后补给骑手,错收是从用户口袋里"
                      "拿了不该拿的钱。",
        "granularity": "区县级。实测同一时刻成都锦江区降水 0.2mm、"
                       "双流区 0.1mm —— 按城市判必然误伤。",
        "cooldown_hours": REJECT_COOLDOWN_HOURS,
        "approved_hours": APPROVED_HOURS,
    }
