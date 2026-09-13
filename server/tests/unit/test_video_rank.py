"""排序公式(DEV-PROMPTS-40 §5.9)和「不卖流量」(S3)的守卫。

- 公式原文:services/video_rank.FORMULA 和文档 §5.9 的代码块**逐字一致**(改了一边另一边就红);
- 逐项复算:用文档里的系数手算几个例子,和纯函数的结果对上;
- 去重:一屏 20 条、同一个 UP 主最多 2 个,超出的顺延到下一屏;
- S3:视频模块全部表里不许有 bid / boost / paid / promot / rank_score / weight_override 这类列;
  排序函数能看到的输入只有公开字段 —— 加一个字段(比如「付费权重」)这里就红。
"""
import dataclasses
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import video_rank as rank

ROOT = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def test_formula_matches_the_doc_word_for_word():
    doc = (ROOT / "docs/DEV-PROMPTS-40.md").read_text(encoding="utf-8")
    sec = doc.split("### 5.9 排序公式", 1)[1]
    block = re.search(r"```\n(.*?)\n```", sec, re.S).group(1)
    assert block == rank.FORMULA, "services/video_rank.FORMULA 必须和 §5.9 逐字一致"
    assert rank.FORMULA in (rank.__doc__ or ""), "模块注释里贴的公式原文也要一致"


def test_weights_are_the_published_ones():
    # 照 §5.9 第一行抄:播放 1、点赞 5、投币 10、收藏 8、评论 6、弹幕 2、分享 10
    assert rank.WEIGHTS == {"views": 1, "likes": 5, "coins": 10, "favorites": 8, "comments": 6,
                            "danmaku": 2, "shares": 10}
    for word, key in (("播放", "views"), ("点赞", "likes"), ("投币", "coins"), ("收藏", "favorites"),
                      ("评论", "comments"), ("弹幕", "danmaku"), ("分享", "shares")):
        assert f"{word} × {rank.WEIGHTS[key]}" in rank.FORMULA
    assert (rank.WINDOW_HOURS, rank.DECAY_OFFSET_HOURS, rank.DECAY_POWER) == (72, 2, 1.5)
    assert (rank.FOLLOW_BONUS, rank.ZONE_BONUS, rank.TOP_ZONES) == (0.3, 0.15, 3)
    assert (rank.SCREEN_SIZE, rank.PER_UPLOADER_PER_SCREEN) == (20, 2)
    assert (rank.WATCHED_RATIO, rank.WATCHED_SKIP_DAYS, rank.RANK_WINDOWS_DAYS) == (0.5, 7, (1, 3, 7))


def test_recompute_by_hand():
    c = rank.Counts(views=100, likes=10, coins=3, favorites=4, comments=5, danmaku=20, shares=2)
    assert rank.interaction(c) == 100 + 50 + 30 + 32 + 30 + 40 + 20 == 302
    inp = rank.RankInput(video_id=1, uploader_id=9, zone="game", published_at=T0 - timedelta(hours=7),
                         counts=c)
    b = rank.breakdown(inp, T0)
    assert b["hours"] == 7.0
    assert math.isclose(b["hot"], 302 / 9 ** 1.5)          # (7 + 2) ^ 1.5 = 27
    assert math.isclose(b["hot"], 302 / 27)
    assert b["recommend"] == b["hot"], "不个性化时推荐 = 热度"
    both = rank.breakdown(inp, T0, followed=True, top_zone=True)
    assert math.isclose(both["recommend"], 302 / 27 * 1.45)
    assert math.isclose(rank.breakdown(inp, T0, followed=True)["recommend"], 302 / 27 * 1.3)
    assert math.isclose(rank.breakdown(inp, T0, top_zone=True)["recommend"], 302 / 27 * 1.15)
    fresh = rank.breakdown(dataclasses.replace(inp, published_at=T0 + timedelta(minutes=5)), T0)
    assert fresh["hours"] == 0.0, "发布时间在未来(时钟误差)按 0 小时算"
    assert math.isclose(fresh["hot"], 302 / 2 ** 1.5)


def test_older_videos_decay():
    c = rank.Counts(likes=10)
    hots = [rank.hot(rank.interaction(c), h) for h in (0, 1, 10, 100)]
    assert hots == sorted(hots, reverse=True)
    assert rank.hot(0, 0) == 0


def test_order_key_is_deterministic():
    a = (1.0, T0, 5)
    b = (1.0, T0 - timedelta(hours=1), 6)
    c = (2.0, T0 - timedelta(hours=5), 7)
    rows = sorted([a, b, c], key=lambda x: rank.order_key(*x))
    assert rows == [c, a, b], "分高的在前;同分时新发布的在前"
    d = (1.0, T0, 9)
    assert sorted([a, d], key=lambda x: rank.order_key(*x)) == [d, a], "再同就按 id,保证确定"


def test_screens_cap_two_per_uploader_and_keep_order():
    # 按分数排好的 12 条:UP 主 1 有 5 条排在最前
    items = [(i, 1) for i in range(5)] + [(i, 2) for i in range(5, 8)] + \
        [(i, u) for i, u in zip(range(8, 12), (3, 4, 5, 6))]
    # 不传 size / per_uploader:测的是线上真在用的缺省值(传了参数的话改坏常量这里也照样绿,
    # 第一版就是这么空转的,弄坏一次才发现)
    screens = rank.paginate_screens(items, lambda x: x[1])
    for s in screens:
        per = {}
        for _, up in s:
            per[up] = per.get(up, 0) + 1
        assert max(per.values()) <= 2
        assert [i for i, _ in s] == sorted(i for i, _ in s), "屏内保持原来的先后"
    where = {i: n for n, s in enumerate(screens) for i, _ in s}
    assert [where[i] for i in range(5)] == [0, 0, 1, 1, 2], "第 3 个起顺延到下一屏"
    assert sum(len(s) for s in screens) == 12, "顺延不丢"


def test_screen_size_is_20():
    items = [(i, i) for i in range(45)]
    screens = rank.paginate_screens(items, lambda x: x[1])
    assert [len(s) for s in screens] == [20, 20, 5]
    assert rank.paginate_screens(items, lambda x: x[1], max_screens=1) == [items[:20]]


def test_watched_rule():
    assert rank.watched_enough(51, 100) and not rank.watched_enough(50, 100)
    assert not rank.watched_enough(10, 0)


# ---------------- S3:不卖流量 ----------------

S3_FORBIDDEN = re.compile(r"bid|boost|paid|promot|rank_score|weight_override")


def test_no_sellable_columns_in_any_video_table():
    from app.models import VIDEO_MODELS
    assert len(VIDEO_MODELS) >= 20, "视频表清单不全,这条守卫扫不到新表"
    bad = [f"{m.__tablename__}.{c.name}" for m in VIDEO_MODELS for c in m.__table__.columns
           if S3_FORBIDDEN.search(c.name)]
    assert not bad, f"S3:视频相关的表里不许出现能被买的列:{bad}"


def test_every_video_table_is_listed():
    """新加的视频表必须进 VIDEO_MODELS,否则上面那条扫描(和注销级联)会漏掉它。"""
    from app import models
    from app.db import Base
    video_src = (ROOT / "server/app/models_video.py").read_text(encoding="utf-8")
    declared = set(re.findall(r'__tablename__ = "([a-z_]+)"', video_src))
    listed = {m.__tablename__ for m in models.VIDEO_MODELS}
    assert declared == listed, declared ^ listed
    assert listed <= set(Base.metadata.tables)


def test_rank_inputs_are_only_public_fields():
    """排序函数能看到的全部东西。加字段之前先想清楚它能不能被买(S3)。"""
    assert {f.name for f in dataclasses.fields(rank.RankInput)} == \
        {"video_id", "uploader_id", "zone", "published_at", "counts"}
    assert {f.name for f in dataclasses.fields(rank.Counts)} == set(rank.WEIGHTS)
    import inspect
    assert list(inspect.signature(rank.recommend).parameters) == ["hot_value", "followed",
                                                                  "top_zone"]
    assert list(inspect.signature(rank.breakdown).parameters) == ["inp", "now", "followed",
                                                                  "top_zone"]


@pytest.mark.parametrize("mod", ["video_rank", "video_feed"])
def test_ranking_code_mentions_nothing_sellable(mod):
    src = (ROOT / f"server/app/services/{mod}.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))
    code = re.sub(r'"""(.*?)"""', "", code, flags=re.S)
    hits = S3_FORBIDDEN.findall(code) + re.findall(r"merchant|sponsor|advert", code)
    assert not hits, f"{mod} 里出现了付费 / 商家 / 运营加权的字眼:{hits}"
