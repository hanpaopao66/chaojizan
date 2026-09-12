"""社交身份的纯函数:用户名规则、隐私真值表、最后上线的模糊显示(DEV-PROMPTS-40 #340)。"""
from datetime import datetime, timedelta, timezone

from app.services.social import last_seen_view, rule_allows, validate_username

NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def test_username_rules():
    assert validate_username("alice") is None
    assert validate_username("Alice_2026") is None
    for bad in ("", "abcd", "a" * 33, "1abcde", "_abcde", "abcde_", "ab__cd", "ab-cde", "张三abcde"):
        assert validate_username(bad), bad
    for reserved in ("admin", "Support", "superz_team", "chaojizan01", "myofficial"):
        assert validate_username(reserved), reserved
    assert validate_username("hellobot"), "bot 结尾只给机器人"
    assert validate_username("hellobot", is_bot=True) is None
    assert validate_username("hello", is_bot=True), "机器人必须 bot 结尾"


def test_privacy_truth_table():
    for rule in ("everyone", "contacts", "nobody"):
        assert rule_allows(rule, same=True, viewer_is_contact=False, blocked=True), "自己永远看得到"
        assert not rule_allows(rule, same=False, viewer_is_contact=True, blocked=True), "拉黑一律不行"
    assert rule_allows("everyone", same=False, viewer_is_contact=False, blocked=False)
    assert rule_allows("contacts", same=False, viewer_is_contact=True, blocked=False)
    assert not rule_allows("contacts", same=False, viewer_is_contact=False, blocked=False)
    assert not rule_allows("nobody", same=False, viewer_is_contact=True, blocked=False)


def test_last_seen_buckets():
    assert last_seen_view(None, True, True, NOW) == {"online": True, "at": None, "approx": None}
    at = NOW - timedelta(hours=2)
    assert last_seen_view(at, False, True, NOW)["at"] == at.isoformat()
    assert last_seen_view(at, True, False, NOW)["approx"] == "recently", "隐藏时在线也只显示「最近」"
    assert last_seen_view(NOW - timedelta(days=5), False, False, NOW)["approx"] == "week"
    assert last_seen_view(NOW - timedelta(days=20), False, False, NOW)["approx"] == "month"
    assert last_seen_view(NOW - timedelta(days=90), False, False, NOW)["approx"] == "long"
