"""消息里要等合规结论的功能开关(DEV-PROMPTS-40 #374 / #375):缺省站在「关」这一边。"""


def test_calls_flag_default_off_in_prod_on_in_dev(monkeypatch):
    from app.config import settings
    from app.services import flags

    assert set(flags.SOCIAL_FLAGS) == {"calls_enabled"}
    monkeypatch.setattr(settings, "app_env", "prod")
    assert flags.video_flag_default() == "off", "生产缺省关:通话的电信业务许可还没定"
    monkeypatch.setattr(settings, "app_env", "dev")
    assert flags.video_flag_default() == "on"


def test_calls_flag_is_known_to_the_admin_console():
    from app.routers.admin import _KNOWN_FLAGS
    assert "calls_enabled" in _KNOWN_FLAGS
