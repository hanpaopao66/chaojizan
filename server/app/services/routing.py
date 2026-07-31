"""骑行路径距离(#139):腾讯路径规划,带缓存与降级。

## 为什么不能继续用直线距离

`pricing.haversine_m` 是直线。实测成都两点:直线 1467m,骑行 1745m,**差 19%**。
隔河、跨高架、单行道只会更大。而配送费按距离算、配送费 100% 归骑手 ——
用一个系统性低估的距离去算它,「100% 归骑手」的承诺就打了折。

## 两条硬约束

**必须缓存。** 抢单池一次要算几十个单,每个都实时请求的话配额瞬间打光
(腾讯按次计费)。缓存键用起终点各自的 ~100m 网格,同一片区共用一条结果 ——
骑手在小区里走两步不该产生一次新的计费请求。

**必须降级。** 路径规划挂了 / 超时 / 配额用尽时回退直线,并**如实标明**
用的是哪种(`source`)。不标的话,骑手看到的距离时准时不准却不知道为什么,
那比一直用直线更糟。
"""
import logging

import httpx

from ..config import settings
from ..redis_client import get_redis
from .pricing import haversine_m

logger = logging.getLogger("superz.routing")

_API = "https://apis.map.qq.com/ws/direction/v1/bicycling/"

# 缓存网格:0.001° ≈ 111m。再细就没有复用率,再粗会把街对面算成同一点
_GRID = 0.001
_TTL_SECONDS = 7 * 24 * 3600      # 路网不常变,一周足够

# 直线 → 骑行的经验放大系数。**只在路径规划不可用时兜底**,
# 实测成都样本约 1.19;取 1.2 略偏保守(宁可高估一点,别让骑手吃亏)
_FALLBACK_FACTOR = 1.2


def _cell(lat: float, lng: float) -> str:
    return f"{int(lat / _GRID)}:{int(lng / _GRID)}"


def _key(a: tuple[float, float], b: tuple[float, float]) -> str:
    return f"route:bike:{_cell(*a)}>{_cell(*b)}"


async def bicycling_m(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float,
) -> tuple[float, str]:
    """骑行距离(米)与来源。

    返回 `(distance_m, source)`,source ∈ {"route", "straight"}。
    **调用方必须把 source 透传给前端** —— 距离准不准,骑手有权知道。
    """
    straight = haversine_m(from_lat, from_lng, to_lat, to_lng)
    if not settings.tencent_map_key:
        return straight * _FALLBACK_FACTOR, "straight"

    a, b = (from_lat, from_lng), (to_lat, to_lng)
    redis = get_redis()
    ck = _key(a, b)
    try:
        cached = await redis.get(ck)
        if cached is not None:
            raw = cached.decode() if isinstance(cached, bytes) else cached
            return float(raw), "route"
    except Exception:
        pass  # 缓存挂了不影响主流程

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(_API, params={
                "from": f"{from_lat},{from_lng}",
                "to": f"{to_lat},{to_lng}",
                "key": settings.tencent_map_key,
            })
            data = resp.json()
        if data.get("status") != 0:
            # 配额用尽和参数错在结果上长得一样,把 message 记下来才查得清
            logger.warning("骑行路径 status=%s %s,回退直线",
                           data.get("status"), data.get("message"))
            return straight * _FALLBACK_FACTOR, "straight"
        routes = (data.get("result") or {}).get("routes") or []
        if not routes:
            return straight * _FALLBACK_FACTOR, "straight"
        dist = float(routes[0].get("distance") or 0)
        if dist <= 0:
            return straight * _FALLBACK_FACTOR, "straight"
        try:
            await redis.set(ck, str(dist), ex=_TTL_SECONDS)
        except Exception:
            pass
        return dist, "route"
    except Exception as e:
        logger.warning("骑行路径请求失败(%s),回退直线", type(e).__name__)
        return straight * _FALLBACK_FACTOR, "straight"


async def detour_m(
    rider: tuple[float, float],
    pickup: tuple[float, float],
    drop: tuple[float, float],
    current_drop: tuple[float, float],
) -> tuple[float, str]:
    """顺路的**绕路增量**(米):接了这单要比只送手头单多跑多远。

    绕路增量 = (当前位置 → 新单取餐 → 新单送达 → 手头单送达)
             − (当前位置 → 手头单送达)

    这才是骑手真正付出的成本。原先用「两个送达点相距 < 800m」判顺路,
    实测反例:送达点相邻但取餐点在反方向 3km 的单会被判成顺路,
    实际多跑近 6 公里 —— 骑手照着这个标记接单会被坑。

    为省配额,这里全部用直线 × 经验系数估算,不发四次路径请求:
    顺路判定要的是**相对大小**(哪单绕得少),不是绝对精度。
    真正展示给骑手的到店/送程距离才走 [bicycling_m]。
    """
    def s(p: tuple[float, float], q: tuple[float, float]) -> float:
        return haversine_m(p[0], p[1], q[0], q[1]) * _FALLBACK_FACTOR

    with_new = s(rider, pickup) + s(pickup, drop) + s(drop, current_drop)
    without = s(rider, current_drop)
    return max(0.0, with_new - without), "straight"
