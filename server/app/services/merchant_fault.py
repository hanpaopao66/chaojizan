"""判商家责任的钱怎么走。2026-09-14 拍板「平台没有钱,不出钱赔付」,2026-09-15 定:
**商家有责任,商家连配送费和小费一起出,顾客拿回全款。**

判商家责任有四条路,钱只有一种走法([apply]):

- 商家同意售后(after_sales.accept_after_sale —— 同意即认责);
- 顾客对「售后被拒」申诉、改判成立(appeals._overturn 的 after_sale_rejected);
- 配送异常「到店未出餐」「餐品不齐」裁成退款(admin.resolve_delivery_issue,services/delivery_fault);
- 食安投诉核实成立(admin.confirm_food_safety)。

1. **顾客拿回全款**:退他实付里还没退回去的钱(refund_calc.merchant_fault_refund_cents),
   含配送费和小费;平台券抵掉的那截不在实付里,不退现金、回平台自己手里。退款由调用方发起;
2. **骑手的配送费和小费照拿**:他跑了这一趟(骑手入账不动);
3. **商家**:这单净额整行冲回(settlement.reverse_merchant_earning,佣金一起冲回 —— 平台不收),
   **再追加一行负数**(fault_charge)把骑手那份(配送费 + 小费)也由商家出 —— 账本只追加,不改旧行。
   商家余额可以因此为负:之后的收入先抵,提现按余额挡(钱包的可提现 = max(0, 余额 − 保证金));
4. **平台**:佣金不收,也不贴钱。

商家自配送(没有骑手)的配送费本来就在商家入账里(settlement.credit_merchant_for_order),
冲回净额就一起冲回了,不另扣;到店自取没有配送费和小费。所以另出的那行只有平台骑手送的单才有。

分账口径(profit_sharing)的单,净额在商家自己的微信商户号里,冲回走渠道的分账回退;
另出的这行一律记在平台代收口径(settle_mode = platform)上 —— 那是商家欠平台的钱
(平台已经把配送费和小费结给了骑手、又全额退给了顾客),从平台侧余额里扣。

## 恒等式(审计规则 merchant_fault_split 按它核)

- 另出的那行 == 这单骑手那份(配送费 + 小费);
- 有另出那行的单:净额冲回了、顾客的实付全退了;
- 于是平台在这一单上:收顾客 T、退顾客 T、付骑手 K、收商家 K、商家净额付了又冲回 —— 0。

## 申诉改判:平台判错了,平台自己认

商家 72 小时内可以在售后判责的原通道申诉(appeals 的 after_sale)。改判成立([undo]):冲回的净额补回
(adjustment 正数行)、另出的那行退回(fault_refund 正数行),**钱由平台出**;顾客已经拿到的退款
不追回;判责方记 platform(和骑手责任改判同一个写法)。

## 公开账本

商家的 fault_charge / fault_refund 两种行不进 merchant_rows(那一栏每一行是「应收 − 佣金 = 净额」的菜钱),
单独进 merchant_fault_rows,逐行公开;补回净额的 adjustment 行照旧在 merchant_rows 里。
见 services/ledger.py、docs/LEDGER-SPEC.md。

## 反查:判了商家责任,就必须有另出的那一行(审计规则 4e)

规则 4d 按上面的恒等式核**已经写了**另出那一行的单;哪条路绕开了 [apply]、一行都没写,4d 看不见 ——
顾客照样拿回全款、骑手照拿,差的那份就成了平台出的钱。4e 从判责的记录反过来找([judged_query]):
新规则生效之后判了商家责任、平台骑手送的、骑手那份 > 0 的单,必须有另出的那一行。

生效时刻([charge_since])由迁移 0141 在升级那一刻记进库里:之前按旧规则判的单本来就没有这一行,
不能报成违规;生产、CI、本地各按各自升级的那一刻算,不用按环境配日期。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EarningKind, MerchantEarning, Order

#: 商家账本上判商家责任的两种行。公开账本把它们从 merchant_rows 里单独拿出来(ledger.MERCHANT_FAULT_KINDS)
FAULT_KINDS = (EarningKind.fault_charge, EarningKind.fault_refund)

#: 另出那行的备注前缀(对账单、流水里给人看的那句)
CHARGE_NOTE = "商家责任,骑手那份配送费和小费由商家出"

#: 商家流水每一种行给店主看的名字 —— 对账单 CSV、逐单明细、税务导出都读这一份,不各写一套
EARNING_KIND_LABELS = {
    "earning": "外卖入账",
    "reversal": "外卖冲账",
    "adjustment": "申诉改判,补回净额(平台出)",
    "fault_charge": "商家责任,骑手那份配送费和小费由你出",
    "fault_refund": "申诉改判,退回配送费和小费(平台出)",
}


def kind_label(kind) -> str:
    kind = getattr(kind, "value", kind)
    return EARNING_KIND_LABELS.get(kind, kind)


@dataclass(frozen=True)
class Split:
    """一次判商家责任的钱:每一项都是正数(分)。"""
    #: 这单冲回的商家净额(还没结算过的单先结算再冲;冲过了就是当初冲的数)
    reversed_net: int
    #: 另出的骑手那份(配送费 + 小费);自配送、自取为 0
    charge: int

    @property
    def merchant_total(self) -> int:
        """商家这一单一共少拿 / 多出多少:冲回的净额 + 另出的那行。改判成立补回的就是它。"""
        return self.reversed_net + self.charge


def rider_share_cents(order) -> int:
    """这单骑手那份:平台骑手送的单是配送费 + 小费,自配送、自取为 0。和 refund_calc.rider_kept_cents 同一份。"""
    from .refund_calc import rider_kept_cents
    return rider_kept_cents(order)


async def _rows(db: AsyncSession, order_id: int) -> dict:
    """这一单商家账本上各种行的净额:{kind: net}(同一种一单最多一行,唯一约束兜着)。"""
    return dict((await db.execute(
        select(MerchantEarning.kind, MerchantEarning.net_cents)
        .where(MerchantEarning.order_id == order_id))).all())


async def apply(db: AsyncSession, order: Order, *, why: str,
                actor_role: str = "system", actor_id: int | None = None) -> Split:
    """判商家责任:冲回这单净额,再追加一行负数把骑手那份也由商家出。**只改库不提交**,
    退款、提交、推送由调用方做(退多少见 refund_calc.merchant_fault_refund_cents)。

    - 送达了、还没确认收货的单先按完成结算(骑手、商家各自入账)再冲 —— 不然之后自动完成时
      商家照常入账,这笔退款就成了平台出的钱;配送异常那条路调用前已经结算过;
    - 幂等:冲过的不再冲、另出过的不再出(已经判过的再调一次原样返回)。
    """
    from ..state_machine import OrderStatus
    from .errand import is_errand
    from .settlement import reverse_merchant_earning, settle_order

    if is_errand(order):
        raise ValueError("跑腿单没有商家,判不了商家责任")
    if order.status == OrderStatus.DELIVERED:
        from ..models import OrderEvent
        order.status = OrderStatus.COMPLETED
        order.completed_at = datetime.now(timezone.utc)
        await settle_order(db, order)
        db.add(OrderEvent(order_id=order.id, from_status=OrderStatus.DELIVERED.value,
                          to_status=OrderStatus.COMPLETED.value,
                          actor_role=actor_role, actor_id=actor_id,
                          note="判商家责任,按完成结算后冲回"))
    if order.status != OrderStatus.COMPLETED:
        # 没结算过的单冲不了账:之后完成时商家会照常入账,钱就成了平台出的。调用方负责先结算
        raise ValueError(f"订单 {order.order_no} 还没结算({order.status.value}),先结算再判")
    note = why[:150]
    await reverse_merchant_earning(db, order, f"商家责任,这单净额冲回:{note}")
    await db.flush()
    rows = await _rows(db, order.id)
    charge = rider_share_cents(order)
    if charge > 0 and EarningKind.fault_charge not in rows:
        db.add(MerchantEarning(
            merchant_id=order.merchant_id, order_id=order.id, order_no=order.order_no,
            # 行内恒等式 net == food − commission 照旧成立(和补回净额的调整行同一个写法)
            food_cents=-charge, commission_cents=0, net_cents=-charge,
            # 商家欠平台的钱,记在平台代收口径上(见模块抬头「分账口径」)
            settle_mode="platform",
            kind=EarningKind.fault_charge,
            note=f"{CHARGE_NOTE}:{note}"[:200]))
        await db.flush()
        rows[EarningKind.fault_charge] = -charge
    return Split(reversed_net=max(-int(rows.get(EarningKind.reversal) or 0), 0),
                 charge=max(-int(rows.get(EarningKind.fault_charge) or 0), 0))


async def undo(db: AsyncSession, order: Order, *, why: str) -> Split | None:
    """商家申诉改判成立:**平台判错了,平台自己认**。**只改库不提交。**

    - 冲回的净额补回:追加一行 adjustment(正数,和 2026-09-14 之前改判补的调整行同一个形状:
      food == net、佣金 0 —— 佣金那一截冲掉了就是冲掉了,平台不再收);
    - 另出的骑手那份退回:追加一行 fault_refund(正数,等于当初另出的);
    - 钱由平台出:顾客已经拿到的退款不追回,骑手照拿的配送费和小费也不动 —— 平台为这一单
      一共出「补回的净额 + 退回的那行」,进透明中心「申诉改判」和公开账本(merchant_rows 的
      adjustment、merchant_fault_rows 的 fault_refund);
    - 幂等:补过的不再补。这一单没冲过也没另出过(比如改判之前的老单)返回 None。

    判责方怎么改(platform)由调用方做 —— 和骑手责任改判同一个写法。
    """
    rows = await _rows(db, order.id)
    reversed_net = max(-int(rows.get(EarningKind.reversal) or 0), 0)
    charge = max(-int(rows.get(EarningKind.fault_charge) or 0), 0)
    if reversed_net <= 0 and charge <= 0:
        return None
    note = why[:150]
    if reversed_net > 0 and EarningKind.adjustment not in rows:
        db.add(MerchantEarning(
            merchant_id=order.merchant_id, order_id=order.id, order_no=order.order_no,
            food_cents=reversed_net, commission_cents=0, net_cents=reversed_net,
            # 平台补给商家的钱,走平台代收口径(分账单冲回时是渠道退回的,补回只能从平台侧给)
            settle_mode="platform",
            kind=EarningKind.adjustment,
            note=f"申诉改判,平台判错了,补回这单净额:{note}"[:200]))
    if charge > 0 and EarningKind.fault_refund not in rows:
        db.add(MerchantEarning(
            merchant_id=order.merchant_id, order_id=order.id, order_no=order.order_no,
            food_cents=charge, commission_cents=0, net_cents=charge,
            settle_mode="platform",
            kind=EarningKind.fault_refund,
            note=f"申诉改判,平台判错了,退回另出的配送费和小费:{note}"[:200]))
    await db.flush()
    return Split(reversed_net=reversed_net, charge=charge)


def merchant_push_text(split: Split, refunded: int) -> str:
    """推给店主的那一句:退了顾客多少、这单净额冲回多少、骑手那份另出多少 —— 几个数都照实说。"""
    parts = [f"顾客全额退款 ¥{refunded / 100:.2f}"] if refunded else []
    if split.reversed_net:
        parts.append(f"这单净额 ¥{split.reversed_net / 100:.2f} 冲回")
    if split.charge:
        parts.append(f"骑手那份配送费和小费 ¥{split.charge / 100:.2f} 也由你出"
                     "(余额不够的,之后的收入先抵)")
    return ",".join(parts) or "这单没有要你出的钱"


#: 「判商家责任要另出骑手那份」这条规则在这个库上从哪一刻起生效:platform_flags 里的这个键,值是 UTC 的
#: ISO 时刻,迁移 0141 在升级那一刻写进去。它不是开关:不在后台「平台开关」页(admin._KNOWN_FLAGS)、
#: 也不写 flag_history、不进透明中心的开关时间线 —— 能改它就等于能让反查对一段时间闭眼
CHARGE_SINCE_FLAG = "merchant_fault_charge_since"


async def charge_since(db: AsyncSession) -> datetime | None:
    """新规则在这个库上生效的时刻(审计规则 4e 从这一刻起反查)。

    没记、记坏了返回 None —— 调用方要把「起算点没了」当问题报出来,不能当成「不用查」。"""
    from ..models import PlatformFlag
    flag = await db.get(PlatformFlag, CHARGE_SINCE_FLAG)
    raw = (flag.value or "").strip() if flag is not None else ""
    if not raw:
        return None
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)


def judged_query(floor: datetime):
    """floor 之后判了商家责任、现在还算商家责任的单:列 (oid 订单 id, at 最后一次判的时刻)。

    四条路落下的记录都认:
    - 售后判责方是商家(after_sales.fault = merchant):商家同意、售后被拒改判成立写它,配送异常判商家责任、
      食安投诉成立也会补一条或改成它。时刻取 processed_at(没写的退回 created_at);
    - 配送异常「到店未出餐」「餐品不齐」裁成退款(delivery_issues),时刻取 resolved_at;
    - 食安投诉核实成立(food_safety_reports.status = confirmed),时刻取 resolved_at。

    后两种单独再认一遍,是为了绕开了售后那张表的路也看得见。这一单的售后判的是别人的(rider 骑手责任;
    platform:商家申诉改判成立,或者历史上的平台认赔)不算 —— 钱按那个责任走了,不该商家另出。

    一单判过几次(比如商家自己同意过,后来食安投诉又成立)只要有一次在 floor 之后就算,时刻取最后一次:
    [apply] 幂等,后一次判的时候没有另出那一行就会补上,所以最后一次在生效之后,就该有这一行。
    """
    from ..models import AfterSale, DeliveryIssue, FoodSafetyReport
    from .delivery_fault import MERCHANT_KINDS

    judged_other = select(AfterSale.order_id).where(AfterSale.fault.in_(("rider", "platform")))
    a_at = func.coalesce(AfterSale.processed_at, AfterSale.created_at)
    d_at = func.coalesce(DeliveryIssue.resolved_at, DeliveryIssue.created_at)
    f_at = func.coalesce(FoodSafetyReport.resolved_at, FoodSafetyReport.created_at)
    rows = union_all(
        select(AfterSale.order_id.label("oid"), a_at.label("at"))
        .where(AfterSale.fault == "merchant", a_at >= floor),
        select(DeliveryIssue.order_id, d_at)
        .where(DeliveryIssue.resolution == "refund", DeliveryIssue.kind.in_(MERCHANT_KINDS),
               d_at >= floor, DeliveryIssue.order_id.notin_(judged_other)),
        select(FoodSafetyReport.order_id, f_at)
        .where(FoodSafetyReport.status == "confirmed", f_at >= floor,
               FoodSafetyReport.order_id.notin_(judged_other)),
    ).subquery()
    return select(rows.c.oid, func.max(rows.c.at).label("at")).group_by(rows.c.oid)
