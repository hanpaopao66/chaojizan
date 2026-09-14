"""配送异常裁决判的是谁的责任、裁成「退款」时钱由谁出。

骑手上报的配送异常分两类(取值见 schemas.DeliveryIssueIn.kind):

- **途中异常**:联系不上顾客、地址有误、餐品损坏、其他。裁成退款(refund)判的是**骑手责任**,
  钱怎么走见 admin.resolve_delivery_issue 那一支;
- **交接异常**:到店未出餐(not_ready)、餐品不齐(items_missing)。餐没做好、没装齐,
  是**商家那一环**的问题 —— 裁成退款判的是**商家责任**:顾客拿回全款(含配送费和小费),
  钱由商家出 —— 这单的净额冲回、骑手那份配送费和小费另出一行(services/merchant_fault,
  和别的判商家责任同一个写法);骑手跑了这一趟,配送费和小费照拿。扣商家的信用分、不扣骑手的;
  商家走售后判责的原通道申诉(appeals 的 after_sale,72 小时,和商家其它售后判责一模一样)。

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

# 判商家责任时退多少、钱怎么走,不在这里另算一份:退全款(refund_calc.merchant_fault_refund_cents),
# 商家这单净额冲回、骑手那份另出(services/merchant_fault)—— 和别的判商家责任同一个写法。
# 原来这里有个 merchant_refund_cents(实付 − 配送费 − 小费,只退餐钱),2026-09-15 起不再这么退
