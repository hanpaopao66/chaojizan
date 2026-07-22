"""地理服务代理。

高德 Web 服务 Key 只放在服务端,客户端一律走这里,避免 Key 泄露被盗刷。
没配 Key 时返回演示数据,保证开发环境全流程能跑。
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import settings
from ..models import User
from ..schemas import PoiTipOut
from ..security import get_current_user

router = APIRouter(prefix="/geo", tags=["地理服务"])

AMAP_TIPS_URL = "https://restapi.amap.com/v3/assistant/inputtips"

# 演示模式的基准点:成都春熙路
_DEMO_LAT, _DEMO_LNG = 30.6598, 104.0810


@router.get("/tips", response_model=list[PoiTipOut])
async def poi_tips(
    keywords: str = Query(min_length=1, max_length=50),
    city: str = "成都",
    user: User = Depends(get_current_user),
):
    """POI 输入提示(选收货地址/店铺选点用)。"""
    if not settings.amap_web_key:
        return [
            PoiTipOut(
                name=f"{keywords}·演示地点{i + 1}",
                district=f"{city} 演示数据(服务端未配置 AMAP_WEB_KEY)",
                lat=_DEMO_LAT + i * 0.002,
                lng=_DEMO_LNG + i * 0.002,
            )
            for i in range(3)
        ]

    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(
                AMAP_TIPS_URL,
                params={
                    "key": settings.amap_web_key,
                    "keywords": keywords,
                    "city": city,
                    "citylimit": "true",
                    "datatype": "poi",
                },
            )
            data = resp.json()
        except httpx.HTTPError:
            raise HTTPException(502, "地图服务暂时不可用,请稍后再试")

    if data.get("status") != "1":
        raise HTTPException(502, f"高德接口错误:{data.get('info', '未知')}")

    tips = []
    for tip in data.get("tips", []):
        location = tip.get("location")
        if not isinstance(location, str) or "," not in location:
            continue  # 过滤没有坐标的模糊提示
        lng, lat = location.split(",", 1)
        district = tip.get("district") or ""
        # 高德的 address 字段偶尔是空数组,只拼接字符串
        addr = tip.get("address")
        if isinstance(addr, str):
            district += addr
        tips.append(
            PoiTipOut(
                name=tip.get("name", ""),
                district=district,
                lat=float(lat),
                lng=float(lng),
            )
        )
    return tips[:10]
