"""消息中心:公告 + 本人触达记录 + 已读水位。商家和骑手共用一套。

## 为什么抽出来而不是各写一份

商家侧先有的这套(routers/merchants.py),骑手侧要的是同一件事:
"平台跟我说过什么话,哪些我还没看"。复制一份的代价不是多几十行,
是**两份会分叉** —— 未读口径、水位 key、订单类排除规则,
改一边忘一边,最后表现成"商家端未读清零了、骑手端还挂着 3"。

## 两个角色的差别只有"哪些算订单类"

订单类推送**不进消息中心**:订单页本身就是它们的家。一个日 300 单的店
配好推送后,消息中心第一页会全是"新订单来了"。

但同一个词对两端含义相反 —— "骑手"对商家是订单动态,对骑手是自己;
"配送异常"对商家是订单动态,对骑手可能是要他处理的事。所以排除词
**按角色分开列**,而不是共用一张表。

排除按标题关键词做:push 的标题是我们自己写死的常量(services/push.py),
不是用户输入,匹配是稳定的。

## 已读水位丢了怎么办

水位存 Redis,而 Redis 没有持久化卷 —— 整体丢失是可能的。丢了**不能**
退化成"未读 = 有史以来全部推送",那会给用户一个"新消息 8342"的徽标,
唯一的效果是他从此再也不点。所以没有水位时只看最近 7 天。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

#: 已读水位:一人一条时间戳。key 里带角色 —— 同一手机号可以既是商家
#: 又是骑手(users 表按 phone+role 建的唯一键),水位不能互相覆盖
_READ_KEY = "msg:read:{role}:{user_id}"

#: 没有水位时(新用户 / Redis 重建)只看最近这些天
FALLBACK_DAYS = 7


class _Rules:
    __slots__ = ("exclude", "categories")

    def __init__(self, exclude: tuple[str, ...],
                 categories: dict[str, tuple[str, ...]]):
        self.exclude = exclude
        self.categories = categories


ROLE_RULES: dict[str, _Rules] = {
    "merchant": _Rules(
        exclude=("订单", "新单", "催单", "骑手", "配送", "送达",
                 "售后", "退款", "取餐"),
        categories={"review": ("评价", "回复", "点评")},
    ),
    # 骑手侧的排除词短得多,而这是**故意**的:
    # "申诉成立""提现已打款""极端天气,注意安全""装备已发放"
    # 恰恰是骑手最该看到的几条,它们不是订单动态。
    # 照抄商家那张表的话,"极端天气"里的安全提醒会因为
    # 没有匹配词侥幸留下,而"申诉成立"会活下来纯属运气 —— 不能靠运气
    "rider": _Rules(
        exclude=("新单", "催单", "取餐", "派了一单", "等待接单",
                 "改派", "订单已取消", "订单地址", "配送地址"),
        categories={
            "money": ("提现", "打款", "收入", "结算", "补偿"),
            "safety": ("天气", "安全", "事故", "疲劳", "保险"),
            "appeal": ("申诉",),
        },
    ),
}


def rules(role: str) -> _Rules:
    return ROLE_RULES[role]


def message_filters(role: str):
    """SQL 层过滤条件(排除订单类)。**必须在 SQL 里做**:
    在 Python 里对取回的一页做 filter,会出现"这一页恰好全被过滤掉 →
    客户端拿到空列表 → 没有游标可以继续翻"的死局。"""
    from ..models import PushLog
    return [PushLog.title.notlike(f"%{kw}%") for kw in rules(role).exclude]


def category_filters(role: str, category: str):
    """按分类过滤。分类同样下推 SQL,理由同上。

    未知分类返回空条件而不是报错 —— 客户端版本比服务端新时,
    宁可多给几条也不要给一个 422。
    """
    from ..models import PushLog
    from sqlalchemy import or_

    kws = rules(role).categories.get(category)
    if kws:
        return [or_(*[PushLog.title.like(f"%{k}%") for k in kws])]
    if category == "system":
        # 系统 = 不属于任何已命名分类的那些
        named = [k for kws_ in rules(role).categories.values() for k in kws_]
        return [PushLog.title.notlike(f"%{k}%") for k in named]
    return []


def classify(role: str, title: str) -> str:
    """按标题归类;都不匹配归系统。"""
    for name, kws in rules(role).categories.items():
        if any(k in title for k in kws):
            return name
    return "system"


async def unread_since(role: str, user_id: int) -> datetime:
    """未读统计的起点:有水位用水位,没有就退回最近 N 天。
    Redis 故障时同样退回 —— 未读数偏大可以忍,首屏 500 不行。"""
    from ..redis_client import get_redis

    fallback = datetime.now(timezone.utc) - timedelta(days=FALLBACK_DAYS)
    try:
        raw = await get_redis().get(_READ_KEY.format(role=role,
                                                     user_id=user_id))
    except Exception:
        return fallback
    if not raw:
        return fallback
    try:
        return datetime.fromisoformat(
            raw.decode() if isinstance(raw, bytes) else raw)
    except ValueError:
        return fallback


async def unread_count(db, role: str, user_id: int) -> int:
    from ..models import PushLog

    since = await unread_since(role, user_id)
    return await db.scalar(
        select(func.count(PushLog.id)).where(
            PushLog.user_id == user_id,
            PushLog.created_at > since,
            *message_filters(role))) or 0


async def mark_read(role: str, user_id: int) -> dict:
    """记已读水位到当前时刻。Redis 挂了不报错 ——
    看消息这个动作本身成功了,未读数下次再对齐就是。"""
    from ..redis_client import get_redis

    try:
        await get_redis().set(_READ_KEY.format(role=role, user_id=user_id),
                              datetime.now(timezone.utc).isoformat())
    except Exception:
        return {"ok": False, "reason": "缓存暂时不可用,未读数稍后自动对齐"}
    return {"ok": True}


async def fetch(db, role: str, user_id: int, *, category: str | None = None,
                before: int | None = None, page_size: int = 50) -> dict:
    """消息中心一页:置顶当前生效的公告 + 本人触达记录 + 未读数。"""
    from sqlalchemy import or_

    from ..models import Announcement, PushLog

    now = datetime.now(timezone.utc)
    ann_rows = await db.scalars(
        select(Announcement).where(
            Announcement.is_active.is_(True),
            Announcement.audience.in_([role, "all"]),
            or_(Announcement.starts_at.is_(None),
                Announcement.starts_at <= now),
            or_(Announcement.ends_at.is_(None), Announcement.ends_at >= now),
        ).order_by(Announcement.created_at.desc()).limit(10))
    announcements = [{"id": a.id, "title": a.title, "content": a.content,
                      "created_at": a.created_at} for a in ann_rows]

    stmt = select(PushLog).where(PushLog.user_id == user_id,
                                 *message_filters(role))
    if category:
        stmt = stmt.where(*category_filters(role, category))
    if before is not None:
        stmt = stmt.where(PushLog.id < before)
    rows = (await db.scalars(
        stmt.order_by(PushLog.id.desc()).limit(page_size))).all()

    return {
        "announcements": announcements,
        "messages": [{"id": r.id, "kind": classify(role, r.title),
                      "title": r.title, "content": r.content,
                      "created_at": r.created_at} for r in rows],
        "unread": await unread_count(db, role, user_id),
        "page_size": page_size,
    }
