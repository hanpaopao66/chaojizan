"""信用分:顾客、商家、骑手三种角色,同一套机制。0–100,公式公开,可以申诉。

顾客的先做(2026-09);2026-09-14 拍板:顾客那套权重不改,商家和骑手也有分,用同一套机制 ——
同一个公式、同一个时间窗、同一套等级、同一套申诉和可见范围,只有「什么算扣分」按角色不同,
因为三种角色能做错的事本来就不一样(和 enforcement.CATALOG 同一个道理)。

## 和「不做分数」那条立场的关系

services/enforcement.py 的抬头写了处置为什么不做分数:分数没法申诉(「我为什么是 72 分」
没有答案)、慢和坏会被折进同一个数轴、一旦有分行为就为分服务。这个信用分是拍板要做的,
设计上逐条回应:

1. **每一分都指回一条记录。**「为什么是 72」的答案是一张清单:基础 90、最近完成 2 单 +2、
   某年某月某单的那条判定 −10、某条违规 −10。每一条扣分都能单独申诉,成立立刻重算。
   分数不落库,永远从原始记录现算(缓存随时可丢)。
2. **只扣平台判定成立、当事人能申诉的事,不扣「做得不好」。** 慢、少、晚、差评都不进来,
   正常的权利不扣分。每种角色算什么、不算什么见下面。
3. **它不改变任何人能看到什么、能接到什么、要付多少钱。** 判据是 models.py 那句 ——
   「这个数字会不会影响他能看到的单?会,就是绳索」。所以它只在**接单之后、这一单上、
   给这一单的交易对方**看,不进派单、定价、ETA、支付、店铺排序 / 曝光 / 搜索、抢单大厅、
   处置(处置照旧按违规计次,和分数高低无关)。
   ⚠️ 放上店铺页、列表、搜索,顾客就会按分挑店 —— 影响的是谁被看见;放进抢单大厅、新单推送,
   骑手就会按分挑店、挑顾客 —— 影响的是谁的单有人接。两样都是绳索。
   tests/unit/test_credit.py 按语法树守着:派单、定价、ETA、支付、处置、推送、开放接口、
   店铺列表 / 搜索、抢单池的代码里不许出现它;它进响应体只有两个口子。

## 三种角色各算什么

加分三种角色一样:最近 [WINDOW_DAYS] 天完成一单 +[ORDER_POINTS],最多 +[ORDER_CAP]。
追加单(随原单一起送,不是另一笔交易)、风控确认刷单的单(口径同月售剔除)不算;
各角色再排除「这一单你这一环没做成」的那种(见 [_order_rows])。

扣分只用确实存在、是结论、落得到记录上的数据(每一条都顺调用链核过,不是按字段名猜的):

- **顾客**:配送异常裁决「按送达处理」—— delivery_issues.resolution = mark_delivered,
  admin.resolve_delivery_issue 那一支写明「用户原因(联系不上 / 地址错)」;违规成立
  (violations.audience = customer)。
- **商家**:平台判出来的售后商家责任 —— after_sales.fault = merchant,**并且**是下面两条之一:
  ① appeals 里 after_sale_rejected 那条改判成立(顾客申诉「售后被拒」,appeals._overturn 那一支:
  「平台认定商家当初就该赔而他拒了」);② 骑手报「到店未出餐」「餐品不齐」、配送异常裁成退款
  判为商家责任时记的那条售后(admin.resolve_delivery_issue,services/delivery_fault);
  违规成立(violations.audience = merchant)。
  商家自己点「同意售后」的那种 fault 也写成 merchant(after_sales.accept_after_sale:「同意即认责」),
  但那是商家自己的决定,不是平台判的 —— **不算**。
- **骑手**:配送异常裁成退款、判骑手责任 —— delivery_issues.resolution = refund 而且不是
  「到店未出餐」「餐品不齐」(那两类判的是商家),admin 那一支写明「骑手责任」,骑手在 appeals 里
  正是按「判骑手责任」申诉的(钱怎么走见 services/rider_fault);售后仲裁判骑手责任 ——
  admin.after_sale_rider_fault 写的 after_sales.fault = rider(配送异常裁成退款时顺手补的那条
  售后记录不重复计);违规成立(violations.audience = rider)。

违规按 enforcement.CATALOG 的严重程度扣(严重 / 一般两档,见 [VIOLATION_POINTS]);
配送异常、售后判为你的责任,每次 −[FAULT_POINTS]。

### 起算日:旧裁决不算

扣分只算**起算日(config.credit_count_from,北京日期,含这一天)之后**的裁决和判定
(见 [count_from] / [counts])。以前后台处理配送异常的按钮叫「退款」,判的人不知道自己是在判
谁的责任、会扣谁的分 —— 拿那时候的裁决扣分,等于事后改了规则。

完成订单的加分**不跟着起算日走**,照常看最近 [WINDOW_DAYS] 天:起算日的理由是「当时判的人
不知道会算分」,完成一单没有这个问题,那是当事人实实在在做完的单,算上只对他有利;而要是
加分也从起算日算,每个老用户、老店、老骑手都会在那一天被清回起始分 —— 历史越长的人亏得越多。
公示里一句话说得清:「扣分只算某天起的裁决和判定」。起算日早于时间窗起点之后,它自然不再起作用。

### 商家的分记在店主名下

违规记在店主头上(models.Violation.subject_id:「连锁店员做的事记在店主头上 —— 处置的是
经营主体」),处置也按店主算(enforcement.level_for)。信用分和处置同一个主体:店主名下
各门店的单、售后、违规合在一起算一个分,连锁的各门店共用。店员、品牌经理没有自己的商家信用分。

## 正常的权利不扣分

逐条核过代码,理由公示在 [public_spec] 的 not_counted 里:

- 顾客:商家接单前取消、接单后 2 分钟内取消、出餐后按账取消、申请售后退款、给差评;
  评价被隐藏、商家「标记异常」、恶意售后黑名单开关、风控冻结待复核、社区处罚、排队被过号、
  住宿未入住也不算(不是结论,或者和交易对方无关)。
- 商家:接单前拒单(orders.transition 里 paid → cancelled,要写原因)、没来得及接单被系统取消、
  自己同意售后和缺货部分退款、拒绝售后(顾客没申诉,或者申诉被驳回)、接单后取消(只有平台判
  「私自取消」成立才算,那一条记在违规里)、出餐慢 / 出餐超时 / 骑手等餐(出餐时长那条君子协定)、
  差评和评分、食安投诉成立(平台先行垫付,after_sales.fault = platform;认定是食品安全事故的
  另记违规,不重复扣)、排队叫号和过号(不是订单)。
- 骑手:不抢单、下线、在线时长;转单(不管当天转了几次 —— 转多了是转单规则暂停当天抢单、
  次日恢复,没有人判过谁的对错);送得慢、超时;差评;上报配送异常(只有平台判为骑手责任的
  才算);报事故、SOS、强制取餐。

## 谁能看到

- 本人:分数、每一项加减分和对应的记录、到哪天不再计分、申诉入口(商家是店主本人);
- 交易对方:**接单之后、只在这一单上、只有分数和等级**(见 [visible_parties]);
- 平台客服:处理申诉时看明细;
- 别处一律没有:店铺页、搜索、列表、抢单大厅、新单推送、开放接口、WebSocket 都不带。
  只有 routers/orders.py 的订单列表和订单详情会带(见 [attach])。

## 缓存和失效

订单列表是轮询接口,不能每次现算。按角色、按人缓存在 Redis
(`credit:v{版本}:{角色}:{user_id}`,[CACHE_TTL_SECONDS]),只存分数和等级。
**事实变了就打掉,而且在提交之后打**,调用点:

- 订单完成(顾客、店主、骑手三方的加分都变):orders.transition、orders.pickup_verify、
  admin.resolve_delivery_issue(裁成退款直接完成)、auto_flow.sweep_once(自动确认收货、自取超时);
- 判定改变:admin.resolve_delivery_issue、admin.after_sale_rider_fault、admin.record_violation、
  admin.overturn_violation、admin.risk_verdict(刷单确认的单不算完成一单);
- 申诉改判:appeals.resolve_appeal(原来的申诉通道,三种角色都走它)、本模块的
  [resolve_ticket_appeal]。

打不掉(Redis 挂了、漏了一个调用点)时最多晚 TTL 那么久;时间窗滚动(记录满 WINDOW_DAYS 天
不再计分)也靠 TTL 带出来。本人看的明细页每次现算,不走缓存。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, null, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..config import settings
from ..redis_client import get_redis

# ---------------------------------------------------------------------------
# 公式。**公示的就是这几个常量** —— /transparency/credit 从 public_spec() 读,
# 规则页从 rules_lines() 读,计算从 compute() 读,三处是同一份,三种角色也是同一份
# ---------------------------------------------------------------------------

#: 口径一变就升:缓存键带着它,部署之后不会拿旧口径的缓存回答。
#: v2:商家、骑手也有了,缓存键带上角色;v3:扣分只算起算日之后的;
#: v4:到店未出餐、餐品不齐裁成退款判的是商家责任(扣商家的、不扣骑手的)
FORMULA_VERSION = 4

#: 起始分。新来的就是这个分,和没有问题的老人在同一个等级,理由见 public_spec 的 base_why
BASE = 90
FLOOR, CEIL = 0, 100
#: 只看最近这么多天。加分和扣分用同一个窗口,满了自动不再计分,不需要谁去「修复」
WINDOW_DAYS = 180

#: 完成一单加几分、最多加多少
ORDER_POINTS = 1
ORDER_CAP = 10

#: 平台判为你的责任的一次(配送异常、售后判责),扣几分
FAULT_POINTS = 10

#: 违规判定成立,按 enforcement.SEVERITY 的档扣。**档是处置目录定的,不在这里另分** ——
#: 哪类算严重在 enforcement.CATALOG 里,这里只管每档扣几分
VIOLATION_POINTS = {"severe": 20, "major": 10}

#: 扣分项不设单项上限,合计也不封顶,只是最后结果不低于 FLOOR
MINUS_CAP = None

#: 有信用分的三种角色。顺序就是透明中心、规则页上的顺序
ROLES = ("customer", "merchant", "rider")
ROLE_LABELS = {"customer": "顾客", "merchant": "商家", "rider": "骑手"}


@dataclass(frozen=True)
class Level:
    floor: int
    key: str
    label: str


#: 等级,从高到低。**最高一档的下沿就是 BASE**:没有扣分项的人一定在最高一档,
#: 新来的、老的都一样(单测守着)
LEVELS = (
    Level(90, "good", "良好"),
    Level(70, "fair", "一般"),
    Level(0, "low", "偏低"),
)

KIND_ORDER = "order_completed"
#: delivery_issues.id。顾客:判为顾客原因(按送达处理);骑手:裁成退款、判为骑手责任。
#: 一条配送异常只有一个裁决,所以同一个 id 不会既算顾客的又算骑手的
KIND_DELIVERY = "delivery_fault"
#: after_sales.id。商家:平台复核改判为商家责任;骑手:平台仲裁判为骑手责任。
#: 一条售后同一时刻只有一个判责方,同样不会两头算
KIND_AFTER_SALE = "after_sale_fault"
#: violations.id。违规记录自带「判定时的身份」(audience),天然不会串
KIND_VIOLATION = "violation"

#: 每种角色能申诉的扣分项。只有扣分能申诉 —— 加分没有人会申诉
APPEALABLE_KINDS = {
    "customer": (KIND_DELIVERY, KIND_VIOLATION),
    "merchant": (KIND_AFTER_SALE, KIND_VIOLATION),
    "rider": (KIND_DELIVERY, KIND_AFTER_SALE, KIND_VIOLATION),
}

#: 原来就有的申诉通道(appeals 表的 target_type,72 小时)。接得上就走它 —— 那边改判时
#: 钱和记录一起改;不在这里的(违规记录)本来就没有结构化入口,走客服工单。
#: 骑手的售后判责原来也没有,只能走工单;商家的售后判责却有 72 小时的原通道 —— 一方能走、
#: 另一方不能,2026-09-14 补上了 after_sale_rider,和商家那条对齐
ORIGINAL_CHANNEL = {
    ("customer", KIND_DELIVERY): "delivery_issue",
    ("rider", KIND_DELIVERY): "delivery_issue",
    ("rider", KIND_AFTER_SALE): "after_sale_rider",
    ("merchant", KIND_AFTER_SALE): "after_sale",
}

#: 原通道改判会发生什么 —— 申诉框里原样告诉申诉的人,对着 appeals._overturn 各支写的
_ORIGINAL_AFTER = {
    ("customer", KIND_DELIVERY): "改判的话,这一条不再计分,钱也会原路退回",
    ("rider", KIND_DELIVERY): "改判的话,这一条不再计分,记录上写明不是你的责任,判责时扣的钱退回",
    ("rider", KIND_AFTER_SALE): "改判的话,这一条不再计分,记录上写明不是你的责任,判责时扣的钱退回",
    ("merchant", KIND_AFTER_SALE): "改判的话,这一条不再计分,被冲掉的那笔净额补回来",
}

#: 交易对方能看到分数的订单状态:接单之后、没取消。
#: 待支付、待接单看不到(那正是挑人的时刻),取消了的单交易已经结束,不给
COUNTERPART_STATUS_VALUES = ("accepted", "ready", "picked_up", "delivered", "completed")

#: 按人缓存多久。时间窗滚动、漏打的失效,最多晚这么久
CACHE_TTL_SECONDS = 600
_CACHE_PREFIX = f"credit:v{FORMULA_VERSION}:"

#: 按下单时间给查询划的下界比窗口多出的天数(走 (xxx_id, created_at) 索引)。
#: 窗口按完成 / 裁决时刻算,而一单从下单到完成最多隔着预约 + 24 小时自动确认 ——
#: 30 天绰绰有余,多圈进来的由完成时刻那个条件再筛一遍
_CREATED_SLACK_DAYS = 30

#: 顾客那一侧的标题用(「配送时联系不上,平台判为顾客原因」)
_ISSUE_KIND_LABELS = {
    "cannot_contact": "联系不上",
    "wrong_address": "地址有误",
    "food_damaged": "出现餐损",
    "items_missing": "餐品不齐",
    "other": "出现异常",
}
#: 骑手那一侧的标题用(骑手上报的是哪一类)
_RIDER_ISSUE_LABELS = {
    "cannot_contact": "联系不上顾客",
    "wrong_address": "地址有误",
    "food_damaged": "餐品损坏",
    "not_ready": "到店未出餐",
    "items_missing": "餐品不齐",
    "other": "其他",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc(v: datetime) -> datetime:
    """库里取出来的时间可能是 naive 的,一律当 UTC(和 appeals.within_window 同一个口径)。"""
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


def window_start(now: datetime) -> datetime:
    return _utc(now) - timedelta(days=WINDOW_DAYS)


def in_window(at: datetime, now: datetime) -> bool:
    """这一条还计不计分:发生在最近 WINDOW_DAYS 天之内(含边界那一刻)。"""
    return _utc(at) >= window_start(now)


def expires_at(at: datetime) -> datetime:
    """到这一刻起这一条不再计分。和 in_window 严格互为反面。"""
    return _utc(at) + timedelta(days=WINDOW_DAYS)


#: 起算日按北京日期算:「9 月 15 日起」对当事人来说就是北京时间那天零点起
_BEIJING = timezone(timedelta(hours=8))


def count_from() -> datetime:
    """扣分从这一刻起算(含):config.credit_count_from 那天的北京时间零点。

    每次现读配置(不在导入时算死):改配置、单测改日期,公示和计算一起跟着变。"""
    d = settings.credit_count_from
    return datetime(d.year, d.month, d.day, tzinfo=_BEIJING).astimezone(timezone.utc)


def count_from_label() -> str:
    """公示里写的那个日期(「2026-09-15」)。"""
    return settings.credit_count_from.isoformat()


def counts(at: datetime, now: datetime) -> bool:
    """这一条扣分记不记分:在时间窗里,**而且不早于起算日**。只管扣分项 —— 完成订单的加分
    只看时间窗(理由见模块抬头「起算日」)。"""
    return in_window(at, now) and _utc(at) >= count_from()


def deduction_since(now: datetime) -> datetime:
    """查扣分项用的下沿:时间窗起点和起算日取晚的那个。和 [counts] 是同一个口径。"""
    return max(window_start(now), count_from())


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"没有这种角色的信用分:{role!r}")


# ---------------------------------------------------------------------------
# 纯函数:事实进、分数出。单测全在这一层
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    """一条计分的扣分事实。**每一条都能指回一行原始记录**(kind + record_id)。"""
    kind: str
    record_id: int
    #: 决定在不在时间窗里:裁决时刻 / 判责时刻 / 判定时刻
    at: datetime
    #: 这一条的分值,带符号(扣分项为负)
    points: int
    #: 给本人看的一句话
    title: str = ""
    order_no: str = ""
    #: 平台写给本人的说明(违规的判定说明、裁决备注、改判说明)
    note: str = ""


@dataclass
class Facts:
    """一个人窗口内计分的全部事实。"""
    #: 窗口内完成的单数。**在查询里数好**:商家、骑手一个窗口里能有上万单,不值得逐行取回。
    #: 查询用的窗口下沿和 [in_window] 是同一个(完成时刻 >= 窗口起点)
    orders: int = 0
    deductions: list[Fact] = field(default_factory=list)


@dataclass(frozen=True)
class Score:
    score: int
    level: Level
    base: int
    #: 实际加上的(封顶之后)
    plus: int
    #: 实际扣掉的合计(不封顶;最后结果不低于 FLOOR)
    minus: int
    #: 窗口内完成的订单数(可能超过封顶)
    orders_in_window: int
    #: 窗口内计分的扣分项,新的在前
    deductions: tuple[Fact, ...]


def level_of(score: int) -> Level:
    for lv in LEVELS:
        if score >= lv.floor:
            return lv
    return LEVELS[-1]


def violation_points(severity: str) -> int:
    """违规扣几分(正数)。目录里新增一档而这里没配的话直接报错 —— 不许默认成 0 分悄悄放过。"""
    return VIOLATION_POINTS[severity]


def compute(orders: int, deductions: Iterable[Fact], now: datetime | None = None) -> Score:
    """**唯一的公式。** 三种角色、本人的明细、交易对方看到的分数、透明中心的说明都是它。

    信用分 = BASE + min(窗口内完成单数 × ORDER_POINTS, ORDER_CAP) − 窗口内扣分合计,
    限定在 FLOOR–CEIL。扣分项在这里按每条的真实时刻再筛一遍(时间窗 + 起算日,见 [counts]),
    查询只负责把候选捞全。
    """
    now = now or utcnow()
    orders = max(int(orders or 0), 0)
    plus = min(orders * ORDER_POINTS, ORDER_CAP)
    live = tuple(sorted((f for f in deductions if f.points < 0 and counts(f.at, now)),
                        key=lambda f: (_utc(f.at), f.record_id), reverse=True))
    minus = sum(-f.points for f in live)
    score = max(FLOOR, min(CEIL, BASE + plus - minus))
    return Score(score=score, level=level_of(score), base=BASE, plus=plus, minus=minus,
                 orders_in_window=orders, deductions=live)


def brief_of(s: Score) -> dict:
    """交易对方看到的全部内容:分数和等级。**没有明细。**"""
    return {"score": s.score, "level": s.level.key, "level_label": s.level.label}


def appeal_state(role: str, fact: Fact, *, original: str | None, ticket: str | None,
                 ticket_note: str = "", original_note: str = "",
                 now: datetime | None = None) -> dict:
    """一条扣分记录旁边的「申诉」该是什么样子。

    - `original`:原来那条申诉通道(appeals 表,见 [ORIGINAL_CHANNEL])里这条记录的状态,
      没申诉过为 None;没有原通道的传 None;
    - `ticket`:走客服工单的信用分申诉(credit_appeals)的状态,没提过为 None。

    能接原通道就接原通道(改判的话钱和记录一起改),接不上的走工单。**申诉成立的那一条根本
    不会出现在扣分项里**(查询已经把它排除了),所以这里不处理 overturned。
    `confirm` 是提交前那个框里说的话 —— 三种角色、两条通道各说各的后果,客户端不另写一份。
    """
    from ..routers.appeals import APPEAL_WINDOW, within_window

    now = now or utcnow()
    after = "申诉成立后,这一条不再计分,分数马上重算"
    base = {"via": "", "target_type": "", "target_id": 0, "deadline": None,
            "state": "", "label": "", "note": "", "after": after, "confirm": ""}
    by_ticket = f"会转给平台客服,回复在「联系平台客服」里看得到。{after}"
    if ticket == "open":
        return {**base, "state": "open", "label": "申诉处理中(客服工单)"}
    if ticket == "upheld":
        return {**base, "state": "upheld", "label": "申诉后维持原判", "note": ticket_note}
    channel = ORIGINAL_CHANNEL.get((role, fact.kind))
    if channel:
        if original is None and within_window(fact.at, now):
            return {**base, "via": "appeal", "target_type": channel,
                    "target_id": fact.record_id, "label": "申诉",
                    "deadline": (_utc(fact.at) + APPEAL_WINDOW).isoformat(),
                    "confirm": f"平台会重新复核这次判定。{_ORIGINAL_AFTER[(role, fact.kind)]}。"}
        if original == "open":
            return {**base, "state": "open", "label": "申诉处理中"}
        if original == "upheld":
            # 原通道维持原判:有新证据还能走一次工单(维持原判的推送里就是这么说的)
            return {**base, "via": "ticket", "state": "upheld", "note": original_note,
                    "label": "维持原判;有新证据可以提客服工单", "confirm": by_ticket}
    # 违规记录没有结构化的申诉入口;原通道过了 72 小时也接不上 —— 走工单
    return {**base, "via": "ticket", "label": "申诉(客服工单)", "confirm": by_ticket}


# ---------------------------------------------------------------------------
# 谁能在哪一单上看到谁的分
# ---------------------------------------------------------------------------


def visible_parties(order, viewer) -> frozenset[str]:
    """这个人现在能在这一单上看到哪几方的信用分(customer / merchant / rider 的子集)。

    前提:订单状态在 [COUNTERPART_STATUS_VALUES] 里(接单之后、没取消)。然后:

    - 商家:**接过这一单**(accepted_at 有值)才看得到顾客的;骑手接到这一单之后
      (rider_id 有值)才看得到骑手的。待接单(新单提醒、新单详情)什么都看不到;
    - 骑手:**这一单的骑手**才看得到顾客的和商家的。抢单大厅里的单 rider_id 是空的,谁都看不到;
    - 顾客:本人的单;商家接单之后看得到商家的,骑手接到单之后看得到骑手的。
      跑腿单没有商家(挂的是每城一个的虚拟服务主体),永远不给「商家」的分;
    - 其他角色(管理员)不走这条:客服有后台接口。

    ⚠️ 商家那条**不自己核归属** —— 调用方(orders.my_orders 按店过滤、get_order 走
    visible_order_or_404)已经核过。别在没核过归属的地方调 [attach]。
    """
    if viewer is None:
        return frozenset()
    status = getattr(order.status, "value", order.status)
    if status not in COUNTERPART_STATUS_VALUES:
        return frozenset()
    from .errand import is_errand

    role = getattr(viewer.role, "value", viewer.role)
    has_rider = order.rider_id is not None
    has_merchant = order.accepted_at is not None and not is_errand(order)
    seen: set[str] = set()
    if role == "merchant":
        if order.accepted_at is None:
            return frozenset()
        seen.add("customer")
        if has_rider:
            seen.add("rider")
    elif role == "rider":
        if not has_rider or order.rider_id != viewer.id:
            return frozenset()
        seen.add("customer")
        if has_merchant:
            seen.add("merchant")
    elif role == "customer":
        if order.customer_id != viewer.id:
            return frozenset()
        if has_merchant:
            seen.add("merchant")
        if has_rider:
            seen.add("rider")
    return frozenset(seen)


# ---------------------------------------------------------------------------
# 取事实。批量:订单列表一次可能要算十几个人,逐个查就是十几倍的往返
# ---------------------------------------------------------------------------


def _order_rows(role: str, ids: list[int], since: datetime, floor: datetime):
    """窗口内算「完成一单」的那些单,列:(uid 主体, oid, order_no, at 完成时刻)。

    三种角色共用的口径:状态为已完成、完成时刻在窗口里、不是追加单(随原单一起送,不是另一笔
    交易)、不是风控确认的刷单(risk_flags.status = confirmed,口径同月售剔除)。
    各角色再排除「这一单你这一环没做成」的:

    - 顾客:配送时判为顾客原因的那一单(他没收到,那一条已经在扣分项里)、到店自取超时没来取、
      系统自动完成的单;
    - 骑手:配送异常裁成退款、直接结束的那一单(没有送到顾客手里;判谁的责任都一样);
    - 商家:骑手报「到店未出餐」「餐品不齐」、判为商家责任提前结束的那一单(餐没出、没装齐,
      这一环没做成,那一条已经在扣分项里)。别的不另排除 —— 餐做好交出去了就是做成了,
      后面配送出的事不是商家这一环的。

    返回 (语句, 完成时刻表达式)。
    """
    from ..models import NOT_APPEND_ORDER, DeliveryIssue, Merchant, Order, OrderEvent
    from ..state_machine import OrderStatus
    from .delivery_fault import MERCHANT_KINDS

    _check_role(role)
    done_at = func.coalesce(Order.completed_at, Order.created_at)
    common = (Order.status == OrderStatus.COMPLETED,
              Order.created_at >= floor,
              done_at >= since,
              NOT_APPEND_ORDER,
              text("coalesce(orders.risk_flags->>'status', '') != 'confirmed'"))
    if role == "merchant":
        subject = Merchant.owner_id
        merchant_fault = exists().where(DeliveryIssue.order_id == Order.id,
                                        DeliveryIssue.resolution == "refund",
                                        DeliveryIssue.kind.in_(MERCHANT_KINDS))
        q = (select(subject.label("uid"), Order.id.label("oid"), Order.order_no,
                    done_at.label("at"))
             .select_from(Order).join(Merchant, Merchant.id == Order.merchant_id)
             .where(subject.in_(ids), *common, ~merchant_fault))
        return q, done_at
    if role == "customer":
        subject = Order.customer_id
        customer_fault = exists().where(DeliveryIssue.order_id == Order.id,
                                        DeliveryIssue.resolution == "mark_delivered")
        pickup_timeout = exists().where(OrderEvent.order_id == Order.id,
                                        OrderEvent.from_status == OrderStatus.READY.value,
                                        OrderEvent.to_status == OrderStatus.COMPLETED.value,
                                        OrderEvent.actor_role == "system")
        extra = (~customer_fault, ~pickup_timeout)
    else:
        subject = Order.rider_id
        undelivered = exists().where(DeliveryIssue.order_id == Order.id,
                                     DeliveryIssue.resolution == "refund")
        extra = (~undelivered,)
    q = (select(subject.label("uid"), Order.id.label("oid"), Order.order_no,
                done_at.label("at"))
         .where(subject.in_(ids), *common, *extra))
    return q, done_at


def _ticket_won(kind: str, record_col):
    """这条记录走客服工单申诉成立了(credit_appeals.status = overturned)。"""
    from ..models import CreditAppeal
    return exists().where(CreditAppeal.kind == kind, CreditAppeal.record_id == record_col,
                          CreditAppeal.status == "overturned")


def _issue_title(kind: str) -> str:
    return f"配送时{_ISSUE_KIND_LABELS.get(kind, '出现异常')},平台判为顾客原因(按送达处理)"


def _rider_issue_title(kind: str) -> str:
    return f"配送异常「{_RIDER_ISSUE_LABELS.get(kind, '其他')}」,平台判为骑手责任"


_MERCHANT_AFTER_SALE_TITLE = "你拒绝的售后,顾客申诉后平台复核判为商家责任"
_RIDER_AFTER_SALE_TITLE = "顾客售后,平台仲裁判为骑手责任(洒餐、丢餐等)"


def _merchant_after_sale_title(issue_kind: str | None) -> str:
    """商家那条售后判责从哪来的:顾客「售后被拒」的申诉改判,或者配送异常判商家责任。"""
    if issue_kind:
        return (f"骑手上报「{_RIDER_ISSUE_LABELS.get(issue_kind, '其他')}」,"
                "平台判为商家责任(商家承担退款)")
    return _MERCHANT_AFTER_SALE_TITLE


def _delivery_query(role: str, ids: list[int], floor: datetime):
    """配送异常:顾客看「按送达处理」的,骑手看裁成退款、判为骑手责任的。
    列:(uid, id, order_no, kind, at, note)。

    到店未出餐、餐品不齐裁成退款判的是**商家**责任(services/delivery_fault),不算骑手的 ——
    商家那一侧记在售后判责上(见 [_after_sale_query])。"""
    from ..models import DeliveryIssue, Order
    from .delivery_fault import MERCHANT_KINDS

    if role == "customer":
        return (select(Order.customer_id, DeliveryIssue.id, DeliveryIssue.order_no,
                       DeliveryIssue.kind, DeliveryIssue.resolved_at, DeliveryIssue.resolve_note)
                .join(Order, Order.id == DeliveryIssue.order_id)
                .where(Order.customer_id.in_(ids), Order.created_at >= floor,
                       DeliveryIssue.resolution == "mark_delivered"))
    return (select(DeliveryIssue.rider_id, DeliveryIssue.id, DeliveryIssue.order_no,
                   DeliveryIssue.kind, DeliveryIssue.resolved_at, DeliveryIssue.resolve_note)
            .where(DeliveryIssue.rider_id.in_(ids), DeliveryIssue.resolution == "refund",
                   DeliveryIssue.kind.notin_(MERCHANT_KINDS)))


def _delivery_appeal_won():
    from ..models import Appeal, DeliveryIssue
    return exists().where(Appeal.target_type == "delivery_issue",
                          Appeal.target_id == DeliveryIssue.id,
                          Appeal.status == "overturned")


def _after_sale_query(role: str, ids: list[int], *, still_at_fault: bool = True):
    """售后判为这个人的责任。列:(uid, id, order_no, at, note, issue_kind)。

    - 商家,两个来源(都是平台判出来的):
      ① 顾客的「售后被拒」申诉改判成立(接上那条改判,它的复核说明就是 note);
      ② 骑手报「到店未出餐」「餐品不齐」、裁成退款判为商家责任时记的那条售后(接上那条配送异常,
         issue_kind 就是它的种类,note 是裁决说明)—— services/delivery_fault;
      而且现在判责方还是商家(fault = merchant)。商家自己同意的也是 fault = merchant,
      但哪一条都接不上 —— 不算;商家对它申诉成立后 fault 变成 platform,自然掉出来;
    - 骑手:after_sales.fault = rider,骑手是这一单的骑手。配送异常裁成退款时顺手补的那条
      售后(同一单有 resolution = refund 的配送异常)不在这里重复计 —— 那一次记在配送异常上。
      issue_kind 恒为空。

    [still_at_fault] 为 False 时不看现在的判责方(明细页列「申诉成立、不再计分」的那些用)。
    """
    from ..models import AfterSale, Appeal, DeliveryIssue, Merchant, Order
    from .delivery_fault import MERCHANT_KINDS

    if role == "merchant":
        # 两个来源各接一张,都是外连接:一条售后只可能对上其中一个(配送异常判的那条一记下就是
        # 「已同意」,顾客没法再对它提「售后被拒」),而每个来源最多一行,不会把售后翻倍
        q = (select(Merchant.owner_id, AfterSale.id, Order.order_no, AfterSale.processed_at,
                    func.coalesce(Appeal.resolve_note, DeliveryIssue.resolve_note),
                    DeliveryIssue.kind)
             .select_from(AfterSale)
             .join(Merchant, Merchant.id == AfterSale.merchant_id)
             .join(Order, Order.id == AfterSale.order_id)
             .outerjoin(Appeal, and_(Appeal.target_type == "after_sale_rejected",
                                     Appeal.target_id == AfterSale.id,
                                     Appeal.status == "overturned"))
             .outerjoin(DeliveryIssue, and_(DeliveryIssue.order_id == AfterSale.order_id,
                                            DeliveryIssue.resolution == "refund",
                                            DeliveryIssue.kind.in_(MERCHANT_KINDS)))
             .where(Merchant.owner_id.in_(ids),
                    or_(Appeal.id.is_not(None), DeliveryIssue.id.is_not(None))))
        return q.where(AfterSale.fault == "merchant") if still_at_fault else q
    via_issue = exists().where(DeliveryIssue.order_id == AfterSale.order_id,
                               DeliveryIssue.resolution == "refund")
    q = (select(Order.rider_id, AfterSale.id, Order.order_no,
                AfterSale.processed_at, AfterSale.reply, null().label("issue_kind"))
         .select_from(AfterSale)
         .join(Order, Order.id == AfterSale.order_id)
         .where(Order.rider_id.in_(ids), ~via_issue))
    return q.where(AfterSale.fault == "rider") if still_at_fault else q


def _rules(role: str) -> dict:
    from .enforcement import rules_of
    return {r.kind: r for r in rules_of(role)}


async def _deductions(db: AsyncSession, role: str, ids: list[int], since: datetime,
                      floor: datetime) -> list[tuple[int, Fact]]:
    """计分的扣分项。**已经排除了申诉成立的记录。**

    `since` 是 [deduction_since]:时间窗起点和起算日取晚的那个 —— 起算日之前的裁决和判定
    根本捞不上来(compute 里 [counts] 还会按同一个口径再筛一遍)。"""
    from ..models import AfterSale, AfterSaleStatus, DeliveryIssue, Violation

    out: list[tuple[int, Fact]] = []
    if role in ("customer", "rider"):
        q = _delivery_query(role, ids, floor).where(
            DeliveryIssue.status == "resolved",
            DeliveryIssue.resolved_at.is_not(None),
            DeliveryIssue.resolved_at >= since,
            ~_delivery_appeal_won(), ~_ticket_won(KIND_DELIVERY, DeliveryIssue.id))
        title = _issue_title if role == "customer" else _rider_issue_title
        for uid, iid, no, kind, at, note in (await db.execute(q)).all():
            out.append((uid, Fact(KIND_DELIVERY, iid, at, -FAULT_POINTS, title(kind),
                                  no or "", note or "")))
    if role in ("merchant", "rider"):
        q = _after_sale_query(role, ids).where(
            AfterSale.status == AfterSaleStatus.accepted,
            AfterSale.processed_at.is_not(None),
            AfterSale.processed_at >= since,
            ~_ticket_won(KIND_AFTER_SALE, AfterSale.id))
        for uid, aid, no, at, note, issue_kind in (await db.execute(q)).all():
            title = (_merchant_after_sale_title(issue_kind) if role == "merchant"
                     else _RIDER_AFTER_SALE_TITLE)
            out.append((uid, Fact(KIND_AFTER_SALE, aid, at, -FAULT_POINTS, title,
                                  no or "", note or "")))
    rules = _rules(role)
    rows = (await db.execute(
        select(Violation.subject_id, Violation.id, Violation.kind, Violation.order_no,
               Violation.note, Violation.created_at)
        .where(Violation.subject_id.in_(ids),
               Violation.audience == role,
               Violation.overturned_at.is_(None),
               Violation.created_at >= since))).all()
    for uid, vid, kind, no, note, at in rows:
        rule = rules.get(kind)
        if rule is None:
            continue   # 目录里删掉的旧类别:不再计入(和 enforcement.counts_for 同一口径)
        out.append((uid, Fact(KIND_VIOLATION, vid, at, -violation_points(rule.severity),
                              f"违规成立:{rule.label}", no or "", note or "")))
    return out


async def load_facts(db: AsyncSession, role: str, uids: Iterable[int],
                     now: datetime | None = None) -> dict[int, Facts]:
    """这些人(同一种角色)窗口内计分的全部事实。"""
    _check_role(role)
    ids = sorted({int(u) for u in uids if u})
    out: dict[int, Facts] = {i: Facts() for i in ids}
    if not ids:
        return out
    now = now or utcnow()
    since = window_start(now)
    floor = since - timedelta(days=_CREATED_SLACK_DAYS)
    # 加分只看时间窗;扣分另外还要不早于起算日(模块抬头「起算日」)
    q, _ = _order_rows(role, ids, since, floor)
    sq = q.subquery()
    for uid, n in (await db.execute(select(sq.c.uid, func.count()).group_by(sq.c.uid))).all():
        if uid in out:
            out[uid].orders = int(n)
    for uid, fact in await _deductions(db, role, ids, deduction_since(now), floor):
        if uid in out:
            out[uid].deductions.append(fact)
    return out


async def _recent_orders(db: AsyncSession, role: str, uid: int, now: datetime) -> list[dict]:
    """明细页上列的最近几单(加分封顶,列全了也只是更长)。"""
    since = window_start(now)
    q, done_at = _order_rows(role, [uid], since, since - timedelta(days=_CREATED_SLACK_DAYS))
    rows = (await db.execute(q.order_by(done_at.desc()).limit(ORDER_CAP))).all()
    return [{"order_no": no, "at": _utc(at).isoformat()} for _, _, no, at in rows]


# ---------------------------------------------------------------------------
# 交易对方看到的:分数和等级,带缓存
# ---------------------------------------------------------------------------


def _key(role: str, uid: int) -> str:
    return f"{_CACHE_PREFIX}{role}:{int(uid)}"


async def _put_cache(role: str, briefs: dict[int, dict]) -> None:
    if not briefs:
        return
    try:
        pipe = get_redis().pipeline()
        for uid, b in briefs.items():
            pipe.set(_key(role, uid), json.dumps(b), ex=CACHE_TTL_SECONDS)
        await pipe.execute()
    except Exception:
        pass   # 写不进去只是下次还得现算,不影响对错


async def briefs_for(db: AsyncSession, role: str, uids: Iterable[int]) -> dict[int, dict]:
    """一批同角色的人的分数和等级。先读缓存(mget 一次),没命中的**只补差集**,一次批量现算。"""
    _check_role(role)
    ids = sorted({int(u) for u in uids if u})
    if not ids:
        return {}
    cached: dict[int, dict] = {}
    try:
        raws = await get_redis().mget([_key(role, i) for i in ids])
        for i, raw in zip(ids, raws):
            if raw is not None:
                cached[i] = json.loads(raw)
    except Exception:
        pass   # 缓存挂了照常现算,只是慢一点
    ids = [i for i in ids if i not in cached]
    if not ids:
        return cached
    now = utcnow()
    facts = await load_facts(db, role, ids, now)
    fresh = {i: brief_of(compute(facts[i].orders, facts[i].deductions, now)) for i in ids}
    await _put_cache(role, fresh)
    fresh.update(cached)
    return fresh


async def invalidate(*uids: int | None) -> None:
    """事实变了,把这几个人的缓存打掉(三种角色的键一起打:一个账号只有一个角色,
    多删两个不存在的键不费事,调用方也就不用知道他是什么角色)。

    **在 commit 之后调** —— 提交前打掉的话,别的请求可能正好在这个空档里按旧数据
    重新算一遍、又写回去。调用点见模块抬头。
    """
    keys = [_key(role, u) for u in uids if u for role in ROLES]
    if not keys:
        return
    try:
        await get_redis().delete(*keys)
    except Exception:
        pass   # 打不掉最多晚 CACHE_TTL_SECONDS


async def invalidate_orders(db: AsyncSession, orders: Iterable) -> None:
    """这些单的三方:顾客、店主、骑手。订单完成、刷单结论变了、这一单上的判定变了时用。
    **在 commit 之后调**(店主要现查一次 merchants.owner_id)。"""
    orders = [o for o in orders if o is not None]
    if not orders:
        return
    from ..models import Merchant

    uids: set[int] = {o.customer_id for o in orders}
    uids |= {o.rider_id for o in orders if o.rider_id}
    try:
        uids |= set(await db.scalars(select(Merchant.owner_id).where(
            Merchant.id.in_({o.merchant_id for o in orders}))))
    except Exception:
        pass   # 查不到店主只是他那边晚一个 TTL
    await invalidate(*uids)


async def invalidate_order(db: AsyncSession, order) -> None:
    await invalidate_orders(db, [order])


async def attach(db: AsyncSession, outs: list, orders: list, viewer) -> None:
    """给订单列表和订单详情填交易对方的信用分:`customer_credit` / `merchant_credit` /
    `rider_credit`,每个都只有分数和等级。谁能看到谁见 [visible_parties]。

    **只在 routers/orders.py 的 my_orders 和 get_order 里调**。抢单池(riders.available_orders)、
    抢单回执、状态流转回执、店铺页、搜索、开放接口、推送都不调 —— 单测按调用点守着。
    这个函数的结果只进响应体,不回写任何地方,不能拿来拒单、改派单顺序、改价格。
    """
    plan = [(o, visible_parties(o, viewer)) for o in orders]
    plan = [(o, seen) for o, seen in plan if seen]
    if not plan:
        return
    owners: dict[int, int] = {}
    mids = {o.merchant_id for o, seen in plan if "merchant" in seen}
    if mids:
        from ..models import Merchant
        owners = dict((await db.execute(
            select(Merchant.id, Merchant.owner_id).where(Merchant.id.in_(mids)))).all())
    subject: dict[tuple[int, str], int] = {}
    want: dict[str, set[int]] = {r: set() for r in ROLES}
    for o, seen in plan:
        for role in seen:
            uid = {"customer": o.customer_id, "rider": o.rider_id,
                   "merchant": owners.get(o.merchant_id)}[role]
            if uid:
                subject[(o.id, role)] = uid
                want[role].add(uid)
    got = {role: await briefs_for(db, role, uids) for role, uids in want.items() if uids}
    from ..schemas import CreditBriefOut
    for out in outs:
        for role in ROLES:
            uid = subject.get((out.id, role))
            if uid is not None and uid in got.get(role, {}):
                setattr(out, f"{role}_credit", CreditBriefOut(**got[role][uid]))


# ---------------------------------------------------------------------------
# 本人看的明细
# ---------------------------------------------------------------------------


async def subject_of(db: AsyncSession, user) -> tuple[str, int]:
    """「我的信用分」是谁的:顾客、骑手是本人;商家是**店主本人**(分数记在店主名下,
    和处置同一个主体 —— 见模块抬头)。店员、品牌经理没有自己的商家信用分。"""
    role = getattr(user.role, "value", user.role)
    if role not in ROLES:
        raise HTTPException(403, "只有顾客、商家、骑手有信用分")
    if role == "merchant":
        from ..models import Merchant
        owns = await db.scalar(select(Merchant.id).where(Merchant.owner_id == user.id).limit(1))
        if owns is None:
            raise HTTPException(404, "商家信用分记在店主名下(和处置同一个主体),"
                                     "店员、品牌经理没有自己的这一页")
    return role, int(user.id)


def _fact_row(f: Fact) -> dict:
    return {"kind": f.kind, "record_id": f.record_id, "title": f.title,
            "order_no": f.order_no, "note": f.note, "points": f.points,
            "at": _utc(f.at).isoformat(), "expires_at": expires_at(f.at).isoformat()}


async def _excluded(db: AsyncSession, role: str, uid: int, now: datetime) -> list[dict]:
    """窗口内申诉成立、不再计分的记录 —— 让本人看得到自己申诉赢了。
    起算日之前的本来就不计分,不列(和扣分项同一个下沿)。"""
    from ..models import AfterSale, AfterSaleStatus, Appeal, DeliveryIssue, Violation

    since = deduction_since(now)
    floor = window_start(now) - timedelta(days=_CREATED_SLACK_DAYS)
    won = "申诉成立,不再计分"
    out: list[dict] = []
    if role in ("customer", "rider"):
        q = _delivery_query(role, [uid], floor).where(
            DeliveryIssue.resolved_at.is_not(None),
            DeliveryIssue.resolved_at >= since,
            or_(_delivery_appeal_won(), _ticket_won(KIND_DELIVERY, DeliveryIssue.id)))
        title = _issue_title if role == "customer" else _rider_issue_title
        for _, iid, no, kind, at, _note in (await db.execute(q)).all():
            out.append({"kind": KIND_DELIVERY, "record_id": iid, "title": title(kind),
                        "order_no": no or "", "at": _utc(at).isoformat(), "why": won})
    if role in ("merchant", "rider"):
        # 两条路赢的:原通道改判(商家 after_sale、骑手 after_sale_rider,fault 变成 platform),
        # 或者走工单成立(fault 不动,credit_appeals 记着成立)。
        # 自己这条申诉要另起别名:商家那一侧外层已经连了顾客那条 after_sale_rejected 申诉,
        # 不另起的话子查询会被自动关联到外层那张 appeals 上
        own = aliased(Appeal)
        channel = ORIGINAL_CHANNEL[(role, KIND_AFTER_SALE)]
        original_won = exists().where(own.target_type == channel,
                                      own.target_id == AfterSale.id,
                                      own.status == "overturned")
        # 工单那条只认**这个人自己**提的:同一条售后记录上别人(比如商家)工单申诉赢了,
        # 不能算成他赢了。骑手工单改判成立时判责方会变成 platform(和原通道一样,
        # services/rider_fault),所以这里不能再按判责方卡
        from ..models import CreditAppeal
        ticket_won = exists().where(CreditAppeal.kind == KIND_AFTER_SALE,
                                    CreditAppeal.record_id == AfterSale.id,
                                    CreditAppeal.status == "overturned",
                                    CreditAppeal.user_id == uid)
        won_q = or_(original_won, ticket_won)
        q = (_after_sale_query(role, [uid], still_at_fault=False)
             .where(AfterSale.status == AfterSaleStatus.accepted,
                    AfterSale.processed_at.is_not(None),
                    AfterSale.processed_at >= since, won_q))
        for _, aid, no, at, _note, issue_kind in (await db.execute(q)).all():
            title = (_merchant_after_sale_title(issue_kind) if role == "merchant"
                     else _RIDER_AFTER_SALE_TITLE)
            out.append({"kind": KIND_AFTER_SALE, "record_id": aid, "title": title,
                        "order_no": no or "", "at": _utc(at).isoformat(), "why": won})
    rules = _rules(role)
    viol_rows = (await db.execute(
        select(Violation.id, Violation.kind, Violation.order_no, Violation.created_at,
               Violation.overturn_note)
        .where(Violation.subject_id == uid, Violation.audience == role,
               Violation.overturned_at.is_not(None),
               Violation.created_at >= since))).all()
    for vid, kind, no, at, note in viol_rows:
        rule = rules.get(kind)
        out.append({"kind": KIND_VIOLATION, "record_id": vid,
                    "title": f"违规成立:{rule.label if rule else kind}",
                    "order_no": no or "", "at": _utc(at).isoformat(),
                    "why": f"{won}{('(' + note + ')') if note else ''}"})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out


#: 本人明细页头上那一句:交易对方看得到什么、看不到什么
_SEEN_BY = {
    "customer": "接了你单的商家、接到你单的骑手只看得到分数和等级,看不到下面这些明细。",
    "merchant": "你接了单的顾客、接到这一单的骑手只看得到分数和等级,看不到下面这些明细;"
                "店铺页、搜索、排序里没有它。",
    "rider": "你接到的单上,顾客和商家只看得到分数和等级,看不到下面这些明细;"
             "抢单大厅里没有它。",
}


async def breakdown(db: AsyncSession, role: str, uid: int,
                    now: datetime | None = None) -> dict:
    """本人(和处理申诉的客服)看的完整明细。每次现算,顺手刷新缓存。"""
    from ..models import Appeal, CreditAppeal

    _check_role(role)
    now = now or utcnow()
    facts = (await load_facts(db, role, [uid], now))[uid]
    s = compute(facts.orders, facts.deductions, now)
    await _put_cache(role, {uid: brief_of(s)})

    ded = s.deductions
    by_kind: dict[str, list[int]] = {}
    for f in ded:
        by_kind.setdefault(f.kind, []).append(f.record_id)
    originals: dict[tuple[str, int], Appeal] = {}
    for kind, ids in by_kind.items():
        channel = ORIGINAL_CHANNEL.get((role, kind))
        if channel:
            for a in await db.scalars(select(Appeal).where(
                    Appeal.target_type == channel, Appeal.target_id.in_(ids))):
                originals[(kind, a.target_id)] = a
    tickets: dict[tuple[str, int], CreditAppeal] = {}
    conds = [and_(CreditAppeal.kind == kind, CreditAppeal.record_id.in_(ids))
             for kind, ids in by_kind.items()]
    if conds:
        tickets = {(c.kind, c.record_id): c for c in await db.scalars(
            select(CreditAppeal).where(or_(*conds)))}

    rows = []
    for f in ded:
        o = originals.get((f.kind, f.record_id))
        t = tickets.get((f.kind, f.record_id))
        rows.append({**_fact_row(f), "appeal": appeal_state(
            role, f, original=o.status if o else None, ticket=t.status if t else None,
            ticket_note=t.resolve_note if t else "",
            original_note=o.resolve_note if o else "", now=now)})

    return {
        "role": role,
        "role_label": ROLE_LABELS[role],
        "score": s.score,
        "level": s.level.key,
        "level_label": s.level.label,
        "base": s.base,
        "plus": s.plus,
        "minus": s.minus,
        # 「90 + 3 − 10 = 83」:四个数都在下面的清单里指得出来
        "formula_line": (f"{s.base} + {s.plus} − {s.minus} = {s.score}"
                         if s.base + s.plus - s.minus == s.score
                         else f"{s.base} + {s.plus} − {s.minus},限定在 "
                              f"{FLOOR}–{CEIL} 之间 = {s.score}"),
        "seen_by": _SEEN_BY[role],
        "orders": {
            "count": s.orders_in_window,
            "points": s.plus,
            "cap": ORDER_CAP,
            "recent": await _recent_orders(db, role, uid, now),
        },
        "deductions": rows,
        "excluded": await _excluded(db, role, uid, now),
        "window_days": WINDOW_DAYS,
        "computed_at": now.isoformat(),
        "rules": public_spec(role),
    }


# ---------------------------------------------------------------------------
# 走客服工单的信用分申诉
# ---------------------------------------------------------------------------

#: 工单正文的开头。后台工单列表靠它一眼认出是信用分申诉
TICKET_PREFIX = "【信用分申诉】"

#: 后台看工单时那一条是什么(「配送异常,判为骑手责任 #12」)
_KIND_LABELS = {
    ("customer", KIND_DELIVERY): "配送异常,判为顾客原因",
    ("rider", KIND_DELIVERY): "配送异常,判为骑手责任",
    ("merchant", KIND_AFTER_SALE): "售后或配送异常,平台判为商家责任",
    ("rider", KIND_AFTER_SALE): "售后,平台仲裁判为骑手责任",
}


def kind_label(role: str, kind: str) -> str:
    if kind == KIND_VIOLATION:
        return "违规记录"
    return _KIND_LABELS.get((role, kind), kind)


def _appeal_hours() -> int:
    from ..routers.appeals import APPEAL_WINDOW
    return int(APPEAL_WINDOW.total_seconds() // 3600)


async def submit_ticket_appeal(db: AsyncSession, user, kind: str, record_id: int,
                               reason: str):
    """原来的申诉通道接不上时,走客服工单申诉一条扣分记录。只改库不提交,调用方提交。

    接得上原通道的(还在 72 小时里)不收 —— 那条通道改判时钱和记录一起改,走工单反而拿不到。
    三种角色同一个入口、同一条规矩:一条记录一次工单申诉。
    """
    from ..models import Appeal, CreditAppeal, Ticket, TicketStatus
    from ..routers.appeals import within_window
    from ..routers.tickets import MAX_OPEN_TICKETS
    from .moderation import guard_text

    role, uid = await subject_of(db, user)
    if kind not in APPEALABLE_KINDS[role]:
        raise HTTPException(422, "只有扣分的记录可以申诉")
    now = utcnow()
    facts = (await load_facts(db, role, [uid], now))[uid]
    fact = next((f for f in facts.deductions if f.kind == kind and f.record_id == record_id
                 and f.points < 0 and counts(f.at, now)), None)
    if fact is None:
        raise HTTPException(404, "这条记录现在不计分,不需要申诉")
    if await db.scalar(select(CreditAppeal.id).where(
            CreditAppeal.kind == kind, CreditAppeal.record_id == record_id)):
        raise HTTPException(409, "这一条已经申诉过了,以平台的复核结论为准")
    channel = ORIGINAL_CHANNEL.get((role, kind))
    if channel:
        original = await db.scalar(select(Appeal).where(
            Appeal.target_type == channel, Appeal.target_id == record_id))
        if original is None and within_window(fact.at, now):
            raise HTTPException(409, f"这一条还在 {_appeal_hours()} 小时申诉期里,"
                                     f"请用它原来的申诉入口 —— {_ORIGINAL_AFTER[(role, kind)]}")
        if original is not None and original.status == "open":
            raise HTTPException(409, "这一条已经在申诉中,等平台复核")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(422, "理由至少写 5 个字,复核的人要有东西可看")
    open_count = await db.scalar(select(func.count()).select_from(Ticket).where(
        Ticket.user_id == user.id, Ticket.status == TicketStatus.open))
    if (open_count or 0) >= MAX_OPEN_TICKETS:
        raise HTTPException(429, f"你有 {open_count} 个工单还没回复,请等平台处理后再提交")
    await guard_text(db, reason, "申诉理由")
    tail = f",订单尾号 {fact.order_no[-6:]}" if fact.order_no else ""
    ticket = Ticket(
        user_id=user.id, role=role, contact=user.dial_phone,
        content=(f"{TICKET_PREFIX}{ROLE_LABELS[role]}:{fact.title}"
                 f"(记录 {kind}#{record_id}{tail})。申诉理由:{reason}")[:500])
    db.add(ticket)
    await db.flush()
    appeal = CreditAppeal(user_id=user.id, kind=kind, record_id=record_id,
                          ticket_id=ticket.id, reason=reason[:500])
    db.add(appeal)
    return appeal, ticket


async def resolve_ticket_appeal(db: AsyncSession, admin, appeal_id: int, result: str,
                                note: str):
    """客服给工单申诉下结论。改判 = 这一条不再计分(违规记录同时推翻,处置级别跟着重算)。

    配送异常、售后判责走工单改判时,顾客、商家的**只改信用分**(credit_appeals 记成立),不动那条
    裁决本身的钱和判责方 —— 动钱的是原来那条申诉通道(appeals),工单这条路只在它接不上时兜底。

    **骑手的例外**(2026-09-14 拍板):判骑手责任要从骑手收入里扣钱(services/rider_fault),
    骑手的申诉「原通道 72 小时 + 工单」两条路都算数 —— 工单改判成立,和原通道一样:扣的加回去、
    保障金池出的回池、判责从骑手转走。返回的 appeal 上挂着 `money_back`(退回骑手多少分),推送用。

    **只改库不提交**,调用方提交后再调 [invalidate] 和推送 —— 和 appeals.resolve_appeal 同一个顺序。
    """
    from ..models import CreditAppeal, Ticket, TicketStatus, User, Violation
    from .admin_audit import log_admin_action

    if result not in ("upheld", "overturned"):
        raise HTTPException(422, "结论只能是 upheld(维持)/ overturned(改判)")
    note = (note or "").strip()
    if len(note) < 2:
        raise HTTPException(422, "写一句复核结论(会原样告诉申诉的人)")
    appeal = await db.scalar(
        select(CreditAppeal).where(CreditAppeal.id == appeal_id)
        .with_for_update().execution_options(populate_existing=True))
    if appeal is None:
        raise HTTPException(404, "没有这条信用分申诉")
    if appeal.status != "open":
        raise HTTPException(409, "这条申诉已经有结论了")
    now = utcnow()
    if result == "overturned" and appeal.kind == KIND_VIOLATION:
        v = await db.scalar(
            select(Violation).where(Violation.id == appeal.record_id)
            .with_for_update().execution_options(populate_existing=True))
        if v is not None and v.overturned_at is None:
            v.overturned_at = now
            v.overturn_note = f"信用分申诉成立:{note}"[:300]
    appeal.money_back = 0
    if result == "overturned" and appeal.kind in (KIND_DELIVERY, KIND_AFTER_SALE):
        who = await db.get(User, appeal.user_id)
        if who is not None and getattr(who.role, "value", who.role) == "rider":
            appeal.money_back = await _undo_rider_fault(db, appeal.kind, appeal.record_id, note)
    appeal.status = result
    appeal.resolve_note = note[:300]
    appeal.admin_id = admin.id
    appeal.resolved_at = now
    if appeal.ticket_id:
        ticket = await db.get(Ticket, appeal.ticket_id, with_for_update=True)
        if ticket is not None and ticket.status != TicketStatus.closed:
            ticket.reply = (("申诉成立,这一条不再计入信用分。" if result == "overturned"
                             else "复核后维持原判,这一条继续计分。") + note)[:500]
            ticket.status = TicketStatus.replied
            ticket.replied_at = now
    await log_admin_action(db, admin, f"credit.appeal.{result}",
                           target_type="credit_appeal", target_id=appeal.id,
                           detail={"user_id": appeal.user_id, "kind": appeal.kind,
                                   "record_id": appeal.record_id})
    return appeal


async def _undo_rider_fault(db: AsyncSession, kind: str, record_id: int, note: str) -> int:
    """骑手走工单申诉判骑手责任成立:扣的钱退回、保障金池回池、判责从骑手转走
    (和 appeals._overturn 那两支同一个写法)。返回退回骑手多少分。"""
    from ..models import AfterSale, DeliveryIssue, Order
    from . import rider_fault

    if kind == KIND_DELIVERY:
        issue = await db.get(DeliveryIssue, record_id, with_for_update=True)
        if issue is None:
            return 0
        order_id = issue.order_id
        issue.resolve_note = (f"{issue.resolve_note};工单申诉改判:非骑手责任"
                              if issue.resolve_note else "工单申诉改判:非骑手责任")[:300]
        a = await db.scalar(select(AfterSale).where(
            AfterSale.order_id == order_id, AfterSale.fault == "rider").with_for_update())
    else:
        a = await db.get(AfterSale, record_id, with_for_update=True)
        if a is None:
            return 0
        order_id = a.order_id
    if a is not None and a.fault == "rider":
        a.fault = "platform"
        a.reply = (f"{a.reply};工单申诉改判:非骑手责任"
                   if a.reply else "工单申诉改判:非骑手责任")[:300]
    order = await db.get(Order, order_id, with_for_update=True)
    back = await rider_fault.undo(db, order, why=f"信用分工单申诉成立:{note}") \
        if order is not None else None
    return back.rider_total if back else 0


async def ticket_appeal_summaries(db: AsyncSession, ticket_ids: list[int]) -> dict[int, dict]:
    """后台工单列表用:哪些工单是信用分申诉、哪种角色的、申诉的是哪一条、现在什么状态。"""
    from ..models import CreditAppeal, User

    if not ticket_ids:
        return {}
    rows = (await db.execute(
        select(CreditAppeal, User.role).join(User, User.id == CreditAppeal.user_id)
        .where(CreditAppeal.ticket_id.in_(ticket_ids)))).all()
    out = {}
    for c, role in rows:
        role = getattr(role, "value", role)
        out[c.ticket_id] = {"id": c.id, "kind": c.kind, "record_id": c.record_id,
                            "user_id": c.user_id, "status": c.status,
                            "resolve_note": c.resolve_note, "role": role,
                            "role_label": ROLE_LABELS.get(role, role),
                            "kind_label": kind_label(role, c.kind)}
    return out


# ---------------------------------------------------------------------------
# 公示。透明中心、规则页、本人明细页读的都是这一份
# ---------------------------------------------------------------------------


def _violation_rows(role: str) -> list[dict]:
    from .enforcement import SEVERITY, rules_of
    return [{"kind": r.kind, "label": r.label, "severity": r.severity,
             "severity_label": SEVERITY[r.severity].label,
             "points": -violation_points(r.severity)}
            for r in rules_of(role)]


def _violation_line(role: str) -> str:
    """「「骚扰、辱骂、威胁」每次 −20;「恶意售后」「刷单」每次 −10」—— 按扣分从多到少。
    每一类加引号:有的类别名里自己就带顿号,不加的话分不清是几类。"""
    by_pts: dict[int, list[str]] = {}
    for v in _violation_rows(role):
        by_pts.setdefault(-v["points"], []).append(f"「{v['label']}」")
    return ";".join(f"{''.join(labels)}每次 −{pts}"
                    for pts, labels in sorted(by_pts.items(), reverse=True))


#: 三种角色「完成一单」各不算哪几种(和 [_order_rows] 一一对应)
_PLUS_NOT_COUNTED = {
    "customer": ["追加的菜(随原单一起送,不算另一单)",
                 "平台核实是刷单的单",
                 "配送时判为你的原因的那一单",
                 "到店自取超时没去取、系统自动完成的单"],
    "merchant": ["追加的菜(随原单一起送,不算另一单)",
                 "平台核实是刷单的单",
                 "骑手报「到店未出餐」「餐品不齐」、判为商家责任提前结束的那一单"],
    "rider": ["追加单(和原单一趟送,不算另一单)",
              "平台核实是刷单的单",
              "配送异常裁成退款、直接结束的那一单(没有送到顾客手里)"],
}

_PLUS_SCOPE = {
    "customer": ("完成的订单", "订单记录 orders:状态为「已完成」"),
    "merchant": ("你名下各门店完成的订单",
                 "订单记录 orders:店主是你的门店、状态为「已完成」"),
    "rider": ("你送完的订单", "订单记录 orders:你配送的、状态为「已完成」"),
}


def _minus_spec(role: str) -> list[dict]:
    hours = _appeal_hours()
    who = ROLE_LABELS[role]
    common = {"points": -FAULT_POINTS, "cap": MINUS_CAP, "window_days": WINDOW_DAYS}
    if role == "customer":
        items = [{
            **common,
            "key": KIND_DELIVERY,
            "label": "配送时联系不上或地址有误,平台判为顾客原因",
            "counts": "骑手上报配送异常、平台裁决「按送达处理」(判为顾客原因)的,"
                      f"每次 −{FAULT_POINTS}",
            "source": "配送异常工单 delivery_issues:裁决 resolution = 按送达处理,"
                      "时间按裁决时刻 resolved_at",
            "appeal": f"裁决后 {hours} 小时内在订单页申诉(改判的话钱原路退回);"
                      f"过了 {hours} 小时走客服工单",
        }]
    elif role == "merchant":
        items = [{
            **common,
            "key": KIND_AFTER_SALE,
            "label": "售后或配送异常,平台判为商家责任",
            "counts": f"平台判为商家责任的,每次 −{FAULT_POINTS}:① 你拒绝的售后,顾客申诉、"
                      "平台复核认定应当受理;② 骑手上报「到店未出餐」「餐品不齐」,平台裁决为商家"
                      "责任、由你承担退款。你自己同意的售后和退款不算",
            "source": "售后记录 after_sales:判责 fault = 商家,而且是平台判出来的 —— ①「售后被拒」"
                      "的申诉改判成立(appeals 里 after_sale_rejected),② 配送异常(到店未出餐、"
                      "餐品不齐)裁决退款时记的那条;时间按判责时刻 processed_at",
            "appeal": f"判责后 {hours} 小时内申诉售后判责(改判的话被冲掉的净额补回来);"
                      f"过了 {hours} 小时走客服工单",
        }]
    else:
        items = [{
            **common,
            "key": KIND_DELIVERY,
            "label": "配送异常,平台裁决为骑手责任",
            "counts": "你上报的配送异常(餐损、丢餐这类),平台裁决退款、判为骑手责任的,"
                      f"每次 −{FAULT_POINTS}。钱另外算:顾客全额退款,这单配送费不计,商家那份餐钱"
                      "先由骑手保障金池出、不够的从你的收入里扣。"
                      "「到店未出餐」「餐品不齐」判的是商家责任,不算你的",
            "source": "配送异常工单 delivery_issues:裁决 resolution = 退款,而且不是到店未出餐、"
                      "餐品不齐,时间按裁决时刻 resolved_at",
            "appeal": f"裁决后 {hours} 小时内申诉(改判的话记录上写明不是你的责任,扣的钱退回);"
                      f"过了 {hours} 小时走客服工单",
        }, {
            **common,
            "key": KIND_AFTER_SALE,
            "label": "顾客售后,平台仲裁判为骑手责任(洒餐、丢餐等)",
            "counts": "顾客申请售后、平台仲裁判为骑手责任的,"
                      f"每次 −{FAULT_POINTS}。钱和配送异常判骑手责任一样算(这单配送费不计,商家那份"
                      "餐钱先由保障金池出、不够的从你的收入里扣)。配送异常裁决时顺带补的那条售后不重复计",
            "source": "售后记录 after_sales:判责 fault = 骑手,这一单是你送的,"
                      "时间按仲裁时刻 processed_at",
            "appeal": f"仲裁后 {hours} 小时内申诉(改判的话记录上写明不是你的责任,扣的钱退回);"
                      f"过了 {hours} 小时走客服工单",
        }]
    items.append({
        "key": KIND_VIOLATION,
        "label": "违规判定成立",
        "items": _violation_rows(role),
        "cap": MINUS_CAP,
        "window_days": WINDOW_DAYS,
        "counts": f"平台判定成立、没被推翻的违规:{_violation_line(role)}",
        "source": f"违规记录 violations:本人、判定时的身份是{who}、未被推翻"
                  "(overturned_at 为空),时间按判定时刻 created_at;"
                  "哪类算严重见平台规则的处置目录",
        "appeal": "走客服工单;申诉成立的那一条会被推翻,处置级别一起重算",
    })
    return items


#: 正常的权利不扣分。每一条都对着代码核过(见模块抬头)
_NOT_COUNTED = {
    "customer": [
        {"what": "商家接单前取消、接单后 2 分钟内取消", "why": "这是你的权利"},
        {"what": "出餐后按账取消", "why": "该你承担的那部分钱已经付了,不再另外扣分"},
        {"what": "申请售后、退款(不管商家同意还是拒绝)", "why": "这是你的权利;"
         "只有平台判定「恶意售后」成立才算,那一条记在违规里"},
        {"what": "给差评、评价被隐藏", "why": "评价被隐藏只说明这条评价不该算在商家头上"
         "(常见的是配送晚了、出餐正常),不等于你做错了什么;辱骂、威胁、拿差评要挟的,"
         "平台会按违规记「骚扰、辱骂、威胁」"},
        {"what": "商家对订单的「标记异常」", "why": "只供平台核查,不对你做任何处置"},
        {"what": "风控限制领券、账号冻结待复核", "why": "冻结是待复核不是结论,"
         "限制管的是领券和补贴,和交易对方无关"},
        {"what": "聊天、视频里的社区处罚", "why": "和交易无关"},
        {"what": "排队被过号、待支付超时关单、住宿未入住", "why": "没有人判过你的对错,"
         "或者该付的已经按规则付了"},
    ],
    "merchant": [
        {"what": "接单前拒单", "why": "这是你的权利(拒单要写原因给顾客)"},
        {"what": "没来得及接单、超时被系统取消的单", "why": "钱全额退给顾客,没有人判过谁的对错"},
        {"what": "自己同意的售后、退款,缺货部分退款", "why": "这是你自己的决定,"
         "同意了就是认了这笔钱,不再另外扣分"},
        {"what": "拒绝售后", "why": "这是你的权利;只有顾客申诉、平台复核认定应当受理的才算,"
         "那一条你还能再申诉"},
        {"what": "接单后取消", "why": "不直接扣分;平台判定「私自取消、强迫用户取消、"
         "下单后加价」成立的,记在违规里"},
        {"what": "出餐慢、出餐超时、骑手到店等餐", "why": "慢不算坏,出餐时长不进任何分数"},
        {"what": "差评、评分", "why": "评分是顾客的看法,不是平台的判定;恶意差评可以申诉隐藏"},
        {"what": "食安投诉成立(平台先行全额退款)", "why": "先赔顾客的钱由平台垫付,投诉本身不扣分;"
         "平台认定是食品安全事故的,按违规记「食品安全事故」,那一条扣分,也能申诉"},
        {"what": "排队叫号、过号", "why": "排队不是订单,不进信用分"},
    ],
    "rider": [
        {"what": "不抢单、挑单、下线、在线时长", "why": "接不接、什么时候跑是你的自由"},
        {"what": "转单(不管当天转了几次)", "why": "转多了是按转单规则暂停当天抢单、"
         "次日自动恢复,没有人判过你的对错,不扣信用分"},
        {"what": "送得慢、超时", "why": "慢不算坏;超时只向顾客致歉,不罚款、不扣你的钱"},
        {"what": "差评、评分", "why": "评分是顾客的看法,不是平台的判定"},
        {"what": "上报配送异常", "why": "上报是你的权利;只有平台裁决为骑手责任的才算,"
         "那一条可以申诉"},
        {"what": "到店未出餐、餐品不齐", "why": "那是商家那一环的问题:平台裁决退款时判的是商家责任、"
         "由商家承担退款,不算你的,你这一趟的配送费照常结算"},
        {"what": "配送异常判为顾客原因、协调后继续送的", "why": "不是你的责任"},
        {"what": "报事故、SOS、强制取餐", "why": "安全第一,这些都不扣分"},
    ],
}

_VISIBILITY = {
    "customer": [
        {"who": "你自己", "what": "分数、每一项加减分和对应的记录、到哪天不再计分、申诉入口"},
        {"who": "商家", "what": "接单之后,在这一单上看到分数和等级,看不到明细。"
         "接单之前(新单提醒、新单详情)看不到"},
        {"who": "骑手", "what": "接到这一单之后,在这一单上看到分数和等级,看不到明细。"
         "抢单大厅、派单推荐里看不到"},
        {"who": "平台客服", "what": "处理你的申诉时看得到明细"},
        {"who": "其他人", "what": "看不到。不出现在店铺页、评价、开放接口和任何公开页面"},
    ],
    "merchant": [
        {"who": "你自己", "what": "分数、每一项加减分和对应的记录、到哪天不再计分、申诉入口。"
         "分数记在店主名下,名下各门店共用一个;店员、品牌经理看不到这一页"},
        {"who": "顾客", "what": "你接单之后,在这一单上看到分数和等级,看不到明细。"
         "店铺页、搜索、列表里看不到"},
        {"who": "骑手", "what": "接到这一单之后,在这一单上看到分数和等级,看不到明细。"
         "抢单大厅、新单推送里看不到"},
        {"who": "平台客服", "what": "处理你的申诉时看得到明细"},
        {"who": "其他人", "what": "看不到。不出现在店铺页、搜索、排序、开放接口和任何公开页面"},
    ],
    "rider": [
        {"who": "你自己", "what": "分数、每一项加减分和对应的记录、到哪天不再计分、申诉入口"},
        {"who": "顾客", "what": "你接到他的单之后,在这一单上看到分数和等级,看不到明细"},
        {"who": "商家", "what": "你接到这家店的单之后,在这一单上看到分数和等级,看不到明细"},
        {"who": "平台客服", "what": "处理你的申诉时看得到明细"},
        {"who": "其他人", "what": "看不到。不出现在抢单大厅、派单推荐、开放接口和任何公开页面"},
    ],
}

_NEVER_USED_FOR = {
    "customer": [
        "不用来自动拒单 —— 商家接单之前根本看不到它",
        "不改派单顺序 —— 抢单大厅里没有它,排序公式里也没有它",
        "不改价格 —— 菜价、配送费、优惠都和它无关",
        "不限制下单、领券、售后 —— 那些只看平台规则里的处置级别",
    ],
    "merchant": [
        "不进店铺排序、曝光和搜索 —— 店铺页、列表、搜索里根本没有它",
        "不影响骑手接不接你的单 —— 抢单大厅、新单推送里没有它,排序公式里也没有它",
        "不改费率和价格 —— 抽成只看单量档位",
        "不触发处置 —— 限制、冻结照旧按违规计次,和分数高低无关",
    ],
    "rider": [
        "不改派单顺序 —— 抢单大厅、派单推荐里没有它,商家和顾客接单之前也看不到它",
        "不改配送费、小费 —— 配送费按距离算,和它无关",
        "不限制上线、抢单 —— 抢单暂停只看转单规则,处置照旧按违规计次,和分数高低无关",
        "不是服务分、派单分、段位 —— 平台仍然没有这些影响接单的东西",
    ],
}

#: 「交易对方」是谁(刷新那一句用)
_OTHERS = {"customer": "商家、骑手", "merchant": "顾客、骑手", "rider": "顾客、商家"}


def public_spec(role: str = "customer") -> dict:
    """某一种角色的信用分怎么算。**每个数字都从上面的常量读**,改常量就等于改公示
    (单测按「改常量公示跟着变」守着);三种角色的结构一模一样,只有「什么算扣分」、
    「什么不扣分」、「谁看得到」按角色不同。"""
    _check_role(role)
    top = LEVELS[0]
    who = ROLE_LABELS[role]
    scope, source = _PLUS_SCOPE[role]
    since = count_from_label()
    return {
        "version": FORMULA_VERSION,
        "role": role,
        "role_label": who,
        "title": f"{who}信用分",
        "range": {"min": FLOOR, "max": CEIL},
        "base": BASE,
        "window_days": WINDOW_DAYS,
        "formula": (f"信用分 = {BASE} + 完成订单加分 − 扣分合计,"
                    f"结果限定在 {FLOOR}–{CEIL} 之间。只看最近 {WINDOW_DAYS} 天;"
                    f"扣分只算 {since} 起(含这一天)的裁决和判定"),
        # 起算日(北京日期)和它的理由。加分不跟着它走 —— 理由也写在这一句里
        "count_from": since,
        "count_from_why": (f"{since} 之前的配送异常裁决、售后判责、违规判定都不扣分:以前后台处理"
                           "配送异常的按钮叫「退款」,判的人不知道自己是在判谁的责任、会扣谁的分,"
                           "拿那时候的裁决扣分等于事后改规则。完成订单的加分照常算最近 "
                           f"{WINDOW_DAYS} 天 —— 那是你实实在在做完的单,不存在当时不知道的问题"),
        "base_why": (f"新{who}从 {BASE} 分起步,和没有任何问题的老{who}在同一个等级"
                     f"(「{top.label}」)。不从 {CEIL} 起,是给完成订单留出加分的余地;"
                     f"也不从更低的分起,因为没有记录不等于有问题 —— 新{who}一上来就是低分,"
                     "等于让交易对方对他另眼相看"),
        "levels": [{"min": lv.floor, "key": lv.key, "label": lv.label} for lv in LEVELS],
        "level_rule": f"只要没有计分的扣分项,不管新老{who}都是「{top.label}」",
        "plus": [{
            "key": KIND_ORDER,
            "label": "完成一单",
            "points": ORDER_POINTS,
            "cap": ORDER_CAP,
            "window_days": WINDOW_DAYS,
            "counts": f"最近 {WINDOW_DAYS} 天里{scope},每单 +{ORDER_POINTS},最多 +{ORDER_CAP}",
            "not_counted": list(_PLUS_NOT_COUNTED[role]),
            "source": f"{source},时间按完成时刻 completed_at",
        }],
        "minus": _minus_spec(role),
        "minus_cap": ("扣分不设上限,扣到 0 为止" if MINUS_CAP is None
                      else f"扣分合计最多 {MINUS_CAP}"),
        "not_counted": [dict(x) for x in _NOT_COUNTED[role]],
        "visibility": [dict(x) for x in _VISIBILITY[role]],
        "never_used_for": list(_NEVER_USED_FOR[role]),
        "appeal": {
            "summary": "每一条扣分旁边都有「申诉」。能走原来的申诉通道就走原来的"
                       "(改判时钱和记录一起改),接不上的走客服工单;申诉成立,这一条立刻不再计分,"
                       "分数马上重算",
            "once": "一条记录走一次工单申诉;原通道维持原判之后,有新证据还可以再走一次工单",
        },
        "refresh": (f"你自己看到的是现算的;{_OTHERS[role]}看到的最多晚 "
                    f"{CACHE_TTL_SECONDS // 60} 分钟。订单完成、裁决、违规判定、申诉改判时会立刻刷新"),
    }


def rules_lines(audience: str) -> list[str]:
    """规则页「信用分」那一节:你自己的分怎么算、谁看得到、不拿它做什么。
    三种角色同一个结构(services/rules.py、商家端规则中心都用它),数字全部从常量来。"""
    _check_role(audience)
    minus = {
        "customer": f"配送时联系不上或地址有误、判为你的原因 −{FAULT_POINTS}",
        "merchant": f"你拒绝的售后被顾客申诉、平台复核判为商家责任,或者骑手报「到店未出餐」"
                    f"「餐品不齐」、平台判为商家责任 −{FAULT_POINTS}",
        "rider": f"配送异常或售后判为骑手责任 −{FAULT_POINTS}",
    }[audience]
    rights = {
        "customer": "取消、退款、售后、差评都是你的权利,不扣分",
        "merchant": "接单前拒单、同意售后和退款、出餐慢、差评都不扣分",
        "rider": "不抢单、下线、转单、送得慢、差评都不扣分",
    }[audience]
    seen = {
        "customer": "商家接单之后、骑手接到单之后才看得到你的分数和等级,看不到明细",
        "merchant": "顾客在你接单之后、骑手在接到这一单之后才看得到你的分数和等级,"
                    "看不到明细;店铺页、搜索、排序里没有它",
        "rider": "顾客和商家在你接到这一单之后才看得到你的分数和等级,看不到明细;"
                 "抢单大厅里没有它",
    }[audience]
    never = {
        "customer": "不用来拒单、排单、定价,也不限制你下单、领券、售后",
        "merchant": "不进店铺排序、曝光和搜索,不改费率,不触发处置(处置照旧按违规计次)",
        "rider": "不进派单和抢单大厅,不改配送费,不触发处置;平台仍然没有服务分、派单分、段位",
    }[audience]
    return [
        f"你有一个 {FLOOR}–{CEIL} 的信用分,公式在透明中心「信用分怎么算」,"
        "每一分都指得出是哪一条记录",
        f"起步 {BASE} 分;最近 {WINDOW_DAYS} 天每完成一单 +{ORDER_POINTS},最多 +{ORDER_CAP}",
        f"只扣平台判定成立的事,而且只算 {count_from_label()} 起的裁决和判定:{minus};"
        f"违规成立,{_violation_line(audience)}",
        rights,
        seen,
        never,
        "每一条扣分都能申诉,成立后立刻不再计分",
    ]


def counterpart_lines(audience: str) -> list[str]:
    """规则页「交易对方的信用分」那一节:接单之后能看到谁的、不许拿它做什么。"""
    _check_role(audience)
    first = {
        "customer": "商家接单之后、骑手接到这一单之后,你在这一单上能看到他们的信用分和等级"
                    "(看不到明细)",
        "merchant": "接单之后,这一单上能看到顾客的信用分和等级;骑手接到这一单之后,"
                    "也能看到骑手的(都看不到明细)。接单之前看不到",
        "rider": "接到这一单之后,能看到这一单顾客和商家的信用分和等级(看不到明细);"
                 "抢单大厅里看不到",
    }[audience]
    second = {
        "customer": "店铺页、搜索、排序里没有商家的信用分,平台也不拿它给你推荐谁 —— "
                    "它不影响你先看到谁",
        "merchant": "平台的排序、派单、价格里都没有它,也不许拿它拒单或挑单 —— "
                    "接单之后取消,照原来的规则处理",
        "rider": "平台的排序、派单、价格里都没有它,也不许拿它挑单 —— "
                 "接单之后转单,照原来的规则处理",
    }[audience]
    return [first, second, "它只算平台判定成立、能申诉的事,公式在透明中心「信用分怎么算」"]
