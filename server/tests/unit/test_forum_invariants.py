"""论坛模块的不变量守卫:代码形状上的那一半(DEV-PROMPTS-41 §3)。

- §3.1 不收钱:/forum/v1、/admin/forum 的路由名、处理函数、service 函数、表和列里没有付款相关的名字;
- §3.2 不要求实名:forum*.py 里不许引用 UserIdentity / require_realname(用户拍板:论坛不要求实名);
- §3.8 开关是急停闸:/forum/v1 下每一条路由都挂着 forum_on,发帖类再挂 forum_post_on;
  生产缺省关、开发缺省开;
- 遍历路由照 test_social_flags 的 walk —— FastAPI 0.139 的 include_router 不摊平,
  只扫 app.routes 的守卫会空转(扫到 0 条也「全过」)。
"""
import re
from pathlib import Path

from app.models import FORUM_MODELS

ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "server/app"

#: 付款相关的名字(英文标识符里的片段)
PAY = re.compile(r"pay|price|cash|money|recharge|top_?up|withdraw|wallet|purchase|refund|"
                 r"premium|vip|donat|sponsor|reward|charge|exchange|redeem|cents|yuan", re.I)
#: tip(打赏)只认独立的词,免得误伤 multiple / tooltip
TIP = re.compile(r"(^|_)tips?($|_)", re.I)
#: 能被买的排序输入(§3.1「模型里不许有可售字段」)
SELLABLE = re.compile(r"bid|boost|promot|sponsor|rank_score|weight_override|ad_", re.I)

#: 发帖类接口:另挂 forum_post_on(「论坛发帖暂停中」)
POST_GATED = {("POST", "/forum/v1/posts"), ("PATCH", "/forum/v1/posts/{pid}")}

FORUM_SOURCES = ("services/forum.py", "services/forum_feed.py", "services/forum_rank.py",
                 "routers/forum.py", "routers/forum_admin.py", "models_forum.py")


def _leaf_routes(routes):
    """FastAPI 0.139 的 include_router 挂的是 _IncludedRouter,要钻进去才看得到真路由。"""
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _leaf_routes(inner.routes)
        else:
            yield r


def _forum_routes(prefixes=("/forum/v1", "/admin/forum")):
    from app.main import app
    return [r for r in _leaf_routes(app.routes)
            if getattr(r, "path", "").startswith(prefixes)]


def _deps(route) -> set[str]:
    out, stack = set(), list(route.dependant.dependencies)
    while stack:
        d = stack.pop()
        if d.call is not None:
            out.add(getattr(d.call, "__name__", ""))
        stack.extend(d.dependencies)
    return out


def _bad(name: str) -> bool:
    return bool(PAY.search(name) or TIP.search(name))


# ---------------- 路由扫得到 ----------------

def test_论坛路由都扫得到():
    routes = _forum_routes()
    assert len(routes) >= 40, f"只扫到 {len(routes)} 条论坛路由,扫描方式和 FastAPI 对不上了"


# ---------------- §3.1 不收钱 ----------------

def test_接口里没有付款字样():
    bad = []
    for r in _forum_routes():
        segs = [s for s in r.path.split("/") if s and not s.startswith("{")]
        for s in segs + [r.endpoint.__name__]:
            if _bad(s.replace("-", "_").replace(".", "_")):
                bad.append(f"{sorted(r.methods)} {r.path} ({r.endpoint.__name__})")
    assert not bad, f"§3.1:论坛出现了付款相关的接口:{bad}"


def test_表和列里没有钱_也没有可售字段():
    bad = [f"{m.__tablename__}.{c.name}" for m in FORUM_MODELS for c in m.__table__.columns
           if _bad(c.name) or SELLABLE.search(c.name)]
    bad += [m.__tablename__ for m in FORUM_MODELS
            if _bad(m.__tablename__) or SELLABLE.search(m.__tablename__)]
    assert not bad, f"§3.1:论坛的表里出现了和钱、和买位置有关的列:{bad}"


def test_service里没有付款函数():
    bad = []
    for rel in FORUM_SOURCES:
        src = (SERVER / rel).read_text(encoding="utf-8")
        for name in re.findall(r"^(?:async )?def ([a-z_0-9]+)", src, re.M):
            if _bad(name):
                bad.append(f"{rel}:{name}")
    assert not bad, f"§3.1:论坛代码里出现了付款相关的函数:{bad}"


def test_全部表都在清单里():
    """FORUM_MODELS 是列名守卫和注销级联的扫描清单 —— 漏一张表,那张表就没人管。"""
    from app import models_forum
    from app.db import Base

    declared = {m.__tablename__ for m in FORUM_MODELS}
    in_module = {v.__tablename__ for v in vars(models_forum).values()
                 if isinstance(v, type) and issubclass(v, Base) and v is not Base}
    assert declared == in_module, f"FORUM_MODELS 和 models_forum.py 里的表对不上:{declared ^ in_module}"
    assert all(t.startswith("forum_") for t in declared), declared


# ---------------- §3.2 不要求实名 ----------------

def test_论坛不引用实名():
    """用户拍板:论坛不要求实名。引用 UserIdentity / require_realname 这里就红。"""
    bad = []
    for rel in FORUM_SOURCES:
        src = (SERVER / rel).read_text(encoding="utf-8")
        for token in ("UserIdentity", "require_realname", "verify-identity"):
            if token in src:
                bad.append(f"{rel}:{token}")
    assert not bad, f"§3.2:论坛不要求实名,不该出现这些:{bad}"


# ---------------- §3.8 开关是急停闸 ----------------

def test_每条论坛路由都挂着开关():
    routes = [r for r in _forum_routes(("/forum/v1",))]
    assert len(routes) >= 35, len(routes)
    for r in routes:
        assert "forum_on" in _deps(r), f"{r.path} 没挂论坛开关"


def test_发帖类再挂发帖开关():
    got = set()
    for r in _forum_routes(("/forum/v1",)):
        if "forum_post_on" in _deps(r):
            got |= {(m, r.path) for m in r.methods if m != "HEAD"}
    assert got == POST_GATED, f"挂着 forum_post_on 的接口对不上:{got ^ POST_GATED}"


def test_开关生产缺省关_开发缺省开():
    from app.config import settings
    from app.services import flags

    assert set(flags.FORUM_FLAGS) == {"forum_enabled", "forum_post_enabled"}
    old = settings.app_env
    try:
        settings.app_env = "prod"
        assert all(flags.forum_flag_default(k) == "off" for k in flags.FORUM_FLAGS), \
            "生产缺省关:合规结论(#374 清单第 18 条)没回来之前不能不经意地打开"
        settings.app_env = "dev"
        assert all(flags.forum_flag_default(k) == "on" for k in flags.FORUM_FLAGS)
    finally:
        settings.app_env = old


def test_后台认得这两个开关():
    from app.routers.admin import _KNOWN_FLAGS
    assert {"forum_enabled", "forum_post_enabled"} <= _KNOWN_FLAGS


def test_config的features里有论坛():
    src = (SERVER / "routers/platform.py").read_text(encoding="utf-8")
    assert '"forum": await forum_flag_on(db, "forum_enabled")' in src
    assert '"forum_post": await forum_flag_on(db, "forum_post_enabled")' in src


# ---------------- 治理与处罚 ----------------

def test_发帖挂在处罚执行点上():
    from app.services.sanctions import BLOCKED_BY
    assert BLOCKED_BY["forum_post"] == ("ban_account", "mute"), \
        "禁言的人也不该能发帖 —— 帖子和评论是一回事"


def test_封号放行的都是只影响自己的():
    """放行表里不许出现发帖、赞、转发这些「别人看得到」的动作。"""
    from app.services.sanctions import ACCOUNT_BAN_ALLOWED
    forum = {p for _m, p in ACCOUNT_BAN_ALLOWED if p.startswith("/forum/v1")}
    assert forum == {"/forum/v1/posts/{pid}/appeal", "/forum/v1/reports",
                     "/forum/v1/posts/views", "/forum/v1/posts/{pid}/bookmark",
                     "/forum/v1/me/mute-words", "/forum/v1/me/settings"}, forum


def test_图片用途是公开的():
    from app.services.storage import PURPOSES
    assert PURPOSES["forum"] is False, "论坛配图发出去就是公开的"


def test_互动消息加了转发和引用():
    from app.models import NOTIFY_KINDS
    assert {"repost", "quote"} <= set(NOTIFY_KINDS)


def test_卡片注册表先有视频和帖子():
    from app.services import cards
    assert {"video", "post"} <= set(cards.known_types())
    # 音乐的四种由音乐后端在 services/music.py 里注册,合并时接进来 —— 现在没有不该报错
    assert cards.placeholder("track", "mt1") == {"type": "track", "id": "mt1",
                                                 "unavailable": True}


def test_注销和导出都接进来了():
    auth = (SERVER / "routers/auth.py").read_text(encoding="utf-8")
    assert "purge_user as purge_forum_user" in auth, "注销没清论坛的数据"
    export = (SERVER / "services/chat_export.py").read_text(encoding="utf-8")
    assert "forum_posts.json" in export, "导出里没有自己的帖子"
    sweep = (SERVER / "services/auto_flow.py").read_text(encoding="utf-8")
    assert "sweep_forum" in sweep, "投票结束、浏览去重表的清扫没接进清扫循环"
