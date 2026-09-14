"""退给顾客多少钱:几条退款路径共用的算法。

2026-09-14 合并时发现,同一件事(「顾客为餐付的钱」)在四处各算各的,算法还不一样:
- 商家同意售后用「实付 − 配送费」:小费也退给了顾客,而骑手照拿小费 —— 那一截是平台出;
- 顾客对「售后被拒」「按送达处理」申诉改判用「菜 + 打包 − 满减 − 已退金额」:
  缺货部分退款时菜价字段已经扣过、已退金额又累加过,**同一笔缺货退款被减了两次**,顾客少拿;
  也没减平台券抵掉的部分,顾客会把平台的券钱当现金拿走;
- 顾客对「取消分摊」申诉改判用「菜 + 打包 − 满减 + 配送费 + 小费 − 已退金额」:同样两处毛病。

口径统一成下面三个函数。字段关系(models.Order):
    实付 total = 菜 + 打包 − 满减 + 配送费 + 小费 − 平台补贴
缺货部分退款会同步扣减菜 / 满减 / 补贴 / 实付,并把退款记进 refund_cents;
其它退款只记 refund_cents、不动实付。所以「缺货以外已经退掉的」= refund_cents − 缺货退款之和。
"""
from sqlalchemy import func, select

#: 缺货退款写退款流水时的原因前缀。写(routers/orders.refund_item)和读(下面)都用它 ——
#: 两边各写一遍字符串的话,改一处另一处就静默查不到数
OUT_OF_STOCK_REFUND_PREFIX = "缺货退款:"


def rider_kept_cents(order) -> int:
    """平台骑手送的单,配送费和小费是骑手已经挣到的,退款不动它们。

    商家自配送(没有骑手)的配送费算在商家入账里(services/settlement),冲回商家净额时一起冲回,
    所以照退;到店自取没有配送费和小费。"""
    if order.rider_id is None:
        return 0
    return order.delivery_fee_cents + order.tip_cents


async def out_of_stock_refunded_cents(db, order) -> int:
    """这单缺货退款(部分 / 整单)已经退掉的钱。口径同核账:不算渠道失败的那几笔。"""
    from ..models import Refund, RefundStatus
    return int(await db.scalar(
        select(func.coalesce(func.sum(Refund.amount_cents), 0)).where(
            Refund.order_id == order.id,
            Refund.status != RefundStatus.failed,
            Refund.reason.like(OUT_OF_STOCK_REFUND_PREFIX + "%"))) or 0)


async def unrefunded_paid_cents(db, order) -> int:
    """顾客实付里还没退回去的钱(不含平台补贴 —— 那本来就不是他付的)。"""
    other = order.refund_cents - await out_of_stock_refunded_cents(db, order)
    return max(order.total_cents - other, 0)


async def goods_unrefunded_cents(db, order) -> int:
    """顾客为这单的**餐**付的、还没退的钱 = 还没退的实付 − 骑手已经挣到的配送费和小费。

    商家有责任(同意售后、售后被拒改判、到店未出餐这类)时退这么多,由商家冲回净额出;
    配送费和小费照归骑手 —— 要不要让商家连配送费一起出、顾客拿回全款,是另一条要拍板的钱路径。"""
    return max(await unrefunded_paid_cents(db, order) - rider_kept_cents(order), 0)
