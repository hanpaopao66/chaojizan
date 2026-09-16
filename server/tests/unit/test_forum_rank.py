"""论坛的排序公式(DEV-PROMPTS-41 §5.7)和「不卖流量」(§3.1)的守卫。

- 公式原文:services/forum_rank.FORMULA 和文档 §5.7 的 ```text 块**逐字一致**(改了一边另一边就红);
- 逐项复算:用文档里的系数手算几个例子,和纯函数的结果对上;
- 去重:一屏 20 条、同一作者最多 2 条,超出的顺延到下一屏;
- §3.1:论坛全部表里不许有 sponsored / boost / paid / promot 这类列;排序函数能看到的输入
  只有公开字段 —— 加一个字段(比如「付费权重」)这里就红。
"""
import dataclasses
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services import forum_rank as rank

ROOT = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def test_公式和文档逐字一致():
    doc = (ROOT / "docs/DEV-PROMPTS-41.md").read_text(encoding="utf-8")
    sec = doc.split("### 5.7", 1)[1]
    block = re.search(r"```text\n(.*?)\n```", sec, re.S).group(1)
    assert block == rank.FORMULA, "services/forum_rank.FORMULA 必须和 §5.7 逐字一致"
    assert rank.FORMULA in (rank.__doc__ or ""), "模块注释里贴的公式原文也要一致"


def test_参数就是公布出去的那几个():
    assert rank.WEIGHTS == {"likes": 1, "reposts": 2, "quotes": 2, "repliers": 3}
    for word, key in (("点赞人数", "likes"), ("转发人数", "reposts"), ("引用人数", "quotes"),
                      ("回复人数", "repliers")):
        w = rank.WEIGHTS[key]
        assert (word in rank.FORMULA) and (f"{w} × {word}" in rank.FORMULA or w == 1)
    assert (rank.WINDOW_HOURS, rank.E_OFFSET) == (72, 1)
    assert (rank.DECAY_OFFSET_HOURS, rank.DECAY_POWER) == (2, 1.5)
    assert (rank.FOLLOW_BONUS, rank.TOPIC_BONUS, rank.TOPIC_LOOKBACK_DAYS) == (1, 0.5, 30)
    assert (rank.SCREEN_SIZE, rank.PER_AUTHOR_PER_SCREEN) == (20, 2)
    assert (rank.TREND_WINDOW_HOURS, rank.TREND_RECENT_HOURS, rank.TREND_RECENT_WEIGHT) == \
        (24, 3, 2)
    assert (rank.TREND_MIN_AUTHORS, rank.TREND_MAX) == (2, 20)
    # /forum/v1/rank/formula 原样返回这一份:少一个参数就等于有一段没公开
    assert set(rank.PARAMS) >= {"window_hours", "like_weight", "repost_weight", "quote_weight",
                                "reply_weight", "e_offset", "decay_offset_hours", "decay_power",
                                "follow_bonus", "topic_bonus", "topic_lookback_days",
                                "screen_size", "per_author_per_screen", "trend_window_hours",
                                "trend_recent_hours", "trend_recent_weight",
                                "trend_min_authors", "trend_max"}


def test_手算复核():
    c = rank.Counts(likes=10, reposts=3, quotes=2, repliers=5)
    assert rank.interaction(c) == 10 + 6 + 4 + 15 == 35
    inp = rank.RankInput(post_id=1, author_id=9, created_at=T0 - timedelta(hours=7), counts=c)
    b = rank.breakdown(inp, T0)
    assert b["parts"]["hours"] == 7.0 and b["parts"]["e"] == 35
    assert math.isclose(b["score"], 36 / 9 ** 1.5)          # (7 + 2) ^ 1.5 = 27
    assert math.isclose(b["score"], 36 / 27)
    both = rank.breakdown(inp, T0, followed=True, topic=True)
    assert math.isclose(both["score"], 36 / 27 * 2 * 1.5)
    assert math.isclose(rank.breakdown(inp, T0, followed=True)["score"], 36 / 27 * 2)
    assert math.isclose(rank.breakdown(inp, T0, topic=True)["score"], 36 / 27 * 1.5)


def test_一个互动都没有的新帖也有分():
    """E 里加 1 再除:不然新帖永远沉底,只有已经火的才更火。"""
    inp = rank.RankInput(post_id=1, author_id=1, created_at=T0, counts=rank.Counts())
    assert rank.breakdown(inp, T0)["score"] == 1 / 2 ** 1.5 > 0


def test_发帖时间在未来按零小时算():
    inp = rank.RankInput(post_id=1, author_id=1, created_at=T0 + timedelta(minutes=5),
                         counts=rank.Counts())
    assert rank.breakdown(inp, T0)["parts"]["hours"] == 0.0


def test_关掉个性化两个方括号都按零算():
    inp = rank.RankInput(post_id=1, author_id=1, created_at=T0 - timedelta(hours=1),
                         counts=rank.Counts(likes=4))
    assert rank.breakdown(inp, T0)["score"] == \
        rank.breakdown(inp, T0, followed=False, topic=False)["score"]


def test_一屏二十条同一作者最多两条():
    items = [(i, i % 3) for i in range(60)]     # 三个作者轮流发
    screens = rank.paginate_screens(items, lambda x: x[1])
    assert len(screens[0]) == 6, "三个作者各 2 条,一屏只凑得出 6 条"
    assert all(sum(1 for x in s if x[1] == a) <= 2 for s in screens for a in (0, 1, 2))
    # 超出的顺延,一条都不丢、先后不变
    flat = [x for s in screens for x in s]
    assert sorted(flat) == sorted(items)
    assert [x[0] for x in flat[:6]] == [0, 1, 2, 3, 4, 5]


def test_同分时新的在前_再同按编号():
    a = rank.order_key(1.0, T0 - timedelta(hours=1), 5)
    b = rank.order_key(1.0, T0 - timedelta(hours=2), 9)
    assert a < b, "同分时新发的在前"
    assert rank.order_key(1.0, T0, 9) < rank.order_key(1.0, T0, 5)


def test_热门话题的分和门槛():
    assert rank.trend_score(10, 3) == 10 + 2 * 3 == 16
    assert rank.trending_enough(2) and not rank.trending_enough(1), \
        "一个人自己刷不出热门话题"


def test_排序输入里只有公开字段():
    """§3.1:RankInput 上加一个字段(「付费权重」「运营加权」)这里就红。"""
    got = {f.name for f in dataclasses.fields(rank.RankInput)}
    assert got == {"post_id", "author_id", "created_at", "counts"}, got
    assert {f.name for f in dataclasses.fields(rank.Counts)} == set(rank.WEIGHTS)
