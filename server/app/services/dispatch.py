"""派单排序算法(#140)。**这个模块是公开算法的唯一事实来源。**

## 为什么单独成一个模块

派单算法对骑手的意义,等同于账目对商家的意义 —— 它决定骑手今天挣多少。
资本平台的算法是黑箱,骑手只能猜"为什么好单不给我"。本平台把它公开
(见 routers/transparency.py 的 /dispatch)。

而公开的前提是**只有一份**:权重定义在这里,接口从这里读,排序也从这里算。
接口里另抄一份字面量的话,抄的那份迟早和真实算法对不上 —— 那时公开的是假的,
比不公开更坏。有测试钉住这件事。

## 平台立场(承诺不做的事,和承诺做的事一样重要)

- **不做强制派单。** 广播抢单,骑手自己选。算法只负责把信息排得更有用,
  不负责替骑手做决定;
- **不按骑手评分/等级差别对待。** 同一批单,所有在线骑手看到的排序口径一致;
- **不因为骑手拒过单就降权。** 拒单不进任何权重。
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 权重。改这里就等于改算法,/dispatch 的公开值会跟着变(同源,不是抄的)。
# 每一条都必须能讲出道理 —— 讲不出道理的数字不配公开。
# ---------------------------------------------------------------------------

#: 等待每分钟折算的"靠近"米数。
#: 让久等的单不至于永远垫底。**有上限**:超过上限的单该走无人接单兜底流程
#: (no_rider_alert / no_rider_cancel),而不是靠把它顶到榜首硬推。
WAIT_WEIGHT_M_PER_MIN = 150.0
WAIT_BONUS_MAX_M = 3000.0

#: 小费每元折算的"靠近"米数。这是**"钱能买多靠前"的定价**,所以必须有上限 ——
#: 无上限意味着出得起钱的人永远排在最前,与"不杀熟"的立场冲突。
#: 上限 1500m 的含义:小费最多把一单往前提"相当于近 1.5 公里",
#: 再多的小费骑手照收,但不再买到更靠前的位置。
TIP_WEIGHT_M_PER_YUAN = 300.0
TIP_BONUS_MAX_M = 1500.0

#: 同商家:在同一家店多取一单,取餐环节几乎零成本 —— 比"路线接近"值钱得多,
#: 所以给独立且更高的权重,不与顺路混成一个布尔。
SAME_SHOP_BONUS_M = 2000.0

#: 顺路按**绕路增量**分档(米)。绕路增量 = 接了这单要比只送手头单多跑多远。
#: 原先用"两个送达点相距 <800m"判顺路,实测反例:送达点相邻但取餐点在反方向
#: 3km 的单也被判顺路,实际多跑近 6 公里。两点距离没有物理意义,绕路增量有。
SAME_WAY_STRONG_MAX_M = 500.0
SAME_WAY_WEAK_MAX_M = 1500.0
SAME_WAY_STRONG_BONUS_M = 1800.0
SAME_WAY_WEAK_BONUS_M = 700.0

#: 送程每米折算的"远离"米数。骑手关心的是整单划不划算,不只是"去拿餐多远"。
#: 取 0.35 而不是 1.0:送程虽然要跑,但它**有配送费覆盖**,
#: 而去取餐的路是白跑的 —— 白跑的路更该被惩罚。
TRIP_WEIGHT = 0.35


@dataclass(frozen=True)
class Candidate:
    """参与排序的一个候选单(全部距离单位:米)。"""

    to_pickup_m: float
    """骑手当前位置 → 取餐点。取不到骑手位置时为 None 的调用方不应走打分路径。"""

    trip_m: float
    """取餐点 → 送达点。"""

    wait_minutes: float
    tip_yuan: float
    same_shop: bool
    detour_m: float | None
    """绕路增量;手头没有在途单时为 None(无从谈顺路)。"""


def trip_economics(
    to_pickup_m: float,
    trip_m: float,
    wait_minutes: float,
    fee_cents: int,
    tip_cents: int,
    *,
    severe_weather: bool = False,
) -> dict:
    """整单的耗时与时薪估算(#142)。

    骑手真正要判断的不是"到店多远",而是**这一单值不值得接**:
    跑多远 / 花多久(含在店等餐)/ 挣多少。

    每分钟收入是骑手用来横向比较的量 —— 一个 3 公里 8 块的单和一个
    1 公里 4 块的单哪个划算,不看总价看时薪。

    骑行时间走 labor_guard(速度是常量,不由骑手表现训练)。
    """
    from . import labor_guard

    ride = (labor_guard.ride_minutes(to_pickup_m, severe_weather=severe_weather)
            + labor_guard.ride_minutes(trip_m, severe_weather=severe_weather))
    total = ride + max(0.0, wait_minutes)
    income = fee_cents + tip_cents
    return {
        "total_minutes": round(total, 1),
        "ride_minutes": round(ride, 1),
        "wait_minutes": round(max(0.0, wait_minutes), 1),
        "income_cents": income,
        # 时薪估算:总耗时为 0 时不除(理论上不会,但除零会让整个抢单池 500)
        "cents_per_minute": round(income / total, 1) if total > 0 else 0,
    }


@dataclass(frozen=True)
class Scored:
    score: float
    same_way_level: str      # strong / weak / none
    breakdown: dict[str, float]


def same_way_level(detour_m: float | None) -> str:
    """顺路等级。手头没单时一律 none —— 没有基准就不该声称顺路。"""
    if detour_m is None:
        return "none"
    if detour_m < SAME_WAY_STRONG_MAX_M:
        return "strong"
    if detour_m < SAME_WAY_WEAK_MAX_M:
        return "weak"
    return "none"


def score(c: Candidate) -> Scored:
    """综合分。**越小越靠前。**

    口径:全部折算成"等效米数"。正项是成本(要跑的路),负项是优先度加成。
    统一成米是为了能讲清楚 —— 骑手问"小费 3 块能提前多少",
    答案是"相当于近 900 米",这句话他听得懂。
    """
    wait_bonus = min(c.wait_minutes * WAIT_WEIGHT_M_PER_MIN, WAIT_BONUS_MAX_M)
    tip_bonus = min(c.tip_yuan * TIP_WEIGHT_M_PER_YUAN, TIP_BONUS_MAX_M)
    shop_bonus = SAME_SHOP_BONUS_M if c.same_shop else 0.0

    level = same_way_level(c.detour_m)
    way_bonus = {
        "strong": SAME_WAY_STRONG_BONUS_M,
        "weak": SAME_WAY_WEAK_BONUS_M,
        "none": 0.0,
    }[level]

    trip_cost = c.trip_m * TRIP_WEIGHT

    total = (c.to_pickup_m + trip_cost
             - wait_bonus - tip_bonus - shop_bonus - way_bonus)
    return Scored(
        score=total,
        same_way_level=level,
        breakdown={
            "to_pickup_m": round(c.to_pickup_m, 1),
            "trip_cost_m": round(trip_cost, 1),
            "wait_bonus_m": round(-wait_bonus, 1),
            "tip_bonus_m": round(-tip_bonus, 1),
            "same_shop_bonus_m": round(-shop_bonus, 1),
            "same_way_bonus_m": round(-way_bonus, 1),
            "total": round(total, 1),
        },
    )


def _labor_promises() -> list[str]:
    from . import labor_guard
    return list(labor_guard.LABOR_PROMISES)


def _labor_spec() -> dict:
    from . import labor_guard
    return labor_guard.public_spec()


def _weather_spec() -> dict:
    from . import weather
    return weather.public_spec()


def public_spec() -> dict:
    """给 /transparency/dispatch 用的算法说明。

    **从上面的常量读,不另写字面量。** 抄一份的话迟早和真实算法对不上,
    那时公开的就是假的。有测试钉住这件事。
    """
    return {
        "formula": (
            "综合分 = 到取餐点距离 + 送程距离×{trip} "
            "− 等待加成 − 小费加成 − 同店加成 − 顺路加成;越小越靠前"
        ).format(trip=TRIP_WEIGHT),
        "unit": "全部折算成「等效米数」——问「小费 3 块能提前多少」,"
                "答案是「相当于近 900 米」,这句话骑手听得懂",
        "weights": [
            {
                "key": "wait",
                "name": "等待时长",
                "value": f"每 1 分钟 ≈ 靠近 {WAIT_WEIGHT_M_PER_MIN:.0f} 米",
                "cap": f"最多 {WAIT_BONUS_MAX_M:.0f} 米",
                "why": "让久等的单不至于永远垫底。设上限是因为:等太久的单"
                       "该走「无人接单兜底」(提醒在线骑手、必要时全额退款并"
                       "赔付商家餐损),而不是靠把它顶到榜首硬推给骑手。",
            },
            {
                "key": "tip",
                "name": "小费",
                "value": f"每 1 元 ≈ 靠近 {TIP_WEIGHT_M_PER_YUAN:.0f} 米",
                "cap": f"最多 {TIP_BONUS_MAX_M:.0f} 米",
                "why": "这是「钱能买多靠前」的定价,所以必须封顶 —— 不封顶就意味着"
                       "出得起钱的人永远排最前。超过上限的小费骑手照收,"
                       "但不再买到更靠前的位置。小费 100% 归骑手,平台分文不取。",
            },
            {
                "key": "same_shop",
                "name": "同商家",
                "value": f"≈ 靠近 {SAME_SHOP_BONUS_M:.0f} 米",
                "cap": None,
                "why": "在同一家店多取一单,取餐环节几乎零成本,"
                       "比「路线接近」值钱得多,所以权重更高。",
            },
            {
                "key": "same_way",
                "name": "顺路",
                "value": (f"强顺路(绕路 < {SAME_WAY_STRONG_MAX_M:.0f} 米)"
                          f" ≈ 靠近 {SAME_WAY_STRONG_BONUS_M:.0f} 米;"
                          f"弱顺路(绕路 < {SAME_WAY_WEAK_MAX_M:.0f} 米)"
                          f" ≈ 靠近 {SAME_WAY_WEAK_BONUS_M:.0f} 米"),
                "cap": None,
                "why": "按**绕路增量**判定,不按两点距离。绕路增量 = 接了这单要比"
                       "只送手头单多跑多远 —— 这才是骑手真正付出的成本。",
            },
            {
                "key": "trip",
                "name": "送程",
                "value": f"每 1 米 ≈ 远离 {TRIP_WEIGHT} 米",
                "cap": None,
                "why": "骑手关心整单划不划算,不只是「去拿餐多远」。"
                       f"系数取 {TRIP_WEIGHT} 而不是 1:送程有配送费覆盖,"
                       "而去取餐的路是白跑的,白跑的路更该被惩罚。",
            },
        ],
        "same_way_definition": {
            "formula": "绕路增量 =(当前位置 → 新单取餐 → 新单送达 → 手头单送达)"
                       "−(当前位置 → 手头单送达)",
            "why": "原先用「两个送达点相距 < 800 米」判顺路。实测反例:"
                   "送达点相邻、取餐点却在反方向 3 公里的单也会被判成顺路,"
                   "实际多跑近 6 公里。两点距离没有物理意义,绕路增量有。",
        },
        "distance": {
            "source": "腾讯位置服务骑行路径规划;不可用时回退直线距离 × 1.2 并标明",
            "why": "直线距离系统性低估。实测成都两点:直线 1467 米、"
                   "骑行 1745 米,差 19%。配送费按距离算且 100% 归骑手,"
                   "用低估的距离去算,承诺就打了折。",
        },
        # 劳动者保护的承诺从 labor_guard 读 —— 那里是那条原则的执行点,
        # 在这里再抄一份就会两边对不上
        "never_do": [
            "不做强制派单 —— 广播抢单,接不接始终是骑手自己的决定",
            "不按骑手评分或等级差别对待 —— 同一批单,所有在线骑手看到的口径一致",
            "不因为骑手拒过单、转过单就降权 —— 拒单不进任何权重",
            "不因为骑手在线时长短就压低他能看到的单",
        ] + _labor_promises(),
        "labor_guard": _labor_spec(),
        "weather": _weather_spec(),
        "changelog": CHANGELOG,
    }


#: 权重变更历史。**改了算法就要记一笔。**
#: 算法可以改,但不能悄悄改 —— 悄悄改就等于从没公开过。
CHANGELOG = [
    {
        "date": "2026-08-29",
        "what": "等餐超时补偿改为运行时开关,当前默认关闭;"
                "恶劣天气加价从「判定即生效」改为「判定后提请平台审核,"
                "审核通过才对该区域生效」。",
        "why": "等餐补偿由平台承担,而平台现阶段没有这笔预算 —— "
               "承诺一笔付不出的钱,比不承诺更坏;机制与审计口径全部保留,"
               "有预算后一键恢复。天气加价直接改用户实付,"
               "自动判定误报(气象格点漂移、短时阵雨)会让用户多花冤枉钱,"
               "所以加一道人工确认;代价是响应变慢,这是有意的取舍。",
    },
    {
        "date": "2026-08-01",
        "what": "排序纳入整单预计耗时与每分钟收入;出餐等待改用商家实测分位数;"
                "新增劳动者保护红线(ETA 只许放宽不许收紧、骑行速度写死不训练、"
                "疲劳提醒但不断单);恶劣天气改为按区县自动判定,"
                "加价的同时放宽时限;配送费加入等餐超时补偿(平台承担)。",
        "why": "旧口径下,骑手看不出一单整体划不划算(只显示到店距离);"
               "出餐等待用的是写死的 20 分钟;恶劣天气靠管理员手动全局开关 ——"
               "成都下暴雨北京也加价,北京下雪没人开开关骑手就白挨冻。"
               "更要紧的是:用实际表现反过来收紧时限,是把骑手逼到"
               "逆行闯灯的那套机制,必须从代码层面堵死。",
    },
    {
        "date": "2026-07-31",
        "what": "顺路判定由「两个送达点相距 < 800 米」改为「绕路增量分档」;"
                "顺路与同商家开始**真正参与排序**(此前只是 UI 标记,不进综合分);"
                "排序纳入送程;等待与小费加成加上限;距离改用骑行路径规划。",
        "why": "旧口径下,送达点相邻但取餐点在反方向 3 公里的单会被标成顺路,"
               "骑手照着接会多跑近 6 公里;而真顺路的单在排序上又毫无优势。",
    },
]
