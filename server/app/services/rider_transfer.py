"""转单的钱:接了不送,立刻扣;扣的钱给最后把这单送到的骑手。

2026-10-06 运营方定:**要么就接,接了就送。** 接了又退回抢单池(转单),
立刻从骑手账上扣 `rider_transfer_fee_cents`(默认 10 元);转单要加钱 ——
扣下来的钱跟着这单走,谁最后送到,订单完成时补给谁。

另外加钱(2026-10-07 运营方定「另外自定义加钱,谁转单谁出」):转单时骑手
可以自己填一个数,在 10 元之外再加,同样立刻从他账上扣、跟着这单走、取消就退。
记成同一种 `transfer_fee` 行(备注写明是自己加的),守恒等式不用变。
无责转单也可以加 —— 他想让人快点接,钱是他自己愿意出的。

只有两种转出不扣:
- 无责转单:过了预计出餐时间、上报「到店未出餐」满 N 分钟商家还没出餐
  (routers/riders.transfer_order 的 waited_free),等不起是商家的问题;
- 交通事故释放(routers/riders 的事故上报),不走转单通道,本来就不经过这里。

## 平台不碰这笔钱

扣的钱只在骑手之间流动:A 转出扣 10,最后送到的 B 完成时拿 10。
这单最后没送成(取消了)就原样退回给扣过钱的骑手 —— 没有接手的人,
这笔钱没有该给的人,平台也不留。

## 账怎么记

全部是 rider_earnings 上追加的行(只追加,不改不删):
- `transfer_fee`  转出扣的钱(负数),一单可以有多行(转了几手就几行);
- `transfer_bonus` 完成时补给送到的骑手(正数),一单一行;
- `transfer_refund` 取消时退回给扣过钱的骑手(正数),一个骑手一行(他转过几次合在一起)。

这三种**不进公开账本的 rider_rows**(那一栏「只进不冲」,见 LEDGER-SPEC §6.2),
单独放在 rider_transfer_rows(services/ledger.py)。每日核账规则 4f 守恒等式:
已完成的单 补的 == 扣的;已取消的单 退的 == 扣的。
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import EarningKind, Order, RiderEarning

TRANSFER_KINDS = (EarningKind.transfer_fee, EarningKind.transfer_bonus,
                  EarningKind.transfer_refund)


def fee_cents() -> int:
    return max(0, settings.rider_transfer_fee_cents)


def charge(db: AsyncSession, order: Order, rider_id: int) -> int:
    """转出扣钱。**只改库不提交**,调用方提交。返回扣了多少(分)。"""
    fee = fee_cents()
    if fee <= 0:
        return 0
    db.add(RiderEarning(
        rider_id=rider_id, order_id=order.id, order_no=order.order_no,
        amount_cents=-fee, kind=EarningKind.transfer_fee,
        note="接单后转出(没送),立刻扣;送到这单的骑手完成时拿到"))
    return fee


def add_extra(db: AsyncSession, order: Order, rider_id: int, cents: int) -> int:
    """转单骑手自己另外加的钱,立刻扣。**只改库不提交**。返回扣了多少(分)。"""
    if cents <= 0:
        return 0
    db.add(RiderEarning(
        rider_id=rider_id, order_id=order.id, order_no=order.order_no,
        amount_cents=-cents, kind=EarningKind.transfer_fee,
        note="转单时自己另外加的钱;送到这单的骑手完成时拿到"))
    return cents


async def pending_cents(db: AsyncSession, order_id: int) -> int:
    """这单上扣了、还没补出去也没退回的钱(分)。"""
    total = await db.scalar(
        select(func.coalesce(func.sum(RiderEarning.amount_cents), 0))
        .where(RiderEarning.order_id == order_id,
               RiderEarning.kind.in_(TRANSFER_KINDS)))
    return -int(total or 0)


async def pay_bonus(db: AsyncSession, order: Order) -> None:
    """订单完成:扣下来的钱补给送到这单的骑手。幂等(一单一行)。"""
    if order.rider_id is None:
        return
    pending = await pending_cents(db, order.id)
    if pending <= 0:
        return
    db.add(RiderEarning(
        rider_id=order.rider_id, order_id=order.id, order_no=order.order_no,
        amount_cents=pending, kind=EarningKind.transfer_bonus,
        note="转单加钱:前面的骑手接了没送,扣的钱归送到的你"))


async def refund_on_cancel(db: AsyncSession, order: Order) -> None:
    """订单取消:还没补出去的扣款原样退回给扣过钱的骑手。幂等。"""
    rows = (await db.execute(
        select(RiderEarning.rider_id, RiderEarning.kind, RiderEarning.amount_cents)
        .where(RiderEarning.order_id == order.id,
               RiderEarning.kind.in_(TRANSFER_KINDS))
        .order_by(RiderEarning.id))).all()
    if not rows or any(k == EarningKind.transfer_bonus for _, k, _ in rows):
        return
    owed: dict[int, int] = {}
    for rider_id, kind, amount in rows:
        # 扣是负数、退是正数,加起来就是还欠这个骑手多少(取反)
        owed[rider_id] = owed.get(rider_id, 0) - amount
    for rider_id, cents in owed.items():
        if cents > 0:
            db.add(RiderEarning(
                rider_id=rider_id, order_id=order.id, order_no=order.order_no,
                amount_cents=cents, kind=EarningKind.transfer_refund,
                note="这单最后取消了,没有接手送到的人,转单扣的钱退回"))
