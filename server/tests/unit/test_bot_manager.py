"""机器人管家(services/bot_manager.py)不连库的那部分:命令列表怎么解析、名字保留、内部 webhook 地址开发者设不出来。"""
import pytest

from app.services import bot_manager as mgr
from app.services import bots
from app.services.bots import BotError
from app.services.social import validate_username


def test_parse_commands_text_like_botfather():
    out = mgr.parse_commands_text("start - 开始\n\n/Menu — 看今天的菜\n  help – 帮助  ")
    assert out == [{"command": "start", "description": "开始"},
                   {"command": "menu", "description": "看今天的菜"},
                   {"command": "help", "description": "帮助"}]


@pytest.mark.parametrize("bad", ["start 开始", "start -", "- 开始"])
def test_parse_commands_text_rejects_lines_without_separator(bad):
    with pytest.raises(ValueError, match="第 1 行"):
        mgr.parse_commands_text(bad)


def test_manager_username_is_reserved_for_everyone_else():
    assert "保留" in validate_username("guanjia_bot", is_bot=True)
    assert "保留" in validate_username("my_guanjia_bot", is_bot=True)
    assert "保留" in validate_username("guanjia2024")
    # 只有服务端建官方机器人时放行(scripts/seed_bot_manager.py → bots.create_bot(system=True))
    assert validate_username(mgr.USERNAME, is_bot=True, reserved_ok=True) is None


def test_internal_webhook_cannot_be_set_by_developers():
    assert mgr.WEBHOOK.startswith(bots.INTERNAL_WEBHOOK_PREFIX)
    with pytest.raises(BotError):
        bots.check_webhook_url_shape(mgr.WEBHOOK)


def test_every_listed_command_has_a_handler():
    listed = {c["command"] for c in mgr.COMMANDS}
    assert listed <= set(mgr._COMMANDS), listed - set(mgr._COMMANDS)
    for c in mgr.COMMANDS:
        assert bots.COMMAND_RE.fullmatch(c["command"]) and 1 <= len(c["description"]) <= 256
