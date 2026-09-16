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
