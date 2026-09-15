"""社交身份的判定都在这:用户名规则、隐私、拉黑、名片(DEV-PROMPTS-40 #340)。

其他模块(聊天、视频、通话)判「能不能看他的在线状态」「能不能拉他进群」
「能不能给他发私信」时一律调这里,不各自写一遍 —— 隐私规则写两份迟早会不一样。
"""
import hashlib
import re
import secrets
from collections.abc import Iterable
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (NOTIFY_DEFAULTS, PRIVACY_DEFAULTS, PRIVACY_VALUES, SocialBlock,
                      SocialContact, SocialProfile, User, Username, UserRole)
from ..models_social import UsernameHold
from ..redis_client import get_redis

#: 能参与「消息」「视频」的账号角色(D1:用户端的顾客账号;机器人由 #355 加)
SOCIAL_ROLES = {UserRole.customer, UserRole.bot}

# ---------------- 用户名(界面上叫「超级赞号」) ----------------

#: 长度范围。客户端「超级赞号」页的规则说明照这两个数写(tests/unit/test_custom_id.py 对着查)
USERNAME_MIN, USERNAME_MAX = 5, 32

#: 5–32 位;字母开头;只能有字母、数字、下划线;不能以下划线结尾;不能连续两个下划线
_USERNAME_RE = re.compile(r"^[A-Za-z](?:[A-Za-z0-9]|_(?!_)){3,30}[A-Za-z0-9]$")

#: 整个名字等于这些的不能注册
_RESERVED_EXACT = {
    "admin", "administrator", "root", "system", "support", "service", "official",
    "help", "security", "staff", "moderator", "null", "undefined", "everyone",
    "all", "here", "botfather", "telegram", "bilibili", "douyin", "wechat",
    "notifications", "settings",
}
#: 名字里带这些的不能注册 —— 防止冒充平台和客服(原因代码 C108)。
#: guanjia:官方的机器人管家 @guanjia_bot(services/bot_manager.py)在对话里发 token 查看按钮,
#: 冒充它的机器人是骗 token 最顺手的办法
_RESERVED_PARTS = ("chaojizan", "superz", "super_z", "official", "admin", "kefu",
                   "guanfang", "guanjia")


def validate_username(name: str, *, is_bot: bool = False, noun: str = "用户名",
                      reserved_ok: bool = False) -> str | None:
    """不合规时返回一句能直接给用户看的话;合规返回 None。

    [noun] 是话里怎么称呼它:人的叫「超级赞号」,群 / 频道的公开链接叫「链接名」,
    机器人(开发者后台)照旧叫「用户名」。规则三者一样 —— 它们共用一个命名空间。
    客户端「超级赞号」页上的规则说明是照这里写的,改规则要一起改。
    [reserved_ok] 只给服务端自己建官方账号用(比如机器人管家),任何接口都不许透传。
    """
    if not name:
        return f"{noun}不能为空"
    if len(name) < USERNAME_MIN:
        return f"{noun}至少 {USERNAME_MIN} 位"
    if len(name) > USERNAME_MAX:
        return f"{noun}最多 {USERNAME_MAX} 位"
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        return f"{noun}只能用字母、数字和下划线"
    if not name[0].isalpha():
        return f"{noun}要以字母开头"
    if name.endswith("_"):
        return f"{noun}不能以下划线结尾"
    if "__" in name:
        return f"{noun}不能有连续两个下划线"
    if not _USERNAME_RE.fullmatch(name):
        return f"{noun}格式不对"
    low = name.lower()
    if not reserved_ok and (low in _RESERVED_EXACT or any(p in low for p in _RESERVED_PARTS)):
        return f"这个{noun}是保留的,换一个吧"
    if is_bot and not low.endswith("bot"):
        return f"机器人的{noun}必须以 bot 结尾"
    if not is_bot and low.endswith("bot"):
        return f"以 bot 结尾的{noun}只给机器人用"
    return None


# ---------------- 超级赞号的改名规则(迁移 0133,2026-09 用户拍板) ----------------
#
# - 第一次设置随时能设;之后一年只能改一次,从上一次设置 / 修改那天算满 365 天;
# - 改掉、清空、随注销释放的旧号冷冻 180 天,这期间谁都不能注册 —— 包括群 / 频道的公开链接;
# - 原主人不受冷冻限制,但拿回来算一次修改,照样要等一年一次的名额(见 hold_blocks)。
#
# 机器人的号不走这套:它们必须以 bot 结尾、人的号不能以 bot 结尾(validate_username),
# 两边永远撞不上,冷冻中的超级赞号不可能被机器人拿走;删机器人也不冷冻它的号(开发者删了重建是常事)。

#: 一年只能改一次
USERNAME_CHANGE_DAYS = 365
#: 换下来的旧号冷冻多久
USERNAME_HOLD_DAYS = 180

_BJ = timezone(timedelta(hours=8))


def username_next_change(set_at: datetime | None) -> datetime | None:
    """下一次能改超级赞号的时刻;None = 没有限制(从没设过,或者是 0133 之前的存量号)。纯函数。

    **按北京时间的日期算,不按时刻**:2026-09-13 晚上 11 点设的,2027-09-13 零点起就能改。
    按时刻算的话,界面上写着「下次可修改:2027-09-13」,那天上午去改却被拒 —— 日期对不上说明。
    """
    if set_at is None:
        return None
    day = set_at.astimezone(_BJ).date() + timedelta(days=USERNAME_CHANGE_DAYS)
    return datetime.combine(day, time.min, tzinfo=_BJ)


def username_locked_until(set_at: datetime | None, now: datetime) -> datetime | None:
    """现在改不了的话,返回什么时候能改;现在能改返回 None。纯函数。"""
    nxt = username_next_change(set_at)
    return nxt if nxt is not None and now < nxt else None


def hold_blocks(frozen_until: datetime | None, released_by: int | None, owner_type: str,
                owner_id: int, now: datetime) -> bool:
    """冷冻中的旧号挡不挡这一次注册。纯函数。

    **原主人不挡**:冷冻防的是别人拿这个号冒充原主人(老联系人、老链接、老二维码找过来,
    找到的是另一个人),原主人自己拿回去不会让任何人认错人。挡他只会让「清空了又后悔」的人
    多等半年,却什么也没保护。他拿回去照样算一次修改,一年一次的名额在 set_username 里另外判。
    """
    if frozen_until is None or frozen_until <= now:
        return False
    return not (owner_type == "user" and released_by == owner_id)


def frozen_reason(noun: str = "超级赞号") -> str:
    """冷冻中的号被人拿来注册时给的话。**不说解冻日期**:日期能倒推出原主人哪天换的号,
    那是别人的事,不该告诉一个想注册这个号的陌生人。"""
    if noun == "超级赞号":
        return f"这个超级赞号刚被原主人换掉或清空,冷冻 {USERNAME_HOLD_DAYS} 天,这期间谁都不能注册"
    return f"这个{noun}是别人刚换掉或清空的超级赞号,冷冻 {USERNAME_HOLD_DAYS} 天,这期间谁都不能用"


async def hold_problem(db: AsyncSession, name: str, owner_type: str, owner_id: int, *,
                       noun: str = "超级赞号", now: datetime | None = None) -> str | None:
    """这个名字在冷冻期、来拿的又不是原主人:返回给人看的话;否则 None。"""
    now = now or datetime.now(timezone.utc)
    row = (await db.execute(select(UsernameHold.frozen_until, UsernameHold.released_by)
                            .where(UsernameHold.username_lc == name.lower()))).first()
    if row is not None and hold_blocks(row[0], row[1], owner_type, owner_id, now):
        return frozen_reason(noun)
    return None


async def release_user_username(db: AsyncSession, user_id: int, name: str, *,
                                now: datetime | None = None) -> None:
    """一个人的超级赞号被换掉 / 清空 / 随注销释放:从命名空间里删掉,旧号冷冻 [USERNAME_HOLD_DAYS] 天。

    删号和写冷冻在同一个事务里(调用方提交):别人要么还看得到号被占着,要么看得到冷冻,
    中间没有「号空着、冷冻还没写」的一刻。
    """
    now = now or datetime.now(timezone.utc)
    until = now + timedelta(days=USERNAME_HOLD_DAYS)
    await db.execute(delete(Username).where(Username.owner_type == "user",
                                            Username.owner_id == user_id))
    await db.execute(insert(UsernameHold).values(
        username_lc=name.lower(), released_by=user_id, frozen_until=until, created_at=now
    ).on_conflict_do_update(index_elements=["username_lc"],
                            set_={"released_by": user_id, "frozen_until": until,
                                  "created_at": now}))


async def claim_username(db: AsyncSession, name: str, owner_type: str, owner_id: int, *,
                         noun: str = "超级赞号", now: datetime | None = None) -> str | None:
    """占下一个名字(人的超级赞号、群 / 频道的公开链接都走这里)。返回 None = 占到了;
    否则是给人看的话(被占了 / 在冷冻期),**这时调用方必须不提交**(抛异常回滚掉这次插入)。

    主键兜并发:两个人同时抢,晚到的插不进去。冷冻在插入**之后**再看一次:检查和插入之间,
    这个名字的原主人刚好把它换掉(删号 + 写冷冻,一个事务),我们的插入会等那个事务提交后成功,
    而之前那次检查没看到冷冻 —— 插入之后这一次看得到。占到了就把这个名字的冷冻记录删掉
    (那只能是已经过期的,或者是原主人自己拿回去)。
    """
    now = now or datetime.now(timezone.utc)
    lc = name.lower()
    res = await db.execute(insert(Username).values(
        username_lc=lc, owner_type=owner_type, owner_id=owner_id
    ).on_conflict_do_nothing(index_elements=["username_lc"]))
    if res.rowcount != 1:
        return f"这个{noun}已经被占用了"
    problem = await hold_problem(db, name, owner_type, owner_id, noun=noun, now=now)
    if problem:
        return problem
    await db.execute(delete(UsernameHold).where(UsernameHold.username_lc == lc))
    return None


def username_searchable(privacy_col):
    """SQL:这个人允许别人按超级赞号找到他(隐私项 username_search 没关;没设过 = 允许)。
    全局搜索、视频里搜 UP 主这些「输号找人」的地方,拿它挡掉关了开关的人。"""
    return func.coalesce(privacy_col["username_search"].astext, "everyone") != "nobody"


async def username_search_off(db: AsyncSession, ids: Iterable[int]) -> set[int]:
    """这些人里关了「按超级赞号找到我」的。"""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return set()
    return set(await db.scalars(select(SocialProfile.user_id).where(
        SocialProfile.user_id.in_(ids),
        SocialProfile.privacy["username_search"].astext == "nobody")))


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
    """一个人的名片,比 [user_cards] 多带标签和勋章(资料页要显示;批量的名片不带,见 services/badges.py)。"""
    card = (await user_cards(db, viewer_id, [user_id])).get(user_id)
    if card is not None:
        from .badges import tags_badges_for
        card.update(await tags_badges_for(db, user_id, viewer_id))
    return card
