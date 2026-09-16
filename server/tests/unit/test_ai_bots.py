"""AI 机器人的节奏和提示词(services/ai_bots.py,#385)。

这里测的是**纯函数那一半**:多久说一次、给模型的话怎么写。
真的发出去那一半(走 forum.create_post、违禁词、先审后发)在 e2e_ai_bots 里。

节奏这件事看着简单,但错了的表现很难看:
- 判松了 → 时间线上一整屏机器人,比空着还难看;
- 判紧了 → 配了半天一条都不发,而且没有任何报错。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import AiPersona
from app.services import ai_bots

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def persona(**kw) -> AiPersona:
    p = AiPersona(user_id=1, persona="你是一位爱做饭的成都上班族", topics="做饭,外卖,夜宵",
                  posts_per_day=2, replies_per_day=5, active=True)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


# ---------------- 多久说一次 ----------------

def test_没说过就该说():
    assert ai_bots.due(None, 2, NOW) is True


def test_刚说完不说():
    assert ai_bots.due(NOW, 2, NOW) is False


@pytest.mark.parametrize("hours,per_day,want", [
    (11, 2, False),   # 每天 2 条 → 最小间隔 12 小时
    (13, 2, True),
    (4, 5, False),    # 每天 5 条 → 最小间隔 4.8 小时
    (5, 5, True),
    (0.9, 24, False),
    (1.1, 24, True),
])
def test_间隔是二十四小时除以条数(hours, per_day, want):
    assert ai_bots.due(NOW - timedelta(hours=hours), per_day, NOW) is want


@pytest.mark.parametrize("per_day", [0, -1])
def test_每天零条就是关着_永远不说(per_day):
    assert ai_bots.due(None, per_day, NOW) is False, "配成 0 是「这一项别做」,不是「不限」"


# ---------------- 给模型的话 ----------------

def test_发帖的提示词从兴趣话题里挑一个当由头():
    got = {ai_bots.post_prompt(persona()) for _ in range(40)}
    assert len(got) > 1, "每次都用同一个由头的话,发出来的会是同一类帖子"
    assert any("做饭" in g for g in got)
    assert any("夜宵" in g for g in got)


def test_没填话题也发得出来():
    assert "身边的小事" in ai_bots.post_prompt(persona(topics=""))


def test_提示词里不许让它假装成人():
    """页面上已经标了是机器人。再让模型"假装"是两件事叠加,而且是往反方向叠。"""
    p = ai_bots.post_prompt(persona())
    for bad in ("假装", "冒充", "不要暴露", "扮演真人"):
        assert bad not in p


def test_提示词交代了别输出多余的东西():
    p = ai_bots.post_prompt(persona())
    assert "只输出正文" in p
    assert "不要标题" in p


def test_回帖的提示词带上对方说了什么_并且只回一句():
    p = ai_bots.reply_prompt(persona(), "今天这家串串太咸了")
    assert "今天这家串串太咸了" in p
    assert "只回一句" in p
    assert "不要复述" in p


def test_回帖时对方的原文截断_不整段塞给模型():
    p = ai_bots.reply_prompt(persona(), "啊" * 1000)
    assert p.count("啊") <= 300


# ---------------- 一轮最多说几条 ----------------

def test_一轮有上限():
    assert 1 <= ai_bots.MAX_PER_TICK <= 3, (
        "一轮吐出一堆,时间线上会出现一整屏机器人 —— 那比空着更难看")


def test_只回最近的帖_窗口不能太长():
    assert 1 <= ai_bots.REPLY_WINDOW_HOURS <= 24, (
        "太旧的帖子下面突然冒出一条回复很突兀")


def test_候选池不是只看最新一条():
    assert ai_bots.REPLY_POOL >= 10, "总是回最新那条的话,看起来就像在蹲守"


# ---------------- 秩序上限:后台可调,但缺省要站得住 ----------------

def test_缺省值就是运营方拍的那几个数():
    """这几个数 2026-09-16 运营方自己定的。改缺省值要有人拍板,不是随手调。"""
    assert ai_bots.LIMIT_DEFAULTS == {
        "ai_bots_per_user": 20,
        "ai_timeline_share": 80,
        "ai_replies_per_post": 100,
        "ai_posts_per_day_max": 48,
        "ai_replies_per_day_max": 96,
    }


class FakeDb:
    """只够 limit() / _pick_target() 用的那点会话。"""

    def __init__(self, flags: dict | None = None, posts=(), bots_under=0):
        self._flags = flags or {}
        self._posts = list(posts)
        self._bots_under = bots_under
        self.counted = 0

    async def get(self, _model, key):
        v = self._flags.get(key)
        if v is None:
            return None
        return type("Row", (), {"key": key, "value": v})()

    async def scalars(self, _q):
        return list(self._posts)

    async def scalar(self, _q):
        self.counted += 1
        n = self._bots_under
        return n(self.counted) if callable(n) else n


def limit(flags, key):
    import asyncio
    return asyncio.run(ai_bots.limit(FakeDb(flags), key))


def test_没人拨过按缺省():
    assert limit({}, "ai_replies_per_post") == 100


def test_后台拨过就按后台的():
    assert limit({"ai_replies_per_post": "3"}, "ai_replies_per_post") == 3


@pytest.mark.parametrize("bad", ["", "  ", "很多", "3.5", None])
def test_填了不是数的按缺省_不把整轮带倒(bad):
    """手工改过库、或者以后前端放进来个空串。**这里炸了的表现是所有 AI 全哑**,
    而且不报错 —— 所以宁可按缺省走。"""
    assert limit({"ai_bots_per_user": bad}, "ai_bots_per_user") == 20


def test_拨成零就是一个都不许():
    assert limit({"ai_bots_per_user": "0"}, "ai_bots_per_user") == 0


# ---------------- 一条帖下面最多站几个机器人 ----------------

def pick(bots_under, n_posts=1, cap="2"):
    import asyncio

    posts = [type("P", (), {"id": i, "pid": f"p{i}", "text": "今天这家串串太咸了"})()
             for i in range(n_posts)]
    db = FakeDb({"ai_replies_per_post": cap}, posts=posts, bots_under=bots_under)
    return asyncio.run(ai_bots._pick_target(db, persona(), NOW))


@pytest.mark.parametrize("under,ok", [(0, True), (1, True), (2, False), (5, False)])
def test_站满了就不再往这条帖下面站(under, ok):
    """上限 2:已经有 2 个就不许第 3 个。差一个的判断(< 还是 <=)错了的表现是
    一条真人帖底下排一长队机器人 —— 那是这个功能最难看的失败形状。"""
    assert (pick(under) is not None) is ok


def test_这条满了就换下一条():
    # 第一条已经站了 5 个(超上限),第二条空着 → 该挑第二条
    got = pick(lambda i: 5 if i == 1 else 0, n_posts=2)
    assert got is not None


def test_全都满了就这一轮不回():
    assert pick(9, n_posts=3) is None


def test_一条帖都没有时不去数机器人():
    db = FakeDb({}, posts=[], bots_under=0)
    import asyncio
    assert asyncio.run(ai_bots._pick_target(db, persona(), NOW)) is None
    assert db.counted == 0, "没有候选还去查上限是白跑一趟"


# ---------------- 用户填的模型地址:由我们的服务器去请求,所以要过内网守卫 ----------------

@pytest.fixture
def prod(monkeypatch):
    """按生产判。本机开发时 127.0.0.1 是**故意**放行的(e2e 要在本机起个假模型),
    不按生产判的话下面几条会因为那个口子而静默变成空测。"""
    from app.config import settings
    monkeypatch.setattr(settings, "app_env", "prod")


def endpoint_err(url: str) -> str:
    import asyncio

    from fastapi import HTTPException

    try:
        asyncio.run(ai_bots.check_endpoint(url))
    except HTTPException as e:
        return str(e.detail)
    return ""


@pytest.mark.parametrize("url,needle", [
    ("", "1–300"),
    ("x" * 301, "1–300"),
    ("http://api.example.com/v1", "https"),
    ("https://", "缺少域名"),
    ("https://u:p@api.example.com/v1", "用户名和密码"),
])
def test_形状不对的地址当场拒(url, needle, prod):
    assert needle in endpoint_err(url)


@pytest.mark.parametrize("url", [
    "https://169.254.169.254/latest/v1",   # 云厂商元数据 —— 最经典的那一招
    "https://10.0.0.5/v1",
    "https://172.16.3.4/v1",
    "https://[::1]/v1",
    "https://127.0.0.1:11434/v1",
])
def test_指向内网和元数据的地址拒掉(url, prod):
    assert "内网或回环" in endpoint_err(url), (
        "这条守的是 SSRF:地址是用户填的,请求是我们的服务器发的")


def test_本机地址只在开发环境放行(monkeypatch):
    """e2e 要在本机起一个假模型。这个口子挂在 `is_dev` 上 ——
    `app_env` 缺省是 prod,所以线上自动是关的。"""
    from app.config import settings
    monkeypatch.setattr(settings, "app_env", "dev")
    assert endpoint_err("http://127.0.0.1:11434/v1") == ""
    monkeypatch.setattr(settings, "app_env", "prod")
    assert "内网或回环" in endpoint_err("https://127.0.0.1:11434/v1")


def test_端口不限_自己跑的模型常在八千和一万一(prod):
    """和 webhook 不同。那边只许 80/88/443/8443 是 Telegram 的规矩;
    而 vLLM 在 8000、Ollama 在 11434。**防 SSRF 靠判 IP,不是判端口。**"""
    assert "端口" not in endpoint_err("https://api.example.com:11434/v1")


# ---------------- AI 号不占开发者那份配额 ----------------

def test_开发者配额把_ai_号排除在外():
    """**这条是个陷阱题。** 所有 AI 号在外键上都挂在**同一个**官方开发者名下
    (机器人账号体系要求主人是开发者),但它们不是那个开发者的 ——
    每个都属于建它的那个用户。

    不排掉的话:`create_bot` 里「每个开发者最多 20 个机器人」会变成
    **全平台最多 20 个 AI 号**,第 21 个用户建第一个号时撞上一句和他毫无关系的话,
    而在那之前一切正常。限 AI 号的是 ai_bots_per_user,不是这一条。
    """
    import inspect

    from app.services import bots

    src = inspect.getsource(bots.create_bot)
    head = src[:src.index("MAX_BOTS_PER_DEVELOPER")]
    assert "is_ai" in head, (
        "数开发者有几个机器人时没把 AI 号排掉 —— 全平台的 AI 号共用一份 20 的配额")


def test_建号时按每人上限拦():
    import inspect

    from app.services import ai_bots as m

    src = inspect.getsource(m.create)
    assert "ai_bots_per_user" in src and "holder.id" in src, (
        "名额要按**持有人**算(ai_personas.owner_id),不是按挂在谁名下算")
