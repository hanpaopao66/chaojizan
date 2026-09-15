"""「已支付」只能由收款入账产生:任何账号都不能靠状态流转接口把单子改成已支付。

以前状态机给「待支付 → 已支付」放行了 customer:顾客调 /orders/{no}/transition 传 paid,
自己的单就成了已支付,一分钱没付 —— 商家照常接单出餐,完成时 settle_order 给商家和骑手记账,
记的是平台没收到的钱。入账只有一个入口:payment_core.mark_order_paid
(微信支付回调;开发环境的模拟支付),它自己改状态,不经过这张表。
"""
import pytest

from app.models import UserRole
from app.state_machine import TRANSITIONS, OrderStatus, TransitionError, assert_transition

PAY = (OrderStatus.PENDING_PAYMENT, OrderStatus.PAID)


class Test已支付只能由收款产生:
    @pytest.mark.parametrize("role", [r.value for r in UserRole])
    def test_任何账号角色都不能自己把单子改成已支付(self, role):
        # 流转接口按 user.role 判权,所以这里把每一种账号角色都过一遍,新加角色自动覆盖
        with pytest.raises(TransitionError) as e:
            assert_transition(*PAY, role)
        assert e.value.forbidden, "应当是 403(没权限),不是 409(状态不允许)"

    def test_表里只剩系统(self):
        # system 不是任何账号的角色,流转接口永远走不到;留着它只为让这张表把「谁能让单子变成已支付」写全
        assert TRANSITIONS[PAY] == {"system"}
        assert "system" not in {r.value for r in UserRole}

    def test_没有别的流转能进已支付(self):
        into_paid = [pair for pair in TRANSITIONS if pair[1] == OrderStatus.PAID]
        assert into_paid == [PAY], f"又多了一条进「已支付」的路:{into_paid}"
