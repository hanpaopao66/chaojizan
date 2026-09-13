"""开发者注册闸门(services/developer_signup.py)。

小程序、小游戏的开发者注册对所有人开放:库里没有 `developer_signup` 这一行(新库、生产从没在后台点过)
时必须按「开放注册」走,不能悄悄变回邀请制。「仅限邀请」「暂停注册」只是出问题时临时收紧用的闸。
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.services import developer_signup


class _DB:
    """只够 signup_mode / gate 用的假会话:get 回开关行,scalar 回邀请名单查询的结果。"""

    def __init__(self, flag_value=None, invited=False):
        self.flag_value, self.invited = flag_value, invited
        self.queried_invites = False

    async def get(self, model, key):
        assert key == developer_signup.FLAG
        if self.flag_value is None:
            return None
        return type("Flag", (), {"value": self.flag_value})()

    async def scalar(self, stmt):
        self.queried_invites = True
        return object() if self.invited else None


def run(coro):
    return asyncio.run(coro)


def test_no_flag_row_means_open():
    assert run(developer_signup.signup_mode(_DB())) == "open"


def test_unknown_value_falls_back_to_open():
    assert run(developer_signup.signup_mode(_DB("whatever"))) == "open"


def test_open_lets_anyone_register_without_touching_invites():
    db = _DB()
    assert run(developer_signup.gate(db, "13900000000")) is None
    assert not db.queried_invites, "开放注册时不该去查邀请名单"


def test_invite_mode_still_works_as_a_temporary_brake():
    with pytest.raises(HTTPException) as e:
        run(developer_signup.gate(_DB("invite"), "13900000000"))
    assert e.value.status_code == 403 and "邀请" in e.value.detail
    assert run(developer_signup.gate(_DB("invite", invited=True), "13900000000")) is not None


def test_closed_blocks_new_developers():
    with pytest.raises(HTTPException) as e:
        run(developer_signup.gate(_DB("closed"), "13900000000"))
    assert e.value.status_code == 403 and "关闭" in e.value.detail


def test_open_is_listed_first_and_labelled_as_open():
    assert list(developer_signup.MODES)[0] == "open"
    assert developer_signup.MODES["open"] == "开放注册"
