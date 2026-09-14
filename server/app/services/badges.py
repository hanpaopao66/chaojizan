"""用户的标签和勋章。

- **标签**:用户自己写,最多 5 个、每个 1–8 个字,过屏蔽词,不能重复。和昵称、签名同一级别的公开信息;
- **勋章**:平台按写在明处的条件自动发。条件只用库里本来就有的记录算(下面每一枚都写了按哪份记录算);
- **隐藏**:整组标签、每一枚勋章都能对别人隐藏。隐藏之后别人看不到,自己看得到(标「已隐藏」)。

## 勋章是现算的,库里不存「谁得了哪枚」

发放用「查的时候现算」,不用「事件触发写表」。事件触发要在每一个会改变条件的地方埋钩子:
订单变成「已完成」就有顾客确认收货、清扫任务自动确认(送达超时、自取超时)、商家核销取餐码、后台先行赔付
好几条路;评价会被申诉改判隐藏、图片会被审核移除;视频有过审、定时发布、下架、申诉改判、设私密、删除……
漏一处,勋章就静默地发错或者收不回来,不报错也没人发现。现算只有一处判据:[Badge.test] 读 [Facts],Facts 从源表数出来。
条件不再满足(视频下架、评价被隐藏)勋章自然就没了,不需要「收回」这个动作;
也因为不存,平台没有「手动给某人发一枚」的路。

## 性能

只有单人资料卡(GET /social/v1/users/{id} 这类,见 services/social.user_card)和 UP 主空间带勋章,
会话列表、成员列表、联系人列表那些批量名片不带,不为它多查。

算一个人是一条 SQL:四个子查询都走索引(reviews.customer_id 的索引是迁移 0134 加的),
而且都带 LIMIT —— 数到门槛就停,下过一千单的人也只数 10 行。
结果在 Redis 里缓存 [CACHE_SECONDS] 秒,别人看你的资料最多晚这么久看到新勋章;
你自己打开自己的资料页、「标签和勋章」页时总是现算,顺手刷新缓存。

## 判据和公示是同一份

透明中心「勋章」那一栏(GET /transparency/badges)读的是这里的 [BADGES];条件那句话里的数字从下面的常量格出来,
[Badge.test] 和 [facts_sql] 用的也是这几个常量。改一个数,公示和判据一起变 —— tests/unit/test_badges.py 钉着。
"""
import json
import logging
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import SocialProfile, User, UserRole
from ..redis_client import get_redis

logger = logging.getLogger("superz.badges")

BJ = timezone(timedelta(hours=8))

# ---------------- 门槛(改这里,公示和判据一起变)----------------

#: 早期用户:北京时间这一刻**之前**注册的,也就是 2026 年 12 月 31 日当天及以前。
#: 按日期不按注册序号:序号要数「你前面有多少人」,而且会把注册量带出去;日期谁都能对着自己的加入时间核
EARLY_BEFORE = datetime(2027, 1, 1, tzinfo=BJ)
#: 带图评价达人:至少几条带图评价
PHOTO_REVIEWS_MIN = 5
#: 老顾客:至少完成几单
COMPLETED_ORDERS_MIN = 10

#: 标签:最多几个、每个最多几个字
TAGS_MAX = 5
TAG_MAX_LEN = 8

#: 别人看到的勋章最多晚这么久(秒)。实际还要压在 PUBLIC_CACHE_MAX_SECONDS 下面 ——
#: 本地和 CI 把它设成 0,e2e「造完数据马上看」就不会看到旧的
CACHE_SECONDS = 600

_LAST_EARLY_DAY = EARLY_BEFORE - timedelta(days=1)
EARLY_TEXT = f"{_LAST_EARLY_DAY.year} 年 {_LAST_EARLY_DAY.month} 月 {_LAST_EARLY_DAY.day} 日"

SOURCE_URL = "https://github.com/hanpaopao66/chaojizan/blob/main/server/app/services/badges.py"


@dataclass(frozen=True)
class Facts:
    """算勋章用的几个数,从源表数出来(见 [facts_sql])。计数数到门槛就停,所以最大就是门槛。"""

    registered_at: datetime | None = None
    real_name: bool = False
    public_videos: int = 0
    photo_reviews: int = 0
    completed_orders: int = 0


@dataclass(frozen=True)
class Badge:
    key: str
    name: str
    #: 一个汉字,客户端画在小方块里(不引图片资源)
    icon: str
    #: 一句话条件:资料页上点开勋章、透明中心,显示的都是这一句
    condition: str
    #: 按库里哪份记录算
    counts: str
    #: 哪些不算
    excludes: str
    #: 判据。只读 Facts,不查库、不看别的
    test: Callable[[Facts], bool]
    #: 机器可读的门槛(透明中心原样给出,e2e 按它造数据)
    min_count: int | None = None
    before: datetime | None = None


BADGES: tuple[Badge, ...] = (
    Badge(
        key="real_name", name="实名认证", icon="实",
        condition="完成了实名认证(姓名和身份证号经过核验)",
        counts="实名认证记录:核验通过才会有这一条",
        excludes="资料页上只显示这个标记,不显示姓名和证号",
        test=lambda f: f.real_name),
    Badge(
        key="early", name="早期用户", icon="早",
        condition=f"在 {EARLY_TEXT}(北京时间)及以前注册",
        counts="账号的注册时间",
        excludes="注销后重新注册的账号,按新的注册时间算",
        test=lambda f: f.registered_at is not None and f.registered_at < EARLY_BEFORE,
        before=EARLY_BEFORE),
    Badge(
        key="uploader", name="UP 主", icon="投",
        condition="有至少 1 个审核通过、正在公开发布的视频",
        counts="视频稿件:已发布、公开、没有删除 —— 和 UP 主空间里「投稿」数的是同一批",
        excludes="审核中、没通过、被下架、设为私密、已删除的稿件",
        test=lambda f: f.public_videos >= 1, min_count=1),
    Badge(
        key="photo_reviewer", name="带图评价达人", icon="图",
        condition=f"写过至少 {PHOTO_REVIEWS_MIN} 条带图的订单评价",
        counts="订单评价:评价时附了图片",
        excludes="图片被审核移除的、被隐藏的(商家申诉成立)、带刷评嫌疑标记的评价",
        test=lambda f: f.photo_reviews >= PHOTO_REVIEWS_MIN, min_count=PHOTO_REVIEWS_MIN),
    Badge(
        key="regular", name="老顾客", icon="老",
        condition=f"完成过至少 {COMPLETED_ORDERS_MIN} 单外卖或跑腿",
        counts="订单:状态是「已完成」",
        excludes="加菜的追加单、钱全部退回的单、被平台确认为刷单的单;住宿和团购券暂不算",
        test=lambda f: f.completed_orders >= COMPLETED_ORDERS_MIN,
        min_count=COMPLETED_ORDERS_MIN),
)
BADGE_KEYS: tuple[str, ...] = tuple(b.key for b in BADGES)
_BY_KEY = {b.key: b for b in BADGES}


def earned_keys(f: Facts) -> list[str]:
    """拿到了哪几枚(按 BADGES 的顺序)。纯函数。"""
    return [b.key for b in BADGES if b.test(f)]


# ---------------- 从源表数 ----------------

def facts_sql() -> str:
    """数 [Facts] 的那条 SQL,一批人一次。

    门槛常量直接格进 SQL(模块里的整数,不是用户输入),绑定参数只有 :ids 一个。
    状态、空串这类「一个取值占了大半」的比较写成字面量,规划器拿得到真实统计 ——
    写成绑定参数的话,预备语句第 6 次起会切成通用计划、一头扎进 status 索引(见 models.NOT_APPEND_ORDER)。
    """
    return f"""
SELECT u.id, u.created_at,
  EXISTS (SELECT 1 FROM user_identities i WHERE i.user_id = u.id) AS real_name,
  (SELECT count(*) FROM (
     SELECT 1 FROM videos v
      WHERE v.uploader_id = u.id AND v.status = 'published' AND v.visibility = 'public'
        AND v.deleted_at IS NULL AND v.published_at IS NOT NULL
      LIMIT 1) s) AS public_videos,
  (SELECT count(*) FROM (
     SELECT 1 FROM reviews r
      WHERE r.customer_id = u.id AND NOT r.hidden AND NOT r.flagged
        AND (CASE WHEN jsonb_typeof(r.image_urls) = 'array'
                  THEN jsonb_array_length(r.image_urls) ELSE 0 END) > 0
      LIMIT {PHOTO_REVIEWS_MIN}) s) AS photo_reviews,
  (SELECT count(*) FROM (
     SELECT 1 FROM orders o
      WHERE o.customer_id = u.id AND o.status = 'completed' AND o.parent_order_no = ''
        AND o.refund_cents < o.total_cents
        AND coalesce(o.risk_flags->>'status', '') <> 'confirmed'
      LIMIT {COMPLETED_ORDERS_MIN}) s) AS completed_orders
FROM users u
WHERE u.id = ANY(:ids)
"""


async def facts_for(db: AsyncSession, ids: Iterable[int]) -> dict[int, Facts]:
    ids = [int(i) for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    rows = (await db.execute(text(facts_sql()), {"ids": ids})).all()
    return {r.id: Facts(registered_at=r.created_at, real_name=bool(r.real_name),
                        public_videos=int(r.public_videos or 0),
                        photo_reviews=int(r.photo_reviews or 0),
                        completed_orders=int(r.completed_orders or 0))
            for r in rows}


# ---------------- 缓存 ----------------

_CACHE_KEY = "badges:v1:{}"


def cache_ttl() -> int:
    return int(max(0.0, min(float(CACHE_SECONDS), float(settings.public_cache_max_seconds))))


async def earned_for(db: AsyncSession, user_id: int, *, fresh: bool = False) -> list[str]:
    """一个人拿到了哪几枚。fresh=True(本人在看)跳过缓存现算,并刷新缓存。

    Redis 不可用时每次现算:慢一点,但不会因为缓存挂了就把勋章显示错。
    """
    ttl = cache_ttl()
    key = _CACHE_KEY.format(user_id)
    if ttl and not fresh:
        try:
            hit = await get_redis().get(key)
        except Exception as exc:  # noqa: BLE001 —— 缓存挂了照样能算
            logger.debug("勋章缓存读失败,现算: %s", exc)
            hit = None
        if hit is not None:
            try:
                got = json.loads(hit)
            except ValueError:
                got = None
            if isinstance(got, list):
                return [k for k in BADGE_KEYS if k in got]
    facts = (await facts_for(db, [user_id])).get(user_id)
    keys = earned_keys(facts) if facts is not None else []
    if ttl:
        try:
            await get_redis().set(key, json.dumps(keys), ex=ttl)
        except Exception as exc:  # noqa: BLE001
            logger.debug("勋章缓存写失败: %s", exc)
    return keys


# ---------------- 给人看的形状 ----------------

def badge_out(b: Badge, **extra) -> dict:
    return {"key": b.key, "name": b.name, "icon": b.icon, "condition": b.condition, **extra}


def _tags_of(p: SocialProfile | None) -> list[str]:
    return [t for t in (p.tags if p is not None else None) or [] if isinstance(t, str) and t]


def _hidden_of(p: SocialProfile | None) -> set[str]:
    return {k for k in (p.badges_hidden if p is not None else None) or [] if k in _BY_KEY}


def empty_view() -> dict:
    return {"tags": [], "tags_hidden": False, "badges": []}


def card_view(p: SocialProfile | None, earned: Iterable[str], *, is_self: bool) -> dict:
    """名片上的标签和勋章(纯函数)。

    - 别人看:隐藏了的直接没有 —— 和「没有」长得一模一样,看不出你藏了什么;
    - 自己看:都在,隐藏了的标 `tags_hidden` / `hidden`,客户端写「已隐藏」。
    """
    got = set(earned)
    tags = _tags_of(p)
    tags_hidden = bool(p.tags_hidden) if p is not None else False
    hidden = _hidden_of(p)
    if is_self:
        return {"tags": tags, "tags_hidden": tags_hidden,
                "badges": [badge_out(b, hidden=b.key in hidden) for b in BADGES if b.key in got]}
    return {"tags": [] if tags_hidden else tags, "tags_hidden": False,
            "badges": [badge_out(b, hidden=False) for b in BADGES
                       if b.key in got and b.key not in hidden]}


async def tags_badges_for(db: AsyncSession, user_id: int, viewer_id: int | None) -> dict:
    """资料卡 / UP 主空间用:一个人的标签和勋章,按 viewer 的视角过滤。viewer_id=None 是没登录的人。

    只给用户端账号:机器人没有订单也没有实名,注册时间却会让它白拿「早期用户」;
    已注销的账号什么都不显示(注销时标签已经清掉,见 services/chat_purge.py)。
    """
    u = await db.get(User, user_id)
    if u is None or u.is_deleted or u.role != UserRole.customer:
        return empty_view()
    p = await db.get(SocialProfile, user_id)
    is_self = viewer_id is not None and viewer_id == user_id
    earned = await earned_for(db, user_id, fresh=is_self)
    return card_view(p, earned, is_self=is_self)


async def settings_view(db: AsyncSession, user: User, p: SocialProfile) -> dict:
    """「标签和勋章」设置页:全部勋章都列出来(拿没拿到、隐没隐藏),条件一起给。总是现算。"""
    earned = set(await earned_for(db, user.id, fresh=True))
    hidden = _hidden_of(p)
    return {
        "tags": _tags_of(p),
        "tags_hidden": bool(p.tags_hidden),
        "tags_max": TAGS_MAX,
        "tag_max_len": TAG_MAX_LEN,
        "badges": [badge_out(b, earned=b.key in earned, hidden=b.key in hidden) for b in BADGES],
    }


# ---------------- 标签 ----------------

#: 标签里不能出现的:冒充平台、客服,或者看着像平台发的标志。
#: 标签和勋章挨着显示 —— 有人把「实名认证」写成标签,别人分不出哪个是平台核验过的
_TAG_RESERVED_PARTS = ("官方", "认证", "实名", "勋章", "客服", "超级赞", "管理员",
                       "chaojizan", "superz", "official", "admin", "kefu", "guanfang")
_SQUASH = re.compile(r"\s+")


def _squash(s: str) -> str:
    return _SQUASH.sub("", s).casefold()


_BADGE_NAMES = {_squash(b.name) for b in BADGES}


def normalize_tags(raw: object) -> tuple[list[str], str | None]:
    """规整并校验一组标签。返回(规整后的标签, 问题);问题是一句能直接给用户看的话。

    规整:去掉首尾空白,中间连续的空白并成一个空格。重复按不分大小写比。
    屏蔽词要查库,不在这里(见 routers/badges.py)。
    """
    if not isinstance(raw, list):
        return [], "标签格式不对"
    if len(raw) > TAGS_MAX:
        return [], f"标签最多 {TAGS_MAX} 个"
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        if not isinstance(x, str):
            return [], "标签格式不对"
        t = " ".join(x.split())
        if not t:
            return [], "标签不能是空的"
        if any(unicodedata.category(c).startswith("C") for c in t):
            return [], "标签里有不能显示的字符"
        if len(t) > TAG_MAX_LEN:
            return [], f"每个标签最多 {TAG_MAX_LEN} 个字:「{t}」"
        low = t.casefold()
        if low in seen:
            return [], f"标签不能重复:「{t}」"
        sq = _squash(t)
        if sq in _BADGE_NAMES or any(p in sq for p in _TAG_RESERVED_PARTS):
            return [], f"「{t}」容易被当成平台发的标志,换一个吧"
        seen.add(low)
        out.append(t)
    return out, None


# ---------------- 公示 ----------------

def public_spec() -> dict:
    """透明中心「勋章」那一栏。**直接读 BADGES 和上面的常量,不另写一份。**"""
    return {
        "badges": [{
            "key": b.key, "name": b.name, "icon": b.icon, "condition": b.condition,
            "counts": b.counts, "excludes": b.excludes,
            "min_count": b.min_count,
            "before": b.before.isoformat() if b.before else None,
        } for b in BADGES],
        "tags": {
            "max": TAGS_MAX,
            "max_len": TAG_MAX_LEN,
            "rules": [
                f"用户自己写,最多 {TAGS_MAX} 个,每个 1–{TAG_MAX_LEN} 个字,不能重复",
                "要过平台的屏蔽词;不能用「官方」「认证」「客服」这类容易被当成平台标志的词,也不能和勋章同名",
            ],
        },
        "visibility": ("标签和勋章跟昵称、签名一样,别人在你的资料页和 UP 主空间里都看得到。"
                       "整组标签、每一枚勋章都能在「消息设置 → 标签和勋章」里隐藏,隐藏之后只有你自己看得到;"
                       "别人看到的和「没有」一样,看不出你藏了什么。"),
        "how": (f"系统里不存「谁得了哪枚」:有人打开资料页时,按上面的条件从订单、评价、稿件、实名记录现数,"
                f"结果最多缓存 {CACHE_SECONDS // 60} 分钟;本人打开自己的资料时总是现数。"
                "条件不再满足(视频下架、评价被隐藏、钱全部退回),勋章就不再显示。"),
        "never": [
            "勋章不卖、不能申请,也没有「平台手动发给某人」的入口",
            "勋章不带任何优惠,不参与排序、派单和推荐,只是资料页上的一个标记",
        ],
        "cache_minutes": CACHE_SECONDS // 60,
        "source_url": SOURCE_URL,
    }
