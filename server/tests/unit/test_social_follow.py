"""全站统一关注(DEV-PROMPTS-41 #377)的几条不变量。

- /social/v1 的关注接口**不挂任何模块开关**:视频、论坛、音乐谁关了都不影响关注;
- 互动消息的种类只有一张表:接口的 Kind 和 models.NOTIFY_KINDS 必须一致(论坛、音乐加种类时两边一起改);
- 关注发 follow 互动消息,在 set_follow 这一处发 —— 视频老接口、/social/v1 新接口都走它。
"""
import inspect
import typing

from app.main import app
from app.models import NOTIFY_KINDS

MODULE_GATES = {"video_on", "upload_on", "chat_on", "music_on", "music_upload_on", "forum_on",
                "forum_post_on"}


def _deps(route) -> set[str]:
    out, stack = set(), list(route.dependant.dependencies)
    while stack:
        d = stack.pop()
        if d.call is not None:
            out.add(getattr(d.call, "__name__", ""))
        stack.extend(d.dependencies)
    return out


def _routes(prefix: str):
    def walk(routes):
        for r in routes:
            inner = getattr(r, "original_router", None)   # FastAPI 0.139 的 include_router 不摊平
            if inner is not None:
                yield from walk(inner.routes)
            else:
                yield r
    return [r for r in walk(app.routes) if getattr(r, "path", "").startswith(prefix)]


def test_关注接口不挂模块开关():
    routes = [r for r in _routes("/social/v1/users/") if "follow" in r.path]
    paths = {(m, r.path) for r in routes for m in r.methods}
    for want in (("POST", "/social/v1/users/{user_id}/follow"),
                 ("DELETE", "/social/v1/users/{user_id}/follow"),
                 ("GET", "/social/v1/users/{user_id}/followers"),
                 ("GET", "/social/v1/users/{user_id}/following"),
                 ("GET", "/social/v1/users/{user_id}/follow-stats")):
        assert want in paths, f"少了 {want}"
    for r in routes:
        gates = _deps(r) & MODULE_GATES
        assert not gates, f"{r.path} 挂了模块开关 {gates} —— 关注是全站的,哪个模块关了都不能挡关注"


def test_互动消息种类只有一张表():
    from app.routers import notifications
    assert typing.get_args(notifications.Kind) == NOTIFY_KINDS, \
        "接口的 Kind 和 models.NOTIFY_KINDS 对不上:加种类时两边要一起改"
    assert "follow" in NOTIFY_KINDS


def test_关注在set_follow这一处发通知():
    from app.services import video_interact
    src = inspect.getsource(video_interact.set_follow)
    assert 'notify(db, target_id, "follow"' in src, "关注不发 follow 互动消息了?"
