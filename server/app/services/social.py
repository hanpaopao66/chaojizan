"""社交身份的判定都在这:用户名规则、隐私、拉黑、名片(DEV-PROMPTS-40 #340)。

其他模块(聊天、视频、通话)判「能不能看他的在线状态」「能不能拉他进群」
「能不能给他发私信」时一律调这里,不各自写一遍 —— 隐私规则写两份迟早会不一样。
"""
import hashlib
import re
import secrets
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (NOTIFY_DEFAULTS, PRIVACY_DEFAULTS, PRIVACY_VALUES, SocialBlock,
                      SocialContact, SocialProfile, User, UserRole)
from ..redis_client import get_redis

#: 能参与「消息」「视频」的账号角色(D1:用户端的顾客账号;机器人由 #355 加)
SOCIAL_ROLES = {UserRole.customer, UserRole.bot}

# ---------------- 用户名 ----------------

#: 5–32 位;字母开头;只能有字母、数字、下划线;不能以下划线结尾;不能连续两个下划线
_USERNAME_RE = re.compile(r"^[A-Za-z](?:[A-Za-z0-9]|_(?!_)){3,30}[A-Za-z0-9]$")

#: 整个名字等于这些的不能注册
_RESERVED_EXACT = {
    "admin", "administrator", "root", "system", "support", "service", "official",
    "help", "security", "staff", "moderator", "null", "undefined", "everyone",
    "all", "here", "botfather", "telegram", "bilibili", "douyin", "wechat",
    "notifications", "settings",
}
#: 名字里带这些的不能注册 —— 防止冒充平台和客服(原因代码 C108)
_RESERVED_PARTS = ("chaojizan", "superz", "super_z", "official", "admin", "kefu",
                   "guanfang")


def validate_username(name: str, *, is_bot: bool = False) -> str | None:
    """不合规时返回一句能直接给用户看的话;合规返回 None。"""
    if not name:
        return "用户名不能为空"
    if len(name) < 5:
        return "用户名至少 5 位"
    if len(name) > 32:
        return "用户名最多 32 位"
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        return "用户名只能用字母、数字和下划线"
    if not name[0].isalpha():
        return "用户名要以字母开头"
    if name.endswith("_"):
        return "用户名不能以下划线结尾"
    if "__" in name:
        return "用户名不能有连续两个下划线"
    if not _USERNAME_RE.fullmatch(name):
        return "用户名格式不对"
    low = name.lower()
    if low in _RESERVED_EXACT or any(p in low for p in _RESERVED_PARTS):
        return "这个用户名是保留的,换一个吧"
    if is_bot and not low.endswith("bot"):
        return "机器人的用户名必须以 bot 结尾"
    if not is_bot and low.endswith("bot"):
        return "以 bot 结尾的用户名只给机器人用"
    return None


# ---------------- 资料 ----------------

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def new_public_id(n: int = 12) -> str:
    return "".join(secrets.choice(_B58) for _ in range(n))


async def ensure_profile(db: AsyncSession, user_id: int) -> SocialProfile:
    """取资料,没有就建一行。并发两个请求同时建时靠主键冲突兜住,不会建出两行。"""
    p = await db.get(SocialProfile, user_id)
    if p is not None:
        return p
    await db.execute(
        insert(SocialProfile)
        .values(user_id=user_id, public_id=new_public_id(), privacy={}, notify={},
                bio="", personalize_video=True, coins=0, user_pts=0)
        .on_conflict_do_nothing(index_elements=["user_id"]))
    await db.flush()
    p = await db.get(SocialProfile, user_id)
    assert p is not None
    return p


def privacy_of(p: SocialProfile | None) -> dict[str, str]:
    out = dict(PRIVACY_DEFAULTS)
    for k, v in ((p.privacy if p else None) or {}).items():
        if k in out and v in PRIVACY_VALUES:
            out[k] = v
    return out


def notify_of(p: SocialProfile | None) -> dict[str, object]:
    out = dict(NOTIFY_DEFAULTS)
    for k, v in ((p.notify if p else None) or {}).items():
        if k in out and isinstance(v, bool):
            out[k] = v
    return out


def display_name(user: User) -> str:
    """没填名字的人显示「用户」+ 4 位编码。编码从 user id 算,**不用手机号**(S2)。"""
    if user.name and user.name.strip():
        return user.name.strip()
    code = hashlib.sha256(f"superz-name:{user.id}".encode()).hexdigest()[:4].upper()
    return f"用户{code}"


# ---------------- 关系 ----------------

async def contact_ids_of(db: AsyncSession, owner_id: int) -> set[int]:
    rows = await db.scalars(select(SocialContact.contact_id)
                            .where(SocialContact.owner_id == owner_id))
    return set(rows)


async def is_contact(db: AsyncSession, owner_id: int, other_id: int) -> bool:
    """owner 的联系人里有没有 other(单向:我加了你,不代表你加了我)。"""
    return await db.get(SocialContact, (owner_id, other_id)) is not None


async def blocked_between(db: AsyncSession, a: int, b: int) -> bool:
    """任意一方拉黑了另一方(S7 双向隔离)。"""
    if a == b:
        return False
    row = await db.scalar(select(SocialBlock.user_id).where(or_(
        (SocialBlock.user_id == a) & (SocialBlock.blocked_id == b),
        (SocialBlock.user_id == b) & (SocialBlock.blocked_id == a))).limit(1))
    return row is not None


async def allowed(db: AsyncSession, owner: SocialProfile | None, owner_id: int,
                  viewer_id: int, field: str) -> bool:
    """owner 的隐私项 field 是否允许 viewer。自己看自己永远允许;拉黑一律不允许。"""
    if owner_id == viewer_id:
        return True
    if await blocked_between(db, owner_id, viewer_id):
        return False
    rule = privacy_of(owner)[field]
    if rule == "everyone":
        return True
    if rule == "nobody":
        return False
    return await is_contact(db, owner_id, viewer_id)


def rule_allows(rule: str, *, same: bool, viewer_is_contact: bool, blocked: bool) -> bool:
    """[allowed] 的纯函数版本(批量构建名片用,单测锁真值表)。"""
    if same:
        return True
    if blocked:
        return False
    if rule == "everyone":
        return True
    if rule == "nobody":
        return False
    return viewer_is_contact


# ---------------- 在线状态 ----------------

ONLINE_KEY = "online:{}"


async def online_map(user_ids: Iterable[int]) -> dict[int, bool]:
    """实时网关连着前台连接的用户在 Redis 里有一个带 TTL 的键(见 realtime/hub.py)。"""
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    try:
        vals = await get_redis().mget([ONLINE_KEY.format(i) for i in ids])
    except Exception:
        return {i: False for i in ids}
    return {i: bool(v) for i, v in zip(ids, vals)}


def last_seen_view(at: datetime | None, online: bool, visible: bool,
                   now: datetime | None = None) -> dict:
    """对别人显示的在线状态。

    - 允许看:在线 / 精确的最后上线时间;
    - 不允许看:只给一个大概 —— 最近(3 天内)/ 一周内 / 一月内 / 很久以前。
      **在线也显示成「最近」**,否则「隐藏最后上线」等于没隐藏(和 Telegram 一样)。
    """
    now = now or datetime.now(timezone.utc)
    if visible:
        return {"online": online,
                "at": None if online or at is None else at.isoformat(),
                "approx": None if online or at is not None else "long"}
    if online or (at is not None and now - at <= timedelta(days=3)):
        approx = "recently"
    elif at is not None and now - at <= timedelta(days=7):
        approx = "week"
    elif at is not None and now - at <= timedelta(days=30):
        approx = "month"
    else:
        approx = "long"
    return {"online": False, "at": None, "approx": approx}


# ---------------- 名片 ----------------

async def user_cards(db: AsyncSession, viewer_id: int, ids: Iterable[int]) -> dict[int, dict]:
    """一批人的名片(按 viewer 的视角过滤隐私)。**永远不含手机号**(S2)。

    批量查:用户、资料、「对方把我加成联系人没有」、「我把对方加成联系人没有」、拉黑、在线,
    共 6 条查询,不随人数增长。
    """
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))}
    profiles = {p.user_id: p for p in await db.scalars(
        select(SocialProfile).where(SocialProfile.user_id.in_(ids)))}
    # 对方(owner)的联系人里有我吗 —— 对方隐私设成「联系人」时用
    they_have_me = set(await db.scalars(select(SocialContact.owner_id).where(
        SocialContact.owner_id.in_(ids), SocialContact.contact_id == viewer_id)))
    mine = {c.contact_id: c for c in await db.scalars(select(SocialContact).where(
        SocialContact.owner_id == viewer_id, SocialContact.contact_id.in_(ids)))}
    blocks = (await db.execute(select(SocialBlock.user_id, SocialBlock.blocked_id).where(or_(
        (SocialBlock.user_id == viewer_id) & SocialBlock.blocked_id.in_(ids),
        (SocialBlock.blocked_id == viewer_id) & SocialBlock.user_id.in_(ids))))).all()
    i_blocked = {b for a, b in blocks if a == viewer_id}
    blocked_me = {a for a, b in blocks if b == viewer_id}
    online = await online_map(ids)
    # 机器人的简介存在 bots 表里(开发者后台填的 about),它没有自己的社交签名:资料页拿它当签名显示
    bot_ids = [uid for uid in ids if (x := users.get(uid)) is not None and x.role == UserRole.bot]
    bot_about: dict[int, str] = {}
    if bot_ids:
        from ..models import Bot
        bot_about = {uid: about or "" for uid, about in (await db.execute(
            select(Bot.user_id, Bot.about).where(Bot.user_id.in_(bot_ids)))).all()}
    viewer_profile = profiles.get(viewer_id) or await db.get(SocialProfile, viewer_id)
    # 互惠(和 Telegram 一样):我自己把最后上线设成「没有人」,我也看不到别人的精确时间
    viewer_hides = privacy_of(viewer_profile)["last_seen"] == "nobody"
    now = datetime.now(timezone.utc)
    out: dict[int, dict] = {}
    for uid in ids:
        u = users.get(uid)
        if u is None:
            continue
        p = profiles.get(uid)
        pv = privacy_of(p)
        same = uid == viewer_id
        blocked = uid in i_blocked or uid in blocked_me

        def ok(field: str) -> bool:
            return rule_allows(pv[field], same=same, viewer_is_contact=uid in they_have_me,
                               blocked=blocked)

        seen_ok = ok("last_seen") and (same or not viewer_hides)
        # 对方拉黑了我:头像和在线状态都不给(S7),名字和用户名照旧(否则连是谁都认不出)
        avatar_ok = ok("avatar") and uid not in blocked_me
        c = mine.get(uid)
        out[uid] = {
            "id": uid,
            "name": display_name(u),
            "username": p.username if p else None,
            "avatar": (u.avatar_url or "") if avatar_ok else "",
            "bio": (p.bio if p else "") or bot_about.get(uid, ""),
            "public_id": p.public_id if p else None,
            "last_seen": last_seen_view(p.last_seen_at if p else None,
                                        online.get(uid, False) and uid not in blocked_me,
                                        seen_ok and uid not in blocked_me, now),
            "is_contact": c is not None,
            "contact_alias": c.alias if c else "",
            "blocked": uid in i_blocked,
            "is_bot": u.role == UserRole.bot,
            "is_self": same,
        }
    return out


async def user_card(db: AsyncSession, viewer_id: int, user_id: int) -> dict | None:
    return (await user_cards(db, viewer_id, [user_id])).get(user_id)
