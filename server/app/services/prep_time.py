"""出餐时长统计(#143):从 OrderEvent 算真实分位数。

## 数据一直在记,只是从来没人读

`OrderEvent` 完整记录了 accepted → ready 的时间戳。
实测本地库:accepted 2423 条、ready 1578 条 —— 出餐时长一直可以算出来。

所以这不是新埋点,是把已有数据接上闭环。

## 但那两个端点都是商家自己点的(#303)

accepted 和 ready **都是商家在自己 App 上的一下点击**,而算出来的 P80
直接变成骑手抢单卡上的「预计等餐 X 分钟」。也就是说,骑手在用一个
由对方单方面生成的数,做一个后果全由自己承担的决定 ——
到店干等的那段时间没有任何补偿(`flags.wait_comp_on` 现阶段是关的)。

这不是假想的风险。下面 OUTLIER_MIN_MINUTES 的注释记的就是实测:
"很多店接单后先点出餐、等真做好了再叫骑手"。当时的办法是把小于 1 分钟
的样本**丢掉**,但那只挡得住最极端的一档。

现在改成用骑手的 `arrived_shop_at` / `picked_up_at` **校准**商家的申报
(见 `true_ready_at`)—— 丢数据不如把数据修对。

## 这里没有惩罚,也不牵涉钱

修正后的数不罚谁、不扣分、不排名,平台不掏钱、商家不赔钱、用户不多付。
出餐这件事靠的是君子协定:大家真诚出餐即可。这个模块只负责
**让"真诚"和"不真诚"看起来不一样** —— 骑手看到真的等待预期,
商家在 `/merchants/me/prep-time` 看到真的自己。

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

import dataclasses
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Merchant, OrderEvent
from ..redis_client import get_redis

logger = logging.getLogger("superz.prep_time")

#: 滚动窗口(天)。30 天足够反映当前水平,又不会被半年前的旧状态拖住
WINDOW_DAYS = 30

#: 样本量下限。少于这个数就**不给点值**,回退商家自报值并标明"样本不足" ——
#: 拿 3 单算出来的 P80 是噪声,而给一个假装精确的数比给区间更坏
MIN_SAMPLES = 10

#: 异常值上限(分钟)。超过它的多半是商家忘了点"出餐"、或订单卡在那里,
#: 不是真实出餐时长。不剔掉的话 P95 会被这些垃圾数据拉飞
OUTLIER_MAX_MINUTES = 120.0

#: 异常值下限(分钟)。**做一份饭不可能不花时间。**
#:
#: 低于这个数的样本几乎都来自商家习惯性连点「接单」→「出餐」
#: (很多店接单后先点出餐、等真做好了再叫骑手),不是真实出餐时长。
#:
#: ⚠️ 有了 `true_ready_at` 之后,**有骑手的单基本不会再落到这里** ——
#: 提前点的那一下会被骑手的等待时长顶回去,得到的是真实值而不是 0。
#: 这条下限现在主要护的是**没有骑手环节的单**(自取、商家自送):
#: 那些单没有第二方的时刻可以校准,只能靠它兜。
#:
#: 不剔掉的后果是实打实的:实测算出来是 0 分钟,商家端会显示
#: 「比承诺快 15 分钟,承诺值可以往下调」—— 他真去调低,
#: 然后每单都超时:超时安抚券由平台掏、骑手到店干等、顾客看到的
#: 送达时间也不准。**三方一起受损,起因只是一个不该采信的 0。**
#:
#: 定 1 分钟是保守的:只剔掉物理上不可能的,不剔掉"很快但真实"的
#: (热一份便当装盒,现实里也要一分钟以上)。
OUTLIER_MIN_MINUTES = 1.0


#: 交接耗时(秒):骑手到店后打包、核对、递手的正常耗时。
#:
#: 它的作用是把「到店即取」和「到店干等」分开 —— 等待不超过它的,
#: 说明餐确实已经好了。取 90 秒是**偏宽**的:宁可把边缘情形算成
#: 「餐已好」,也不要把一次正常交接读成商家的慢。
HANDOVER_SECONDS = 90


def true_ready_at(
    declared_ready: datetime,
    arrived_shop_at: datetime | None,
    picked_up_at: datetime | None,
) -> datetime:
    """这一单的餐**真正交到骑手手上**的时刻。

    ## 为什么不能直接用商家点的那一下

    「出餐时长」原先是 `accepted → ready`,**两个端点都是商家在自己
    App 上点的一下**。而算出来的 P80 直接变成骑手抢单卡上的
    「预计等餐 X 分钟」,骑手照着它决定接不接单 —— 而到店干等的那段
    时间没有任何补偿(`flags.wait_comp_on` 现阶段是关的)。

    也就是说:**骑手在用一个由对方单方面生成的数,做一个后果全由自己
    承担的决定。** 这是这里要修的东西。

    而这不是假想:下面 OUTLIER_MIN_MINUTES 的注释记着实测观察 ——
    "很多店接单后先点出餐、等真做好了再叫骑手"。当时只能把小于 1 分钟的
    样本丢掉,而一家真要 25 分钟、却在第 5 分钟点出餐的店,完整穿过那道过滤。

    ## 规则:等待发生了,就以交接时刻为准

        没有骑手环节(自取/商家自送/没取成)  → 申报值,无从校准
        骑手到店即取(等待 ≤ 交接耗时)        → 申报值,申报被证实
        骑手等了                              → max(申报值, 取餐 − 交接耗时)

    第三条里的 `max` 不是保险,是**保护诚实的商家**:骑手来早了、
    餐确实还要做,商家在真做好的那一刻点了出餐 —— 这时申报值比
    「取餐 − 交接」更晚也更准,该用它。

    ## 这条规则的判据:提前点必须一分收益都没有

    这是整件事成立的唯一条件,也是最容易做漏的地方。固定住现实
    (骑手 10 分钟到店、餐 40 分钟到手),无论商家在第几分钟点「已出餐」,
    结果恒等于 `40 − 交接耗时`。

    ⚠️ 曾经写过一版「商家在骑手到店之后点的就信它」,理由是"骑手就站在
    跟前,提前点没意义"。那是错的:它把最优时机从"接单时"挪到了
    "骑手到店那一刻",在上面的例子里能拿到 10 分而不是 38.5 分 ——
    洞还在,只是换了个位置。单测 `test_越提前点等待越长而总数不变` 守这条。

    ## 它测的是什么,不是什么

    严格说这个数不是"厨房里做了多久",是**从接单到餐真正到手有多久**。
    这正是骑手需要的那个数 —— 他要决定的是"我去这家要不要等"。

    已知的不精确:骑手到店后自己磨蹭(去买瓶水再回来),或者在同一家店
    等着一起取第二单,都会算进来。前者少见且损己不利己;后者那段等待
    对骑手是真实发生的,写进"这家店会让你等多久"并不算错。

    ## 这个数不用来罚谁

    没有惩罚含义,不牵涉任何一分钱:平台不掏、商家不赔、用户不多付,
    也不进排序(见 routers/merchants._SORTS)。出餐这件事靠君子协定 ——
    大家真诚出餐即可。这里只负责让"真诚"和"不真诚"看起来不一样。
    """
    if arrived_shop_at is None or picked_up_at is None:
        return declared_ready
    if (picked_up_at - arrived_shop_at).total_seconds() <= HANDOVER_SECONDS:
        return declared_ready
    return max(declared_ready,
               picked_up_at - timedelta(seconds=HANDOVER_SECONDS))


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


#: 「提前点出餐」的判据:骑手到店之后还要等这么久,就算一次可疑。
#: 复用等餐补偿的免费额度 —— 那条线的含义本来就是「正常出餐区间」,
#: 超过它意味着骑手真的在白等,而商家早就把这一单标成「已出餐」了。
EARLY_READY_WAIT_MINUTES = 15


async def early_ready_suspects(db: AsyncSession, *, days: int = 14,
                               min_orders: int = 5) -> list[dict]:
    """「提前点出餐」的嫌疑商家。**只标出来,平台不自动处罚。**

    ## 为什么要盯这个

    出餐是**商家自己点的**,而出餐之后:用户失去全额退款权(取消要按判责
    分摊,餐费归商家)、商家的餐费也就保住了。也就是说商家有一个明确的动机
    ——**早点按「出餐」,既锁死用户的取消权,又把餐费收进口袋**,哪怕锅
    还没热。

    判责分摊那套口径把分界线划在「出餐」这个动作上,是因为它是平台唯一
    看得见的事实。但看得见不等于可信 —— 所以必须有一处在看它可不可信。

    ## 信号:骑手到店之后还要等多久

    商家如实点出餐,骑手到店就能取走,等待接近 0;商家提前点,骑手到店
    只能干等。`picked_up_at − arrived_shop_at` 就是这个差,而它本来就在
    算等餐补偿,不是新埋点。

    ## 为什么不自动处罚

    与 `pricing.wait_compensation_cents` 同一条立场:**治理靠数据,
    不靠罚钱**。罚下去商家会改成「等骑手快到了再点出餐」,数据一样失真,
    而平台连信号都没了。摆在管理端让人去看、去谈,比自动扣钱有用。
    """
    from sqlalchemy import text as _text
    rows = (await db.execute(_text("""
        SELECT o.merchant_id, m.name,
               count(*) AS n,
               count(*) FILTER (
                 WHERE extract(epoch FROM (o.picked_up_at - o.arrived_shop_at))
                       / 60.0 > :thr) AS n_waited,
               round(avg(extract(epoch FROM
                     (o.picked_up_at - o.arrived_shop_at)) / 60.0)::numeric,
                     1) AS avg_wait_min
        FROM orders o JOIN merchants m ON m.id = o.merchant_id
        WHERE o.arrived_shop_at IS NOT NULL
          AND o.picked_up_at IS NOT NULL
          AND o.picked_up_at > o.arrived_shop_at
          AND o.created_at >= now() - make_interval(days => :days)
        GROUP BY o.merchant_id, m.name
        HAVING count(*) >= :min_orders
    """), {"thr": EARLY_READY_WAIT_MINUTES, "days": days,
           "min_orders": min_orders})).all()
    out = []
    for r in rows:
        if not r.n_waited:
            continue
        out.append({
            "merchant_id": r.merchant_id,
            "merchant_name": r.name,
            "orders": r.n,
            "waited_orders": r.n_waited,
            "suspect_ratio": round(r.n_waited / r.n, 3),
            "avg_wait_minutes": float(r.avg_wait_min or 0),
        })
    out.sort(key=lambda x: (-x["suspect_ratio"], -x["waited_orders"]))
    return out


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


#: 出餐分位数的缓存时长(秒)。
#:
#: 这个数扫 30 天的 order_events 再在内存里按单配对 —— 实测单次 23ms,
#: profile 下**占了抢单池接口 85% 的耗时**。而抢单池是每个骑手每 5 秒
#: 调一次的接口,午高峰几十个人一起刷,这一处就把整个接口串成一条队。
#:
#: 加缓存前后,同一台机器同一个压测(ab,零失败):
#:
#:     并发 10   15.7 次/秒  p50= 619ms  →  149.2 次/秒  p50= 60ms
#:     并发 30   14.2 次/秒  p50=1927ms  →  138.1 次/秒  p50=184ms
#:     并发 60   13.1 次/秒  p50=4410ms  →  138.0 次/秒  p50=379ms
#:
#: 凭什么敢缓存:这是 **30 天的分位数**,多一单少一单挪不动它。
#: 60 秒对它来说是一瞬间,而骑手 5 秒一刷,一个 TTL 内十二次刷新
#: 只有第一次付钱。代价是新店的出餐统计最多晚一分钟生效 —— 没人会察觉。
#:
#: ⚠️ 但商家**自报**的那个兜底值不一样,那是他刚亲手改的,
#: 必须立刻生效,所以有下面的 invalidate。
_CACHE_TTL_SECONDS = 60

#: 缓存键前缀。**口径一变就要升版号** —— 缓存里存的是算好的分位数,
#: 不升的话部署后 60 秒内还在按旧口径回答。写和失效必须用同一个常量,
#: 分开写字面量迟早对不上,而对不上时失效就是个静默的空操作
_CACHE_PREFIX = "prep:v2:"


async def invalidate(merchant_id: int) -> None:
    """商家改了自报出餐时长,把缓存打掉。

    分位数本身晚一分钟没人察觉,但**自报值是商家刚刚亲手改的** ——
    改完看不到变化会被当成没保存成功。这类"我刚改的东西没生效"
    是缓存最容易制造、也最不值得制造的困惑。
    """
    try:
        await get_redis().delete(f"{_CACHE_PREFIX}{merchant_id}")
    except Exception:
        pass  # 打不掉最多多等 60 秒,不值得让保存失败


async def stats_for(
    db: AsyncSession, merchant_ids: list[int],
) -> dict[int, PrepStat]:
    """批量取分位数(带 60 秒缓存,见 _CACHE_TTL_SECONDS)。

    抢单池一次要算几十个商家,**必须批量** —— 逐个查会把一次抢单
    变成几十次往返。
    """
    if not merchant_ids:
        return {}
    ids = sorted(set(merchant_ids))

    # 缓存**按单个商家**存,不按集合。
    #
    # 按集合存看着更省事,但骑手是散在城里的:每人看到的店集合都不一样,
    # 键就各不相同,缓存等于没有。按店存则相反 —— 城中心那几家热门店
    # 会被所有人复用,骑手越多命中率越高。
    redis = get_redis()
    cached: dict[int, PrepStat] = {}
    try:
        raws = await redis.mget([f"{_CACHE_PREFIX}{i}" for i in ids])
        for i, raw in zip(ids, raws):
            if raw is not None:
                cached[i] = PrepStat(**json.loads(raw))
    except Exception:
        pass  # 缓存挂了照常现算,只是慢一点

    ids = [i for i in ids if i not in cached]
    if not ids:
        return cached
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    declared = dict((await db.execute(
        select(Merchant.id, Merchant.promise_ready_minutes)
        .where(Merchant.id.in_(ids)))).all())

    # accepted 与 ready 两类事件各拉一遍,在内存里按 order_id 配对。
    # 不用 SQL 自连接:事件表按 order_id 有索引,两次简单查询比一次
    # 自连接更好读,而且这里的量级(30 天 × 几十家店)撑得住
    from ..models import Order

    # 骑手的到店/取餐时刻和事件一起取回来 —— 它们是校准商家申报的依据
    # (见 true_ready_at)。两列都在 orders 上,这个 join 本来就有,不多一次往返
    rows = (await db.execute(
        select(OrderEvent.order_id, OrderEvent.to_status,
               OrderEvent.created_at, Order.merchant_id,
               Order.arrived_shop_at, Order.picked_up_at)
        .join(Order, Order.id == OrderEvent.order_id)
        .where(Order.merchant_id.in_(ids),
               OrderEvent.to_status.in_(("accepted", "ready")),
               OrderEvent.created_at >= since))).all()

    def _utc(v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    accepted: dict[int, datetime] = {}
    #: order_id → (商家点「已出餐」的时刻, merchant_id)。
    #: ⚠️ 下面遍历它时**别把变量叫 declared** —— 外面 `declared` 是
    #: 「商家自报的承诺分钟数」那个字典,覆盖掉的话后面 declared.get(mid)
    #: 会拿到一个 datetime,整个接口 500。riders.py 的 drops 踩过同一类坑
    ready: dict[int, tuple[datetime, int]] = {}
    #: order_id → (到店, 取餐)。同一单的每一行都带着这两列,取一次即可
    rider_ts: dict[int, tuple[datetime | None, datetime | None]] = {}
    for order_id, status, at, mid, arrived, picked in rows:
        at = _utc(at)
        rider_ts[order_id] = (_utc(arrived), _utc(picked))
        if status == "accepted":
            # 同一单可能有多条(重新接单):取最早的那条
            if order_id not in accepted or at < accepted[order_id]:
                accepted[order_id] = at
        else:
            if order_id not in ready or at < ready[order_id][0]:
                ready[order_id] = (at, mid)

    buckets: dict[int, list[float]] = {i: [] for i in ids}
    for order_id, (ready_at, mid) in ready.items():
        start = accepted.get(order_id)
        if start is None:
            continue
        arrived, picked = rider_ts.get(order_id, (None, None))
        at = true_ready_at(ready_at, arrived, picked)
        minutes = (at - start).total_seconds() / 60
        # 负数(时钟回拨/数据错乱)与超长(商家忘了点出餐)都不是真实出餐时长
        if OUTLIER_MIN_MINUTES <= minutes <= OUTLIER_MAX_MINUTES:
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
    try:
        pipe = redis.pipeline()
        for mid, st in out.items():
            pipe.set(f"{_CACHE_PREFIX}{mid}", json.dumps(dataclasses.asdict(st)),
                     ex=_CACHE_TTL_SECONDS)
        await pipe.execute()
    except Exception:
        pass  # 写不进去只是下次还得现算,不影响正确性
    out.update(cached)
    return out
