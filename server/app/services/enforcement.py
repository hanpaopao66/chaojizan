"""处置目录:同类行为计次,不折算成分数(#306)。

## 为什么不做「超级分」

平台在三处公开承诺过「没有违规积分,任何指标都不折算成分数」,
骑手侧还有「没有服务分、派单分、等级、段位」。判据是 models.py 里那句:

    **这个数字会不会影响他能看到的单?** 会,就是绳索;不会,才是数据。

分数按定义要影响处置,也就影响他能不能接单、能不能营业 —— 是绳索。
除此之外还有三件实际会发生的事:

1. **分数没法申诉。**「我为什么是 72 分」没有答案,只有"这些事加起来"。
   而计次是「你 8 月 3 日那单被判虚假出餐」—— 可以逐条申诉、逐条推翻。
2. **慢和坏会被折进同一个数轴。** 折完就分不出哪部分是能力问题。
3. **一旦有分,行为就为分服务。** riders.py 那句原话:
   「一旦骑手看到"你排第 87 名",他就会开始为名次跑单」——
   那正是我们在出餐时长上刚拆掉的那个循环。

## 级别是**算出来的**,不是存的

存的只有「成立的违规事件」(models.Violation),级别 = f(事件, 窗口, 目录)。

这条不变量换来两件计分做不到的事:

- **归零是自动的** —— 窗口一滚出去就不算了,不需要"修复"机制;
- **申诉推翻一条,级别自动重算** —— 不需要手动减分,而"减多少"这个问题
  在计分制里永远说不清。

## 对称:阈值绑在严重程度上,不绑在端上

三端能做的坏事不一样(骑手偷不了餐的反面是商家送不了餐),所以
**行为清单**必然不同。但**同一严重程度用同一套阈值**,而且申诉、可见、
归零三件事三端一字不差 —— 这才是「一方能做另一方不能做」的反面。

把阈值写在 SEVERITY 里而不是写在每一条上,对称就是结构性的:
想给某一端开小灶,得先改 SEVERITY,而那是三端共用的。
"""
from __future__ import annotations

from dataclasses import dataclass

#: 处置级别。和 User.risk_level 同一套取值 —— 那边已经有了可见性与申诉口径,
#: 不另起一套(两套级别迟早对不上,而对不上的那天没人会发现)
LEVEL_NONE = ""
LEVEL_LIMIT = "limit"
LEVEL_FROZEN = "frozen"

#: 级别的强弱序。算总级别时取最强的那个
LEVEL_ORDER = {LEVEL_NONE: 0, LEVEL_LIMIT: 1, LEVEL_FROZEN: 2}

LEVEL_LABELS = {
    LEVEL_NONE: "正常",
    LEVEL_LIMIT: "限制",
    LEVEL_FROZEN: "冻结",
}


@dataclass(frozen=True)
class Severity:
    """一档严重程度:几次、多长窗口、到了给什么级别。

    **三端共用**。想给某一端换个阈值,得改这里,而这里是三端共用的 ——
    对称因此是结构性的,不靠自觉。
    """
    key: str
    label: str
    times: int          # 窗口内成立几次
    window_days: int
    level: str


#: 两档就够。再细分下去,「为什么这条是三次那条是四次」就没法解释了 ——
#: 而解释不了的规则等于没有规则
SEVERITY = {
    "severe": Severity(
        key="severe", label="严重", times=1, window_days=180,
        level=LEVEL_FROZEN),
    "major": Severity(
        key="major", label="一般", times=3, window_days=30,
        level=LEVEL_LIMIT),
}


@dataclass(frozen=True)
class Rule:
    """一条处置规则。**公示的表就是这张表** —— 规则页从它生成。"""
    audience: str
    kind: str
    label: str
    severity: str
    #: 怎么认定的。auto = 系统判定(判据写在 detect 里);
    #: manual = 人工判定(证据链靠工单/申诉,系统给不出结论)
    decided: str
    note: str = ""

    @property
    def sev(self) -> Severity:
        return SEVERITY[self.severity]


#: 处置目录。**只列"故意破坏规则",不列"做得不好"** ——
#: 慢、少、晚都是能力和条件的问题,不在这里,也不折算成任何分数。
CATALOG: tuple[Rule, ...] = (
    # ---- 用户 ----
    Rule("customer", "malicious_after_sale", "恶意售后", "major", "manual",
         "虚构问题骗退款、批量薅券。判定后禁止自助售后,只能走工单"),
    Rule("customer", "fake_order", "刷单", "major", "manual",
         "与商家串通制造虚假交易"),
    Rule("customer", "harassment", "骚扰、辱骂、威胁", "severe", "manual",
         "对骑手或商家"),
    # ---- 商家 ----
    Rule("merchant", "fake_ready", "虚假出餐", "major", "auto",
         "餐没好就点「已出餐」,把骑手骗到店里干等。"
         "判据是骑手到店后仍要等 —— 系统看得见,不用人举报"),
    Rule("merchant", "force_cancel", "私自取消、强迫用户取消、下单后加价",
         "major", "manual"),
    Rule("merchant", "food_safety", "食品安全事故", "severe", "manual",
         "成立即转人工复核"),
    Rule("merchant", "harassment", "骚扰、辱骂、威胁", "severe", "manual",
         "对用户或骑手"),
    # ---- 骑手 ----
    Rule("rider", "theft", "偷餐、恶意毁损、私自处置他人物品",
         "severe", "manual"),
    Rule("rider", "fake_delivery", "虚假送达", "major", "manual",
         "没送到却点送达"),
    Rule("rider", "harassment", "骚扰、辱骂、威胁", "severe", "manual",
         "对用户或商家"),
)


def rules_of(audience: str) -> tuple[Rule, ...]:
    return tuple(r for r in CATALOG if r.audience == audience)


def strongest(levels) -> str:
    """一堆级别里最强的那个。"""
    return max(levels, key=lambda x: LEVEL_ORDER[x], default=LEVEL_NONE)


def level_from_counts(audience: str, counts: dict[str, int]) -> str:
    """按「每类行为成立几次」算出级别。

    `counts` 是 kind → 窗口内成立次数。**不累加不同类的次数** ——
    那就是计分了:两次虚假出餐加一次骚扰等于三次什么?没有答案。
    每一类各自看自己的阈值,取触发到的最强那一档。
    """
    hit = [r.sev.level for r in rules_of(audience)
           if counts.get(r.kind, 0) >= r.sev.times]
    return strongest(hit)


def public_table(audience: str) -> list[dict]:
    """公示用的处置表。**规则页直接从目录生成** ——
    公示的表和实际执行的表是同一张,不可能对不上。"""
    out = []
    for r in rules_of(audience):
        sev = r.sev
        when = (f"成立 {sev.times} 起"
                if sev.times == 1
                else f"{sev.window_days} 天内成立 {sev.times} 起")
        out.append({
            "kind": r.kind,
            "label": r.label,
            "when": when,
            "level": sev.level,
            "level_label": LEVEL_LABELS[sev.level],
            "decided": r.decided,
            "note": r.note,
        })
    return out


# ---------------------------------------------------------------------------
# 算级别。**存的是事件,级别现算** —— 见模块抬头
# ---------------------------------------------------------------------------


async def counts_for(subject_id: int, audience: str, db) -> dict[str, int]:
    """这个人各类行为在**各自窗口内**成立了几次。

    每一类用自己的窗口(严重档 180 天、一般档 30 天),所以不能一条 SQL
    统一 group by —— 那会把两个窗口混成一个。类别是个位数,一次查回来
    在内存里分桶更直白也更不容易错。
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from ..models import Violation

    rules = rules_of(audience)
    if not rules:
        return {}
    now = datetime.now(timezone.utc)
    oldest = now - timedelta(
        days=max(r.sev.window_days for r in rules))
    rows = (await db.execute(
        select(Violation.kind, Violation.created_at)
        .where(Violation.subject_id == subject_id,
               Violation.audience == audience,
               Violation.overturned_at.is_(None),
               Violation.created_at >= oldest))).all()
    by_kind = {r.kind: r.sev.window_days for r in rules}
    counts: dict[str, int] = {}
    for kind, at in rows:
        days = by_kind.get(kind)
        if days is None:
            continue          # 目录里删掉的旧类别:不再计入,也不报错
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at >= now - timedelta(days=days):
            counts[kind] = counts.get(kind, 0) + 1
    return counts


async def level_for(user, db) -> str:
    """这个人**当前**的处置级别。

    = max(按目录算出来的, 人工直接处置的)

    保留 `User.risk_level` 那条人工通道:反作弊命中、紧急情况,需要一个
    不必先坐实某一类行为就能拦住的口子。但它同样对本人可见、可申诉 ——
    两条通道的**可见性和申诉资格完全一样**,只是认定路径不同。

    人工那条不进目录计数:它没有"第几次"这个概念,也就没法按次归零。
    """
    audience = _audience_of(user)
    computed = level_from_counts(audience, await counts_for(
        user.id, audience, db))
    return strongest([computed, user.risk_level or LEVEL_NONE])


def _audience_of(user) -> str:
    """判定身份。`UserRole` 的取值和这里的 audience 不同名,单独映一次。"""
    role = getattr(user.role, "value", user.role)
    return {"customer": "customer", "merchant": "merchant",
            "rider": "rider"}.get(str(role), "customer")
