"""预计出餐时刻:出餐超时判定和骑手无责转单共用的那一个口径。

不到这个时刻,骑手到店等餐是自己来早了 —— 转单照转,但不算无责;
过了这个时刻商家还没出餐,才轮到「等不起是商家的问题」。
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.prep_time import expected_ready_at

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _shop(promise=15, busy=False, extra=10):
    return SimpleNamespace(promise_ready_minutes=promise,
                           busy_active=busy, busy_extra_minutes=extra)


def _order(accepted_at=T0, scheduled_at=None):
    return SimpleNamespace(accepted_at=accepted_at, scheduled_at=scheduled_at)


def test_即时单是接单加承诺出餐时长():
    assert expected_ready_at(_order(), _shop(15)) == T0 + timedelta(minutes=15)


def test_忙碌模式同步放宽():
    got = expected_ready_at(_order(), _shop(15, busy=True, extra=10))
    assert got == T0 + timedelta(minutes=25)


def test_预约单以预约时间为准():
    at = T0 + timedelta(hours=2)
    assert expected_ready_at(_order(scheduled_at=at), _shop()) == at


def test_没接单就没有出餐时间():
    assert expected_ready_at(_order(accepted_at=None), _shop()) is None


def test_库里读出的无时区时间按UTC():
    naive = T0.replace(tzinfo=None)
    assert expected_ready_at(_order(accepted_at=naive), _shop(15)) == (
        T0 + timedelta(minutes=15))
