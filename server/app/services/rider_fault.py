"""判骑手责任的钱怎么走。2026-09-14 拍板:**平台没有钱,不做平台出钱的赔付。**

判骑手责任有两条路 —— 配送异常裁成退款(餐损、丢餐这类途中异常,admin.resolve_delivery_issue)、
售后仲裁判骑手责任(admin.after_sale_rider_fault)—— 从此同一个写法([apply]):

1. 顾客照旧全额退款:那是他自己付的钱(退款由调用方发起,这里不碰);
2. 商家无责,这单的净额照旧留着;
3. **这单骑手的收入冲回**:没送到就不计收入(骑手账本追加 fault_reversal 负数行);
   **平台这单的佣金也不挣** —— 这单平台最后一分不剩(见下面的恒等式);
4. 剩下的缺口就是商家那份净额(本质是商家那份餐钱):**先从骑手保障金池出**
   (池子余额按公开账本算,见 [fund_balance]),**池子不够的部分从骑手收入里扣**
   (追加 fault_charge 负数行 —— 账本只追加,不改旧行)。余额为负时后续收入先抵,提现照旧按余额挡;
5. 骑手能申诉(原通道 72 小时 + 客服工单)。改判成立([undo]):从骑手扣的那部分加回去
   (fault_refund 正数行),保障金池出的那部分回池(return)。

**不封顶**(2026-09-15 定,维持现状)—— 骑手出的那部分可以很大,所以三件事在规则页、信用分公示、
骑手端培训和配送异常页都写明:池子先出、不封顶、能申诉(原通道 72 小时 + 客服工单,成立的全部退回)。

## 恒等式(审计规则 rider_fault_split 按它核)

- 冲回的收入 == 这单骑手入账行的金额(一分不多扣);
- 池子出的 + 骑手另扣的 == 商家留着的这单净额;
- 于是平台在这一单上:收顾客 T、退顾客 T、付商家净额 M、骑手收入付了又收回,
  池子和骑手补进来 M —— 最后是 0,既不赚佣金也不贴钱。

跑腿单没有商家,M = 0:骑手这单收入冲回,平台那 2% 服务费也不收,池子和骑手都不用另出。

## 公开账本

骑手的这三种行不进 rider_rows(那一栏的规矩是「配送费只进不冲」,见证节点按它核),
单独进 rider_fault_rows;池子的每一笔支出、回池进 rider_fund.rows —— 和计提一样可查。
见 services/ledger.py、docs/LEDGER-SPEC.md。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import EarningKind, MerchantEarning, Order, RiderEarning, RiderFundMovement

#: 池子的事务锁号(pg_advisory_xact_lock):两个裁决同时读余额再各自支出,会把池子支成负数
FUND_LOCK_ID = 7_140_001

#: 骑手账本上判骑手责任的三种行。公开账本把它们从 rider_rows 里单独拿出来(ledger.RIDER_FAULT_KINDS)
FAULT_KINDS = (EarningKind.fault_reversal, EarningKind.fault_charge, EarningKind.fault_refund)

PAYOUT, RETURN = "payout", "return"

_BJ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class Split:
    """一次判骑手责任的钱:每一项都是正数(分)。"""
    #: 这单骑手收入冲回了多少
    income: int
    #: 商家留着的这单净额(缺口)
    merchant: int
    #: 其中保障金池出的
    fund: int
    #: 其中从骑手收入里另扣的(池子不够的部分)
    rider: int
    #: 保障金池出之前的余额
    fund_before: int

    @property
    def rider_total(self) -> int:
        """骑手这一单一共少拿 / 被扣多少:冲回的收入 + 另扣的。改判成立加回去的就是它。"""
        return self.income + self.rider


def split_gap(merchant_net: int, fund_balance: int) -> tuple[int, int]:
    """缺口怎么分:先池子(不超过余额),不够的骑手出。**纯函数,单测全在这一层。**

    返回 (池子出, 骑手出)。缺口为负或 0(跑腿单、满减大过餐费)时两边都是 0。
    """
    gap = max(int(merchant_net), 0)
    fund = min(gap, max(int(fund_balance), 0))
    return fund, gap - fund


def _bj_midnight_utc(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=_BJ).astimezone(timezone.utc)


async def fund_balance(db: AsyncSession) -> dict:
    """骑手保障金池现在有多少钱:**按公开账本算**。

    - 计提:已经关账的日子读锚点里冻结的 rider_fund.accrued_cents(当天的每单计提额也冻在里面,
      改了配置不会回头改历史);还没关账的那几天(今天、清扫没来得及建锚点的日子)按现行配置现算
      —— 和 ledger.build_day_payload 同一个口径:每一条配送入账行(kind = earning)计提一笔;
    - 支出、回池:rider_fund_movements,每一笔都进公开账本的 rider_fund.rows。
    """
    anchored, last_day = (await db.execute(text(
        "SELECT coalesce(sum((payload::jsonb -> 'rider_fund' ->> 'accrued_cents')::bigint), 0),"
        "       max(day) FROM ledger_anchors"))).one()
    live_q = select(func.count(RiderEarning.id)).where(
        RiderEarning.kind == EarningKind.earning)
    if last_day:
        live_q = live_q.where(RiderEarning.created_at >= _bj_midnight_utc(
            date.fromisoformat(last_day) + timedelta(days=1)))
    live = int(await db.scalar(live_q) or 0)
    accrued = int(anchored or 0) + live * settings.rider_fund_per_order_cents
    moved = dict((await db.execute(
        select(RiderFundMovement.kind, func.coalesce(func.sum(RiderFundMovement.amount_cents), 0))
        .group_by(RiderFundMovement.kind))).all())
    paid, returned = int(moved.get(PAYOUT, 0)), int(moved.get(RETURN, 0))
    return {"accrued_cents": accrued, "paid_cents": paid, "returned_cents": returned,
            "balance_cents": accrued - paid + returned,
            "per_order_cents": settings.rider_fund_per_order_cents}


async def _rows(db: AsyncSession, order_id: int) -> dict:
    """这一单骑手账本上各种行的金额和池子的进出:{kind: amount}。"""
    rider = dict((await db.execute(
        select(RiderEarning.kind, RiderEarning.amount_cents)
        .where(RiderEarning.order_id == order_id))).all())
    fund = dict((await db.execute(
        select(RiderFundMovement.kind, RiderFundMovement.amount_cents)
        .where(RiderFundMovement.order_id == order_id))).all())
    return {"rider": rider, "fund": fund}


async def apply(db: AsyncSession, order: Order, *, why: str) -> Split:
    """判骑手责任:冲回这单骑手收入,商家那份净额先池子后骑手。**只改库不提交**,调用方提交。

    同一单只会判一次(配送异常裁成退款时补的那条售后,售后仲裁那条路进不来;唯一约束兜底)。
    已经判过的再调一次原样返回,不重复扣。
    """
    if order.rider_id is None:
        raise ValueError("这一单没有骑手,判不了骑手责任")
    # 池子的余额读和支出写要串行:两个裁决同时读到同一个余额、各自支出,池子会被支成负数
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": FUND_LOCK_ID})
    rows = await _rows(db, order.id)
    done = rows["rider"].get(EarningKind.fault_reversal) is not None or \
        rows["rider"].get(EarningKind.fault_charge) is not None or PAYOUT in rows["fund"]
    income = max(int(rows["rider"].get(EarningKind.earning) or 0), 0)
    merchant_net = int(await db.scalar(
        select(MerchantEarning.net_cents).where(
            MerchantEarning.order_id == order.id,
            MerchantEarning.kind == EarningKind.earning)) or 0)
    if done:
        fund = int(rows["fund"].get(PAYOUT) or 0)
        return Split(income=income, merchant=max(merchant_net, 0), fund=fund,
                     rider=-int(rows["rider"].get(EarningKind.fault_charge) or 0),
                     fund_before=0)
    before = (await fund_balance(db))["balance_cents"]
    fund, rider = split_gap(merchant_net, before)
    note = why[:200]
    if income > 0:
        db.add(RiderEarning(rider_id=order.rider_id, order_id=order.id, order_no=order.order_no,
                            amount_cents=-income, kind=EarningKind.fault_reversal,
                            note=f"骑手责任,这单收入不计:{note}"[:200]))
    if rider > 0:
        db.add(RiderEarning(rider_id=order.rider_id, order_id=order.id, order_no=order.order_no,
                            amount_cents=-rider, kind=EarningKind.fault_charge,
                            note=f"骑手责任,保障金池不够的部分:{note}"[:200]))
    if fund > 0:
        db.add(RiderFundMovement(order_id=order.id, order_no=order.order_no, kind=PAYOUT,
                                 amount_cents=fund, note=f"骑手责任,商家那份餐钱:{note}"[:200]))
    await db.flush()
    return Split(income=income, merchant=max(merchant_net, 0), fund=fund, rider=rider,
                 fund_before=before)


async def undo(db: AsyncSession, order: Order, *, why: str) -> Split | None:
    """申诉改判成立:从骑手扣的那部分加回去,保障金池出的那部分回池。**只改库不提交。**

    这一单没按骑手责任扣过钱(比如改判之前的老裁决)返回 None;已经退过的不重复退。
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": FUND_LOCK_ID})
    rows = await _rows(db, order.id)
    taken = -int(rows["rider"].get(EarningKind.fault_reversal) or 0) \
        - int(rows["rider"].get(EarningKind.fault_charge) or 0)
    fund = int(rows["fund"].get(PAYOUT) or 0)
    if taken <= 0 and fund <= 0:
        return None
    note = why[:200]
    if taken > 0 and rows["rider"].get(EarningKind.fault_refund) is None \
            and order.rider_id is not None:
        db.add(RiderEarning(rider_id=order.rider_id, order_id=order.id, order_no=order.order_no,
                            amount_cents=taken, kind=EarningKind.fault_refund,
                            note=f"申诉改判,退回:{note}"[:200]))
    if fund > 0 and RETURN not in rows["fund"]:
        db.add(RiderFundMovement(order_id=order.id, order_no=order.order_no, kind=RETURN,
                                 amount_cents=fund, note=f"申诉改判,回池:{note}"[:200]))
    await db.flush()
    income = -int(rows["rider"].get(EarningKind.fault_reversal) or 0)
    return Split(income=income, merchant=0, fund=fund,
                 rider=-int(rows["rider"].get(EarningKind.fault_charge) or 0), fund_before=0)


async def judge_after_sale(db: AsyncSession, a, order: Order, *, reason: str,
                           actor_role: str, actor_id: int | None) -> tuple[int, Split]:
    """一条售后判骑手责任的整套动作,**只改库不提交**。返回 (退给顾客多少, 这一次的钱)。

    后台售后仲裁(admin.after_sale_rider_fault)和跑腿单「售后被拒」的申诉改判
    (appeals._overturn:跑腿没有商家,改判成立只可能是骑手的问题)共用这一份,钱只有一种走法:

    1. 送达了、还没确认收货的,先按完成结算(骑手、商家各自入账)再冲 —— 不然之后自动完成时
       照常入账,这一截就成了平台出的钱;
    2. 售后记成已受理、判骑手责任(骑手 72 小时内可以在 after_sale_rider 申诉);
    3. 顾客全额退款(含配送费):退他实付里还没退回去的钱(refund_calc.unrefunded_paid_cents ——
       缺货、改地址退过的已经从实付里扣了,帮买按小票退过的差价没扣,都只算一次);
    4. [apply]:这单骑手收入冲回、商家那份先池子后骑手。

    调用方负责校验(这一单有骑手、售后没受理过、还有钱可退)、提交、推送、刷信用分缓存。
    """
    from ..models import AfterSaleStatus, OrderEvent
    from ..state_machine import OrderStatus
    from .refund_calc import unrefunded_paid_cents
    from .settlement import settle_order
    from .wechat_pay import request_refund

    now = datetime.now(timezone.utc)
    if order.status == OrderStatus.DELIVERED:
        order.status = OrderStatus.COMPLETED
        order.completed_at = now
        await settle_order(db, order)
        db.add(OrderEvent(order_id=order.id, from_status=OrderStatus.DELIVERED.value,
                          to_status=OrderStatus.COMPLETED.value,
                          actor_role=actor_role, actor_id=actor_id,
                          note="售后判骑手责任,按完成结算后冲回"))
    # 原来直接退 total_cents:帮买按小票退过差价的单(那笔退款不扣实付)会把差价再退一遍
    refund_amount = await unrefunded_paid_cents(db, order)
    a.status = AfterSaleStatus.accepted
    a.fault = "rider"
    a.reply = (reason or "配送责任")[:300]
    a.processed_at = now
    note = "骑手责任,全额退款(含配送费)"
    order.refund_note = f"{order.refund_note};{note}" if order.refund_note else note
    # refund_cents 由 request_refund 自己累计(提前加会让通道反推出 2T)
    await request_refund(db, order, refund_amount, "售后判骑手责任")
    split = await apply(db, order, why=f"售后仲裁:{a.reply}")
    return refund_amount, split


def rider_push_text(split: Split) -> str:
    """推给骑手的那一句:这单少拿多少、池子出多少、另扣多少 —— 几个数都照实说。"""
    parts = [f"这单收入 ¥{split.income / 100:.2f} 不计"] if split.income else []
    if split.merchant:
        line = f"商家那份餐钱 ¥{split.merchant / 100:.2f} 先由骑手保障金池出"
        if split.rider:
            line += (f" ¥{split.fund / 100:.2f},池子不够的 ¥{split.rider / 100:.2f} "
                     "从你的收入里扣(余额不够的,之后的收入先抵)")
        parts.append(line)
    return ";".join(parts) or "这单没有要你出的钱"
