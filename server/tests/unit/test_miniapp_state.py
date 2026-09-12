"""小程序四个状态机的全迁移表(#320,§5.8)。

逐格验:表里写了的能走,没写的一律 TransitionError。把某一格悄悄放开(比如「驳回 → 通过」)
这里就红 —— 申诉改判是 admin_miniapps._overturn 里单独写的路,不走这张表。
"""
import itertools

import pytest

from app.services import miniapp_state as sm
from app.state_machine import TransitionError

EXPECTED = {
    "developer": {
        ("unverified", "pending"), ("unverified", "verified"), ("unverified", "closed"),
        ("pending", "verified"), ("pending", "rejected"), ("pending", "closed"),
        ("rejected", "pending"), ("rejected", "closed"),
        ("verified", "suspended"), ("verified", "closed"),
        ("suspended", "verified"), ("suspended", "closed"),
    },
    "app": {
        ("draft", "online"), ("draft", "removed"),
        ("online", "offline"), ("online", "suspended"), ("online", "removed"),
        ("offline", "online"), ("offline", "suspended"), ("offline", "removed"),
        ("suspended", "online"), ("suspended", "removed"),
    },
    "version": {
        ("uploaded", "trial"), ("uploaded", "reviewing"),
        ("trial", "reviewing"), ("trial", "uploaded"),
        ("reviewing", "approved"), ("reviewing", "rejected"), ("reviewing", "withdrawn"),
        ("withdrawn", "reviewing"), ("withdrawn", "trial"),
        ("approved", "released"), ("released", "superseded"), ("superseded", "released"),
    },
    "capability": {
        ("requested", "approved"), ("requested", "rejected"), ("approved", "revoked"),
        ("rejected", "requested"), ("revoked", "requested"),
    },
}
MACHINES = {"developer": sm.DEVELOPER, "app": sm.APP, "version": sm.VERSION,
            "capability": sm.CAPABILITY}


@pytest.mark.parametrize("machine", list(EXPECTED))
def test_every_cell(machine):
    states = list(MACHINES[machine])
    for cur, target in itertools.product(states, states):
        if (cur, target) in EXPECTED[machine]:
            sm.assert_transition(machine, cur, target)
        else:
            with pytest.raises(TransitionError):
                sm.assert_transition(machine, cur, target)


def test_terminal_states():
    assert sm.APP["removed"] == set(), "移除是终态(申诉改判不走这张表)"
    assert sm.VERSION["rejected"] == set(), "驳回的版本不能再送审,改了重新传"
    assert sm.DEVELOPER["closed"] == set()


def test_unknown_state_raises():
    with pytest.raises(TransitionError):
        sm.assert_transition("app", "nonsense", "online")


def test_every_state_has_a_label():
    for m in MACHINES.values():
        for s in m:
            assert s in sm.LABELS, s


def test_servable_states_exclude_rejected():
    """驳回的版本不从托管出口出去;其余(含审核中、历史版本)可以 —— 审核员和回滚要用。"""
    assert "rejected" not in sm.SERVABLE_VERSION_STATES
    assert {"reviewing", "released", "superseded"} <= sm.SERVABLE_VERSION_STATES
