"""全国城市清单(腾讯行政区划接口)。

## 为什么不在客户端塞一张城市表

那张表迟早和服务端对不上,而且新开一个城市就要发一次版。
清单从服务端来,客户端只负责画。

## 为什么用腾讯的行政区划接口而不是自己维护一份

一次拿到 **名称 + 拼音 + 中心坐标**,三样都是这个功能需要的:
拼音用来做 A–Z 索引,中心坐标用来"选了城市就按该城市中心找店"。
自己维护一份就要自己跟着行政区划调整走(撤县设区、更名),
而那件事每年真的在发生。

## 直辖市怎么处理

接口返回三层:省 / 市 / 区。直辖市(北京、上海、天津、重庆)的第二层
直接就是**区**,不是市 —— 按 `cidx`(父级在下一层的区间)展开时,
如果父级本身就是直辖市,那么它自己才是"城市",下一层的区不该混进城市列表。
不处理的话城市选择器里会出现「东城」「朝阳」和「成都」并列。

缓存 7 天:行政区划不是按天变的,而这个接口每次要传 500 多个对象。
"""
import json
import logging

import httpx

from ..config import settings
from ..redis_client import get_redis

logger = logging.getLogger("superz.city_list")

_API = "https://apis.map.qq.com/ws/district/v1/list"
_CACHE_KEY = "geo:city_list:v1"
_TTL_SECONDS = 7 * 86400

#: 直辖市与特别行政区:它们自己就是"城市",下一层是区不是市
_MUNICIPALITIES = frozenset({"北京", "上海", "天津", "重庆",
                             "香港", "澳门"})


def _initial(pinyin: list | None, name: str) -> str:
    """拼音首字母(大写)。取不到归到 # —— 不要静默丢掉这个城市。"""
    if pinyin and isinstance(pinyin, list) and pinyin[0]:
        ch = str(pinyin[0])[0].upper()
        if "A" <= ch <= "Z":
            return ch
    return "#"


def parse(result: list) -> list[dict]:
    """把腾讯的三层结构拍平成城市列表。**纯函数,单测直接喂它。**

    分开写不是为了好看:网络那一层测不了,而"直辖市会不会把区
    混进城市列表"这种判断恰恰是最容易错、也最该被钉住的部分。
    """
    if len(result) < 2:
        return []
    provinces, cities = result[0], result[1]
    out: list[dict] = []
    for prov in provinces:
        pname = str(prov.get("name") or "")
        if pname in _MUNICIPALITIES:
            # 直辖市:它本身就是城市,下一层的区跳过
            loc = prov.get("location") or {}
            out.append({
                "name": str(prov.get("fullname") or pname),
                "short": pname,
                "province": pname,
                "initial": _initial(prov.get("pinyin"), pname),
                "pinyin": "".join(prov.get("pinyin") or []),
                "lat": loc.get("lat"), "lng": loc.get("lng"),
            })
            continue
        lo, hi = (prov.get("cidx") or [0, -1])[:2]
        for city in cities[lo:hi + 1]:
            cname = str(city.get("name") or "")
            if not cname:
                continue
            loc = city.get("location") or {}
            out.append({
                "name": str(city.get("fullname") or cname),
                "short": cname,
                "province": pname,
                "initial": _initial(city.get("pinyin"), cname),
                "pinyin": "".join(city.get("pinyin") or []),
                "lat": loc.get("lat"), "lng": loc.get("lng"),
            })
    return out


async def all_cities() -> list[dict]:
    """全国城市清单。拿不到返回空列表 —— 调用方要能在没有它时照常工作。"""
    redis = get_redis()
    try:
        cached = await redis.get(_CACHE_KEY)
        if cached is not None:
            raw = cached.decode() if isinstance(cached, bytes) else cached
            return json.loads(raw)
    except Exception:
        pass
    if not settings.tencent_map_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                _API, params={"key": settings.tencent_map_key})
            data = resp.json()
        if data.get("status") != 0:
            logger.warning("腾讯行政区划 status=%s %s",
                           data.get("status"), data.get("message"))
            return []
        out = parse(data.get("result") or [])
        if out:
            try:
                await redis.set(_CACHE_KEY, json.dumps(out, ensure_ascii=False),
                                ex=_TTL_SECONDS)
            except Exception:
                pass
        return out
    except Exception:
        logger.warning("腾讯行政区划拉取失败", exc_info=True)
        return []
