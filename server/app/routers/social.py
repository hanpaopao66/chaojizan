"""社交身份接口 `/social/v1`(DEV-PROMPTS-40 #340):资料、@用户名、找人、联系人、拉黑。

**所有响应都不含别人的手机号**(S2)。按手机号找人只返回找到的那个人的名片,
找不到和「对方关了按手机号查找」回同一句话 —— 否则等于告诉你「这个号注册过」。
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (PRIVACY_VALUES, SocialBlock, SocialContact, SocialProfile, User,
                      UserRole, Username)
from ..ratelimit import check_daily_limit, check_rate_limit
from ..security import get_current_user
from ..services.social import (SOCIAL_ROLES, allowed, display_name, ensure_profile,
                               notify_of, privacy_of, user_card, user_cards,
                               validate_username)

router = APIRouter(prefix="/social/v1", tags=["社交"])

#: 按手机号找人:每人每天 20 次(§5.7,防撞库)
FIND_BY_PHONE_PER_DAY = 20

#: 名片二维码 / 分享链接的前缀(§5.1)
PUBLIC_BASE = "https://chaojizan.cc"


async def social_user(user: User = Depends(get_current_user)) -> User:
    """「消息」「视频」只对用户端账号开放(D1)。商家、骑手、开发者账号调这些接口回 403。"""
    if user.role not in SOCIAL_ROLES:
        raise HTTPException(403, "消息和视频只在用户端开放")
    return user


def _me_out(user: User, p: SocialProfile) -> dict:
    return {
        "id": user.id,
        "name": display_name(user),
        "username": p.username,
        "bio": p.bio or "",
        "avatar": user.avatar_url or "",
        "public_id": p.public_id,
        "privacy": privacy_of(p),
        "notify": notify_of(p),
        "personalize_video": p.personalize_video,
        "coins": p.coins,
        "link": f"{PUBLIC_BASE}/@{p.username}" if p.username else f"{PUBLIC_BASE}/u/{p.public_id}",
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
        p.bio = body.bio.strip()
    if body.privacy is not None:
        cur = privacy_of(p)
        for k, v in body.privacy.items():
            if k not in cur:
                raise HTTPException(422, f"没有这个隐私项:{k}")
            if v not in PRIVACY_VALUES:
                raise HTTPException(422, "隐私只能设成 所有人 / 联系人 / 没有人")
            cur[k] = v
        p.privacy = cur
    if body.notify is not None:
        cur_n = notify_of(p)
        for k, v in body.notify.items():
            if k not in cur_n:
                raise HTTPException(422, f"没有这个通知项:{k}")
            cur_n[k] = bool(v)
        p.notify = cur_n
    if body.personalize_video is not None:
        p.personalize_video = body.personalize_video
    await db.commit()
    return _me_out(user, p)


class UsernameIn(BaseModel):
    username: str = Field(default="", max_length=32)


async def _username_problem(db: AsyncSession, name: str, owner_type: str,
                            owner_id: int) -> str | None:
    problem = validate_username(name)
    if problem:
        return problem
    row = await db.get(Username, name.lower())
    if row is not None and not (row.owner_type == owner_type and row.owner_id == owner_id):
        return "这个用户名已经被占用了"
    return None


@router.get("/username-check")
async def username_check(u: str, user: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    """输入时实时检查(占用、保留字、格式各有一句明确的话)。"""
    problem = await _username_problem(db, u, "user", user.id)
    return {"ok": problem is None, "reason": problem or ""}


@router.put("/me/username")
async def set_username(body: UsernameIn, user: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """设置 / 修改 / 清空(传空串)用户名。旧名字立即释放。"""
    await check_rate_limit("social_username", str(user.id), 10)
    p = await ensure_profile(db, user.id)
    name = body.username.strip().lstrip("@")
    if p.username:
        await db.execute(delete(Username).where(Username.owner_type == "user",
                                                Username.owner_id == user.id))
    if not name:
        p.username = None
        await db.commit()
        return _me_out(user, p)
    problem = await _username_problem(db, name, "user", user.id)
    if problem:
        raise HTTPException(409 if "占用" in problem else 422, problem)
    res = await db.execute(insert(Username).values(
        username_lc=name.lower(), owner_type="user", owner_id=user.id
    ).on_conflict_do_nothing(index_elements=["username_lc"]))
    if res.rowcount != 1:
        # 两个人同时抢同一个名字:主键兜底,晚到的那个在这里拿到明确的话
        raise HTTPException(409, "这个用户名已经被占用了")
    p.username = name
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
    """@用户名 → 人或者公开群 / 频道。"""
    row = await db.get(Username, username.strip().lstrip("@").lower())
    if row is None:
        raise HTTPException(404, "没有找到这个用户名")
    if row.owner_type == "user":
        return {"type": "user", "user": await _card_or_404(db, user, row.owner_id)}
    from ..services.chat_view import public_chat_card  # 聊天模块(#344)提供
    card = await public_chat_card(db, user, row.owner_id)
    if card is None:
        raise HTTPException(404, "没有找到这个用户名")
    return {"type": "chat", "chat": card}


@router.get("/resolve-id/{public_id}")
async def resolve_public_id(public_id: str, user: User = Depends(social_user),
                            db: AsyncSession = Depends(get_db)):
    """没设用户名的人,名片二维码是 `/u/<public_id>`。"""
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
