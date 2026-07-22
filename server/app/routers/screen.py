"""公开经营大屏数据源(/screen 页面,无鉴权)。

口径与 /stats/overview(公开账本)一致:全部是平台级汇总,无任何个人信息,
手机号打码、坐标只到城市级。GMV 是否对外展示由 platform_flags.screen_show_gmv
控制(管理员 POST /admin/flags/screen_show_gmv 改,off=隐藏,其余=展示)。

演示模式(SCREEN_DEMO=1):真实数据上叠加确定性模拟增量,响应带 demo=true,
前端明示"演示数据"角标——对外的数字可以好看,但不能装成真的。
"""
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import PlatformFlag
from ..ratelimit import check_rate_limit
from ..state_machine import STATUS_LABELS, OrderStatus

router = APIRouter(prefix="/screen", tags=["公开大屏"])

SH = ZoneInfo("Asia/Shanghai")
# 有效订单口径(与 /stats/overview 相同):付了钱且没退的
_VALID = "status NOT IN ('pending_payment','cancelled')"
_TODAY_SH = ("date_trunc('day', now() AT TIME ZONE 'Asia/Shanghai')"
             " AT TIME ZONE 'Asia/Shanghai'")

# 进程内小缓存:公开接口谁都能刷,数据库只按 TTL 频率被打
_cache: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str) -> dict | None:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def _cache_put(key: str, data: dict, ttl: float) -> None:
    _cache[key] = (time.monotonic() + ttl, data)


async def _guard(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    await check_rate_limit("screen", ip, 120)


async def _show_gmv(db: AsyncSession) -> bool:
    flag = await db.get(PlatformFlag, "screen_show_gmv")
    return flag is None or flag.value != "off"


def _mask_phone(phone: str) -> str:
    if len(phone) >= 7:
        return phone[:3] + "****" + phone[-4:]
    return "****"


# ---------- 演示模式:确定性模拟增量(响应里 demo=true,前端明示) ----------

_DEMO_EPOCH = 1735689600  # 2025-01-01,增量随时间缓慢上涨,大屏看着是"活"的


def _demo_boost(per_hour: float, base: int) -> int:
    return base + int((time.time() - _DEMO_EPOCH) / 3600 * per_hour)


_DEMO_CITIES = [
    ("西安市", 34.34, 108.94), ("成都市", 30.57, 104.07),
    ("重庆市", 29.56, 106.55), ("武汉市", 30.59, 114.31),
    ("长沙市", 28.23, 112.94), ("郑州市", 34.75, 113.63),
    ("杭州市", 30.29, 120.15), ("广州市", 23.13, 113.26),
]
_DEMO_SHOPS = ["张记面馆", "老碗牛肉面", "巷口麻辣烫", "川香冒菜",
               "半亩豆花", "夜市烤串王", "阿婆砂锅粥", "秦镇米皮"]


@router.get("/stats")
async def screen_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """大屏汇总:注册规模 / 累计订单 / 趋势 / 城市分布 / 状态分布 / 配送效率。"""
    await _guard(request)
    if (hit := _cache_get("stats")) is not None:
        return hit
    show_gmv = await _show_gmv(db)

    # 注册规模:用户/骑手按角色,商家按审核通过口径;司机是打车业务预留位
    reg = (await db.execute(sa_text(f"""
        SELECT count(*) FILTER (WHERE role = 'customer'),
               count(*) FILTER (WHERE role = 'customer'
                                AND created_at >= {_TODAY_SH}),
               count(*) FILTER (WHERE role = 'rider'),
               count(*) FILTER (WHERE role = 'rider'
                                AND created_at >= {_TODAY_SH}),
               count(*) FILTER (WHERE role = 'rider' AND is_online)
        FROM users
    """))).one()
    mer = (await db.execute(sa_text(f"""
        SELECT count(*),
               count(*) FILTER (WHERE created_at >= {_TODAY_SH})
        FROM merchants WHERE status = 'approved'
    """))).one()

    # 累计/今日订单与 GMV(用户实付口径)
    totals = (await db.execute(sa_text(f"""
        SELECT count(*), coalesce(sum(total_cents), 0),
               count(*) FILTER (WHERE created_at >= {_TODAY_SH}),
               coalesce(sum(total_cents) FILTER (
                   WHERE created_at >= {_TODAY_SH}), 0)
        FROM orders WHERE {_VALID}
    """))).one()

    # 近 7 天趋势(缺的天补 0,大屏折线不能断)
    trend_rows = (await db.execute(sa_text(f"""
        SELECT (created_at AT TIME ZONE 'Asia/Shanghai')::date AS d,
               count(*), coalesce(sum(total_cents), 0)
        FROM orders
        WHERE {_VALID} AND created_at >= {_TODAY_SH} - interval '6 days'
        GROUP BY 1 ORDER BY 1
    """))).all()
    by_day = {r[0].isoformat(): r for r in trend_rows}
    today_sh = datetime.now(SH).date()
    trend = []
    for i in range(6, -1, -1):
        day = (today_sh - timedelta(days=i)).isoformat()
        r = by_day.get(day)
        trend.append({"day": day[5:], "orders": r[1] if r else 0,
                      "gmv_cents": (r[2] if r else 0) if show_gmv else None})

    # 今日/昨日分时(对比曲线)
    hourly_rows = (await db.execute(sa_text(f"""
        SELECT ((created_at AT TIME ZONE 'Asia/Shanghai')::date
                = (now() AT TIME ZONE 'Asia/Shanghai')::date) AS is_today,
               extract(hour FROM created_at AT TIME ZONE 'Asia/Shanghai')::int,
               count(*)
        FROM orders
        WHERE {_VALID} AND created_at >= {_TODAY_SH} - interval '1 day'
        GROUP BY 1, 2
    """))).all()
    hourly_today = [0] * 24
    hourly_yesterday = [0] * 24
    for is_today, hour, n in hourly_rows:
        (hourly_today if is_today else hourly_yesterday)[hour] = n

    # 城市累计订单 TOP10(订单挂商家城市;坐标取该城商家均值,城市级聚合)
    cities = [{"city": r[0], "orders": r[1],
               "gmv_cents": r[2] if show_gmv else None,
               "lat": round(r[3], 2), "lng": round(r[4], 2)}
              for r in (await db.execute(sa_text(f"""
        SELECT m.city, count(*), coalesce(sum(o.total_cents), 0),
               avg(m.lat), avg(m.lng)
        FROM orders o JOIN merchants m ON m.id = o.merchant_id
        WHERE o.{_VALID} AND m.city <> ''
        GROUP BY m.city ORDER BY 2 DESC LIMIT 10
    """))).all()]

    # 今日订单状态分布(进行中的看板环)
    status_rows = (await db.execute(sa_text(f"""
        SELECT status, count(*) FROM orders
        WHERE {_VALID} AND created_at >= {_TODAY_SH}
        GROUP BY 1
    """))).all()
    by_status = dict(status_rows)
    status_dist = [
        {"status": s.value, "label": STATUS_LABELS[s],
         "count": by_status.get(s.value, 0)}
        for s in (OrderStatus.PAID, OrderStatus.ACCEPTED, OrderStatus.READY,
                  OrderStatus.PICKED_UP, OrderStatus.DELIVERED,
                  OrderStatus.COMPLETED)
    ]

    # 今日平均配送时长(取餐→送达,事件日志口径)
    avg_min = await db.scalar(sa_text(f"""
        SELECT avg(extract(epoch FROM d.created_at - p.created_at)) / 60
        FROM order_events d
        JOIN order_events p ON p.order_id = d.order_id
                           AND p.to_status = 'picked_up'
        WHERE d.to_status = 'delivered' AND d.created_at >= {_TODAY_SH}
    """))

    # 覆盖城市:开城清单配置了按清单计,没配按已过审商家城市去重
    open_cities_flag = await db.get(PlatformFlag, "open_cities")
    if open_cities_flag is not None and open_cities_flag.value.strip():
        covered_cities = len([c for c in open_cities_flag.value.split(",")
                              if c.strip()])
    else:
        covered_cities = await db.scalar(sa_text("""
            SELECT count(DISTINCT city) FROM merchants
            WHERE status = 'approved' AND city <> ''
        """))

    # 帮商家省钱账:行业总负担普遍约 20%(佣金+履约+推广)对比我们实收佣金。
    # 基数 = 入账 food 口径(菜品+打包-满减),佣金对账本全量求和(冲账自动抵扣)
    sav_row = (await db.execute(sa_text("""
        SELECT coalesce(sum(food_cents) FILTER (WHERE kind = 'earning'), 0),
               coalesce(sum(commission_cents), 0)
        FROM merchant_earnings
    """))).one()
    saved_cents = max(0, int(sav_row[0] * 0.20) - sav_row[1])

    # 环保:无需餐具订单(下单页餐具份数选 0,备注口径,历史单同样可统计)
    eco_orders = await db.scalar(sa_text(f"""
        SELECT count(*) FROM orders
        WHERE {_VALID} AND remark LIKE '%餐具 0 份%'
    """))

    # 时效分布(近 7 天):配送时长(取餐→送达)分桶 + 出餐超时率
    delivery_buckets = [0, 0, 0, 0]  # 0-15 / 15-30 / 30-45 / 45+ 分钟
    for idx, n in (await db.execute(sa_text("""
        SELECT least(floor(extract(epoch FROM d.created_at - p.created_at)
                           / 60 / 15)::int, 3), count(*)
        FROM order_events d
        JOIN order_events p ON p.order_id = d.order_id
                           AND p.to_status = 'picked_up'
        WHERE d.to_status = 'delivered'
          AND d.created_at >= now() - interval '7 days'
        GROUP BY 1
    """))).all():
        if 0 <= idx <= 3:
            delivery_buckets[idx] = n
    late_row = (await db.execute(sa_text(f"""
        SELECT count(*) FILTER (WHERE ready_late), count(*)
        FROM orders
        WHERE {_VALID} AND created_at >= now() - interval '7 days'
          AND status IN ('ready','picked_up','delivered','completed')
    """))).one()

    data = {
        "registrations": {
            "users": {"total": reg[0], "today": reg[1]},
            "merchants": {"total": mer[0], "today": mer[1]},
            "riders": {"total": reg[2], "today": reg[3]},
            # 打车业务筹备中:字段预留,前端标注"即将开通"
            "drivers": {"total": 0, "today": 0, "coming": True},
        },
        "orders": {
            "total": totals[0],
            "gmv_cents": totals[1] if show_gmv else None,
            "today": totals[2],
            "today_gmv_cents": totals[3] if show_gmv else None,
        },
        "trend": trend,
        "hourly": {"today": hourly_today, "yesterday": hourly_yesterday},
        "cities": cities,
        "status_dist": status_dist,
        "delivery": {"riders_online": reg[4],
                     "avg_minutes": round(avg_min, 1) if avg_min else None,
                     # 近 7 天配送时长分布(0-15/15-30/30-45/45+ 分钟)与出餐超时率
                     "duration_buckets": delivery_buckets,
                     "ready_late_ratio": (round(late_row[0] / late_row[1], 4)
                                          if late_row[1] else None)},
        "coverage": {"cities": covered_cities, "merchants": mer[0]},
        # 对比口径:行业佣金+履约+推广总负担普遍约 20%,我们只收 ≤5% 佣金
        "merchant_savings": ({"saved_cents": saved_cents,
                              "industry_rate": 0.20}
                             if show_gmv else None),
        "eco": {"no_tableware_orders": eco_orders},
        "show_gmv": show_gmv,
        "demo": settings.screen_demo,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if settings.screen_demo:
        _apply_demo(data, show_gmv)
    _cache_put("stats", data, 10)
    return data


@router.get("/orders/latest")
async def screen_latest_orders(
    request: Request,
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """最新订单流水(滚动播报用):手机号打码,坐标只到城市级两位小数。"""
    await _guard(request)
    key = f"latest:{limit}"
    if (hit := _cache_get(key)) is not None:
        return hit
    show_gmv = await _show_gmv(db)
    rows = (await db.execute(sa_text(f"""
        SELECT o.id, o.order_no, o.status, o.total_cents, o.created_at,
               m.name, m.city, m.lat, m.lng, u.phone
        FROM orders o
        JOIN merchants m ON m.id = o.merchant_id
        JOIN users u ON u.id = o.customer_id
        WHERE o.{_VALID}
        ORDER BY o.id DESC LIMIT :limit
    """), {"limit": limit})).all()
    items = [{
        "id": r[0],
        # 订单号只露尾巴,防止拿全号去碰其他接口
        "order_no_tail": r[1][-6:],
        "status": r[2],
        "status_label": STATUS_LABELS[OrderStatus(r[2])],
        "amount_cents": r[3] if show_gmv else None,
        "created_at": r[4].astimezone(timezone.utc).isoformat(),
        "merchant": r[5],
        "city": r[6] or "",
        "lat": round(r[7], 2), "lng": round(r[8], 2),
        "phone": _mask_phone(r[9]),
    } for r in rows]
    data = {"items": items, "show_gmv": show_gmv, "demo": settings.screen_demo}
    if settings.screen_demo and len(items) < limit:
        data["items"] = items + _demo_orders(limit - len(items), show_gmv)
    _cache_put(key, data, 5)
    return data


def _apply_demo(data: dict, show_gmv: bool) -> None:
    """演示增量:各口径按固定速率随时间上涨,重启不回退、刷新单调不跳变。"""
    reg = data["registrations"]
    reg["users"]["total"] += _demo_boost(9, 128000)
    reg["users"]["today"] += _demo_boost(0, 310)
    reg["merchants"]["total"] += _demo_boost(0.4, 3600)
    reg["merchants"]["today"] += _demo_boost(0, 12)
    reg["riders"]["total"] += _demo_boost(0.8, 8200)
    reg["riders"]["today"] += _demo_boost(0, 36)
    data["orders"]["total"] += _demo_boost(160, 2400000)
    data["orders"]["today"] += _demo_boost(0, 5200)
    if show_gmv:
        data["orders"]["gmv_cents"] += _demo_boost(160, 2400000) * 3200
        data["orders"]["today_gmv_cents"] += _demo_boost(0, 5200) * 3200
    data["delivery"]["riders_online"] += _demo_boost(0, 420)
    if not data["delivery"]["avg_minutes"]:
        data["delivery"]["avg_minutes"] = 27.6
    seen = {c["city"] for c in data["cities"]}
    for i, (city, lat, lng) in enumerate(_DEMO_CITIES):
        if city not in seen and len(data["cities"]) < 10:
            n = _demo_boost(20 - i * 2, 260000 - i * 24000)
            data["cities"].append({
                "city": city, "orders": n,
                "gmv_cents": n * 3200 if show_gmv else None,
                "lat": lat, "lng": lng})
    data["cities"].sort(key=lambda c: c["orders"], reverse=True)
    hour = datetime.now(SH).hour
    for h in range(24):
        wave = 60 + 340 * max(0, 1 - min(abs(h - 12), abs(h - 18.5)) / 3)
        data["hourly"]["yesterday"][h] += int(wave)
        if h <= hour:
            data["hourly"]["today"][h] += int(wave * 1.08)
    for row in data["trend"]:
        row["orders"] += 5200
        if show_gmv and row["gmv_cents"] is not None:
            row["gmv_cents"] += 5200 * 3200


def _demo_orders(count: int, show_gmv: bool) -> list[dict]:
    now = datetime.now(timezone.utc)
    tick = int(time.time() // 40)  # 每 40 秒轮换一条,轮询能看到"新订单"进来
    items = []
    for i in range(count):
        city, lat, lng = _DEMO_CITIES[(tick + i) % len(_DEMO_CITIES)]
        items.append({
            "id": -(tick - i),  # 负数递增:客户端按 id 判新单,与真实订单不撞
            "order_no_tail": f"{(tick * 7 + i * 13) % 1000000:06d}",
            "status": "picked_up", "status_label": "配送中",
            "amount_cents": 1800 + (tick + i) * 137 % 4200 if show_gmv else None,
            "created_at": (now - timedelta(seconds=40 * i)).isoformat(),
            "merchant": _DEMO_SHOPS[(tick + i) % len(_DEMO_SHOPS)],
            "city": city, "lat": lat, "lng": lng,
            "phone": f"1{(3 + (tick + i) % 6)}8****{(tick * 31 + i * 77) % 10000:04d}",
        })
    return items
