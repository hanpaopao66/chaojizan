"""出餐时长统计(#143):从 OrderEvent 算真实分位数。

## 数据一直在记,只是从来没人读

`OrderEvent` 完整记录了 accepted → ready 的时间戳。
实测本地库:accepted 2423 条、ready 1578 条 —— 出餐时长一直可以算出来。

所以这不是新埋点,是把已有数据接上闭环。

## 为什么需要它

现在三个数各说各话:
- `Merchant.promise_ready_minutes` 商家自报,没人核;
- `eta.py` 用**写死的 20 分钟**兜底,压根没读过商家自报值;
- 骑手到店要等多久,谁也不知道。

后果是 ETA 系统性不准 → 骑手在店里干等 → 单位时间收入下降。
而超时赔付由平台承担,商家出餐慢、平台掏钱、商家零反馈 —— 闭环不通。

## 红线(见 labor_guard.py)

这里算出来的统计量,**用途是有限的**:

✅ 给骑手更准的等待预期
✅ 给用户更准的 ETA(且只能放宽,见 clamp_eta_minutes)
✅ 治理慢出餐商家
✅ 给平台定更合理的配送费(等餐补偿)

❌ **绝不用于缩短骑手的配送时限**
❌ **绝不用于给骑手排名或考核**

出餐时长是**商家**的表现,不是骑手的。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Merchant, OrderEvent

logger = logging.getLogger("superz.prep_time")

#: 滚动窗口(天)。30 天足够反映当前水平,又不会被半年前的旧状态拖住
WINDOW_DAYS = 30

#: 样本量下限。少于这个数就**不给点值**,回退商家自报值并标明"样本不足" ——
#: 拿 3 单算出来的 P80 是噪声,而给一个假装精确的数比给区间更坏
MIN_SAMPLES = 10

#: 异常值上限(分钟)。超过它的多半是商家忘了点"出餐"、或订单卡在那里,
#: 不是真实出餐时长。不剔掉的话 P95 会被这些垃圾数据拉飞
OUTLIER_MAX_MINUTES = 120.0


@dataclass(frozen=True)
class PrepStat:
    merchant_id: int
    samples: int
    p50: float | None
    p80: float | None
    p95: float | None

    #: 样本不足时用的兜底值(商家自报)
    fallback_minutes: int

    @property
    def enough(self) -> bool:
        return self.samples >= MIN_SAMPLES

    @property
    def wait_minutes(self) -> float:
        """给骑手/ETA 用的等待预期。

        用 **P80 而不是 P50**:骑手按中位数到店,有一半的概率要白等。
        按 P80 来,五次里大概四次不用等 —— 等待的成本落在骑手身上,
        预期就该偏保守一点。
        """
        if self.enough and self.p80 is not None:
            return self.p80
        return float(self.fallback_minutes)

    @property
    def source(self) -> str:
        return "measured" if self.enough else "declared"


def _quantile(sorted_vals: list[float], q: float) -> float:
    """线性插值分位数。样本少时不引 numpy —— 为一个分位数拉个大依赖不值。"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


async def stat_for(db: AsyncSession, merchant_id: int) -> PrepStat:
    """单个商家的出餐时长分位数。"""
    stats = await stats_for(db, [merchant_id])
    return stats[merchant_id]


async def stats_for(
    db: AsyncSession, merchant_ids: list[int],
) -> dict[int, PrepStat]:
    """批量取分位数。

    抢单池一次要算几十个商家,**必须批量** —— 逐个查会把一次抢单
    变成几十次往返。
    """
    if not merchant_ids:
        return {}
    ids = list(set(merchant_ids))
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    declared = dict((await db.execute(
        select(Merchant.id, Merchant.promise_ready_minutes)
        .where(Merchant.id.in_(ids)))).all())

    # accepted 与 ready 两类事件各拉一遍,在内存里按 order_id 配对。
    # 不用 SQL 自连接:事件表按 order_id 有索引,两次简单查询比一次
    # 自连接更好读,而且这里的量级(30 天 × 几十家店)撑得住
    from ..models import Order

    rows = (await db.execute(
        select(OrderEvent.order_id, OrderEvent.to_status,
               OrderEvent.created_at, Order.merchant_id)
        .join(Order, Order.id == OrderEvent.order_id)
        .where(Order.merchant_id.in_(ids),
               OrderEvent.to_status.in_(("accepted", "ready")),
               OrderEvent.created_at >= since))).all()

    accepted: dict[int, datetime] = {}
    ready: dict[int, tuple[datetime, int]] = {}
    for order_id, status, at, mid in rows:
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if status == "accepted":
            # 同一单可能有多条(重新接单):取最早的那条
            if order_id not in accepted or at < accepted[order_id]:
                accepted[order_id] = at
        else:
            if order_id not in ready or at < ready[order_id][0]:
                ready[order_id] = (at, mid)

    buckets: dict[int, list[float]] = {i: [] for i in ids}
    for order_id, (at, mid) in ready.items():
        start = accepted.get(order_id)
        if start is None:
            continue
        minutes = (at - start).total_seconds() / 60
        # 负数(时钟回拨/数据错乱)与超长(商家忘了点出餐)都不是真实出餐时长
        if 0 <= minutes <= OUTLIER_MAX_MINUTES:
            buckets.setdefault(mid, []).append(minutes)

    out: dict[int, PrepStat] = {}
    for mid in ids:
        vals = sorted(buckets.get(mid, []))
        fb = declared.get(mid) or 15
        out[mid] = PrepStat(
            merchant_id=mid,
            samples=len(vals),
            p50=_quantile(vals, 0.50) if vals else None,
            p80=_quantile(vals, 0.80) if vals else None,
            p95=_quantile(vals, 0.95) if vals else None,
            fallback_minutes=fb,
        )
    return out
