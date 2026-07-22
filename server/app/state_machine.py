"""订单状态机 —— 整个平台的心脏。

所有状态变更必须经过 assert_transition,禁止在业务代码里直接改 status,
保证任何时刻订单状态都是合法的、可审计的(配合 OrderEvent 表)。
"""
from enum import Enum


class OrderStatus(str, Enum):
    PENDING_PAYMENT = "pending_payment"  # 待支付
    PAID = "paid"                        # 已支付,等商家接单
    ACCEPTED = "accepted"                # 商家已接单,制作中
    READY = "ready"                      # 出餐完成,等骑手取餐
    PICKED_UP = "picked_up"              # 骑手已取餐,配送中
    DELIVERED = "delivered"              # 已送达
    COMPLETED = "completed"              # 用户确认完成(结算触发点)
    CANCELLED = "cancelled"              # 已取消(已支付订单取消 = 全额退款)


STATUS_LABELS = {
    OrderStatus.PENDING_PAYMENT: "待支付",
    OrderStatus.PAID: "待接单",
    OrderStatus.ACCEPTED: "制作中",
    OrderStatus.READY: "待取餐",
    OrderStatus.PICKED_UP: "配送中",
    OrderStatus.DELIVERED: "已送达",
    OrderStatus.COMPLETED: "已完成",
    OrderStatus.CANCELLED: "已取消",
}

# (当前状态, 目标状态) -> 允许操作的角色
# system = 支付回调 / 定时任务(超时自动取消、自动确认收货)
TRANSITIONS: dict[tuple[OrderStatus, OrderStatus], set[str]] = {
    (OrderStatus.PENDING_PAYMENT, OrderStatus.PAID): {"customer", "system"},
    (OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED): {"customer", "system"},
    (OrderStatus.PAID, OrderStatus.ACCEPTED): {"merchant"},
    (OrderStatus.PAID, OrderStatus.CANCELLED): {"customer", "merchant", "system"},
    (OrderStatus.ACCEPTED, OrderStatus.READY): {"merchant"},
    # 用户在接单后有 2 分钟反悔窗口(时间校验在路由层,状态机只放行角色)
    (OrderStatus.ACCEPTED, OrderStatus.CANCELLED): {"customer", "merchant", "system"},
    (OrderStatus.READY, OrderStatus.PICKED_UP): {"rider"},
    (OrderStatus.PICKED_UP, OrderStatus.DELIVERED): {"rider"},
    (OrderStatus.DELIVERED, OrderStatus.COMPLETED): {"customer", "system"},
}

# 骑手可抢单的状态(抢单改的是 rider_id,不是 status)
GRABBABLE_STATUSES = {OrderStatus.ACCEPTED, OrderStatus.READY}


class TransitionError(Exception):
    def __init__(self, message: str, forbidden: bool = False):
        super().__init__(message)
        self.message = message
        self.forbidden = forbidden  # True = 角色无权限(403), False = 状态不允许(409)


def assert_transition(current: OrderStatus, target: OrderStatus, role: str) -> None:
    allowed_roles = TRANSITIONS.get((current, target))
    if allowed_roles is None:
        raise TransitionError(
            f"订单不能从「{STATUS_LABELS[current]}」变为「{STATUS_LABELS[target]}」"
        )
    if role not in allowed_roles:
        raise TransitionError(f"当前角色无权执行此操作", forbidden=True)
