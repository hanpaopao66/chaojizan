"""会话权限真值表(DEV-PROMPTS-40 §5.6)。客户端据 perms 决定按钮出不出现,接口据同一份拒绝。"""
from datetime import datetime, timedelta, timezone

from app.services.chat_perms import (can_delete_for_all, can_edit_message, perms_for,
                                     reaction_allowed)

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def p(chat_type, role, rights=None, restrictions=None, settings=None):
    return perms_for(chat_type, settings, role, rights, restrictions, now=NOW)


def test_private_and_saved_are_peers():
    for t in ("private", "saved"):
        x = p(t, "member" if t == "private" else "owner")
        assert x.in_chat and x.send_messages and x.send_media and x.pin_messages
        assert not x.is_admin and not x.ban_users and not x.add_admins and not x.change_info
    assert p("private", "member").send_polls is False, "私聊不能发投票(和 TG 一样)"


def test_not_in_chat_can_do_nothing():
    for role in (None, "left", "banned", "whatever"):
        assert not p("group", role).in_chat and not p("group", role).send_messages


def test_group_owner_and_admin_rights():
    owner = p("group", "owner")
    assert owner.is_owner and owner.add_admins and owner.ban_users and owner.slow_mode_exempt
    admin = p("group", "admin", {"delete_messages": True, "pin_messages": True})
    assert admin.is_admin and admin.delete_others and admin.pin_messages
    assert not admin.ban_users and not admin.add_admins and not admin.change_info
    assert admin.send_messages, "群管理员总能发言"


def test_group_member_defaults():
    m = p("group", "member")
    assert m.send_messages and m.send_media and m.invite_users
    assert not m.pin_messages and not m.change_info and not m.delete_others


def test_group_default_perms_and_restrictions():
    s = {"default_perms": {"send_media": False}}
    assert p("group", "member", settings=s).send_media is False
    r = {"perms": {"send_messages": False}, "until": (NOW + timedelta(hours=1)).isoformat()}
    x = p("group", "restricted", restrictions=r)
    assert not x.send_messages and not x.send_media and not x.send_polls, "禁言连带所有发言"
    expired = {"perms": {"send_messages": False}, "until": (NOW - timedelta(minutes=1)).isoformat()}
    assert p("group", "restricted", restrictions=expired).send_messages, "限制到期自动解除"


def test_channel():
    sub = p("channel", "member")
    assert sub.in_chat and not sub.send_messages, "订阅者只能看"
    poster = p("channel", "admin", {"post_messages": True})
    assert poster.send_messages and not poster.edit_others
    editor = p("channel", "admin", {"post_messages": False, "edit_messages": True})
    assert not editor.send_messages and editor.edit_others


def test_edit_window():
    m = p("group", "member")
    assert can_edit_message("group", m, mine=True, age_hours=47.9, kind="text")
    assert not can_edit_message("group", m, mine=True, age_hours=48.1, kind="text")
    assert not can_edit_message("group", m, mine=False, age_hours=1, kind="text")
    assert not can_edit_message("group", m, mine=True, age_hours=1, kind="poll")
    editor = p("channel", "admin", {"edit_messages": True})
    assert can_edit_message("channel", editor, mine=False, age_hours=500, kind="text")


def test_delete_for_all():
    m = p("group", "member")
    assert can_delete_for_all("private", p("private", "member"), mine=False), "私聊随时可为双方删"
    assert can_delete_for_all("group", m, mine=True)
    assert not can_delete_for_all("group", m, mine=False)
    assert can_delete_for_all("group", p("group", "admin", {"delete_messages": True}), mine=False)
    assert not can_delete_for_all("channel", p("channel", "member"), mine=False)


def test_reactions():
    assert reaction_allowed(None, "👍")
    assert not reaction_allowed(None, "🦄"), "不在可用集合里"
    assert not reaction_allowed({"reactions": "none"}, "👍")
    assert reaction_allowed({"reactions": ["🔥"]}, "🔥") and not reaction_allowed({"reactions": ["🔥"]}, "👍")
