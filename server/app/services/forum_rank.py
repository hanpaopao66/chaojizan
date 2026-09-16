"""论坛推荐与热门话题的排序公式(DEV-PROMPTS-41 §5.7)。**公开,纯函数。**

公式原文(和 docs/DEV-PROMPTS-41.md §5.7 的代码块逐字一致,tests/unit/test_forum_rank.py 对着文档比):

```text
互动分 E = 点赞人数 + 2 × 转发人数 + 2 × 引用人数 + 3 × 回复人数(都按人去重,只算发帖后 72 小时内)
推荐分 = (E + 1) ÷ (发帖后小时数 + 2)^1.5 × (1 + [我关注了作者]) × (1 + 0.5 × [帖子里有我近30天发过或点过赞的话题])
候选是 72 小时内的原帖(不含回复),作者没被我拉黑、也没拉黑我,不含我的屏蔽词;每屏 20 条,同一作者最多 2 条
关掉个性化后两个方括号都按 0 算
热门话题分数 = 近24小时用过这个话题的人数 + 2 × 近3小时用过的人数;近24小时至少 2 人用过才上榜,最多 20 个;运营隐藏的话题不上榜
```

为什么是纯函数、为什么输入这么少(§3.1 不收钱、§3.5 公开公式):

- 输入只有**公开的**东西 —— 四种互动在 72 小时窗口里按人去重的个数、发帖时间;个性化再加两个布尔
  (我关注了作者没有、帖子里有没有我最近用过的话题)。**没有任何付费、运营加权的入口**:
  RankInput 上加一个字段,单测就红;
- E 里加 1 再除:刚发出来、一个互动都没有的帖子分数不是 0,时间新就能排在前面 —— 不然
  新帖永远沉底,只有已经火的才更火;
- 「只算 72 小时内、同一个人每种互动只算一次」由取数那一层保证(forum_feed.window_counts
  从明细表按时间窗 COUNT DISTINCT),这里只管算。
"""
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

FORMULA = """互动分 E = 点赞人数 + 2 × 转发人数 + 2 × 引用人数 + 3 × 回复人数(都按人去重,只算发帖后 72 小时内)
推荐分 = (E + 1) ÷ (发帖后小时数 + 2)^1.5 × (1 + [我关注了作者]) × (1 + 0.5 × [帖子里有我近30天发过或点过赞的话题])
候选是 72 小时内的原帖(不含回复),作者没被我拉黑、也没拉黑我,不含我的屏蔽词;每屏 20 条,同一作者最多 2 条
关掉个性化后两个方括号都按 0 算
热门话题分数 = 近24小时用过这个话题的人数 + 2 × 近3小时用过的人数;近24小时至少 2 人用过才上榜,最多 20 个;运营隐藏的话题不上榜"""

#: 互动分 E 的权重(公式第一行):点赞 1、转发 2、引用 2、回复 3
WEIGHTS: dict[str, int] = {"likes": 1, "reposts": 2, "quotes": 2, "repliers": 3}
#: 只算发帖后这么多小时内的互动;候选也只取这么新的原帖
WINDOW_HOURS = 72
#: 推荐分 = (E + 1) ÷ (小时数 + DECAY_OFFSET_HOURS) ^ DECAY_POWER × …
E_OFFSET = 1
DECAY_OFFSET_HOURS = 2
DECAY_POWER = 1.5
#: 两个个性化加权:关注了作者 ×(1 + 1)、有我最近用过的话题 ×(1 + 0.5)
FOLLOW_BONUS = 1
TOPIC_BONUS = 0.5
#: 「我近 30 天发过或点过赞的话题」往回看几天
TOPIC_LOOKBACK_DAYS = 30
#: 一屏 20 条,同一作者最多 2 条
SCREEN_SIZE = 20
PER_AUTHOR_PER_SCREEN = 2
#: 热门话题:近 24 小时的人数 + 2 × 近 3 小时的人数;24 小时内至少 2 人才上榜,最多 20 个
TREND_WINDOW_HOURS = 24
TREND_RECENT_HOURS = 3
TREND_RECENT_WEIGHT = 2
TREND_MIN_AUTHORS = 2
TREND_MAX = 20

#: `/forum/v1/rank/formula` 原样返回的参数(§3.5:公式和参数全公开)
PARAMS: dict[str, float] = {
    "window_hours": WINDOW_HOURS,
    "like_weight": WEIGHTS["likes"],
    "repost_weight": WEIGHTS["reposts"],
    "quote_weight": WEIGHTS["quotes"],
    "reply_weight": WEIGHTS["repliers"],
    "e_offset": E_OFFSET,
    "decay_offset_hours": DECAY_OFFSET_HOURS,
    "decay_power": DECAY_POWER,
    "follow_bonus": FOLLOW_BONUS,
    "topic_bonus": TOPIC_BONUS,
    "topic_lookback_days": TOPIC_LOOKBACK_DAYS,
    "screen_size": SCREEN_SIZE,
    "per_author_per_screen": PER_AUTHOR_PER_SCREEN,
    "trend_window_hours": TREND_WINDOW_HOURS,
    "trend_recent_hours": TREND_RECENT_HOURS,
    "trend_recent_weight": TREND_RECENT_WEIGHT,
    "trend_min_authors": TREND_MIN_AUTHORS,
    "trend_max": TREND_MAX,
}


@dataclass(frozen=True)
class Counts:
    """一条帖子在 72 小时窗口里的四种互动(每种按人去重后的个数)。"""

    likes: int = 0
    reposts: int = 0
    quotes: int = 0
    repliers: int = 0

    def as_dict(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in WEIGHTS}


@dataclass(frozen=True)
class RankInput:
    """排序函数能看到的全部东西。**只有公开字段**(§3.1):加字段之前先想清楚它能不能被买。"""

    post_id: int
    author_id: int
    created_at: datetime
    counts: Counts = field(default_factory=Counts)


def interaction(c: Counts) -> int:
    """互动分 E = 点赞人数 + 2 × 转发人数 + 2 × 引用人数 + 3 × 回复人数"""
    return sum(getattr(c, k) * w for k, w in WEIGHTS.items())


def hours_since(created_at: datetime, now: datetime) -> float:
    """发帖后的小时数(不会是负数:时钟误差让发帖时间跑到未来时按 0 算)。"""
    return max(0.0, (now - created_at).total_seconds() / 3600)


def score(e: int, hours: float, *, followed: bool = False, topic: bool = False) -> float:
    """推荐分 = (E + 1) ÷ (发帖后小时数 + 2)^1.5 × (1 + [我关注了作者])
    × (1 + 0.5 × [帖子里有我近30天发过或点过赞的话题])。

    关掉个性化:调用方把两个布尔都传 False(两个方括号都按 0 算)。
    """
    base = (e + E_OFFSET) / (hours + DECAY_OFFSET_HOURS) ** DECAY_POWER
    return base * (1 + FOLLOW_BONUS * bool(followed)) * (1 + TOPIC_BONUS * bool(topic))


def breakdown(inp: RankInput, now: datetime, *, followed: bool = False,
              topic: bool = False) -> dict:
    """一条帖子的全部中间量。接口原样下发(§8.3 的 `rank`),任何人可以拿计算器复算。"""
    e = interaction(inp.counts)
    hours = hours_since(inp.created_at, now)
    return {"score": score(e, hours, followed=followed, topic=topic),
            "parts": {**inp.counts.as_dict(), "hours": hours, "e": e,
                      "following": bool(followed), "topic": bool(topic)},
            "why": why(inp.counts, e, hours, followed=followed, topic=topic)}


def why(c: Counts, e: int, hours: float, *, followed: bool, topic: bool) -> str:
    """「为什么推荐」:把公式里起作用的每一项用人话说成一句。"""
    bits = [f"近 {WINDOW_HOURS} 小时 {c.likes} 人点赞、{c.reposts} 人转发、"
            f"{c.quotes} 人引用、{c.repliers} 人回复(互动分 {e}),发帖 {hours:.1f} 小时"]
    if followed:
        bits.append(f"你关注了作者(× {1 + FOLLOW_BONUS:g})")
    if topic:
        bits.append(f"有你近 {TOPIC_LOOKBACK_DAYS} 天用过的话题(× {1 + TOPIC_BONUS:g})")
    return ";".join(bits)


def order_key(value: float, created_at: datetime, post_id: int) -> tuple:
    """分数高的在前;同分时新发的在前;再同就按 id(结果确定,同一分钟里两次请求逐条相等)。"""
    return (-value, -created_at.timestamp(), -post_id)


def paginate_screens(items: Iterable, author_of: Callable, *, size: int = SCREEN_SIZE,
                     per_author: int = PER_AUTHOR_PER_SCREEN,
                     max_screens: int | None = None,
                     capped: Callable | None = None,
                     cap_share: int = 100) -> list[list]:
    """按排好的顺序切屏:一屏 size 条,同一作者最多 per_author 条。

    超出的不丢,顺延到下一屏(保持原来的先后)。某一屏凑不满 size 条说明剩下的全是同几个人的。

    ## AI 内容的占比闸(#386)

    [capped] 判一条是不是"要限量的那类"(AI 号发的),[cap_share] 是它们最多占
    **一屏**的百分之几(后台 `ai_timeline_share`,缺省 80)。

    **按屏算,不按总数算。** 按总数算的话,第一屏可以全是机器人、第五屏全是真人,
    平均下来还是达标 —— 而人看到的就是第一屏。占比这件事只有"你这一眼看到的"才算数。

    `cap_share=0` 是"机器人不进时间线":这时候一屏里一条都放不下,
    **剩下的全是机器人时会切出一个空屏** —— 那就停在这里,不是无限循环
    (空屏往下顺延,顺延的还是同一批,`pool` 永远不变小)。这一条是这个函数里
    唯一会挂死整个请求的形状,所以特意写在这儿。
    """
    pool = list(items)
    screens: list[list] = []
    cap_n = size if capped is None else max(0, size * cap_share // 100)
    while pool and (max_screens is None or len(screens) < max_screens):
        screen: list = []
        seen: dict = {}
        n_capped = 0
        rest: list = []
        for it in pool:
            who = author_of(it)
            is_capped = capped is not None and capped(it)
            if (len(screen) < size and seen.get(who, 0) < per_author
                    and not (is_capped and n_capped >= cap_n)):
                screen.append(it)
                seen[who] = seen.get(who, 0) + 1
                if is_capped:
                    n_capped += 1
            else:
                rest.append(it)
        if not screen:
            # 剩下的全被闸拦着。再顺延一轮拦的还是同一批,pool 不会变小 ——
            # 这里不停下就是个死循环,整个请求挂在那儿不返回
            break
        screens.append(screen)
        pool = rest
    return screens


def trend_score(authors_24h: int, authors_3h: int) -> int:
    """热门话题分数 = 近24小时用过这个话题的人数 + 2 × 近3小时用过的人数。"""
    return authors_24h + TREND_RECENT_WEIGHT * authors_3h


def trending_enough(authors_24h: int) -> bool:
    """近 24 小时至少 2 个人用过才上榜(一个人自己刷不出热门话题)。"""
    return authors_24h >= TREND_MIN_AUTHORS
