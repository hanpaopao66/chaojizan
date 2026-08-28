"""订单异常的判责与分摊口径。**这是对外公开的承诺,不是内部实现细节。**

原则一句话:**谁的问题,谁负责;平台不出补贴。**

## 「平台承担」不等于「平台补贴」

平台立场是不靠补贴换增长(用户端「我们承诺不做的事」印着这句)。但那说的是
**营销补贴** —— 拿钱买增长。而无人接单时平台赔商家、等餐超时平台补骑手,
性质完全不同:那是**履约成本**,而且恰恰是因为「运力不足确实是平台的问题」,
是「谁的问题谁负责」的结果,不是它的例外。这个区分 pricing.py 里已经写过一次,
这里是同一条。

## 唯一的例外:向责任方收钱会制造更坏的激励时,改用数据治理

骑手到店等餐,责任在商家(出餐慢),但补偿由平台出。理由见
`pricing.wait_compensation_cents`:**转嫁商家会让商家宁可晚点按「出餐」**,
数据一失真,出餐时长统计、ETA、派单全跟着歪。所以「治理靠数据,不靠罚钱」。

这条例外的判据是明确的 —— **只在"罚责任方会污染平台赖以判断的数据"时适用**,
不是一个可以随便援引的口子。

## 分摊按「成本发生的时刻」切,不按状态名切

判责之所以能有客观标准,是因为订单每往前走一步,就有一笔成本**真实发生
且不可回收**:

    未接单      无人垫成本                    → 取消全额退,谁都不受损
    备餐中      商家开始备餐(部分)            → 仍全额退(反悔窗口内)
    已出餐      餐费成本 100% 发生            → 餐费不可回收
    骑手到店    骑手已空跑一趟                → 那趟路白跑了
    配送中      骑手劳动已付出                → 配送费已挣到

所以分界线落在这些**事实**上(`order.status` + `arrived_shop_at`),
不落在客服的主观判断上。规则化得了的就规则化,规则化不了的
(餐损、送错、做错菜)才进人工仲裁 —— 那些本来就该有人看。

## 取消场景平台一律不收佣金

佣金是平台在一单上的**全部**收入,也是出问题时平台唯一能自己让出去的部分。
这单没走完,平台没提供完整服务,就不该收这笔钱。**这不是补贴** ——
补贴是倒贴钱买增长,这是没做完的服务不收费。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 分摊阶段。按成本发生的时刻命名,**不按订单状态名命名** ——
# 状态是实现,成本是事实,对外解释和写测试都该对着事实。
# ---------------------------------------------------------------------------

#: 未接单 / 接单后反悔窗口内:无人垫过成本
STAGE_BEFORE_COST = "before_cost"
#: 已出餐,骑手还没到店:餐费成本已发生
STAGE_COOKED = "cooked"
#: 已出餐,骑手已到店但还没取餐:餐费 + 骑手白跑一趟
STAGE_RIDER_ARRIVED = "rider_arrived"
#: 已取餐配送中:餐费 + 骑手劳动都已付出
STAGE_IN_DELIVERY = "in_delivery"

STAGE_LABELS = {
    STAGE_BEFORE_COST: "还没有人垫成本",
    STAGE_COOKED: "商家已出餐",
    STAGE_RIDER_ARRIVED: "骑手已到店",
    STAGE_IN_DELIVERY: "骑手已取餐,配送中",
}

# ---------------------------------------------------------------------------
# 唯一一个"定价"参数。**其余规则都是 0 或 100%,不需要拍脑袋的数。**
# ---------------------------------------------------------------------------

#: 骑手到店但没取到餐时,按配送费的这个比例给他「空跑费」。
#:
#: 为什么需要这个数:配送费是按**商家→用户**的距离算的,骑手→商家那一段
#: 本来就不单独计费 —— 它是骑手为了挣这笔配送费而做的投入。单被取消,
#: 这份投入就打了水漂,而这不是他的问题。
#:
#: 为什么是二分之一:配送费覆盖的是"取餐 + 送达"这一整趟,他完成了取餐段、
#: 没完成送达段。**这个数是可以调的,而且应该由人来定,不该由代码默认** ——
#: 它是这套口径里唯一一个"多少算公平"的判断,写在这里就是为了让它显眼。
IDLE_TRIP_SHARE = 0.5


@dataclass
class Line:
    """账单上的一行。`to` 是这笔钱的去向,`why` 是给用户看的原话。"""

    name: str
    cents: int
    to: str          # customer 退回用户 / merchant 归商家 / rider 归骑手 / platform
    why: str


@dataclass
class Split:
    """一次取消的完整账目。四方相加必须等于用户已付的总额。"""

    stage: str
    refund_cents: int = 0      # 退回用户
    merchant_cents: int = 0    # 商家保留(应收口径,已扣满减)
    rider_cents: int = 0       # 骑手拿到
    commission_cents: int = 0  # 平台收(取消场景恒为 0)
    food_to: str = ""          # 餐的去向说明;没有餐时为空
    lines: list[Line] = field(default_factory=list)

    @property
    def total_cents(self) -> int:
        return (self.refund_cents + self.merchant_cents
                + self.rider_cents + self.commission_cents)


def stage_of(status: str, *, rider_arrived: bool) -> str:
    """把订单状态翻成分摊阶段。**只管出餐之后**。

    出餐之前的取消由既有规则处理(未接单随时退、接单后 2 分钟反悔窗口、
    商家超时未出餐可自助全退),那套规则已经上线、已经推敲过,
    这个模块不重复实现也不覆盖它 —— 传进来直接抛,让调用方走原路。
    """
    if status == "ready":
        return STAGE_RIDER_ARRIVED if rider_arrived else STAGE_COOKED
    if status == "picked_up":
        return STAGE_IN_DELIVERY
    raise ValueError(
        f"「{status}」不归分摊口径管:出餐之前的取消走既有的全额退款规则")


#: 出餐之前为什么不归这里管。
#:
#: 商家点没点「出餐」平台看得见,锅里有没有东西平台看不见。所以出餐之前
#: 只能用**时间**当代理判据 —— 那就是既有的 2 分钟反悔窗口,以及"商家超时
#: 未出餐可自助全退"。那套规则的取舍已经做过了,这次不动它。
#:
#: 这里要补的是出餐**之后**的那段:成本已经真实发生、平台看得见发生了多少,
#: 于是可以按事实分摊,而不是继续用"一律禁止取消"这一个粗手段。
WHY_BEFORE_COOK_UNCHANGED = (
    "出餐之前平台看不见商家做没做,只能用时间当代理判据 —— "
    "那套规则(2 分钟反悔窗口、商家超时可全退)已经在跑,这次不改。"
    "出餐之后成本看得见,才谈得上按事实分摊。"
)

#: 提前点出餐的对抗信号。**只识别,不自动处罚**(治理靠数据不靠罚钱)。
EARLY_READY_WATCH = (
    "出餐是商家自己点的,而出餐之后用户失去全额退款权、餐费也保住了 —— "
    "商家因此有动机提前点。出餐到骑手取餐的间隔异常长会暴露这件事,"
    "平台只在管理端标出来,不自动扣钱。"
)


def split_for_cancel(
    stage: str,
    *,
    food_cents: int,
    packing_fee_cents: int,
    discount_cents: int,
    delivery_fee_cents: int,
    tip_cents: int,
) -> Split:
    """算一次用户取消的四方账。纯函数,不查库不看表。

    入参就是订单上那几个钱字段;商家应收口径与 settlement.credit_merchant
    保持一致(菜品 + 打包 − 满减,钳 0)。
    """
    # **先钳 0 再加总。** 商家应收钳了 0(与 settlement.credit_merchant 同口径),
    # 用户已付这边就必须用同一个钳过的数 —— 否则满减大于餐费时,
    # 一边是负数一边是 0,四方永远对不平。单测 test_满减大于餐费时商家不倒扣
    # 就是踩着这个写的。
    merchant_gross = max(food_cents + packing_fee_cents - discount_cents, 0)
    paid = merchant_gross + delivery_fee_cents + tip_cents
    s = Split(stage=stage)

    if stage == STAGE_BEFORE_COST:
        s.refund_cents = paid
        s.lines = [Line("全部", paid, "customer",
                        "还没有人垫过成本,全额退回")]
        return s

    # 出餐之后:餐费一律不退,归商家。商家没做错任何事,而餐不可回收。
    s.merchant_cents = merchant_gross
    s.lines.append(Line("餐费 + 打包费", merchant_gross, "merchant",
                        "餐已经做好了,商家没做错任何事,这笔成本收不回来"))

    if stage == STAGE_COOKED:
        # 骑手还没到店,配送这段一点没发生 —— 全退用户
        s.refund_cents = delivery_fee_cents + tip_cents
        s.lines.append(Line("配送费 + 小费", delivery_fee_cents + tip_cents,
                            "customer", "骑手还没到店,配送还没开始"))
    elif stage == STAGE_RIDER_ARRIVED:
        idle = min(int(delivery_fee_cents * IDLE_TRIP_SHARE), delivery_fee_cents)
        s.rider_cents = idle
        s.refund_cents = delivery_fee_cents - idle + tip_cents
        s.lines.append(Line("空跑费", idle, "rider",
                            "骑手已经到店,这趟路白跑了,不是他的问题"))
        s.lines.append(Line("配送费余额 + 小费",
                            delivery_fee_cents - idle + tip_cents, "customer",
                            "剩下的配送段没有发生,退回"))
    elif stage == STAGE_IN_DELIVERY:
        # 配送费归骑手是既有原则(售后冲账都不冲他),这里同口径
        s.rider_cents = delivery_fee_cents + tip_cents
        s.lines.append(Line("配送费 + 小费", delivery_fee_cents + tip_cents,
                            "rider", "骑手已经取餐上路,这趟劳动付出了"))
        s.food_to = ("这份餐归骑手处置 —— 餐在他车上,送回商家也不能再卖。"
                     "这不是奖励,是让一份已经发生的成本少浪费一点。")
    else:
        raise ValueError(f"未知的分摊阶段:{stage}")

    # 平台佣金:取消场景恒为 0。放在最后单列一行,让用户看见平台让掉了什么。
    s.lines.append(Line("平台佣金", 0, "platform",
                        "这一单没走完,平台没有提供完整服务,所以不收"))
    assert s.total_cents == paid, (s.total_cents, paid)
    return s


#: 分摊入账行的备注前缀。**审计靠它把这条钱路径认出来**,所以定义在这里、
#: 结算和审计两边都从这儿读 —— 各写一遍的话,哪天改了一处,审计就会悄悄
#: 漏掉一整类单子(而漏掉的表现是"全绿",不是报错)。
#:
#: 取消单上已经有两种不同的钱路径,必须分得清:
#:   无人接单兜底  商家拿全额、用户也全额退 —— 差额是**平台认赔**
#:   判责分摊      商家 + 骑手 + 退款 == 用户已付 —— 平台不垫钱
SPLIT_EARNING_NOTE = "用户取消,判责分摊"


#: 承诺不做的事。**每一条都有对应测试** —— 承诺要能被验证,否则只是话术。
#: 与 labor_guard.LABOR_PROMISES 同一个规矩。
LIABILITY_PROMISES = [
    "取消订单时平台一分佣金都不收 —— 没走完的服务不收钱",
    "配送费和小费一分不抽,全归骑手;骑手已经付出的劳动,不会因为"
    "订单被取消而白干",
    "不会因为用户取消,就让商家自己吞掉已经做好的餐",
    "不拿「可能已经开始做了」这种平台看不见的事实去扣用户的钱",
    "每一次取消都出示完整账单:每一分钱去了哪、为什么 —— "
    "不会只给一句「不支持退款」",
]


def public_spec() -> dict:
    """判责与分摊的公开说明(/transparency/liability)。

    数字从上面的常量直接读,**不另抄一份** —— 抄一份的话改了代码忘了改
    公示,公示就成了假的。有测试钉着这件事。
    """
    return {
        "principle": "谁的问题,谁负责。平台不出补贴。",
        "what_platform_bears": {
            "rule": "责任在平台时,平台自己赔;这是履约成本,不是补贴",
            "examples": [
                "运力不足没人接单:用户全额退,已出餐的商家由平台按应收全额赔,"
                "佣金一分不收",
                "骑手到店等餐:补偿由平台出",
            ],
            "why_not_subsidy": "补贴是拿钱买增长;这些是没做好本职工作的赔偿。"
                               "两者都花钱,但性质不同。",
        },
        "the_one_exception": {
            "case": "骑手等餐,责任在商家,却由平台补",
            "why": "转嫁商家会让商家宁可晚点按「出餐」。数据一失真,"
                   "出餐时长统计、预计送达、派单全跟着歪。治理靠数据,不靠罚钱。",
            "scope": "只在「罚责任方会污染平台赖以判断的数据」时适用,"
                     "不是一个可以随便援引的口子。",
        },
        "stages": [
            {"stage": k, "label": v,
             "cost_incurred": _STAGE_COST_TEXT[k]} for k, v in STAGE_LABELS.items()
        ],
        "idle_trip_share": {
            "value": IDLE_TRIP_SHARE,
            "means": f"骑手到店没取到餐时,拿配送费的 {IDLE_TRIP_SHARE:.0%}",
            "why": "配送费覆盖「取餐 + 送达」一整趟,他完成了取餐段。",
        },
        "why_before_cook_unchanged": WHY_BEFORE_COOK_UNCHANGED,
        "early_ready_watch": EARLY_READY_WATCH,
        "promises": LIABILITY_PROMISES,
        "appeal": {
            "who": "用户、商家、骑手都能对平台的判责结果申诉",
            "window_hours": 72,
            "what_happens": "平台复核。改判时平台认亏,不向任何一方追款。",
        },
    }


_STAGE_COST_TEXT = {
    STAGE_BEFORE_COST: "没有任何一方垫过不可回收的成本",
    STAGE_COOKED: "餐费成本已经 100% 发生",
    STAGE_RIDER_ARRIVED: "餐费已发生,而且骑手白跑了一趟",
    STAGE_IN_DELIVERY: "餐费已发生,骑手的劳动也已经付出",
}
