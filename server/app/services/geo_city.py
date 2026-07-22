"""天地图逆地理:坐标 → 城市名(多城市运营隔离用)。

失败/未配置一律返回 ""(空 city 不参与隔离,人工在管理后台补填)。
结果按坐标网格缓存 24 小时(城市粒度,0.01° 网格足够)。
"""
import json
import logging

import httpx

from ..config import settings
from ..redis_client import get_redis

logger = logging.getLogger("superz.geo_city")

_API = "https://api.tianditu.gov.cn/geocoder"


async def city_of(lat: float, lng: float) -> str:
    """逆地理解析城市名(如「成都市」)。失败返回 ""。"""
    if not settings.tianditu_server_key:
        return ""
    cache_key = f"geo:city:{round(lat, 2)}:{round(lng, 2)}"
    redis = get_redis()
    cached = await redis.get(cache_key)
    if cached is not None:
        return cached.decode() if isinstance(cached, bytes) else cached
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(_API, params={
                "postStr": json.dumps(
                    {"lon": lng, "lat": lat, "ver": 1}),
                "type": "geocode",
                "tk": settings.tianditu_server_key,
            })
            data = resp.json()
        comp = (data.get("result") or {}).get("addressComponent") or {}
        # 直辖市 city 为空时用省(如「北京市」);都取不到返回空
        city = str(comp.get("city") or comp.get("province") or "")[:20]
        if city:
            await redis.set(cache_key, city, ex=86400)
        return city
    except Exception:
        logger.warning("天地图逆地理失败 (%.4f,%.4f),city 留空人工填",
                       lat, lng)
        return ""
