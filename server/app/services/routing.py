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
import asyncio
import logging

import httpx

from ..config import settings
from ..redis_client import get_redis
from .pricing import haversine_m

logger = logging.getLogger("superz.routing")

_API = "https://apis.map.qq.com/ws/direction/v1/bicycling/"

#: 出行方式 → 腾讯路径规划接口。
#:
#: 加步行和驾车不是为了"多用几个接口",是因为**同样 800 米,
#: 骑过去和走过去是两种体感**:自取的人是走过去的,给他骑行距离
#: 等于让他按错误的前提做决定(#298)。
_MODE_API = {
    "bike": _API,
    "walk": "https://apis.map.qq.com/ws/direction/v1/walking/",
    "drive": "https://apis.map.qq.com/ws/direction/v1/driving/",
}

#: 直线 → 各方式实际路径的经验放大系数(只在路径规划不可用时兜底)。
#:
#: 步行比骑行小:人能穿小区、走天桥、逆行人行道;
#: 驾车比骑行大:单行道、禁左、高架要绕上绕下。
_MODE_FALLBACK = {"bike": 1.2, "walk": 1.15, "drive": 1.35}

#: 距离矩阵接口的 mode 取值(和路径规划接口不同名,别混用)
_MODE_MATRIX = {"bike": "bicycling", "walk": "walking", "drive": "driving"}

#: 各方式的合理速度区间(km/h),用来体检接口回来的 duration。
#:
#: ⚠️ 这道体检是有来历的:腾讯**各接口的 duration 单位不统一** ——
#: 路径规划是分钟,距离矩阵是秒(#289 踩过一次)。单位错了不会报错,
#: 只会把「走 12 分钟」显示成「走 720 分钟」或者「走 0.2 分钟」。
#: 算出来的速度离谱就当没拿到,**不把一个自己都不信的数显示给用户**。
_MODE_SPEED_RANGE = {"bike": (5.0, 35.0), "walk": (1.5, 10.0),
                     "drive": (5.0, 130.0)}

# 缓存网格:0.001° ≈ 111m。再细就没有复用率,再粗会把街对面算成同一点
_GRID = 0.001
_TTL_SECONDS = 7 * 24 * 3600      # 路网不常变,一周足够

#: 规划不出路线时的**负缓存** TTL(秒)。
#:
#: 腾讯对某些点对会返回 status=384「提供的起终点无法规划出骑行线路」——
#: 城中村里的坐标、刚建好还没进路网的楼、以及演示数据里挨得极近的两点。
#: 这类点对**不会因为再问一次就变得能规划**。
#:
#: 而原来只有成功那条写缓存,五条兜底路径一条都不写:抢单池里一个这样的
#: 点对,骑手每 5 秒刷一次就重打一次腾讯接口。实测 20 单的池子里
#: 一次刷新要 6.1 秒 —— **上一次还没回来,下一次已经发出去了**,
#: 而且每一次都在烧配额。
#:
#: 比正缓存(7 天)短得多:路网确实会更新,新修的路该有机会被重新发现。
#: 半小时是个折中:够挡住高频刷新,又不会让一条新路等一周。
_NEG_TTL_SECONDS = 1800

# 直线 → 骑行的经验放大系数。**只在路径规划不可用时兜底**,
# 实测成都样本约 1.19;取 1.2 略偏保守(宁可高估一点,别让骑手吃亏)
_FALLBACK_FACTOR = 1.2


def _cell(lat: float, lng: float) -> str:
    return f"{int(lat / _GRID)}:{int(lng / _GRID)}"


def _key(a: tuple[float, float], b: tuple[float, float],
         mode: str = "bike") -> str:
    """缓存键。**默认 bike 不能改** —— 距离矩阵(#289)写进去的是这个键,
    单点调用要读得到它写的,前缀一变两套缓存就各热各的,等于白做。"""
    return f"route:{mode}:{_cell(*a)}>{_cell(*b)}"


def parse_route_cache(raw: str) -> tuple[float, float | None]:
    """读缓存里的 "距离|时长"。

    **抽成函数不是为了复用,是为了能被测试直接调。** 这段逻辑写在
    `bicycling_route` 里的时候,单测只能复刻一份来测 —— 那测的是副本,
    真代码改了测试照样绿。

    格式两代并存:
    - 新:`"1861.0|9.0"`(时长可能是空串,腾讯偶尔不给 duration);
    - 旧:`"1861.0"`。TTL 一周,**升级后那一周缓存里全是旧值** ——
      读不了就一路回退直线兜底,而直线比路网短,表现出来是
      「ETA 莫名其妙紧了一周」。

    解析不了就抛,由调用方的 try/except 兜住并走正常请求。
    """
    if "|" in raw:
        d_raw, t_raw = raw.split("|", 1)
        return float(d_raw), (float(t_raw) if t_raw else None)
    return float(raw), None


def dump_route_cache(distance_m: float, duration_min: float | None) -> str:
    """写缓存的格式。和 [parse_route_cache] 成对,改一个必须改另一个。"""
    return f"{distance_m}|{'' if duration_min is None else duration_min}"


async def bicycling_m(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float,
) -> tuple[float, str]:
    """骑行距离(米)与来源。

    返回 `(distance_m, source)`,source ∈ {"route", "straight"}。
    **调用方必须把 source 透传给前端** —— 距离准不准,骑手有权知道。

    要时长的话用 [bicycling_route],这个函数只是它的距离视图。
    """
    dist, _minutes, src = await bicycling_route(
        from_lat, from_lng, to_lat, to_lng)
    return dist, src


async def _give_up(redis, key: str, fallback):
    """记下「这个点对规划不出来」,然后返回直线兜底。

    不记的话,抢单池里一个这样的点对会被每 5 秒重问一次 —— 实测 20 单的
    池子一次刷新要 6.1 秒,而客户端的轮询间隔就是 5 秒。
    """
    try:
        # 距离写 0 当负缓存标记:parse_route_cache 读得回来,
        # 而 0 米在业务上不可能是真实距离
        await redis.set(key, dump_route_cache(0.0, None), ex=_NEG_TTL_SECONDS)
    except Exception:
        pass  # 缓存挂了不影响正确性,只是下次还得再问一遍
    return fallback


async def route(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float,
    mode: str = "bike",
) -> tuple[float, float | None, str]:
    """路径距离(米)、路网时长(分钟)与来源。`mode`:bike / walk / drive。

    **同样 800 米,骑过去和走过去是两种体感** —— 自取的人是走过去的,
    住宿的人多半开车。给错方式的距离,等于让人按错误的前提做决定(#298)。

    返回 `(distance_m, duration_minutes, source)`。
    腾讯骑行接口的 `routes[0].duration` **单位是分钟**(官方文档核实过)。
    走直线兜底时 duration 为 None —— 我们估不出路口和红灯,
    **不该编一个数出来**。

    ## 这个时长拿来干什么

    ETA 的骑行段现在是「距离 ÷ 15km/h」(labor_guard.RIDE_SPEED_KMH),
    15 是故意压低的常量,把红灯、找楼栋、等电梯都包了进去。但它是
    **一个平均值拍在所有路线上** —— 市区过 8 个红灯和郊区一条直路
    拿的是同一份余量。

    路网时长补的就是这个:**只在它更长时才用**,见 labor_guard 里
    ride_minutes 的说明。
    """
    straight = haversine_m(from_lat, from_lng, to_lat, to_lng)
    fallback = (straight * _MODE_FALLBACK[mode], None, "straight")
    if not settings.tencent_map_key:
        # 没配 key 时不写负缓存:那不是"这条路规划不出来",
        # 是"我们没去问"。配上 key 之后应当立刻生效,不该被缓存挡半小时
        return fallback

    a, b = (from_lat, from_lng), (to_lat, to_lng)
    redis = get_redis()
    ck = _key(a, b, mode)
    try:
        cached = await redis.get(ck)
        if cached is not None:
            raw = cached.decode() if isinstance(cached, bytes) else cached
            dist_c, dur_c = parse_route_cache(raw)
            # 负缓存标记:距离写 0 表示"这个点对规划不出路线",
            # 别再去问了(见 _NEG_TTL_SECONDS)
            if dist_c <= 0:
                return fallback
            return dist_c, dur_c, "route"
    except Exception:
        pass  # 缓存挂了不影响主流程

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(_MODE_API[mode], params={
                "from": f"{from_lat},{from_lng}",
                "to": f"{to_lat},{to_lng}",
                "key": settings.tencent_map_key,
            })
            data = resp.json()
        if data.get("status") != 0:
            # 配额用尽和参数错在结果上长得一样,把 message 记下来才查得清
            logger.warning("%s 路径 status=%s %s,回退直线", mode,
                           data.get("status"), data.get("message"))
            return await _give_up(redis, ck, fallback)
        routes = (data.get("result") or {}).get("routes") or []
        if not routes:
            return await _give_up(redis, ck, fallback)
        dist = float(routes[0].get("distance") or 0)
        if dist <= 0:
            return await _give_up(redis, ck, fallback)
        # duration 单位是分钟。缺了当没有 —— 不拿距离反推一个假时长
        raw_dur = routes[0].get("duration")
        dur = float(raw_dur) if raw_dur not in (None, "") else None
        if dur is not None and dur <= 0:
            dur = None
        # 单位体检:算出来的速度不合常理就当没拿到(见 _MODE_SPEED_RANGE)
        if dur is not None:
            kmh = (dist / 1000) / (dur / 60)
            lo, hi = _MODE_SPEED_RANGE[mode]
            if not (lo <= kmh <= hi):
                logger.warning(
                    "%s 路径时长不合常理:%.0fm / %.1f 分钟 = %.1f km/h,当没拿到",
                    mode, dist, dur, kmh)
                dur = None
        try:
            await redis.set(ck, dump_route_cache(dist, dur), ex=_TTL_SECONDS)
        except Exception:
            pass
        return dist, dur, "route"
    except Exception as e:
        logger.warning("%s 路径请求失败(%s),回退直线",
                       mode, type(e).__name__)
        return await _give_up(redis, ck, fallback)


async def bicycling_route(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float,
) -> tuple[float, float | None, str]:
    """骑行路径。ETA、抢单距离都走这个 —— 主场景是骑手。"""
    return await route(from_lat, from_lng, to_lat, to_lng, "bike")


async def billing_distance_m(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float,
) -> tuple[float, str]:
    """**算配送费用的**距离(米)与来源。返回 `(distance_m, source)`。

    ## 为什么单独一个函数

    配送费一分不少全归骑手,所以这个数直接就是骑手的收入。
    它必须比别处更谨慎,单独拎出来,好写红线、好写测试、好被人看见。

    ## 只放宽不收紧

    取 `max(直线, 路网)`。方向不能反 ——

    - 直线永远 ≤ 实际要骑的路,这是几何决定的,不是估算误差;
    - 万一腾讯回来一个比直线还短的数(路网数据异常、坐标落到了
      高架另一侧),那是**接口的问题,不该由骑手承担**。

    和 `labor_guard.clamp_eta_minutes` 是同一条原则的两处落点:
    **任何第三方数据只能让骑手的处境变好,不能变坏。**

    ## 为什么这件事值一次网络调用

    实测成都样本:直线 1467m,骑行 1745m,差 19%。而计价是按整公里
    分档的(起步 2km,每超 1km +¥1)—— 19% 的低估在 2–4km 区间里
    经常正好差一整档,也就是**每单少 1 块钱**。一天 30 单就是 30 块。

    这不是精度问题,是系统性地少付,而且是单边的:
    直线永远偏低,不存在偶尔多给。
    """
    straight = haversine_m(from_lat, from_lng, to_lat, to_lng)
    try:
        routed, _dur, source = await route(
            from_lat, from_lng, to_lat, to_lng, "bike")
    except Exception:
        logger.warning("配送费取路网距离失败,退回直线兜底", exc_info=True)
        return straight * _MODE_FALLBACK["bike"], "straight"
    # ⚠️ max 不能省(见上面「只放宽不收紧」)
    return max(straight, routed), source


async def walking_route(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float,
) -> tuple[float, float | None, str]:
    """步行路径。到店自取、团购到店核销用。

    自取的人是**走过去**的:骑行路线会让他上机动车道、绕开步行街,
    而人可以穿小区、走天桥。给骑行距离等于让他按错误的前提决定
    "要不要自己去拿"。
    """
    return await route(from_lat, from_lng, to_lat, to_lng, "walk")


async def driving_route(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float,
) -> tuple[float, float | None, str]:
    """驾车路径。住宿列表用 —— 订酒店的人多半开车过去。

    「离你 3 公里」和「开车 12 分钟」是两个概念:前者是地图上的长度,
    后者才是他要做的决定(今晚住不住这家)。
    """
    return await route(from_lat, from_lng, to_lat, to_lng, "drive")


#: 距离矩阵单次请求的上限(腾讯:20 起点 × 25 终点)。
#: 我们的形态是「1 个骑手 → N 家店」,所以只用得上终点那一维
_MATRIX_MAX_DESTS = 25

_MATRIX_API = "https://apis.map.qq.com/ws/distance/v1/matrix"

#: 腾讯的「每秒请求量已达到上限」。**不是每日配额用尽** —— 等一下就好,
#: 所以要和真正的配额耗尽区分开:前者该重试,后者重试只是多烧一次
_RATE_LIMIT_STATUS = {120}
#: 实测这个 key 的每秒配额比想象中严:0.35 秒的间隔仍会撞上
#: status=120,而**撞一次的代价是整批回退直线**,然后逐单补打 40 次
#: 单点请求 —— 冷缓存一次刷新 7.5 秒。宁可等 1.1 秒。
_RATE_LIMIT_PAUSE = 1.1

#: 矩阵调用之间的**进程级**最小间隔。
#:
#: 原来节流只管同一次调用内部的分批,管不住"两次独立调用背靠背发出去"——
#: 抢单池预热正好是这种形态(先热骑手→商家,再按店热商家→送达点),
#: 实测第二次直接撞上 status=120「此key每秒请求量已达到上限」,
#: 整批回退直线、白跑一趟,还得等重试。
#:
#: 用一把锁串行化并保证间隔:矩阵本来就是"一次问一批",
#: 它不需要并发,而它一旦被限流,代价是整批失效。
_matrix_gate = asyncio.Lock()
_matrix_last = 0.0



async def route_matrix(
    origin: tuple[float, float],
    dests: list[tuple[float, float]],
    mode: str = "bike",
) -> dict[tuple[float, float], tuple[float, float | None, str]]:
    """一个起点到多个终点的路径距离(#289;#298 加 mode)。

    返回 `{(lat, lng): (distance_m, duration_min, source)}`,
    source ∈ {"route", "straight"},和 [bicycling_route] 完全一致 ——
    调用方不需要知道这个数是矩阵来的还是单点来的。

    ## 为什么需要它

    抢单列表原来在 **for 循环里**逐单调 [bicycling_m](骑手→商家、
    商家→用户各一次)。一屏 20 单就是 40 次串行 HTTP,每次超时 3 秒。
    Redis 缓存挡掉了重复,但**缓存冷的时候正是午高峰第一批单** ——
    而那正是这个 App 存在的时刻。

    ## 缓存和单点调用是同一套

    键、格式、TTL 全用 [_key] / [dump_route_cache] / [_TTL_SECONDS]。
    **这一条不能省**:两套缓存各热各的,等于白做 —— 矩阵回来的结果
    单点调用读不到,单点热好的缓存矩阵也用不上。

    ## 拿不到就退回直线,和单点一个口径

    没配 key、接口挂了、配额用尽、某个点没返回 —— 一律
    `straight × _FALLBACK_FACTOR` 并标 `"straight"`,**不编数**。
    """
    out: dict[tuple[float, float], tuple[float, float | None, str]] = {}
    if not dests:
        return out

    redis = get_redis()
    # 按**缓存格**去重后再问接口。
    #
    # 缓存键是 111m 见方的格子,同一格里的点本来就共用一个答案 ——
    # 而现实里同格的点非常多:一栋楼里的几家酒店、同一家店的好几单。
    # 不去重就会把同一个点重复问几十遍,50 个终点切成两批发出去,
    # 第二批直接撞上「此key每秒请求量已达到上限」,一半的卡片没有时长,
    # 看着像"这些算不出来",其实只是我们自己把自己限流了。
    #
    # 去重之后 50 家酒店常常只剩三四个真正要问的点,一批就够。
    todo: list[tuple[float, float]] = []
    seen_cells: dict[str, tuple[float, float]] = {}
    same_cell: dict[tuple[float, float], tuple[float, float]] = {}
    for d in dests:
        straight = haversine_m(origin[0], origin[1], d[0], d[1])
        try:
            cached = await redis.get(_key(origin, d, mode))
            if cached is not None:
                raw = cached.decode() if isinstance(cached, bytes) else cached
                dist_c, dur_c = parse_route_cache(raw)
                out[d] = (dist_c, dur_c, "route")
                continue
        except Exception:
            pass  # 缓存挂了不影响主流程
        if not settings.tencent_map_key:
            out[d] = (straight * _MODE_FALLBACK[mode], None, "straight")
            continue
        cell = _key(origin, d, mode)
        rep = seen_cells.get(cell)
        if rep is None:
            seen_cells[cell] = d
            todo.append(d)
        elif rep != d:
            same_cell[d] = rep  # 跟着代表点走,不单独问

    # 串行 + 保证间隔:跨调用也不许把自己限流(见 _matrix_gate)。
    #
    # ⚠️ 锁要罩住**整个分批循环**,不能只罩住开头的等待 ——
    # 只罩开头的话两个并发调用会同时拿到锁又同时放开,然后各自
    # 开始打接口,间隔等于没有。踩过一次。
    global _matrix_last
    async with _matrix_gate:
        gap = _RATE_LIMIT_PAUSE - (asyncio.get_event_loop().time() - _matrix_last)
        if gap > 0:
            await asyncio.sleep(gap)

        # 分批打:超过单次上限就切片,别指望接口帮我们截断
        for i in range(0, len(todo), _MATRIX_MAX_DESTS):
            batch = todo[i:i + _MATRIX_MAX_DESTS]
            rows: list[dict] | None = None
            for attempt in range(2):
                try:
                    async with httpx.AsyncClient(timeout=4) as client:
                        resp = await client.get(_MATRIX_API, params={
                            "mode": _MODE_MATRIX[mode],
                            "from": f"{origin[0]},{origin[1]}",
                            "to": ";".join(f"{d[0]},{d[1]}" for d in batch),
                            "key": settings.tencent_map_key,
                        })
                        data = resp.json()
                    status = data.get("status")
                    if status == 0:
                        rows = ((data.get("result") or {}).get("rows") or [{}])[0] \
                            .get("elements")
                        break
                    if status in _RATE_LIMIT_STATUS and attempt == 0:
                        # **每秒**请求量上限,不是每日配额 —— 等一下再打就过了。
                        # 50 家酒店切成两批、40 单抢单池切成两批,两批背靠背
                        # 发出去就会撞上;第二批静默回退直线,一半的卡片没有
                        # 时长,看着像"这些店算不出来",其实只是发太快了
                        await asyncio.sleep(_RATE_LIMIT_PAUSE)
                        continue
                    # 配额用尽和参数错在结果上长得一样,把 message 记下来才查得清
                    logger.warning("距离矩阵 status=%s %s,这一批回退直线",
                                   status, data.get("message"))
                    break
                except Exception as e:
                    logger.warning("距离矩阵请求失败(%s),这一批回退直线",
                                   type(e).__name__)
                    break
            else:
                logger.warning("距离矩阵限流重试后仍失败,这一批回退直线")

            _matrix_last = asyncio.get_event_loop().time()
            # 批与批之间歇一下,别自己把自己限流(上面的重试是兜底,不是常态)
            if i + _MATRIX_MAX_DESTS < len(todo):
                await asyncio.sleep(_RATE_LIMIT_PAUSE)

            for j, d in enumerate(batch):
                straight = haversine_m(origin[0], origin[1], d[0], d[1])
                el = rows[j] if rows is not None and j < len(rows) else None
                dist = float((el or {}).get("distance") or 0)
                if dist <= 0:
                    out[d] = (straight * _MODE_FALLBACK[mode], None, "straight")
                    continue
                # 矩阵接口的 duration 单位是**秒**(和骑行路径的分钟不一样,
                # 官方文档两处口径确实不同)—— 换算成分钟再往下传,
                # 否则 ETA 会拿到一个 60 倍的数
                raw_dur = (el or {}).get("duration")
                dur = float(raw_dur) / 60 if raw_dur not in (None, "") else None
                if dur is not None and dur <= 0:
                    dur = None
                out[d] = (dist, dur, "route")
                try:
                    await redis.set(_key(origin, d, mode),
                                    dump_route_cache(dist, dur),
                                    ex=_TTL_SECONDS)
                except Exception:
                    pass

    # 同格的点抄代表点的答案。代表点自己也没算出来的,退回直线 ——
    # 口径和单点调用一致,不编数
    for d, rep in same_cell.items():
        if rep in out:
            out[d] = out[rep]
    for d in dests:
        if d not in out:
            straight = haversine_m(origin[0], origin[1], d[0], d[1])
            out[d] = (straight * _MODE_FALLBACK[mode], None, "straight")
    return out


async def bicycling_matrix(
    origin: tuple[float, float],
    dests: list[tuple[float, float]],
) -> dict[tuple[float, float], tuple[float, float | None, str]]:
    """骑行矩阵。抢单列表用 —— 一屏 20 单不该打 40 次 HTTP。"""
    return await route_matrix(origin, dests, "bike")


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
