"""顾客信用分:0–100,公式公开,交易对方可见,可以申诉(2026-09 拍板)。

## 和「不做分数」那条立场的关系

services/enforcement.py 的抬头写了处置为什么不做分数,理由有三条:分数没法申诉
(「我为什么是 72 分」没有答案)、慢和坏会被折进同一个数轴、一旦有分行为就为分服务。
这个信用分是拍板要做的,设计上逐条回应:

1. **每一分都指回一条记录。**「为什么是 72」的答案是一张清单:基础 90、最近完成 2 单
   +2、某年某月某单配送时联系不上 −10、某条违规 −10。每一条扣分都能单独申诉,
   申诉成立立刻重算。分数不落库,永远从原始记录现算(缓存随时可丢)。
2. **只扣被判定成立的不当行为,不扣「做得不好」。** 见下面「算什么、不算什么」。
3. **它不改变任何人能看到什么、能买到什么。** 不自动拒单、不改派单顺序、不改价格、
   不限制下单领券售后;商家接单之后、骑手接到单之后才看得到。按 models.py 那句判据
   ——「这个数字会不会影响他能看到的单?会,就是绳索」—— 它不影响,所以是数据。
   ⚠️ 谁想让派单、排序、定价、自动接单读它,就是在把它变成绳索。
   tests/unit/test_customer_credit.py 有结构守卫:派单、定价、抢单池的源码里不许出现它。

## 算什么、不算什么

**正常的权利不扣分。** 商家接单前取消、接单后 2 分钟内取消、出餐后按账取消
(该付的钱已经付了)、申请售后和退款(不管商家同意还是拒绝)、给差评 —— 都是顾客的权利,
在这些事上扣分就是在惩罚行使权利。**只扣平台判定成立、而且当事人有地方申诉的事**:

- 配送异常裁决为「按送达处理」(联系不上 / 地址有误,判为顾客原因)。
  来源 delivery_issues(resolution = mark_delivered),时刻取 resolved_at;
- 违规判定成立(enforcement.CATALOG 里顾客的那几类:恶意售后、刷单、骚扰辱骂威胁)。
  来源 violations(audience = customer、overturned_at 为空),时刻取 created_at。

加分只有一项:完成订单。来源 orders(status = completed),时刻取 completed_at。

刻意没算进来的(每一条都核过数据,理由也公示在 public_spec 的 not_counted 里):

- **评价被隐藏**:商家申诉差评成立只说明「这条评价不该算在商家头上」,常见的是配送晚了、
  出餐是正常的(见 appeals._target_summary 附的配送证据)—— 写评价的人没做错什么。
  真是恶意的(辱骂、威胁、拿差评要挟),平台会按违规记一条「骚扰、辱骂、威胁」;
- **商家「标记异常」**(order_flags):既定口径是只供平台核查、不对顾客做任何处置,
  顾客不知道被标了、也没地方申诉。拿它扣分就成了一条绕过申诉的处罚路径;
- **恶意售后黑名单开关**(users.after_sale_banned):是一个开关,指不回哪一单、哪一天;
  要计分的恶意售后以违规记录(violations)为准;
- **风控限制 / 冻结**(users.risk_level):冻结是「待人工复核」,不是结论;限制管的是领券和补贴,
  和交易对方无关;
- **社区处罚**(social_sanctions):管的是聊天和视频里的言行,和交易无关;商家、骑手本来就没有
  社交账号(SOCIAL_ROLES 只有顾客),把它折进交易信用会让一条视频评论影响买外卖;
- **排队被过号**:商家的单方面操作,没人判过;**住宿未入住**:首晚房费已按规则付了。

## 谁能看到

- 顾客本人:分数、每一项加减分和对应的记录、到哪天不再计分、申诉入口;
- 商家:**接单之后**,在这一单上看到分数和等级,看不到明细;
- 骑手:**接到这一单之后**,在这一单上看到分数和等级,看不到明细;
- 接单之前(新单提醒、新单详情、抢单大厅、派单推荐)一律看不到 —— 否则会被拿来挑顾客,
  这违背「不按人挑单」。只有 routers/orders.py 的订单列表和订单详情会带上它(见 [attach]),
  抢单池、开放接口、推送、WebSocket 都不带。

## 缓存和失效

订单列表是轮询接口,不能每次现算。按人缓存在 Redis(`credit:v{版本}:{user_id}`,
[CACHE_TTL_SECONDS]),只存分数和等级。**事实变了就打掉**,调用点:

- 订单完成:orders.transition、orders.pickup_verify、admin.resolve_delivery_issue
  (先行赔付直接完成)、auto_flow.sweep_once(自动确认收货、自取超时);
- 判定改变:admin.resolve_delivery_issue(判为顾客原因)、admin.record_violation、
  admin.overturn_violation、admin 风控订单结论(刷单确认的单不算完成订单);
- 申诉改判:appeals.resolve_appeal(配送异常的原申诉通道)、本模块的 [resolve_ticket_appeal]。

打不掉(Redis 挂了、漏了一个调用点)时最多晚 TTL 那么久;时间窗滚动(记录满 180 天
不再计分)也靠 TTL 带出来。本人看的明细页每次现算,不走缓存。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..redis_client import get_redis

# ---------------------------------------------------------------------------
# 公式。**公示的就是这几个常量** —— /transparency/credit 从 public_spec() 读,
# 规则页从 rules_lines() 读,计算从 compute() 读,三处是同一份
# ---------------------------------------------------------------------------

#: 口径一变就升:缓存键带着它,部署之后不会拿旧口径的缓存回答
FORMULA_VERSION = 1

#: 起始分。新用户就是这个分,和没有问题的老用户在同一个等级,理由见 public_spec 的 base_why
BASE = 90
FLOOR, CEIL = 0, 100
#: 只看最近这么多天。加分和扣分用同一个窗口,满了自动不再计分,不需要谁去「修复」
WINDOW_DAYS = 180

#: 完成一单加几分、最多加多少
ORDER_POINTS = 1
ORDER_CAP = 10

#: 配送异常判为顾客原因,每次扣几分
DELIVERY_FAULT_POINTS = 10

#: 违规判定成立,按 enforcement.SEVERITY 的档扣。**档是处置目录定的,不在这里另分** ——
#: 哪类算严重在 enforcement.CATALOG 里,这里只管每档扣几分
VIOLATION_POINTS = {"severe": 20, "major": 10}

#: 扣分项不设单项上限,合计也不封顶,只是最后结果不低于 FLOOR
MINUS_CAP = None


@dataclass(frozen=True)
class Level:
    floor: int
    key: str
    label: str


#: 等级,从高到低。**最高一档的下沿就是 BASE**:没有扣分项的人一定在最高一档,
#: 新用户、老用户都一样(单测守着)
LEVELS = (
    Level(90, "good", "良好"),
    Level(70, "fair", "一般"),
    Level(0, "low", "偏低"),
)

KIND_ORDER = "order_completed"
KIND_DELIVERY = "delivery_fault"
KIND_VIOLATION = "violation"
#: 能申诉的扣分项。只有扣分能申诉 —— 加分没有人会申诉
APPEALABLE_KINDS = (KIND_DELIVERY, KIND_VIOLATION)

#: 交易对方能看到分数的订单状态:接单之后、没取消。
#: 待支付、待接单看不到(那正是挑顾客的时刻),取消了的单交易已经结束,不给
COUNTERPART_STATUS_VALUES = ("accepted", "ready", "picked_up", "delivered", "completed")

#: 按人缓存多久。时间窗滚动、漏打的失效,最多晚这么久
CACHE_TTL_SECONDS = 600
_CACHE_PREFIX = f"credit:v{FORMULA_VERSION}:"

#: 按下单时间给查询划的下界比窗口多出的天数(走 (customer_id, created_at) 索引)。
#: 窗口按完成 / 裁决时刻算,而一单从下单到完成最多隔着预约 + 24 小时自动确认 ——
#: 30 天绰绰有余,多圈进来的由 compute 按真实时刻再筛一遍
_CREATED_SLACK_DAYS = 30

_ISSUE_KIND_LABELS = {
    "cannot_contact": "联系不上",
    "wrong_address": "地址有误",
    "food_damaged": "出现餐损",
    "items_missing": "餐品不齐",
    "other": "出现异常",
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


# ---------------------------------------------------------------------------
# 纯函数:事实进、分数出。单测全在这一层
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    """一条计分的事实。**每一条都能指回一行原始记录**(kind + record_id)。"""
    kind: str
    record_id: int
    #: 决定在不在时间窗里:完成时刻 / 裁决时刻 / 判定时刻
    at: datetime
    #: 这一条的分值,带符号。完成订单 +1,扣分项为负
    points: int
    #: 给本人看的一句话
    title: str = ""
    order_no: str = ""
    #: 平台写给本人的说明(违规的判定说明、配送异常的裁决备注)
    note: str = ""


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


def compute(facts: Iterable[Fact], now: datetime | None = None) -> Score:
    """**唯一的公式。** 本人的明细、交易对方看到的分数、透明中心的说明都是它。

    信用分 = BASE + min(窗口内完成单数 × ORDER_POINTS, ORDER_CAP) − 窗口内扣分合计,
    限定在 FLOOR–CEIL。时间窗在这里按每条的真实时刻筛,查询只负责把候选捞全。
    """
    now = now or utcnow()
    live = [f for f in facts if in_window(f.at, now)]
    orders = sum(1 for f in live if f.kind == KIND_ORDER)
    plus = min(orders * ORDER_POINTS, ORDER_CAP)
    deductions = tuple(sorted((f for f in live if f.points < 0),
                              key=lambda f: (_utc(f.at), f.record_id), reverse=True))
    minus = sum(-f.points for f in deductions)
    score = max(FLOOR, min(CEIL, BASE + plus - minus))
    return Score(score=score, level=level_of(score), base=BASE, plus=plus, minus=minus,
                 orders_in_window=orders, deductions=deductions)


def brief_of(s: Score) -> dict:
    """交易对方看到的全部内容:分数和等级。**没有明细。**"""
    return {"score": s.score, "level": s.level.key, "level_label": s.level.label}


def appeal_state(fact: Fact, *, original: str | None, ticket: str | None,
                 ticket_note: str = "", original_note: str = "",
                 now: datetime | None = None) -> dict:
    """一条扣分记录旁边的「申诉」该是什么样子。

    - `original`:原来那条申诉通道(appeals 表)里这条记录的状态,没申诉过为 None。
      只有配送异常有原通道(delivery_issue,72 小时);违规记录没有,传 None;
    - `ticket`:走客服工单的信用分申诉(credit_appeals)的状态,没提过为 None。

    能接原通道就接原通道(改判的话钱也退回),接不上的走工单。**申诉成立的那一条根本
    不会出现在扣分项里**(查询已经把它排除了),所以这里不处理 overturned。
    """
    from ..routers.appeals import APPEAL_WINDOW, within_window

    now = now or utcnow()
    after = "申诉成立后,这一条不再计分,分数马上重算"
    base = {"via": "", "target_type": "", "target_id": 0, "deadline": None,
            "state": "", "label": "", "note": "", "after": after}
    if ticket == "open":
        return {**base, "state": "open", "label": "申诉处理中(客服工单)"}
    if ticket == "upheld":
        return {**base, "state": "upheld", "label": "申诉后维持原判", "note": ticket_note}
    if fact.kind == KIND_DELIVERY:
        if original is None and within_window(fact.at, now):
            return {**base, "via": "appeal", "target_type": "delivery_issue",
                    "target_id": fact.record_id, "label": "申诉",
                    "deadline": (_utc(fact.at) + APPEAL_WINDOW).isoformat()}
        if original == "open":
            return {**base, "state": "open", "label": "申诉处理中"}
        if original == "upheld":
            # 原通道维持原判:有新证据还能走一次工单(维持原判的推送里就是这么说的)
            return {**base, "via": "ticket", "state": "upheld", "note": original_note,
                    "label": "维持原判;有新证据可以提客服工单"}
    # 违规记录没有结构化的申诉入口;配送异常过了 72 小时也接不上原通道 —— 走工单
    return {**base, "via": "ticket", "label": "申诉(客服工单)"}


# ---------------------------------------------------------------------------
# 取事实。批量:订单列表一次可能要算十几个顾客,逐个查就是十几倍的往返
# ---------------------------------------------------------------------------


def _customer_rules() -> dict:
    from .enforcement import rules_of
    return {r.kind: r for r in rules_of("customer")}


def _issue_title(kind: str) -> str:
    return f"配送时{_ISSUE_KIND_LABELS.get(kind, '出现异常')},平台判为顾客原因(按送达处理)"


async def load_facts(db: AsyncSession, uids: Iterable[int],
                     now: datetime | None = None) -> dict[int, list[Fact]]:
    """这些人窗口内计分的全部事实。**已经排除了申诉成立的记录**。"""
    from ..models import (NOT_APPEND_ORDER, Appeal, CreditAppeal, DeliveryIssue, Order,
                          OrderEvent, Violation)
    from ..state_machine import OrderStatus

    ids = sorted({int(u) for u in uids if u})
    out: dict[int, list[Fact]] = {i: [] for i in ids}
    if not ids:
        return out
    now = now or utcnow()
    since = window_start(now)
    created_floor = since - timedelta(days=_CREATED_SLACK_DAYS)

    # 1) 完成的订单。「正常完成」不含:
    #    - 追加单(随原单一起送,不是另一笔交易);
    #    - 风控确认刷单的单(口径同月售剔除:risk_flags.status = confirmed);
    #    - 配送时判为顾客原因的那一单(他没收到,那一条已经在扣分项里);
    #    - 到店自取超时没来取、系统自动完成的单(auto_flow 的「自取超时自动完成」)
    done_at = func.coalesce(Order.completed_at, Order.created_at)
    customer_fault = exists().where(DeliveryIssue.order_id == Order.id,
                                    DeliveryIssue.resolution == "mark_delivered")
    pickup_timeout = exists().where(OrderEvent.order_id == Order.id,
                                    OrderEvent.from_status == OrderStatus.READY.value,
                                    OrderEvent.to_status == OrderStatus.COMPLETED.value,
                                    OrderEvent.actor_role == "system")
    rows = (await db.execute(
        select(Order.id, Order.customer_id, Order.order_no, done_at)
        .where(Order.customer_id.in_(ids),
               Order.status == OrderStatus.COMPLETED,
               Order.created_at >= created_floor,
               done_at >= since,
               NOT_APPEND_ORDER,
               text("coalesce(orders.risk_flags->>'status', '') != 'confirmed'"),
               ~customer_fault, ~pickup_timeout))).all()
    for oid, uid, no, at in rows:
        out[uid].append(Fact(KIND_ORDER, oid, at, ORDER_POINTS, "完成一单", no))

    # 2) 配送异常判为顾客原因,原申诉通道和工单申诉都没改判的
    appeal_won = exists().where(Appeal.target_type == "delivery_issue",
                                Appeal.target_id == DeliveryIssue.id,
                                Appeal.status == "overturned")
    ticket_won = exists().where(CreditAppeal.kind == KIND_DELIVERY,
                                CreditAppeal.record_id == DeliveryIssue.id,
                                CreditAppeal.status == "overturned")
    rows = (await db.execute(
        select(DeliveryIssue.id, Order.customer_id, DeliveryIssue.order_no,
               DeliveryIssue.kind, DeliveryIssue.resolved_at, DeliveryIssue.resolve_note)
        .join(Order, Order.id == DeliveryIssue.order_id)
        .where(Order.customer_id.in_(ids),
               Order.created_at >= created_floor,
               DeliveryIssue.status == "resolved",
               DeliveryIssue.resolution == "mark_delivered",
               DeliveryIssue.resolved_at.is_not(None),
               DeliveryIssue.resolved_at >= since,
               ~appeal_won, ~ticket_won))).all()
    for iid, uid, no, kind, at, note in rows:
        out[uid].append(Fact(KIND_DELIVERY, iid, at, -DELIVERY_FAULT_POINTS,
                             _issue_title(kind), no or "", note or ""))

    # 3) 违规判定成立、没被推翻的
    rules = _customer_rules()
    rows = (await db.execute(
        select(Violation.id, Violation.subject_id, Violation.kind, Violation.order_no,
               Violation.note, Violation.created_at)
        .where(Violation.subject_id.in_(ids),
               Violation.audience == "customer",
               Violation.overturned_at.is_(None),
               Violation.created_at >= since))).all()
    for vid, uid, kind, no, note, at in rows:
        rule = rules.get(kind)
        if rule is None:
            continue   # 目录里删掉的旧类别:不再计入(和 enforcement.counts_for 同一口径)
        out[uid].append(Fact(KIND_VIOLATION, vid, at, -violation_points(rule.severity),
                             f"违规成立:{rule.label}", no or "", note or ""))
    return out


# ---------------------------------------------------------------------------
# 交易对方看到的:分数和等级,带缓存
# ---------------------------------------------------------------------------


async def _put_cache(briefs: dict[int, dict]) -> None:
    if not briefs:
        return
    try:
        pipe = get_redis().pipeline()
        for uid, b in briefs.items():
            pipe.set(f"{_CACHE_PREFIX}{uid}", json.dumps(b), ex=CACHE_TTL_SECONDS)
        await pipe.execute()
    except Exception:
        pass   # 写不进去只是下次还得现算,不影响对错


async def briefs_for(db: AsyncSession, uids: Iterable[int]) -> dict[int, dict]:
    """一批顾客的分数和等级。先读缓存(mget 一次),没命中的**只补差集**,一次批量现算。"""
    ids = sorted({int(u) for u in uids if u})
    if not ids:
        return {}
    cached: dict[int, dict] = {}
    try:
        raws = await get_redis().mget([f"{_CACHE_PREFIX}{i}" for i in ids])
        for i, raw in zip(ids, raws):
            if raw is not None:
                cached[i] = json.loads(raw)
    except Exception:
        pass   # 缓存挂了照常现算,只是慢一点
    ids = [i for i in ids if i not in cached]
    if not ids:
        return cached
    now = utcnow()
    facts = await load_facts(db, ids, now)
    fresh = {i: brief_of(compute(facts[i], now)) for i in ids}
    await _put_cache(fresh)
    fresh.update(cached)
    return fresh


async def invalidate(*uids: int | None) -> None:
    """事实变了,把这几个人的缓存打掉。调用点见模块抬头。**在 commit 之后调** ——
    提交前打掉的话,别的请求可能正好在这个空档里按旧数据重新算一遍、又写回去。"""
    keys = [f"{_CACHE_PREFIX}{int(u)}" for u in uids if u]
    if not keys:
        return
    try:
        await get_redis().delete(*keys)
    except Exception:
        pass   # 打不掉最多晚 CACHE_TTL_SECONDS


def counterpart_may_see(order, viewer) -> bool:
    """这个人现在能不能在这一单上看到顾客的信用分。

    - 商家:**接过这一单**(accepted_at 有值)且没取消。待接单(新单提醒、新单详情)看不到;
      跑腿单没有商家接单这一步,挂靠的服务主体永远看不到;
    - 骑手:**这一单的骑手**且没取消。抢单大厅里的单 rider_id 是空的,谁都看不到;
    - 其他角色(顾客自己、管理员)不走这条:本人有自己的明细页,客服有后台接口。

    ⚠️ 商家那条**不自己核归属** —— 调用方(orders.my_orders 按店过滤、get_order 走
    visible_order_or_404)已经核过。别在没核过归属的地方调 [attach]。
    """
    if viewer is None:
        return False
    status = getattr(order.status, "value", order.status)
    if status not in COUNTERPART_STATUS_VALUES:
        return False
    role = getattr(viewer.role, "value", viewer.role)
    if role == "merchant":
        return order.accepted_at is not None
    if role == "rider":
        return order.rider_id is not None and order.rider_id == viewer.id
    return False


async def attach(db: AsyncSession, outs: list, orders: list, viewer) -> None:
    """给商家 / 骑手的订单列表和订单详情填 `customer_credit`(只有分数和等级)。

    **只在 routers/orders.py 的 my_orders 和 get_order 里调**。抢单池(riders.available_orders)、
    抢单回执、状态流转回执、开放接口、推送都不调 —— 单测按调用点守着。
    不能用来自动拒单、改派单顺序、改价格:这个函数的结果只进响应体,不回写任何地方。
    """
    want = [o for o in orders if counterpart_may_see(o, viewer)]
    if not want:
        return
    got = await briefs_for(db, [o.customer_id for o in want])
    by_id = {o.id: o.customer_id for o in want}
    from ..schemas import CustomerCreditOut
    for out in outs:
        uid = by_id.get(out.id)
        if uid is not None and uid in got:
            out.customer_credit = CustomerCreditOut(**got[uid])


# ---------------------------------------------------------------------------
# 本人看的明细
# ---------------------------------------------------------------------------


def _fact_row(f: Fact) -> dict:
    return {"kind": f.kind, "record_id": f.record_id, "title": f.title,
            "order_no": f.order_no, "note": f.note, "points": f.points,
            "at": _utc(f.at).isoformat(), "expires_at": expires_at(f.at).isoformat()}


async def _excluded(db: AsyncSession, uid: int, now: datetime) -> list[dict]:
    """窗口内申诉成立、不再计分的记录 —— 让本人看得到自己申诉赢了。"""
    from ..models import Appeal, CreditAppeal, DeliveryIssue, Order, Violation

    since = window_start(now)
    out: list[dict] = []
    issue_rows = (await db.execute(
        select(DeliveryIssue.id, DeliveryIssue.order_no, DeliveryIssue.kind,
               DeliveryIssue.resolved_at)
        .join(Order, Order.id == DeliveryIssue.order_id)
        .where(Order.customer_id == uid,
               DeliveryIssue.resolution == "mark_delivered",
               DeliveryIssue.resolved_at.is_not(None),
               DeliveryIssue.resolved_at >= since,
               or_(exists().where(Appeal.target_type == "delivery_issue",
                                  Appeal.target_id == DeliveryIssue.id,
                                  Appeal.status == "overturned"),
                   exists().where(CreditAppeal.kind == KIND_DELIVERY,
                                  CreditAppeal.record_id == DeliveryIssue.id,
                                  CreditAppeal.status == "overturned"))))).all()
    for iid, no, kind, at in issue_rows:
        out.append({"kind": KIND_DELIVERY, "record_id": iid, "title": _issue_title(kind),
                    "order_no": no or "", "at": _utc(at).isoformat(),
                    "why": "申诉成立,不再计分"})
    rules = _customer_rules()
    viol_rows = (await db.execute(
        select(Violation.id, Violation.kind, Violation.order_no, Violation.created_at,
               Violation.overturn_note)
        .where(Violation.subject_id == uid, Violation.audience == "customer",
               Violation.overturned_at.is_not(None),
               Violation.created_at >= since))).all()
    for vid, kind, no, at, note in viol_rows:
        rule = rules.get(kind)
        out.append({"kind": KIND_VIOLATION, "record_id": vid,
                    "title": f"违规成立:{rule.label if rule else kind}",
                    "order_no": no or "", "at": _utc(at).isoformat(),
                    "why": f"申诉成立,不再计分{('(' + note + ')') if note else ''}"})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out


async def breakdown(db: AsyncSession, uid: int, now: datetime | None = None) -> dict:
    """本人(和处理申诉的客服)看的完整明细。每次现算,顺手刷新缓存。"""
    from ..models import Appeal, CreditAppeal

    now = now or utcnow()
    facts = (await load_facts(db, [uid], now))[uid]
    s = compute(facts, now)
    await _put_cache({uid: brief_of(s)})

    ded = s.deductions
    issue_ids = [f.record_id for f in ded if f.kind == KIND_DELIVERY]
    viol_ids = [f.record_id for f in ded if f.kind == KIND_VIOLATION]
    originals: dict[int, Appeal] = {}
    if issue_ids:
        originals = {a.target_id: a for a in await db.scalars(
            select(Appeal).where(Appeal.target_type == "delivery_issue",
                                 Appeal.target_id.in_(issue_ids)))}
    tickets: dict[tuple[str, int], CreditAppeal] = {}
    conds = []
    if issue_ids:
        conds.append(and_(CreditAppeal.kind == KIND_DELIVERY,
                          CreditAppeal.record_id.in_(issue_ids)))
    if viol_ids:
        conds.append(and_(CreditAppeal.kind == KIND_VIOLATION,
                          CreditAppeal.record_id.in_(viol_ids)))
    if conds:
        tickets = {(c.kind, c.record_id): c for c in await db.scalars(
            select(CreditAppeal).where(or_(*conds)))}

    rows = []
    for f in ded:
        o = originals.get(f.record_id) if f.kind == KIND_DELIVERY else None
        t = tickets.get((f.kind, f.record_id))
        rows.append({**_fact_row(f), "appeal": appeal_state(
            f, original=o.status if o else None, ticket=t.status if t else None,
            ticket_note=t.resolve_note if t else "",
            original_note=o.resolve_note if o else "", now=now)})

    orders = sorted((f for f in facts if f.kind == KIND_ORDER and in_window(f.at, now)),
                    key=lambda f: _utc(f.at), reverse=True)
    return {
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
        "orders": {
            "count": s.orders_in_window,
            "points": s.plus,
            "cap": ORDER_CAP,
            # 只列最近的十来单:加分封顶,列全了也只是更长
            "recent": [{"order_no": f.order_no, "at": _utc(f.at).isoformat()}
                       for f in orders[:ORDER_CAP]],
        },
        "deductions": rows,
        "excluded": await _excluded(db, uid, now),
        "window_days": WINDOW_DAYS,
        "computed_at": now.isoformat(),
        "rules": public_spec(),
    }


# ---------------------------------------------------------------------------
# 走客服工单的信用分申诉
# ---------------------------------------------------------------------------

#: 工单正文的开头。后台工单列表靠它一眼认出是信用分申诉
TICKET_PREFIX = "【信用分申诉】"


async def submit_ticket_appeal(db: AsyncSession, user, kind: str, record_id: int,
                               reason: str):
    """原来的申诉通道接不上时,走客服工单申诉一条扣分记录。只改库不提交,调用方提交。

    接得上原通道的(配送异常还在 72 小时内)不收 —— 那条通道改判时连钱一起退,
    走工单反而拿不到。
    """
    from ..models import Appeal, CreditAppeal, Ticket, TicketStatus
    from ..routers.appeals import within_window
    from ..routers.tickets import MAX_OPEN_TICKETS
    from .moderation import guard_text

    if kind not in APPEALABLE_KINDS:
        raise HTTPException(422, "只有扣分的记录可以申诉")
    now = utcnow()
    facts = (await load_facts(db, [user.id], now))[user.id]
    fact = next((f for f in facts if f.kind == kind and f.record_id == record_id
                 and f.points < 0 and in_window(f.at, now)), None)
    if fact is None:
        raise HTTPException(404, "这条记录现在不计分,不需要申诉")
    if await db.scalar(select(CreditAppeal.id).where(
            CreditAppeal.kind == kind, CreditAppeal.record_id == record_id)):
        raise HTTPException(409, "这一条已经申诉过了,以平台的复核结论为准")
    if kind == KIND_DELIVERY:
        original = await db.scalar(select(Appeal).where(
            Appeal.target_type == "delivery_issue", Appeal.target_id == record_id))
        if original is None and within_window(fact.at, now):
            raise HTTPException(409, "这一条还在 72 小时申诉期里,请用它原来的申诉入口 —— "
                                     "那边改判的话,钱也会原路退回")
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
        user_id=user.id, role=getattr(user.role, "value", user.role),
        contact=user.dial_phone,
        content=(f"{TICKET_PREFIX}{fact.title}(记录 {kind}#{record_id}{tail})。"
                 f"申诉理由:{reason}")[:500])
    db.add(ticket)
    await db.flush()
    appeal = CreditAppeal(user_id=user.id, kind=kind, record_id=record_id,
                          ticket_id=ticket.id, reason=reason[:500])
    db.add(appeal)
    return appeal, ticket


async def resolve_ticket_appeal(db: AsyncSession, admin, appeal_id: int, result: str,
                                note: str):
    """客服给工单申诉下结论。改判 = 这一条不再计分(违规记录同时推翻,处置级别跟着重算)。

    **只改库不提交**,调用方提交后再调 [invalidate] 和推送 —— 和 appeals.resolve_appeal 同一个顺序。
    """
    from ..models import CreditAppeal, Ticket, TicketStatus, Violation
    from .admin_audit import log_admin_action

    if result not in ("upheld", "overturned"):
        raise HTTPException(422, "结论只能是 upheld(维持)/ overturned(改判)")
    note = (note or "").strip()
    if len(note) < 2:
        raise HTTPException(422, "写一句复核结论(会原样告诉顾客)")
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


async def ticket_appeal_summaries(db: AsyncSession, ticket_ids: list[int]) -> dict[int, dict]:
    """后台工单列表用:哪些工单是信用分申诉、申诉的是哪一条、现在什么状态。"""
    from ..models import CreditAppeal

    if not ticket_ids:
        return {}
    rows = list(await db.scalars(select(CreditAppeal).where(
        CreditAppeal.ticket_id.in_(ticket_ids))))
    return {c.ticket_id: {"id": c.id, "kind": c.kind, "record_id": c.record_id,
                          "user_id": c.user_id, "status": c.status,
                          "resolve_note": c.resolve_note}
            for c in rows}


# ---------------------------------------------------------------------------
# 公示。透明中心、规则页、本人明细页读的都是这一份
# ---------------------------------------------------------------------------


def _violation_rows() -> list[dict]:
    from .enforcement import SEVERITY, rules_of
    return [{"kind": r.kind, "label": r.label, "severity": r.severity,
             "severity_label": SEVERITY[r.severity].label,
             "points": -violation_points(r.severity)}
            for r in rules_of("customer")]


def _violation_line() -> str:
    """「骚扰、辱骂、威胁 每次 −20;恶意售后、刷单 每次 −10」—— 按扣分从多到少。"""
    by_pts: dict[int, list[str]] = {}
    for v in _violation_rows():
        by_pts.setdefault(-v["points"], []).append(v["label"])
    return ";".join(f"{'、'.join(labels)} 每次 −{pts}"
                    for pts, labels in sorted(by_pts.items(), reverse=True))


def public_spec() -> dict:
    """信用分怎么算。**每个数字都从上面的常量读**,改常量就等于改公示(单测按「改常量公示跟着变」守着)。"""
    top = LEVELS[0]
    viol = _violation_rows()
    viol_line = _violation_line()
    return {
        "version": FORMULA_VERSION,
        "range": {"min": FLOOR, "max": CEIL},
        "base": BASE,
        "window_days": WINDOW_DAYS,
        "formula": (f"信用分 = {BASE} + 完成订单加分 − 扣分合计,"
                    f"结果限定在 {FLOOR}–{CEIL} 之间。只看最近 {WINDOW_DAYS} 天"),
        "base_why": (f"新用户从 {BASE} 分起步,和没有任何问题的老用户在同一个等级"
                     f"(「{top.label}」)。不从 {CEIL} 起,是给完成订单留出加分的余地;"
                     "也不从更低的分起,因为没有记录不等于有问题 —— 新用户一上来就是低分,"
                     "等于让接单的人对他另眼相看"),
        "levels": [{"min": lv.floor, "key": lv.key, "label": lv.label} for lv in LEVELS],
        "level_rule": f"只要没有计分的扣分项,不管新老用户都是「{top.label}」",
        "plus": [{
            "key": KIND_ORDER,
            "label": "完成一单",
            "points": ORDER_POINTS,
            "cap": ORDER_CAP,
            "window_days": WINDOW_DAYS,
            "counts": f"最近 {WINDOW_DAYS} 天里完成的订单,每单 +{ORDER_POINTS},"
                      f"最多 +{ORDER_CAP}",
            "not_counted": ["追加的菜(随原单一起送,不算另一单)",
                            "平台核实是刷单的单",
                            "配送时判为你的原因的那一单",
                            "到店自取超时没去取、系统自动完成的单"],
            "source": "订单记录 orders:状态为「已完成」,时间按完成时刻 completed_at",
        }],
        "minus": [
            {
                "key": KIND_DELIVERY,
                "label": "配送时联系不上或地址有误,平台判为顾客原因",
                "points": -DELIVERY_FAULT_POINTS,
                "cap": MINUS_CAP,
                "window_days": WINDOW_DAYS,
                "counts": "骑手上报配送异常、平台裁决「按送达处理」(判为顾客原因)的,"
                          f"每次 −{DELIVERY_FAULT_POINTS}",
                "source": "配送异常工单 delivery_issues:裁决 resolution = 按送达处理,"
                          "时间按裁决时刻 resolved_at",
                "appeal": "裁决后 72 小时内在订单页申诉(改判的话钱原路退回);"
                          "过了 72 小时走客服工单",
            },
            {
                "key": KIND_VIOLATION,
                "label": "违规判定成立",
                "items": viol,
                "cap": MINUS_CAP,
                "window_days": WINDOW_DAYS,
                "counts": f"平台判定成立、没被推翻的违规:{viol_line}",
                "source": "违规记录 violations:本人、未被推翻(overturned_at 为空),"
                          "时间按判定时刻 created_at;哪类算严重见平台规则的处置目录",
                "appeal": "走客服工单;申诉成立的那一条会被推翻,处置级别一起重算",
            },
        ],
        "minus_cap": ("扣分不设上限,扣到 0 为止" if MINUS_CAP is None
                      else f"扣分合计最多 {MINUS_CAP}"),
        "not_counted": [
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
        "visibility": [
            {"who": "你自己", "what": "分数、每一项加减分和对应的记录、到哪天不再计分、申诉入口"},
            {"who": "商家", "what": "接单之后,在这一单上看到分数和等级,看不到明细。"
             "接单之前(新单提醒、新单详情)看不到"},
            {"who": "骑手", "what": "接到这一单之后,在这一单上看到分数和等级,看不到明细。"
             "抢单大厅、派单推荐里看不到"},
            {"who": "平台客服", "what": "处理你的申诉时看得到明细"},
            {"who": "其他人", "what": "看不到。不出现在店铺页、评价、开放接口和任何公开页面"},
        ],
        "never_used_for": [
            "不用来自动拒单 —— 商家接单之前根本看不到它",
            "不改派单顺序 —— 抢单大厅里没有它,排序公式里也没有它",
            "不改价格 —— 菜价、配送费、优惠都和它无关",
            "不限制下单、领券、售后 —— 那些只看平台规则里的处置级别",
        ],
        "appeal": {
            "summary": "每一条扣分旁边都有「申诉」。能走原来的申诉通道就走原来的"
                       "(改判时钱也会退),接不上的走客服工单;申诉成立,这一条立刻不再计分,"
                       "分数马上重算",
            "once": "一条记录走一次工单申诉;原通道维持原判之后,有新证据还可以再走一次工单",
        },
        "refresh": (f"你自己看到的是现算的;商家、骑手看到的最多晚 {CACHE_TTL_SECONDS // 60} 分钟。"
                    "订单完成、裁决、违规判定、申诉改判时会立刻刷新"),
    }


def rules_lines(audience: str) -> list[str]:
    """规则页上的那几条(services/rules.py 用)。数字全部从常量来。"""
    if audience == "customer":
        return [
            f"你有一个 {FLOOR}–{CEIL} 的信用分,公式在透明中心「信用分怎么算」,"
            "每一分都指得出是哪一条记录",
            f"起步 {BASE} 分;最近 {WINDOW_DAYS} 天每完成一单 +{ORDER_POINTS},"
            f"最多 +{ORDER_CAP}",
            f"只扣平台判定成立的事:配送时联系不上或地址有误、判为你的原因"
            f" −{DELIVERY_FAULT_POINTS};违规成立,{_violation_line()}",
            "取消、退款、售后、差评都是你的权利,不扣分",
            "商家接单之后、骑手接到单之后才看得到你的分数和等级,看不到明细",
            "不用来拒单、排单、定价,也不限制你下单、领券、售后",
            "每一条扣分都能申诉,成立后立刻不再计分",
        ]
    return [
        "接单之后,这一单上能看到顾客的信用分和等级(看不到明细);接单之前看不到",
        "平台的排序、派单、价格里都没有它,也不许拿它拒单或挑单 —— "
        "接单之后取消或转单,照原来的规则处理",
        "它只算平台判定成立的事(配送时联系不上被判顾客原因、违规成立),"
        "公式在透明中心「信用分怎么算」",
    ]
