"""天气(#146):Open-Meteo 按坐标查,自动判定恶劣天气。

## 为什么换掉手动开关

原先恶劣天气加价是管理员**手动**开关,而且是**全局**的 ——
成都下暴雨,北京的骑手也拿加价;北京下雪没人开开关,骑手就白挨冻。

## 为什么选 Open-Meteo

- **无需 key**,官方声明免费商用 —— 不必再申请任何资质;
- **按坐标查**,天然到区县甚至街道级(本系统每个商家都有精确坐标);
- 返回标准 **WMO 天气码**,可编程判定,不是一句中文描述。

实测同一时刻:成都锦江区 降水 0.2mm / 风 8.8km/h / 码 53;
成都双流区 0.1mm / 4.6km/h / 码 51;北京朝阳 0.0mm / 码 3 ——
**区县级差异真实存在**,全局开关必然误伤。

⚠️ 实测过:连续快请求会被限流(SSL EOF)。所以必须缓存 + 网格聚合。

## 判定阈值是公开的

阈值就是下面这几个常量,/transparency 读同一份 —— 与派单算法同一口径:
公开的必须是真在跑的那个,不是另抄一份说明。
"""
import logging

import httpx

from ..redis_client import get_redis

logger = logging.getLogger("superz.weather")

_API = "https://api.open-meteo.com/v1/forecast"

# 缓存网格:0.1° ≈ 11km。天气不是按米变的,网格粗一点没关系,配额省很多。
# 比路径规划的 0.001° 粗 100 倍,是有意的 —— 两者变化的空间尺度差着量级
_GRID = 0.1
_TTL_SECONDS = 1800          # 30 分钟:天气变化没那么快,再短就是白烧配额

# ---------------------------------------------------------------------------
# 恶劣天气判定阈值。**这几个数是公开的**(见 /transparency/dispatch),
# 每一条都要讲得出道理 —— 讲不出道理的阈值不配用来决定骑手的收入。
# ---------------------------------------------------------------------------

#: 小时降水量(mm)。0.5mm 是"明显在下、地面湿滑"的量级;
#: 再低就是毛毛雨,骑手不至于因此更危险,加价反而稀释了真正恶劣时的信号
RAIN_MM = 0.5

#: 风速(km/h)。30km/h ≈ 5 级风,电动车侧风已经明显影响操控
WIND_KMH = 30.0

#: WMO 天气码里判定为恶劣的集合。
#: 取值依据 WMO 4677 标准码表:
#:   56/57 冻雨、65/67 大雨、71-77 雪、82/86 强阵雨/阵雪、95-99 雷暴
#: **不含 51/53(毛毛雨)与 61/63(小到中雨)** —— 那些靠降水量阈值判,
#: 免得把"飘点雨"也算成恶劣,让加价变成常态而失去意义
SEVERE_CODES = frozenset({
    56, 57,              # 冻雨:路面结冰,最危险的一类
    65, 67,              # 大雨 / 大冻雨
    71, 73, 75, 77,      # 雪
    82, 86,              # 强阵雨 / 强阵雪
    95, 96, 99,          # 雷暴(含冰雹)
})


def _cell(lat: float, lng: float) -> str:
    return f"{round(lat / _GRID)}:{round(lng / _GRID)}"


def is_severe(weather_code: int, precip_mm: float, wind_kmh: float) -> bool:
    """是否恶劣天气。三个判据取**或**:任一条命中就算。

    取或不取与:大雨、大风、下雪各自都足以让骑行变危险,
    要求同时满足等于永远不触发。
    """
    return (weather_code in SEVERE_CODES
            or precip_mm >= RAIN_MM
            or wind_kmh >= WIND_KMH)


async def current(lat: float, lng: float) -> dict | None:
    """当前天气。查不到返回 None —— **调用方必须把 None 当作"不改变现状"**,
    而不是当作"天气很好"。正在下雨时因为查不到而关掉加价,是最坏的结果。
    """
    redis = get_redis()
    ck = f"weather:{_cell(lat, lng)}"
    try:
        cached = await redis.get(ck)
        if cached is not None:
            import json
            raw = cached.decode() if isinstance(cached, bytes) else cached
            return json.loads(raw)
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(_API, params={
                "latitude": lat,
                "longitude": lng,
                "current": "temperature_2m,precipitation,weather_code,"
                           "wind_speed_10m",
                "timezone": "Asia/Shanghai",
            })
            data = resp.json()
        cur = data.get("current") or {}
        if "weather_code" not in cur:
            return None
        out = {
            "temp_c": cur.get("temperature_2m"),
            "precip_mm": float(cur.get("precipitation") or 0),
            "weather_code": int(cur.get("weather_code") or 0),
            "wind_kmh": float(cur.get("wind_speed_10m") or 0),
            "at": cur.get("time"),
        }
        out["severe"] = is_severe(
            out["weather_code"], out["precip_mm"], out["wind_kmh"])
        try:
            import json
            await redis.set(ck, json.dumps(out), ex=_TTL_SECONDS)
        except Exception:
            pass
        return out
    except Exception as e:
        # 限流(实测过 SSL EOF)、超时、服务挂 —— 一律返回 None 让调用方维持现状
        logger.warning("天气查询失败(%s) @%.3f,%.3f", type(e).__name__, lat, lng)
        return None


def public_spec() -> dict:
    """恶劣天气判定规则的公开说明。阈值从上面的常量读,不另抄一份。"""
    return {
        "source": "Open-Meteo(无需 key,按坐标查,官方声明免费商用)",
        "granularity": "按坐标查询,精度到区县;缓存网格约 11 公里 / 30 分钟",
        "rule": "以下三条任一命中即判为恶劣天气(取或不取与:"
                "大雨、大风、下雪各自都足以让骑行变危险,要求同时满足等于永远不触发)",
        "thresholds": [
            {"key": "rain", "name": "小时降水量",
             "value": f"≥ {RAIN_MM} 毫米",
             "why": "0.5 毫米是「明显在下、地面湿滑」的量级。再低就是毛毛雨,"
                    "骑手不至于因此更危险 —— 而把飘点雨也算成恶劣,"
                    "会让加价变成常态,真正恶劣时反而失去信号。"},
            {"key": "wind", "name": "风速",
             "value": f"≥ {WIND_KMH} 公里/小时",
             "why": "约 5 级风,电动车侧风已经明显影响操控。"},
            {"key": "code", "name": "天气现象",
             "value": "冻雨、大雨、雪、强阵雨、雷暴(WMO 标准码 "
                      + "/".join(str(c) for c in sorted(SEVERE_CODES)) + ")",
             "why": "依据 WMO 4677 标准码表。**不含毛毛雨与小到中雨** —— "
                    "那些交给降水量阈值判,避免重复触发。"},
        ],
        "on_severe": [
            "配送费加价,加价 100% 归骑手,平台分文不取",
            "**同时放宽预计送达时间** —— 只加价不放宽时限,"
            "等于用钱买骑手冒险",
        ],
        "degradation": "天气服务查不到时**维持当前状态不变**,"
                       "不会因为查不到就关掉加价 —— 正在下雨时把加价关了是最坏的结果",
    }
