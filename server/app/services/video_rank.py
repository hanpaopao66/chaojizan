"""推荐 / 热门 / 排行榜 / 竖屏流的排序公式(DEV-PROMPTS-40 §5.9)。**公开,纯函数。**

公式原文(和 docs/DEV-PROMPTS-40.md §5.9 逐字一致,tests/unit/test_video_rank.py 对着文档比):

```
互动分 = 播放 × 1 + 点赞 × 5 + 投币 × 10 + 收藏 × 8 + 评论 × 6 + 弹幕 × 2 + 分享 × 10
         (只数最近 72 小时内的增量;同一个人对同一个视频每种互动只算一次)
热度   = 互动分 ÷ (发布后的小时数 + 2) ^ 1.5
推荐   = 热度 × (1 + 0.3 × 我关注了这个 UP 主 + 0.15 × 这是我近 30 天最常看的 3 个分区之一)
         关掉个性化:两个加权都是 0
去重   = 同一个 UP 主在一屏(20 条)里最多 2 个;看过的(播放进度 > 50%)7 天内不再推
排行榜 = 某分区(或全站)按「互动分」在 1 / 3 / 7 天窗口里排序
竖屏流 = 只取竖屏视频(宽 < 高),同「推荐」
```

为什么是纯函数、为什么输入这么少(S3 不卖流量):

- 输入只有**公开的**东西 —— 七种互动的去重计数、发布时间、UP 主是谁、分区;个性化再加两个布尔
  (我关注了他没有、这是不是我常看的分区)。**没有任何付费、商家、运营加权的入口**:
  RankInput 上加一个字段,单测就红;
- 每条推荐都带着算出它的那几个数(`breakdown`),客户端「为什么推荐」直接展示,谁都能拿计算器复算;
- 「只数 72 小时内、同一个人每种互动只算一次」由取数那一层保证(services/video_feed.window_counts
  从明细表按时间窗 COUNT DISTINCT),这里只管算。
"""
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

FORMULA = """互动分 = 播放 × 1 + 点赞 × 5 + 投币 × 10 + 收藏 × 8 + 评论 × 6 + 弹幕 × 2 + 分享 × 10
         (只数最近 72 小时内的增量;同一个人对同一个视频每种互动只算一次)
热度   = 互动分 ÷ (发布后的小时数 + 2) ^ 1.5
推荐   = 热度 × (1 + 0.3 × 我关注了这个 UP 主 + 0.15 × 这是我近 30 天最常看的 3 个分区之一)
         关掉个性化:两个加权都是 0
去重   = 同一个 UP 主在一屏(20 条)里最多 2 个;看过的(播放进度 > 50%)7 天内不再推
排行榜 = 某分区(或全站)按「互动分」在 1 / 3 / 7 天窗口里排序
竖屏流 = 只取竖屏视频(宽 < 高),同「推荐」"""

#: 互动分的权重(公式第一行)
WEIGHTS: dict[str, int] = {
    "views": 1, "likes": 5, "coins": 10, "favorites": 8, "comments": 6, "danmaku": 2, "shares": 10,
}
#: 互动分只数这么多小时内的增量
WINDOW_HOURS = 72
#: 热度 = 互动分 ÷ (小时数 + DECAY_OFFSET_HOURS) ^ DECAY_POWER
DECAY_OFFSET_HOURS = 2
DECAY_POWER = 1.5
#: 推荐的两个个性化加权
FOLLOW_BONUS = 0.3
ZONE_BONUS = 0.15
TOP_ZONES = 3
ZONE_LOOKBACK_DAYS = 30
#: 一屏 20 条,同一个 UP 主最多 2 个
SCREEN_SIZE = 20
PER_UPLOADER_PER_SCREEN = 2
#: 看过的(进度 > 50%)7 天内不再推
WATCHED_RATIO = 0.5
WATCHED_SKIP_DAYS = 7
#: 排行榜的窗口(天)
RANK_WINDOWS_DAYS = (1, 3, 7)


@dataclass(frozen=True)
class Counts:
    """一个视频在时间窗里的七种互动(每种按人去重后的个数)。"""

    views: int = 0
    likes: int = 0
    coins: int = 0
    favorites: int = 0
    comments: int = 0
    danmaku: int = 0
    shares: int = 0

    def as_dict(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in WEIGHTS}


@dataclass(frozen=True)
class RankInput:
    """排序函数能看到的全部东西。**只有公开字段**(S3):加字段之前先想清楚它能不能被买。"""

    video_id: int
    uploader_id: int
    zone: str
    published_at: datetime
    counts: Counts = field(default_factory=Counts)


def interaction(c: Counts) -> int:
    """互动分 = 播放 × 1 + 点赞 × 5 + 投币 × 10 + 收藏 × 8 + 评论 × 6 + 弹幕 × 2 + 分享 × 10"""
    return sum(getattr(c, k) * w for k, w in WEIGHTS.items())


def hours_since(published_at: datetime, now: datetime) -> float:
    """发布后的小时数(不会是负数)。"""
    return max(0.0, (now - published_at).total_seconds() / 3600)


def hot(score: int, hours: float) -> float:
    """热度 = 互动分 ÷ (发布后的小时数 + 2) ^ 1.5"""
    return score / (hours + DECAY_OFFSET_HOURS) ** DECAY_POWER


def recommend(hot_value: float, followed: bool, top_zone: bool) -> float:
    """推荐 = 热度 × (1 + 0.3 × 我关注了这个 UP 主 + 0.15 × 这是我近 30 天最常看的 3 个分区之一)。
    关掉个性化:调用方把两个布尔都传 False(两个加权都是 0)。"""
    return hot_value * (1 + FOLLOW_BONUS * bool(followed) + ZONE_BONUS * bool(top_zone))


def breakdown(inp: RankInput, now: datetime, *, followed: bool = False,
              top_zone: bool = False) -> dict:
    """一条视频的全部中间量。接口原样下发,客户端「为什么推荐」展示、任何人可以复算。"""
    score = interaction(inp.counts)
    hours = hours_since(inp.published_at, now)
    h = hot(score, hours)
    return {"counts": inp.counts.as_dict(), "interaction": score, "hours": hours, "hot": h,
            "followed": bool(followed), "top_zone": bool(top_zone),
            "recommend": recommend(h, followed, top_zone)}


def order_key(value: float, published_at: datetime, video_id: int) -> tuple:
    """分数高的在前;同分时新发布的在前;再同就按 id(保证结果确定,同一分钟内两次请求逐条相等)。"""
    return (-value, -published_at.timestamp(), -video_id)


def paginate_screens(items: Iterable, uploader_of: Callable, *, size: int = SCREEN_SIZE,
                     per_uploader: int = PER_UPLOADER_PER_SCREEN,
                     max_screens: int | None = None) -> list[list]:
    """按排好的顺序切屏:一屏 size 条,同一个 UP 主最多 per_uploader 个。

    超出的不丢,顺延到下一屏(保持原来的先后)。某一屏凑不满 size 条说明剩下的全是同几个 UP 主的。
    """
    pool = list(items)
    screens: list[list] = []
    while pool and (max_screens is None or len(screens) < max_screens):
        screen: list = []
        seen: dict = {}
        rest: list = []
        for it in pool:
            up = uploader_of(it)
            if len(screen) < size and seen.get(up, 0) < per_uploader:
                screen.append(it)
                seen[up] = seen.get(up, 0) + 1
            else:
                rest.append(it)
        screens.append(screen)
        pool = rest
    return screens


def watched_enough(position_ms: int, duration_ms: int) -> bool:
    """看过 = 播放进度 > 50%。"""
    return duration_ms > 0 and position_ms / duration_ms > WATCHED_RATIO
