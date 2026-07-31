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
