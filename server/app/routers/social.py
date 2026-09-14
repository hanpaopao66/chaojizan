"""社交身份接口 `/social/v1`(DEV-PROMPTS-40 #340):资料、@超级赞号、找人、联系人、拉黑。

「超级赞号」是界面上的叫法(相当于微信号),代码和接口里沿用 username。
加联系人和 Telegram 一样:直接加进自己的联系人,不用对方同意,也只加在自己这边。

**所有响应都不含别人的手机号**(S2)。按手机号找人只返回找到的那个人的名片,
找不到和「对方关了按手机号查找」回同一句话 —— 否则等于告诉你「这个号注册过」。
按超级赞号找人同理(见 resolve)。
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (PRIVACY_VALUES, SocialBlock, SocialContact, SocialProfile, User,
                      UserRole, Username)
from ..ratelimit import check_daily_limit, check_rate_limit
from ..security import get_current_user
from ..services.moderation import find_banned, guard_text
from ..services.social import (SOCIAL_ROLES, allowed, claim_username, display_name,
                               ensure_profile, hold_problem, notify_of, privacy_of,
                               release_user_username, user_card, user_cards,
                               username_locked_until, validate_username)

router = APIRouter(prefix="/social/v1", tags=["社交"])

#: 按手机号找人:每人每天 20 次(§5.7,防撞库)
FIND_BY_PHONE_PER_DAY = 20

#: 名片二维码 / 分享链接的前缀(§5.1)
PUBLIC_BASE = "https://chaojizan.cc"

#: 界面上是开关的隐私项:只有「所有人」「没有人」两档。给它「联系人」没有意义
#: (能按号找到我的联系人,本来就在他的联系人里了),还会让开关显示不出状态
SWITCH_PRIVACY = {"username_search": "按超级赞号找到我"}

#: 按超级赞号没找到,和「对方关了按超级赞号找到我」回同一句话
_NOT_FOUND_BY_USERNAME = "没有找到。可能是超级赞号输错了,或者对方关闭了「按超级赞号找到我」"


def card_link(p: SocialProfile) -> str:
    """名片二维码 / 分享链接。

    有超级赞号、而且允许按号找到 → `/@号`;没有号,或者关了「按超级赞号找到我」→ `/u/<public_id>`。
    关了开关还用 `/@号` 的话,名片码自己就打不开了(resolve 对别人回 404,见那里的注释)。
    """
    if p.username and privacy_of(p)["username_search"] != "nobody":
        return f"{PUBLIC_BASE}/@{p.username}"
    return f"{PUBLIC_BASE}/u/{p.public_id}"


_READ_METHODS = ("GET", "HEAD", "OPTIONS")


async def social_user(request: Request, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> User:
    """「消息」「视频」只对用户端账号开放(D1)。商家、骑手、开发者账号调这些接口回 403。

    **封号在这里统一挡**(#368):社交相关的写接口都挂着这个依赖,被封号的人发来的写请求
    除了 services/sanctions.ACCOUNT_BAN_ALLOWED 里那几个(申诉、读、只有自己看得见的设置、
    拉黑、退群……)一律 403。默认是挡 —— 以后新加的写接口忘了处理封号,也不会漏过去。
    禁言、封群这些「只挡某几件事」的,在各自的写路径上判(见 services/sanctions.py 的表)。
    """
    if user.role not in SOCIAL_ROLES:
        raise HTTPException(403, "消息和视频只在用户端开放")
    if request.method not in _READ_METHODS:
        from ..services import sanctions
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        if (request.method, path) not in sanctions.ACCOUNT_BAN_ALLOWED:
            await sanctions.check_user(db, user.id, "social_write")
    return user


def _me_out(user: User, p: SocialProfile) -> dict:
    locked = username_locked_until(p.username_set_at, datetime.now(timezone.utc))
    return {
        "id": user.id,
        "name": display_name(user),
        "username": p.username,
        # 超级赞号现在改不了的话,什么时候能改(客户端显示「下次可修改:yyyy-mm-dd」);
        # null = 现在就能设 / 改。清空了号的人也看这个:清空之后再设一个算一次修改
        "username_next_change_at": locked.isoformat() if locked else None,
        "bio": p.bio or "",
        "avatar": user.avatar_url or "",
        "public_id": p.public_id,
        "privacy": privacy_of(p),
        "notify": notify_of(p),
        "personalize_video": p.personalize_video,
        "coins": p.coins,
        "link": card_link(p),
    }


@router.get("/me")
async def me(user: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    p = await ensure_profile(db, user.id)
    await db.commit()
    return _me_out(user, p)


class MePatch(BaseModel):
    bio: str | None = Field(default=None, max_length=140)
    privacy: dict[str, str] | None = None
    notify: dict[str, bool] | None = None
    personalize_video: bool | None = None


@router.patch("/me")
async def patch_me(body: MePatch, user: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    p = await ensure_profile(db, user.id)
    if body.bio is not None:
        # 封号期间这个接口放行(改隐私、通知是自我保护),但签名是给别人看的文字,照样挡
        from ..services.sanctions import check_user
        await check_user(db, user.id, "social_write")
        await guard_text(db, body.bio, "签名")
        p.bio = body.bio.strip()
    if body.privacy is not None:
        cur = privacy_of(p)
        for k, v in body.privacy.items():
            if k not in cur:
                raise HTTPException(422, f"没有这个隐私项:{k}")
            if v not in PRIVACY_VALUES:
                raise HTTPException(422, "隐私只能设成 所有人 / 联系人 / 没有人")
            if k in SWITCH_PRIVACY and v == "contacts":
                raise HTTPException(422, f"「{SWITCH_PRIVACY[k]}」只能开或关")
            cur[k] = v
        p.privacy = cur
    if body.notify is not None:
        cur_n = notify_of(p)
        for k, v in body.notify.items():
            if k not in cur_n:
                raise HTTPException(422, f"没有这个通知项:{k}")
            cur_n[k] = bool(v)
        p.notify = cur_n
        # 我的其他设备跟着变(比如在网页版上把「视频互动」静音了,手机上的角标当场变灰)
        from ..services.rt_events import append_user_event
        await append_user_event(db, user.id, "settings", {"notify": cur_n})
    if body.personalize_video is not None:
        p.personalize_video = body.personalize_video
    await db.commit()
    return _me_out(user, p)


class UsernameIn(BaseModel):
    username: str = Field(default="", max_length=32)


async def _username_problem(db: AsyncSession, name: str, owner_type: str,
                            owner_id: int) -> str | None:
    """这个号能不能归我:格式、屏蔽词、被占、冷冻,各有一句明确的话。

    先查占用、再查冷冻,顺序不能反:原主人换号是「删号 + 写冷冻」一个事务,
    先看到号没了的人,接着一定看得到冷冻;反过来查的话,可能冷冻还没看到、号已经没了。
    """
    problem = validate_username(name, noun="超级赞号")
    if problem:
        return problem
    if await find_banned(db, name):
        return "这个超级赞号包含不允许使用的内容"

    row = await db.get(Username, name.lower())
    if row is not None and not (row.owner_type == owner_type and row.owner_id == owner_id):
        return "这个超级赞号已经被占用了"
    return await hold_problem(db, name, owner_type, owner_id)


def _status_of(problem: str) -> int:
    """被占、冷冻是 409(号本身没毛病,只是现在归不了你);格式、保留字、屏蔽词是 422。"""
    return 409 if ("占用" in problem or "冷冻" in problem) else 422


@router.get("/username-check")
async def username_check(u: str, user: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    """输入时实时检查(占用、冷冻、保留字、格式各有一句明确的话)。

    只看这个号能不能归我;我自己现在能不能改(一年一次)看 /me 的 username_next_change_at。
    """
    problem = await _username_problem(db, u.strip().lstrip("@"), "user", user.id)
    return {"ok": problem is None, "reason": problem or ""}


@router.put("/me/username")
async def set_username(body: UsernameIn, user: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """设置 / 修改 / 清空(传空串)超级赞号。规则(迁移 0133,2026-09 用户拍板):

    - 第一次设置随时能设;之后一年只能改一次,从上一次设置 / 修改那天算满 365 天
      (username_next_change)。存量号(0133 之前设的,username_set_at 为空)下一次不用等;
    - **清空随时能清**,不看一年的名额:不想再被人按号找到,不能被「一年只能改一次」卡住。
      清空不重新计时,但清空之后再设一个算一次修改 —— 否则「清空 → 马上设新号」就把一年一次绕过去了;
    - 换掉、清空的旧号冷冻 180 天,谁都不能注册;原主人自己拿回来不受冷冻限制,但算一次修改
      (services/social.hold_blocks 里写了为什么);
    - 只改大小写不算修改:号不区分大小写,链接、按号找人都照旧,谁也不会因此认错人。
    """
    await check_rate_limit("social_username", str(user.id), 10)
    p = await ensure_profile(db, user.id)
    name = body.username.strip().lstrip("@")
    old = p.username
    now = datetime.now(timezone.utc)
    if not name:
        if old:
            await release_user_username(db, user.id, old, now=now)
            p.username = None
        await db.commit()
        return _me_out(user, p)
    if old and old.lower() == name.lower():
        if old != name:
            # 照样过一遍格式:str.lower() 会把个别非 ASCII 字符(比如开尔文符号 K)变成 k,
            # 不查的话能借「只改大小写」塞进一个长得像字母的怪字符
            problem = validate_username(name, noun="超级赞号")
            if problem:
                raise HTTPException(422, problem)
            p.username = name
            await db.commit()
        return _me_out(user, p)
    locked = username_locked_until(p.username_set_at, now)
    if locked is not None:
        raise HTTPException(409, {
            "error": "username_cooldown",
            "message": f"超级赞号一年只能改一次,下次可修改:{locked:%Y-%m-%d}",
            "next_change_at": locked.isoformat(),
        })
    problem = await _username_problem(db, name, "user", user.id)
    if problem:
        raise HTTPException(_status_of(problem), problem)
    if old:
        await release_user_username(db, user.id, old, now=now)
    # 两个人同时抢同一个号:主键兜底,晚到的那个在这里拿到明确的话(不提交,换下来的旧号也跟着回滚)
    problem = await claim_username(db, name, "user", user.id, now=now)
    if problem:
        raise HTTPException(_status_of(problem), problem)
    p.username = name
    p.username_set_at = now
    await db.commit()
    return _me_out(user, p)


async def _card_or_404(db: AsyncSession, viewer: User, target_id: int) -> dict:
    target = await db.get(User, target_id)
    if target is None or target.role not in SOCIAL_ROLES:
        raise HTTPException(404, "没有这个用户")
    card = await user_card(db, viewer.id, target_id)
    assert card is not None
    return card


@router.get("/users/{user_id}")
async def get_user(user_id: int, user: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    return await _card_or_404(db, user, user_id)


@router.get("/resolve/{username}")
async def resolve(username: str, user: User = Depends(social_user),
                  db: AsyncSession = Depends(get_db)):
    """@超级赞号 → 人,或者公开群 / 频道(添加联系人按号找、点开 `chaojizan.cc/@号` 链接都走这里)。

    **对方关了「按超级赞号找到我」**(隐私项 username_search = nobody):对别人回和「没有这个号」
    一模一样的 404,不然等于告诉你「这个号有人用,只是不让你找」。拉黑了的两个人之间也找不到
    (和按手机号找人一样,都走 services/social.allowed)。

    **那名片链接为什么照样能打开**:`chaojizan.cc/@号` 和在输入框里输号是一回事 —— 知道号就能拼出
    这个链接,所以它跟着开关走,关了之后以前发出去的 @ 链接也打不开。本人的名片二维码 / 分享链接
    这时改用 `chaojizan.cc/u/<public_id>`(card_link),走 /resolve-id,不看这个开关:public_id
    是 12 位随机串,猜不出来,拿得到它就说明是他本人给出去的(或者看过他名片的人转给你的,
    和转发名片一样),不是「知道号就能找」。所以关了开关,本人分享出去的名片码照样能加他。
    """
    row = await db.get(Username, username.strip().lstrip("@").lower())
    if row is None:
        raise HTTPException(404, _NOT_FOUND_BY_USERNAME)
    if row.owner_type == "user":
        p = await db.get(SocialProfile, row.owner_id)
        if not await allowed(db, p, row.owner_id, user.id, "username_search"):
            raise HTTPException(404, _NOT_FOUND_BY_USERNAME)
        return {"type": "user", "user": await _card_or_404(db, user, row.owner_id)}
    from ..services.chat_view import public_chat_card  # 聊天模块(#344)提供
    card = await public_chat_card(db, user, row.owner_id)
    if card is None:
        raise HTTPException(404, _NOT_FOUND_BY_USERNAME)
    return {"type": "chat", "chat": card}


@router.get("/resolve-id/{public_id}")
async def resolve_public_id(public_id: str, user: User = Depends(social_user),
                            db: AsyncSession = Depends(get_db)):
    """名片码 `/u/<public_id>`:没设超级赞号、或者关了「按超级赞号找到我」的人用它。
    不看 username_search 开关,为什么见 resolve 的注释。"""
    uid = await db.scalar(select(SocialProfile.user_id)
                          .where(SocialProfile.public_id == public_id))
    if uid is None:
        raise HTTPException(404, "没有找到这个用户")
    return {"type": "user", "user": await _card_or_404(db, user, uid)}


class PhoneIn(BaseModel):
    phone: str = Field(max_length=20)


_NOT_FOUND_BY_PHONE = "没有找到。对方可能还没注册,或者关闭了「按手机号找到我」"


@router.post("/find-by-phone")
async def find_by_phone(body: PhoneIn, user: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    """完整手机号精确匹配(D2)。每天 20 次;没注册和不让找回同一句话。"""
    phone = re.sub(r"\D", "", body.phone)
    if not re.fullmatch(r"1\d{10}", phone):
        raise HTTPException(422, "请输入完整的 11 位手机号")
    await check_daily_limit("social_find_phone", str(user.id), FIND_BY_PHONE_PER_DAY,
                            "今天按手机号找人的次数用完了(每天 20 次),明天再试")
    target = await db.scalar(select(User).where(
        User.phone == phone, User.role == UserRole.customer).order_by(User.id).limit(1))
    if target is None or target.id == user.id:
        raise HTTPException(404, _NOT_FOUND_BY_PHONE)
    p = await db.get(SocialProfile, target.id)
    if not await allowed(db, p, target.id, user.id, "phone_search"):
        raise HTTPException(404, _NOT_FOUND_BY_PHONE)
    return await _card_or_404(db, user, target.id)


# ---------------- 联系人 ----------------

@router.get("/contacts")
async def contacts(user: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    rows = list(await db.scalars(select(SocialContact).where(SocialContact.owner_id == user.id)))
    cards = await user_cards(db, user.id, [c.contact_id for c in rows])
    items = [cards[c.contact_id] for c in rows if c.contact_id in cards]
    items.sort(key=lambda c: (c["contact_alias"] or c["name"]).lower())
    return {"items": items}


class ContactIn(BaseModel):
    user_id: int
    alias: str = Field(default="", max_length=40)


@router.post("/contacts")
async def add_contact(body: ContactIn, user: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    if body.user_id == user.id:
        raise HTTPException(422, "不能把自己加成联系人")
    await _card_or_404(db, user, body.user_id)
    n = await db.scalar(select(func.count()).select_from(SocialContact)
                        .where(SocialContact.owner_id == user.id))
    if (n or 0) >= 5000:
        raise HTTPException(422, "联系人最多 5000 个")
    await db.execute(insert(SocialContact).values(
        owner_id=user.id, contact_id=body.user_id, alias=body.alias.strip()
    ).on_conflict_do_update(index_elements=["owner_id", "contact_id"],
                            set_={"alias": body.alias.strip()}))
    await db.commit()
    return await _card_or_404(db, user, body.user_id)


@router.delete("/contacts/{user_id}")
async def remove_contact(user_id: int, user: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    await db.execute(delete(SocialContact).where(SocialContact.owner_id == user.id,
                                                 SocialContact.contact_id == user_id))
    await db.commit()
    return {"ok": True}


# ---------------- 拉黑 ----------------

@router.get("/blocks")
async def blocks(user: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    ids = list(await db.scalars(select(SocialBlock.blocked_id)
                                .where(SocialBlock.user_id == user.id)
                                .order_by(SocialBlock.created_at.desc())))
    cards = await user_cards(db, user.id, ids)
    return {"items": [cards[i] for i in ids if i in cards]}


class BlockIn(BaseModel):
    user_id: int


@router.post("/blocks")
async def block(body: BlockIn, user: User = Depends(social_user),
                db: AsyncSession = Depends(get_db)):
    if body.user_id == user.id:
        raise HTTPException(422, "不能拉黑自己")
    await _card_or_404(db, user, body.user_id)
    await db.execute(insert(SocialBlock).values(user_id=user.id, blocked_id=body.user_id)
                     .on_conflict_do_nothing(index_elements=["user_id", "blocked_id"]))
    await db.commit()
    from ..services import social_hooks
    await social_hooks.on_block_changed(user.id, body.user_id, True)
    return await _card_or_404(db, user, body.user_id)


@router.delete("/blocks/{user_id}")
async def unblock(user_id: int, user: User = Depends(social_user),
                  db: AsyncSession = Depends(get_db)):
    await db.execute(delete(SocialBlock).where(SocialBlock.user_id == user.id,
                                               SocialBlock.blocked_id == user_id))
    await db.commit()
    from ..services import social_hooks
    await social_hooks.on_block_changed(user.id, user_id, False)
    return {"ok": True}
