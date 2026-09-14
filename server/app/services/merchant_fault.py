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
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
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
