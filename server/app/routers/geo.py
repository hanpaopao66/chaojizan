"""地理服务代理。

腾讯位置服务的 Key 只放在服务端,客户端一律走这里 —— Key 一旦进了 APK
就等于公开,被盗刷是迟早的事(配额是按 key 计费的)。
没配 Key 时返回演示数据,保证开发环境全流程能跑。

坐标口径:腾讯返回 GCJ-02,与本系统全局一致,直接透传不转换。
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

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
            district="演示数据", lat=lat, lng=lng)

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
    return PoiTipOut(
        name=name,
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
