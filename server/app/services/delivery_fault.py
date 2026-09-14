"""配送异常裁决判的是谁的责任、裁成「退款」时钱由谁出。

骑手上报的配送异常分两类(取值见 schemas.DeliveryIssueIn.kind):

- **途中异常**:联系不上顾客、地址有误、餐品损坏、其他。裁成退款(refund)判的是**骑手责任**,
  钱怎么走见 admin.resolve_delivery_issue 那一支;
- **交接异常**:到店未出餐(not_ready)、餐品不齐(items_missing)。餐没做好、没装齐,
  是**商家那一环**的问题 —— 裁成退款判的是**商家责任**:退款由商家承担(照售后判商家责任
  那条路,把这单的净额冲回),扣商家的信用分、不扣骑手的;商家走售后判责的原通道申诉
  (appeals 的 after_sale,72 小时,和商家其它售后判责一模一样)。

以前这两类裁成退款也记成骑手责任、扣骑手的信用分 —— 骑手到店没拿到餐、拿到的餐不齐,
反倒算他的错。

判谁的责任只有这一份,三处共用:admin 的裁决(钱和判责)、appeals 的申诉资格、
credit 的扣分项;出参(schemas.DeliveryIssueOut 的 fault / refund_fault)也从这里读,
后台和骑手端照着它显示,不各写一份。
"""
from __future__ import annotations

#: 裁成退款时算**商家**责任的两类。取值对着 schemas.DeliveryIssueIn.kind
MERCHANT_KINDS = ("not_ready", "items_missing")

#: 给人看的名字(推送、明细标题用)。和骑手端上报页的叫法一致
KIND_LABELS = {
    "cannot_contact": "联系不上顾客",
    "wrong_address": "地址有误",
    "food_damaged": "餐品损坏",
    "not_ready": "到店未出餐",
    "items_missing": "餐品不齐",
    "other": "其他",
}


def refund_fault(kind: str) -> str:
    """这一类异常裁成退款时判谁的责任:merchant / rider。"""
    return "merchant" if kind in MERCHANT_KINDS else "rider"


def fault_of(kind: str, resolution: str) -> str:
    """一条已裁决的配送异常判的是谁的责任:

    - customer:按送达处理(联系不上、地址错,顾客原因);
    - rider / merchant:裁成退款,按异常的种类定(见 [refund_fault]);
    - 空串:协调后继续送、还没裁决 —— 没有判谁的责任。
    """
    if resolution == "mark_delivered":
        return "customer"
    if resolution == "refund":
        return refund_fault(kind)
    return ""


def merchant_refund_cents(order) -> int:
    """判商家责任时退给顾客多少:顾客为这单的**餐**付的钱 = 实付 − 配送费 − 小费。

    这笔钱全由商家出:这单的商家入账整行冲回(settlement.reverse_merchant_earning,和售后判
    商家责任同一个写法),冲回的是「菜品 + 打包 − 满减」,其中佣金那一截平台也一并不收。
    顾客实付里如果有平台券抵掉的部分,那部分不退现金 —— 那是平台的钱,冲回来还给平台自己
    (谁出的钱谁收回,和缺货部分退款同一个口径)。

    配送费和小费照常归骑手,也不退给顾客:骑手跑了这一趟,到店没拿到餐、拿到的餐不齐都不是他的错;
    退给顾客的话这一截就只能平台出,而平台不出钱赔付(2026-09-14 拍板)。
    要不要让商家连配送费一起承担、顾客拿回全款,是另一条要拍板的钱路径,这里没做。
    """
    # 商家自配送没有骑手,配送费算在商家入账里、冲回净额时一起冲回,所以照退(refund_calc.rider_kept_cents)
    from .refund_calc import rider_kept_cents
    return max(order.total_cents - rider_kept_cents(order), 0)
