"""消息里要等合规结论的功能开关(DEV-PROMPTS-40 #374 / #375):缺省站在「关」这一边。"""


def test_calls_flag_default_off_in_prod_on_in_dev(monkeypatch):
    from app.config import settings
    from app.services import flags

    assert set(flags.SOCIAL_FLAGS) == {"chat_enabled", "calls_enabled"}
    monkeypatch.setattr(settings, "app_env", "prod")
    assert flags.social_flag_default("calls_enabled") == "off", "生产缺省关:通话的电信业务许可还没定"
    assert flags.social_flag_default("chat_enabled") == "on", "消息生产也开:急停闸,不是准入闸"
    monkeypatch.setattr(settings, "app_env", "dev")
    assert flags.social_flag_default("calls_enabled") == "on"


def test_social_flags_are_known_to_the_admin_console():
    from app.routers.admin import _KNOWN_FLAGS
    assert {"chat_enabled", "calls_enabled"} <= _KNOWN_FLAGS


def test_every_chat_route_hangs_on_the_chat_flag():
    """急停要真能停:/chat/v1 下每一条路由都挂着 chat_on(通话路由也在 /chat/v1 下)。"""
    from app.main import app

    def walk(routes):
        for r in routes:
            inner = getattr(r, "original_router", None)   # FastAPI 0.139 的 include_router 不摊平
            if inner is not None:
                yield from walk(inner.routes)
            else:
                yield r

    chat_routes = [r for r in walk(app.routes) if getattr(r, "path", "").startswith("/chat/v1")]
    assert len(chat_routes) > 50, len(chat_routes)
    for r in chat_routes:
        deps = {getattr(d.call, "__name__", "") for d in r.dependant.dependencies}
        assert "chat_on" in deps, f"{r.path} 没挂消息开关"
