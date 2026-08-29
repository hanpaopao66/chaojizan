"""腾讯地图逆地理:坐标 → 城市名(多城市运营隔离用)。

失败/未配置一律返回 ""(空 city 不参与隔离,人工在管理后台补填)。
结果按坐标网格缓存 24 小时(城市粒度,0.01° 网格足够)。

坐标口径:腾讯地图用 **GCJ-02**,与本系统全局口径一致 —— 直接传,不转换。
(天地图是 WGS-84,原先每次都要先转一道;换腾讯后这层没有了。)
"""
import logging

import httpx

from ..config import settings
from ..redis_client import get_redis

logger = logging.getLogger("superz.geo_city")

_API = "https://apis.map.qq.com/ws/geocoder/v1/"


async def district_of(lat: float, lng: float) -> tuple[str, str]:
    """逆地理解析 (城市, 区县),如 ("成都市", "锦江区")。失败返回 ("", "")。

    恶劣天气加价要按**区县**判(实测同一时刻成都锦江区降水 0.2mm、
    双流区 0.1mm),city 那一层太粗 —— 全城一起加价必然误伤。
    """
    city = await city_of(lat, lng)
    if not city:
        return "", ""
    # city_of 已经把整个 address_component 拿回来过一次并缓存了城市名。
    # 区县单独缓存一份:两者 TTL 一样,但 key 不同,免得为了区县再打一次接口
    cache_key = f"geo:district:{round(lat, 2)}:{round(lng, 2)}"
    redis = get_redis()
    cached = await redis.get(cache_key)
    if cached is not None:
        d = cached.decode() if isinstance(cached, bytes) else cached
        return city, d
    if not settings.tencent_map_key:
        return city, ""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(_API, params={
                "location": f"{lat},{lng}",
                "key": settings.tencent_map_key,
                "get_poi": 0,
            })
            data = resp.json()
        if data.get("status") != 0:
            return city, ""
        comp = (data.get("result") or {}).get("address_component") or {}
        district = str(comp.get("district") or "")[:20]
        if district:
            await redis.set(cache_key, district, ex=86400)
        return city, district
    except Exception:
        logger.warning("腾讯逆地理(区县)失败 (%.4f,%.4f)", lat, lng)
        return city, ""


async def city_of(lat: float, lng: float) -> str:
    """逆地理解析城市名(如「成都市」)。失败返回 ""。"""
    if not settings.tencent_map_key:
        return ""
    cache_key = f"geo:city:{round(lat, 2)}:{round(lng, 2)}"
    redis = get_redis()
    cached = await redis.get(cache_key)
    if cached is not None:
        return cached.decode() if isinstance(cached, bytes) else cached
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(_API, params={
                "location": f"{lat},{lng}",
                "key": settings.tencent_map_key,
                # get_poi=0:只要行政区划,不要周边 POI。少要一份用不上的数据,
                # 也少一分「我们到底向第三方要了什么」的解释成本
                "get_poi": 0,
            })
            data = resp.json()
        # status 非 0 是业务错误(配额用尽 / key 无权限 / 签名不对)。
        # 它和网络失败一样走「留空人工填」,但**必须把 message 记下来** ——
        # 配额用尽和 key 打错在结果上长得一模一样,不记就只能靠猜
        if data.get("status") != 0:
            logger.warning("腾讯逆地理 status=%s %s (%.4f,%.4f),city 留空",
                           data.get("status"), data.get("message"), lat, lng)
            return ""
        comp = (data.get("result") or {}).get("address_component") or {}
        # 直辖市 city 为空时用省(如「北京市」);都取不到返回空
        city = str(comp.get("city") or comp.get("province") or "")[:20]
        if city:
            await redis.set(cache_key, city, ex=86400)
        return city
    except Exception:
        logger.warning("腾讯逆地理失败 (%.4f,%.4f),city 留空人工填", lat, lng)
        return ""
