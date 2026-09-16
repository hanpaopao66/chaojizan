"""音乐的公开公式(DEV-PROMPTS-41 §5.4)和「不卖流量」的守卫。

- 公式原文:services/music_rank.FORMULA 和文档 §5.4 的 ```text 块**逐字一致**(改一边另一边就红);
- 逐项复算:用文档里的系数手算几个例子,和纯函数的结果对上;
- 去重:每个榜最多 100 首、同一位音乐人最多 10 首;每日推荐 20 首、同一位最多 3 首;
- S3:音乐模块的表里不许有能被买的列;算分代码里不许出现付费 / 商家 / 运营加权的字眼。
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services import music_rank as rank

ROOT = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def test_formula_matches_the_doc_word_for_word():
    doc = (ROOT / "docs/DEV-PROMPTS-41.md").read_text(encoding="utf-8")
    sec = doc.split("### 5.4", 1)[1]
    block = re.search(r"```text\n(.*?)\n```", sec, re.S).group(1)
    assert block == rank.FORMULA, "services/music_rank.FORMULA 必须和 §5.4 逐字一致"
    assert rank.FORMULA in (rank.__doc__ or ""), "模块注释里贴的公式原文也要一致"


def test_params_are_the_published_ones():
    # 照 §5.4 抄:7、14、24、30、5、100、10、20、200、3
    assert (rank.HOT_WINDOW_DAYS, rank.NEW_RELEASE_DAYS, rank.RISING_WINDOW_HOURS) == (7, 14, 24)
    assert (rank.LIKE_WEIGHT, rank.PLAYLIST_WEIGHT) == (3, 5)
    assert (rank.RISING_MIN_LISTENERS, rank.RISING_FLOOR) == (5, 5)
    assert (rank.CHART_SIZE, rank.PER_ARTIST_PER_CHART) == (100, 10)
    assert (rank.DAILY_SIZE, rank.DAILY_PER_ARTIST) == (20, 3)
    assert (rank.DAILY_LOOKBACK_DAYS, rank.DAILY_SKIP_RECENT_DAYS) == (30, 7)
    assert (rank.GENRE_WEIGHT, rank.GENRE_CAP) == (20, 10)
    assert rank.FOLLOW_BONUS == 200
    assert (rank.ARTIST_LIKE_WEIGHT, rank.ARTIST_LIKE_CAP) == (20, 5)
    assert (rank.PLAYLIST_RECENT_DAYS, rank.PLAYLIST_RECENT_WEIGHT,
            rank.PLAYLIST_MIN_TRACKS) == (30, 5, 5)
    assert (rank.LISTEN_MIN_MS, rank.LISTEN_MIN_RATIO, rank.LISTEN_DEDUP_MINUTES) == \
        (30_000, 0.5, 30)
    # /music/v1/rank/formula 原样下发这一份:公式里出现的每个数字都得在里面
    for key in ("hot_window_days", "like_weight", "playlist_weight", "new_release_days",
                "rising_window_hours", "rising_min_listeners", "rising_floor", "chart_size",
                "per_artist_per_chart", "daily_size", "daily_per_artist", "genre_weight",
                "genre_cap", "follow_bonus", "artist_like_weight", "artist_like_cap",
                "playlist_recent_days", "playlist_recent_weight", "playlist_min_tracks"):
        assert key in rank.PARAMS, key


def test_listen_threshold_is_min_30s_or_half():
    assert rank.listen_threshold_ms(20_000) == 10_000, "20 秒的歌听 10 秒就算"
    assert rank.listen_threshold_ms(200_000) == 30_000, "3 分多的歌听满 30 秒才算"
    assert rank.listen_threshold_ms(60_000) == 30_000
    assert rank.counted(10_000, 20_000) and not rank.counted(9_999, 20_000)
    assert not rank.counted(999_999, 0), "还没转码完(时长 0)的歌一律不算"


def test_recompute_by_hand():
    # 热歌榜 = 收听 + 3 × 喜欢 + 5 × 加歌单
    assert rank.hot_score(35, 4, 2) == 35 + 12 + 10 == 57
    # 新歌榜 = 收听 + 3 × 喜欢
    assert rank.new_score(35, 4) == 47
    # 飙升 = (L − P) ÷ max(P, 5)
    assert rank.rising_score(30, 10) == 2.0
    assert rank.rising_score(10, 0) == 2.0, "前 24 小时 0 人时分母取 5"
    assert rank.rising_score(3, 10) == -0.7
    assert rank.rising_eligible(5) and not rank.rising_eligible(4)
    # 每日推荐 = 热歌分 + 20 × min(同曲风, 10) + 200 × [关注] + 20 × min(喜欢过他几首, 5)
    assert rank.daily_score(57, 3, False, 0) == 57 + 60
    assert rank.daily_score(57, 30, True, 9) == 57 + 200 + 200 + 100, "两个 min 都要封顶"
    assert rank.daily_score(57, 0, False, 0) == 57, "关掉个性化 = 只按热歌榜分数"
    # 推荐歌单 = 5 × 近 30 天新增收藏人数 + 总收藏人数
    assert rank.playlist_score(2, 7) == 17


def test_order_key_is_deterministic():
    a = (10.0, T0, 5)
    b = (10.0, T0 - timedelta(hours=1), 6)
    c = (20.0, T0 - timedelta(days=5), 7)
    assert sorted([a, b, c], key=lambda x: rank.order_key(*x)) == [c, a, b], \
        "分高的在前;同分时发布新的在前"
    d = (10.0, T0, 9)
    assert sorted([a, d], key=lambda x: rank.order_key(*x)) == [d, a], "再同就按歌曲编号"
    # 没有发布时间(理论上不该进榜)也不能炸
    assert rank.order_key(1.0, None, 3) == (-1.0, -0.0, -3)


def test_chart_caps_ten_per_artist_and_hundred_total():
    # 音乐人 1 有 30 首排在最前,后面是别人的
    items = [(i, 1) for i in range(30)] + [(i, 2 + (i % 50)) for i in range(30, 200)]
    keep = rank.cap_per_artist(items, lambda x: x[1], cap=rank.PER_ARTIST_PER_CHART,
                               size=rank.CHART_SIZE)
    assert len(keep) == 100
    per: dict = {}
    for _, a in keep:
        per[a] = per.get(a, 0) + 1
    assert max(per.values()) <= 10, per
    assert per[1] == 10, "第 11 首起丢掉,不顺延 —— 榜是固定长度的表"
    assert [i for i, _ in keep] == sorted(i for i, _ in keep), "保持原来的先后"


def test_daily_caps_three_per_artist_and_twenty_total():
    items = [(i, 1) for i in range(10)] + [(i, 2 + i) for i in range(10, 60)]
    keep = rank.cap_per_artist(items, lambda x: x[1], cap=rank.DAILY_PER_ARTIST,
                               size=rank.DAILY_SIZE)
    assert len(keep) == 20
    assert sum(1 for _, a in keep if a == 1) == 3


def test_why_is_readable():
    assert rank.hot_why(35, 4, 2) == "近 7 天 35 人收听、4 人喜欢、2 人加入歌单"
    assert rank.hot_why(35, 0, 0) == "近 7 天 35 人收听"
    assert "前 24 小时" in rank.rising_why(30, 10)
    out = rank.rank_out(1 / 3, {"a": 1}, "因为")
    assert set(out) == {"score", "parts", "why"} and out["score"] == 0.3333


# ---------------- S3:不卖流量 ----------------

S3_FORBIDDEN = re.compile(r"bid|boost|paid|promot|rank_score|weight_override")


def test_no_sellable_columns_in_any_music_table():
    from app.models import MUSIC_MODELS

    assert len(MUSIC_MODELS) >= 15, "音乐表清单不全,这条守卫扫不到新表"
    bad = [f"{m.__tablename__}.{c.name}" for m in MUSIC_MODELS for c in m.__table__.columns
           if S3_FORBIDDEN.search(c.name)]
    assert not bad, f"音乐相关的表里不许出现能被买的列:{bad}"


def test_every_music_table_is_listed():
    """新加的音乐表必须进 MUSIC_MODELS,否则上面那条扫描(和注销级联)会漏掉它。"""
    from app import models
    from app.db import Base

    src = (ROOT / "server/app/models_music.py").read_text(encoding="utf-8")
    declared = set(re.findall(r'__tablename__ = "([a-z_]+)"', src))
    listed = {m.__tablename__ for m in models.MUSIC_MODELS}
    assert declared == listed, declared ^ listed
    assert listed <= set(Base.metadata.tables)


def test_ranking_code_mentions_nothing_sellable():
    src = (ROOT / "server/app/services/music_rank.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))
    code = re.sub(r'"""(.*?)"""', "", code, flags=re.S)
    hits = S3_FORBIDDEN.findall(code) + re.findall(r"merchant|sponsor|advert", code)
    assert not hits, f"music_rank 里出现了付费 / 商家 / 运营加权的字眼:{hits}"
