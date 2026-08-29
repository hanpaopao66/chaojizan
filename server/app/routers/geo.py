"""地理服务代理。

腾讯位置服务的 Key 只放在服务端,客户端一律走这里 —— Key 一旦进了 APK
就等于公开,被盗刷是迟早的事(配额是按 key 计费的)。
没配 Key 时返回演示数据,保证开发环境全流程能跑。

坐标口径:腾讯返回 GCJ-02,与本系统全局一致,直接透传不转换。
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db

from ..config import settings
from ..models import User
from ..schemas import PoiTipOut
from ..security import get_current_user

router = APIRouter(prefix="/geo", tags=["地理服务"])

SUGGESTION_URL = "https://apis.map.qq.com/ws/place/v1/suggestion"
REVERSE_URL = "https://apis.map.qq.com/ws/geocoder/v1/"

# 演示模式的基准点:成都春熙路
_DEMO_LAT, _DEMO_LNG = 30.6598, 104.0810


@router.get("/tips", response_model=list[PoiTipOut])
async def poi_tips(
    keywords: str = Query(min_length=1, max_length=50),
    city: str = "成都",
    user: User = Depends(get_current_user),
):
    """POI 输入提示(选收货地址/店铺选点用)。"""
    if not settings.tencent_map_key:
        return [
            PoiTipOut(
                name=f"{keywords}·演示地点{i + 1}",
                district=f"{city} 演示数据(服务端未配置 TENCENT_MAP_KEY)",
                lat=_DEMO_LAT + i * 0.002,
                lng=_DEMO_LNG + i * 0.002,
            )
            for i in range(3)
        ]

    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(
                SUGGESTION_URL,
                params={
                    "keyword": keywords,
                    "region": city,
                    # region_fix=1:**只在本市内搜**。不加的话搜「一号店」
                    # 会把全国同名地点都返回,用户很容易选中外地的那个,
                    # 下单后才发现超出配送范围
                    "region_fix": 1,
                    "key": settings.tencent_map_key,
                },
            )
            data = resp.json()
        except httpx.HTTPError:
            raise HTTPException(502, "地图服务暂时不可用,请稍后再试")

    if data.get("status") != 0:
        raise HTTPException(502, f"地图接口错误:{data.get('message', '未知')}")

    tips = []
    for item in data.get("data") or []:
        loc = item.get("location") or {}
        lat, lng = loc.get("lat"), loc.get("lng")
        if lat is None or lng is None:
            continue  # 过滤没有坐标的模糊提示 —— 没坐标就没法算配送费
        tips.append(
            PoiTipOut(
                name=item.get("title", ""),
                district=item.get("address", "") or "",
                lat=float(lat),
                lng=float(lng),
            )
        )
    return tips[:10]


@router.get("/reverse", response_model=PoiTipOut)
async def reverse_geocode(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    user: User = Depends(get_current_user),
):
    """坐标 → 地址(地图选点用)。

    用户在地图上拖动图钉选位置后,要把坐标换成人能看懂的地址填进去。
    没有这一步的话,用户存下来的地址是一串经纬度 —— 骑手看不懂,
    商家也没法判断这单送不送得到。
    """
    if not settings.tencent_map_key:
        return PoiTipOut(
            name="演示地点(服务端未配置 TENCENT_MAP_KEY)",
            district="演示数据", lat=lat, lng=lng, city="")

    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(REVERSE_URL, params={
                "location": f"{lat},{lng}",
                "key": settings.tencent_map_key,
                # 这里**要** POI:纯行政区划("锦江区")当收货地址没用,
                # 得给出"XX 大厦""XX 小区"这种骑手找得到的参照物
                "get_poi": 1,
            })
            data = resp.json()
        except httpx.HTTPError:
            raise HTTPException(502, "地图服务暂时不可用,请稍后再试")

    if data.get("status") != 0:
        raise HTTPException(502, f"地图接口错误:{data.get('message', '未知')}")

    result = data.get("result") or {}
    # 优先用「推荐地址」:腾讯已经按"适合作为收货地址"挑过一轮,
    # 比原始的 address 字段更像人会写的地址
    formatted = result.get("formatted_addresses") or {}
    name = (formatted.get("recommend")
            or formatted.get("rough")
            or result.get("address")
            or "")
    # 结构化城市名,和 services/geo_city.py 同一个口径:
    # address_component.city,直辖市那里 city 为空所以退回 province。
    # **不让客户端从地址串里抠** —— 正则一贪婪就变成「陕西省西安市」
    comp = result.get("address_component") or {}
    return PoiTipOut(
        name=name,
        city=str(comp.get("city") or comp.get("province") or "")[:20],
        district=result.get("address", "") or "",
        # 回传的是**用户点的那个坐标**,不是腾讯匹配到的 POI 坐标 ——
        # 用户拖到自家单元门口,不该被吸附到几十米外的小区大门
        lat=lat,
        lng=lng,
    )


@router.get("/around")
async def poi_around(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    user: User = Depends(get_current_user),
):
    """地图选点页下方的周边地点列表(#170)。

    ## 为什么要有这个列表

    光给一个中心图钉 + 反查出来的一行地址,用户很难确认"这就是我家" ——
    反查给的往往是路名,而他要的是「XX 小区 10 号楼」。

    主流外卖 App 的做法是:地图下面列一串周边地点,带距离,直接点选。
    用户认地名比认坐标容易得多。

    ## 一次调用拿全

    腾讯的逆地理编码带 `get_poi=1` 时会一并返回周边 POI 与距离,
    不用再打一次周边搜索 —— **少一次调用就少一份配额和延迟**。

    坐标口径:腾讯返回 GCJ-02,与本系统全局一致,直接透传。
    """
    if not settings.tencent_map_key:
        return {"current": f"演示地点(未配置 TENCENT_MAP_KEY)",
                "items": [
                    {"name": f"演示地点{i + 1}", "address": "演示数据",
                     "distance_m": i * 50,
                     "lat": lat + i * 0.0005, "lng": lng + i * 0.0005}
                    for i in range(3)]}

    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(REVERSE_URL, params={
                "location": f"{lat},{lng}",
                "key": settings.tencent_map_key,
                "get_poi": 1,
                # 只要"适合当收货地址"的类别:小区/楼宇/学校/医院/写字楼。
                # 不加的话周边全是餐馆和便利店 —— 那不是收货地址
                "poi_options": "address_format=short;radius=500;policy=4",
            })
            data = resp.json()
        except httpx.HTTPError:
            raise HTTPException(502, "地图服务暂时不可用,请稍后再试")

    if data.get("status") != 0:
        raise HTTPException(502, f"地图接口错误:{data.get('message', '未知')}")

    result = data.get("result") or {}
    formatted = result.get("formatted_addresses") or {}
    items = []
    for poi in (result.get("pois") or [])[:15]:
        loc = poi.get("location") or {}
        if loc.get("lat") is None or loc.get("lng") is None:
            continue  # 没坐标的选了也没用 —— 骑手送不到
        items.append({
            "name": poi.get("title", ""),
            "address": poi.get("address", "") or "",
            # 距离让用户一眼判断"是不是我家那栋" —— 比看地图快
            "distance_m": round(float(poi.get("_distance") or 0)),
            "lat": float(loc["lat"]),
            "lng": float(loc["lng"]),
        })
    items.sort(key=lambda x: x["distance_m"])
    return {
        # 图钉正下方是哪儿(地图上那个气泡显示它)
        "current": (formatted.get("recommend") or result.get("address") or ""),
        "items": items,
    }


@router.get("/weather")
async def weather_at(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    user: User = Depends(get_current_user),
):
    """当前位置天气与是否触发恶劣天气加价(#146)。

    三端共用:骑手端显示「当前恶劣天气,本单加价 ¥X」、
    用户端显示「雨天配送,预计送达已顺延」、商家端提示可能出餐延迟。

    判定阈值与 /transparency/dispatch 公开的是**同一份常量**。
    """
    from ..config import settings
    from ..services import weather as wx

    w = await wx.current(lat, lng)
    if w is None:
        # 查不到就如实说不知道,不要假装天气很好 ——
        # 前端据此不显示天气提示,而不是显示「天气良好」
        return {"available": False}
    return {
        "available": True,
        "severe": w["severe"],
        "temp_c": w["temp_c"],
        "precip_mm": w["precip_mm"],
        "wind_kmh": w["wind_kmh"],
        "surcharge_cents": (settings.delivery_weather_surcharge_cents
                            if w["severe"] else 0),
        # 加价全归骑手 —— 这句每次都带上,不是废话:
        # 用户看到加价时会问"这钱给谁了"
        "note": ("恶劣天气配送加价,全额归骑手;预计送达时间已相应放宽"
                 if w["severe"] else ""),
    }


@router.get("/cities")
async def open_city_list(db: AsyncSession = Depends(get_db)):
    """可选城市(地址搜索的城市切换器用,#172)。

    ## 清单从哪来:**实际有商家的城市**,不是编一个名单

    腾讯的 POI 搜索用 `region_fix=1` 把结果限死在指定城市 ——
    城市选错,用户搜自己家会一条都搜不到。所以这个清单必须准。

    准的定义是「这里点得到外卖」,而不是「我们打算开这里」:
    - 配了 `open_cities` 就以它为准(管理员明确圈定的经营范围);
    - 没配就取**已通过审核的商家所在城市** —— 有店才叫开城,
      列一个没有商家的城市,用户切过去只会看到空列表。

    公开接口:选城市这一步在登录前就可能发生(先看有没有店再决定注册)。
    """
    from ..services.flags import open_cities

    allow = await open_cities(db)
    rows = (await db.execute(text("""
        SELECT city, count(*) AS n FROM merchants
        WHERE status = 'approved' AND city <> ''
        GROUP BY city ORDER BY n DESC
    """))).all()
    have = [{"name": c, "merchants": n} for c, n in rows]

    by_name = {h["name"]: h["merchants"] for h in have}
    if allow:
        # 开城清单是权威:清单里的城市即便还没有商家也列出来(可能刚开城),
        # 但**标出来没有店** —— 让用户知道切过去会看到什么
        items = [{"name": c, "merchants": by_name.get(c, 0)} for c in allow]
        source = "open_cities"
    else:
        items, source = have, "merchants"

    # ---- 全部城市(#308)----
    #
    # 原先这个接口只给「有店的城市」。而人是会出差、会搬家的:
    # 到了一个还没开通的城市,列表里一条都没有,他连"这里到底开没开"
    # 都看不出来 —— 只会以为 App 坏了。
    #
    # 所以给全量清单,但**每一条都标着有几家店**:
    # 让他自己看到"这里还没有商家",而不是让他猜。
    all_cities: list[dict] = []
    try:
        from ..services.city_list import all_cities as fetch_all
        for c in await fetch_all():
            # 商家的 city 存的是「成都市」这种全名(腾讯逆地理的口径),
            # 而清单里 name 也是全名 —— 直接对得上,不做模糊匹配:
            # 模糊匹配会把「吉林省」和「吉林市」算成一个
            all_cities.append({**c, "merchants": by_name.get(c["name"], 0)})
    except Exception:
        # 拿不到全量清单不影响原有能力 —— 切换器照常能用有店的那几个
        pass

    return {
        "items": items,
        "source": source,
        # 热门 = 有店且店多的。不是编辑推荐,也没有位置可以买
        "hot": sorted(have, key=lambda h: -h["merchants"])[:12],
        "all": all_cities,
    }


@router.get("/route")
async def route_estimate(
    from_lat: float = Query(ge=-90, le=90),
    from_lng: float = Query(ge=-180, le=180),
    to_lat: float = Query(ge=-90, le=90),
    to_lng: float = Query(ge=-180, le=180),
    mode: str = Query(default="walk", pattern="^(walk|drive|bike)$"),
    user: User = Depends(get_current_user),
):
    """两点之间按出行方式算的实际路径距离与时长(#298)。

    ## 为什么不能都用一个数

    **同样 800 米,骑过去和走过去是两种体感。**

    - 到店自取、团购到店核销的人是**走过去**的。给他骑行距离,
      等于让他按错误的前提决定"要不要自己去拿" ——
      骑行路线会上机动车道、绕开步行街,而人能穿小区、走天桥;
    - 订酒店的人多半**开车**过去。「离你 3 公里」是地图上的长度,
      「开车 12 分钟」才是他要做的那个决定。

    ## 时长可能是 null

    没配 Key、接口挂了、或者回来的时长不合常理(腾讯各接口 duration
    单位不统一,#289 踩过),一律给 null。客户端**只显示距离,不显示时间**
    —— 编一个时间出来,用户按它出门,迟到的是他。

    距离永远有值:最差也是直线 × 经验系数,并在 `source` 里标成
    `straight`,客户端据此说"约"。
    """
    from ..services.routing import route as _route

    dist, minutes, source = await _route(from_lat, from_lng,
                                         to_lat, to_lng, mode)
    return {
        "distance_m": round(dist),
        "minutes": None if minutes is None else max(1, round(minutes)),
        "mode": mode,
        "source": source,
    }
