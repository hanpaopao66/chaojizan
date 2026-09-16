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


# ---------------- 机器人内容占一屏的上限(#386) ----------------

def _mix(pattern: str) -> list[tuple[int, bool]]:
    """按图案造一屏候选:`a` = AI 的,`h` = 真人的。**每条一个不同的作者** ——
    不然「同一作者最多 2 条」那条闸会先拦住,测不到占比这一条。"""
    return [(i, ch == "a") for i, ch in enumerate(pattern)]


def _pages(pattern: str, share: int, size: int = 10):
    return rank.paginate_screens(_mix(pattern), lambda x: x[0], size=size,
                                 per_author=2, capped=lambda x: x[1],
                                 cap_share=share)


def test_不给闸时一切照旧():
    """`capped=None` 是缺省。已有的调用一个字都不用改,行为要和从前一模一样。"""
    items = list(range(25))
    assert rank.paginate_screens(items, lambda x: x, size=10, per_author=99) == [
        list(range(10)), list(range(10, 20)), list(range(20, 25))]


def test_八成的闸_一屏十条最多八条机器人():
    got = _pages("a" * 20, 80, size=10)
    assert [sum(1 for _, ai in s if ai) for s in got[:2]] == [8, 8], (
        f"一屏十条、上限八成 → 最多 8 条机器人:{got}")


def test_挤下来的不丢_顺延到下一屏():
    got = _pages("aaaaaaaaaahhhhhhhhhh", 80, size=10)
    flat = [i for s in got for i, _ in s]
    assert sorted(flat) == list(range(20)), f"一条都不该丢:{got}"
    # 头两条真人帖被提前,好凑满第一屏 —— 顺序在同类里仍然保持
    ai_first = [i for i, ai in got[0] if ai]
    assert ai_first == sorted(ai_first), "机器人那几条之间的先后不许被打乱"


def test_一屏里机器人不够上限时不硬凑():
    got = _pages("ahahahahah", 80, size=10)
    assert len(got[0]) == 10 and sum(1 for _, ai in got[0] if ai) == 5, (
        "上限是「最多」,不是「必须凑到」")


def test_拨到一百等于不限():
    assert len(_pages("a" * 10, 100, size=10)[0]) == 10


def test_拨到零就是机器人不进时间线_而且不会挂死():
    """**这一条是这个函数里唯一会挂死整个请求的形状。**

    上限 0 时一屏里一条机器人都放不下,于是剩下的全被顺延 —— 而顺延的还是同一批,
    `pool` 永远不变小。不特意停下就是个死循环:请求不返回、连接一直占着,
    而日志里什么都没有。
    """
    got = _pages("a" * 30, 0, size=10)
    assert got == [] or all(not ai for s in got for _, ai in s), got


def test_拨到零时真人的帖照常出_机器人那些被丢在后面():
    got = _pages("aaaaahhhhh", 0, size=10)
    assert [i for s in got for i, _ in s] == [5, 6, 7, 8, 9], (
        f"真人的五条该照常出,机器人的五条一条都不出:{got}")


def test_闸只拦被标记的那一类_真人再多也不受影响():
    got = _pages("h" * 30, 0, size=10)
    assert sum(len(s) for s in got) == 30, "拨到 0 拦的是机器人,不是所有人"
