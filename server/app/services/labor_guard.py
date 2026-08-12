"""劳动者保护(#144)。**这个模块是本辑的地基,其余功能都要服从它。**

## 要防的是什么

外卖行业最被诟病的一件事:系统不断压缩配送时间,骑手为了不超时逆行、闯灯、
边骑边看手机。**那不是骑手不守规矩,是算法把人逼到那一步。**

机制是这样形成的:平台用「实际送达时间」反过来训练「预计送达时间」,
骑手跑得越快,系统认为越应该更快 —— 一个自我收紧的循环。
跑得快的人不是被奖励,是被加码。

## 不可协商的原则

> **任何由骑手实际表现算出来的统计量,都不得用于收紧对骑手的要求。**

出餐时长统计用来治理**商家**、给骑手**更准的预期**、给平台**定更合理的配送费**
—— 但**不用来缩短骑手的时限**。

本模块提供的 [clamp_eta_minutes] 就是这条原则的执行点:
ETA 只能被放宽,不能被收紧。有测试钉着。
"""
from __future__ import annotations

import logging

# ---------------------------------------------------------------------------
# 骑行速度。**写死在这里,不由实际数据训练。**
#
# 这是整条原则最关键的一个数:一旦允许它跟着骑手的实际速度走,
# 自我收紧的循环就建立起来了 —— 骑手跑得快 → 速度上调 → 时限变紧 →
# 只能跑更快。这个数必须是常量。
#
# 15 km/h 是**保守**取值:电动车空载能跑 25,但真实配送包含等红灯、
# 找楼栋、爬楼、等电梯、找不到门牌打电话。按巡航速度算 ETA,
# 等于默认骑手一路绿灯且送到楼下就完事。
# ---------------------------------------------------------------------------
logger = logging.getLogger("superz.labor_guard")

RIDE_SPEED_KMH = 15.0

#: 恶劣天气时的骑行速度(km/h)。下雨路滑、视线差,**慢是应该的**。
#: 与加价配套:只加价不放宽时限,等于用钱买骑手冒险。
RIDE_SPEED_KMH_SEVERE = 11.0

#: 连续在线多久提醒休息(分钟)
FATIGUE_REMIND_MINUTES = 4 * 60

#: 连续在线多久降低推送频率并置顶休息提示(分钟)。
#: **不硬性禁止接单** —— 骑手要吃饭,一刀切断人家收入是另一种不尊重。
#: 但平台不能装作没看见。
FATIGUE_THROTTLE_MINUTES = 8 * 60


#: 路网时长的上界,按常量估算的倍数。
#:
#: 路网时长是**外部数据**,而 clamp_eta_minutes 只挡收紧、不挡放宽 ——
#: 一个离谱的值(坐标落到河对岸、路网数据错、接口抽风)会直接变成给顾客的
#: 承诺:3 公里的单承诺 4 小时送到。顾客不会等,他会取消。
#:
#: 2.0 是宽松但有效的界:市区多灯的路线合理范围大概在常量的 1.0~1.5 倍,
#: 超过 2 倍基本不是"路口多",是数据错了。超界时取上界并记日志。
ROUTE_MINUTES_MAX_FACTOR = 2.0


def ride_minutes(distance_m: float, *, severe_weather: bool = False,
                 route_minutes: float | None = None) -> float:
    """骑行时间(分钟)。速度是常量,不随骑手实际表现变化。

    ## route_minutes:路线级余量(#268)

    常量速度是**一个平均值拍在所有路线上** —— 市区过 8 个红灯和郊区
    一条直路拿的是同一份余量。传进腾讯路网算出来的时长(骑行接口的
    `routes[0].duration`,单位分钟)可以补上这个差。

    **只取更大的那个,这个方向不能反:**

    - 路网时长更短时**用常量的** —— 它算的是纯骑行,不含取餐、找楼栋、
      爬楼、打电话找不到门牌。照它给 ETA 就是把这些时间从骑手身上抠掉;
    - 路网时长更长时(市区多灯多路口)用它,这正是要补的那个缺口。

    所以这条改动**只可能放宽 ETA,不可能收紧**。

    ## 为什么这不违反「速度常量不许训练」那条红线

    路网时长是**路况数据**,不是我们骑手跑出来的数。红线防的是
    「骑手跑得快 → 速度上调 → 时限变紧 → 只能跑更快」这个自我收紧循环,
    而腾讯的数跟我们哪个骑手跑多快没有关系。

    ⚠️ 下一个人看到这里可能会想「那用骑手实际耗时不是更准」——
    **不行**,那正是红线挡的东西。

    ## 恶劣天气照样取 max

    恶劣天气用更慢的常量速度(11km/h),多数情况下它已经比路网长了。
    但**万一路网更长**(暴雨天的市区高峰),还是该用路网 ——
    「只放宽」这条规则不该因为天气就开个例外。

    ## 上界

    路网时长是外部数据,而 clamp_eta_minutes 只挡收紧不挡放宽 ——
    一个离谱的值会直接变成给顾客的承诺(3 公里承诺 4 小时)。
    所以超过常量的 [ROUTE_MINUTES_MAX_FACTOR] 倍就截断并记日志:
    那基本不是"路口多",是坐标或路网数据错了。
    """
    speed = RIDE_SPEED_KMH_SEVERE if severe_weather else RIDE_SPEED_KMH
    constant = distance_m / 1000 / speed * 60
    if route_minutes is None or route_minutes <= 0:
        return constant
    ceiling = constant * ROUTE_MINUTES_MAX_FACTOR
    route = float(route_minutes)
    if route > ceiling:
        logger.warning(
            "路网时长 %.1f 分钟超过常量估算 %.1f 的 %.1f 倍,按上界截断 —— "
            "多半是坐标或路网数据有问题,不是路口多",
            route, constant, ROUTE_MINUTES_MAX_FACTOR)
        route = ceiling
    return max(constant, route)


# 爬楼:每层多算的分钟数。上楼提着餐、下楼还要走一趟,
# 一层一分钟是保守估计。有电梯的按 2 分钟固定(等电梯 + 上下),
# 不按层数累加 —— 20 楼有电梯并不比 5 楼有电梯慢多少
STAIR_MINUTES_PER_FLOOR = 1.0
ELEVATOR_MINUTES = 2.0
# 一楼不算爬楼
GROUND_FLOOR = 1


def floor_minutes(floor: int | None, has_elevator: bool | None) -> float:
    """楼层带来的额外时长(分钟)。

    **没填就是 0**:猜一个出来会让 ETA 变成假承诺 —— 顾客看到的时间
    不该建立在我们对他家几楼的猜测上。

    这个数**加进给顾客看的 ETA**,不是只放宽骑手的判定 ——
    因为爬 6 楼确实更慢,一个诚实的 30 分钟好过一个乐观的 25 分钟再超时。
    平台的立场一贯是"先说清楚再让用户下单",这里是同一条。
    """
    if not floor or floor <= GROUND_FLOOR:
        return 0.0
    if has_elevator:
        return ELEVATOR_MINUTES
    # 无电梯:爬到几楼算几层。上限 30 层 —— 再高的多半是填错了,
    # 而一个填错的楼层不该把 ETA 撑到离谱
    return min(floor, 30) * STAIR_MINUTES_PER_FLOOR


def clamp_eta_minutes(proposed: float, baseline: float) -> float:
    """**ETA 单向钳制:只许放宽,不许收紧。**

    `baseline` 是按常量速度算出来的保底时长;`proposed` 是任何其他来源
    (实测统计、路况修正、商家出餐分位数……)给出的建议值。

    返回二者中**更宽松**的那个。

    为什么必须有这个函数:少了它,任何一处"我们用实测数据优化一下 ETA"
    的改动都可能悄悄把时限收紧 —— 而那正是把骑手逼到逆行闯灯的机制。
    它写成一个显式的、有名字的、有测试的函数,就是为了让收紧这件事
    **无法不小心发生**:想收紧就必须显式绕过它,而绕过它会在评审里被看见。
    """
    return max(proposed, baseline)


def fatigue_level(online_minutes: float) -> str:
    """疲劳等级:none / remind / throttle。

    throttle 只降低推送频率并置顶提示,**不禁止抢单**。
    """
    if online_minutes >= FATIGUE_THROTTLE_MINUTES:
        return "throttle"
    if online_minutes >= FATIGUE_REMIND_MINUTES:
        return "remind"
    return "none"


def fatigue_message(level: str, online_minutes: float) -> str | None:
    hours = online_minutes / 60
    if level == "throttle":
        return (f"你已经连续在线 {hours:.1f} 小时了。"
                "接单照常,但我们把新单提醒调慢了 —— 该歇会儿了。")
    if level == "remind":
        return f"连续在线 {hours:.1f} 小时,记得找地方歇一歇、喝口水。"
    return None


#: 承诺不做的事(进 /transparency/dispatch 的 never_do)。
#: **每一条都有对应测试** —— 承诺要能被验证,否则只是话术。
LABOR_PROMISES = [
    "不用骑手的实际速度反过来缩短配送时限 —— "
    "骑行速度是写死的常量,跑得快不会被加码",
    "预计送达时间只会因路况、天气变宽,不会因为你跑得快而变紧",
    "出餐慢造成的延迟不算在骑手头上 —— 那是商家的问题,不是你的",
    "恶劣天气加价的同时一定放宽时限 —— 只加价不放宽,等于用钱买你冒险",
    "连续在线过久会提醒你休息,但**不会断你的单** —— "
    "一刀切断收入是另一种不尊重",
]


def public_spec() -> dict:
    """劳动者保护的公开说明。常量从上面读,不另抄一份。"""
    return {
        "principle": "任何由骑手实际表现算出来的统计量,"
                     "都不得用于收紧对骑手的要求",
        "why": "平台用「实际送达时间」反过来训练「预计送达时间」,"
               "骑手跑得越快系统认为越该更快 —— 一个自我收紧的循环。"
               "跑得快的人不是被奖励,是被加码。这就是骑手被逼到"
               "逆行、闯灯、边骑边看手机的机制。",
        "ride_speed": {
            "normal": f"{RIDE_SPEED_KMH} 公里/小时",
            "severe_weather": f"{RIDE_SPEED_KMH_SEVERE} 公里/小时",
            "why": "写死的常量,不由实际数据训练。取值保守:电动车空载能跑 25,"
                   "但真实配送包含等红灯、找楼栋、爬楼、等电梯、"
                   "找不到门牌打电话 —— 按巡航速度算 ETA,"
                   "等于默认骑手一路绿灯且送到楼下就完事。",
        },
        "fatigue": {
            "remind_after": f"{FATIGUE_REMIND_MINUTES // 60} 小时",
            "throttle_after": f"{FATIGUE_THROTTLE_MINUTES // 60} 小时",
            "what_throttle_means": "只降低新单提醒频率并置顶休息提示,"
                                   "**不禁止接单**",
        },
        "promises": LABOR_PROMISES,
    }
