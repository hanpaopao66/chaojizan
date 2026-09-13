"""贴纸包 `/chat/v1/stickers`(DEV-PROMPTS-40 #351,D17)。

- 谁都能建自己的贴纸包(上传 PNG / WebP,服务端统一转 512px WebP),一包最多 120 张;
- 贴纸包按短名公开:别人在聊天里点你发的贴纸就能看到整包、一键添加(和 Telegram 一样);
- 平台的官方包(is_official)对所有人默认可用,不用添加;
- 贴纸图片走公开桶(services/media.py 里 purpose=sticker 不设私密)—— 发出去的贴纸本来就是给人看的。

发贴纸消息走 `POST /chat/v1/chats/{id}/messages`,kind=sticker + sticker_id(chat_store 里)。
"""
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import MediaFile, Sticker, StickerSet, User, UserStickerSet
from ..services import storage
from ..services.moderation import guard_text
from .social import social_user
from .chat import chat_on

router = APIRouter(prefix="/chat/v1/stickers", tags=["聊天"], dependencies=[Depends(chat_on)])

#: 一包最多几张(D17)
SET_MAX_STICKERS = 120
#: 一个人最多建几个包 / 装几个包
SETS_PER_USER = 50
INSTALLED_MAX = 200

_SHORT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,63}$")


def sticker_out(st: Sticker, mf: MediaFile | None) -> dict:
    return {
        "id": st.id,
        "set_id": st.set_id,
        "emoji": st.emoji,
        "media": None if mf is None else {
            "id": mf.id, "w": mf.w, "h": mf.h,
            "url": storage.url_for(mf.key, False) if mf.key else "",
        },
    }


async def _stickers(db: AsyncSession, set_ids: list[int]) -> dict[int, list[dict]]:
    if not set_ids:
        return {}
    rows = list(await db.scalars(select(Sticker).where(Sticker.set_id.in_(set_ids))
                                 .order_by(Sticker.set_id, Sticker.position, Sticker.id)))
    media = {m.id: m for m in await db.scalars(
        select(MediaFile).where(MediaFile.id.in_([r.media_id for r in rows])))} if rows else {}
    out: dict[int, list[dict]] = {i: [] for i in set_ids}
    for r in rows:
        out[r.set_id].append(sticker_out(r, media.get(r.media_id)))
    return out


async def _sets_out(db: AsyncSession, me: User, sets: list[StickerSet], *,
                    full: bool = True) -> list[dict]:
    ids = [s.id for s in sets]
    installed = set(await db.scalars(select(UserStickerSet.set_id).where(
        UserStickerSet.user_id == me.id, UserStickerSet.set_id.in_(ids)))) if ids else set()
    stickers = await _stickers(db, ids)
    out = []
    for s in sets:
        items = stickers.get(s.id, [])
        out.append({
            "id": s.id, "short_name": s.short_name, "title": s.title,
            "is_official": s.is_official, "is_mine": s.owner_id == me.id,
            "installed": s.is_official or s.id in installed,
            "count": len(items),
            "cover": items[0] if items else None,
            "stickers": items if full else [],
        })
    return out


async def _set_or_404(db: AsyncSession, set_id: int) -> StickerSet:
    s = await db.get(StickerSet, set_id)
    if s is None:
        raise HTTPException(404, "没有这个贴纸包")
    return s


async def _own_set(db: AsyncSession, set_id: int, me: User) -> StickerSet:
    s = await _set_or_404(db, set_id)
    if s.owner_id != me.id:
        raise HTTPException(403, "只有贴纸包的作者能改")
    return s


@router.get("/sets")
async def my_sets(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """贴纸面板用:官方包 + 我装的包(按我排的顺序),每包带全部贴纸;另附我自己建的包。"""
    official = list(await db.scalars(select(StickerSet).where(StickerSet.is_official)
                                     .order_by(StickerSet.id)))
    mine_installed = list(await db.execute(
        select(StickerSet).join(UserStickerSet, UserStickerSet.set_id == StickerSet.id)
        .where(UserStickerSet.user_id == me.id)
        .order_by(UserStickerSet.position, UserStickerSet.installed_at)))
    installed = [row[0] for row in mine_installed if not row[0].is_official]
    created = list(await db.scalars(select(StickerSet).where(StickerSet.owner_id == me.id)
                                    .order_by(StickerSet.id)))
    return {
        "installed": await _sets_out(db, me, official + installed),
        "created": await _sets_out(db, me, created, full=False),
    }


@router.get("/sets/by-name/{short_name}")
async def set_by_name(short_name: str, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    s = await db.scalar(select(StickerSet).where(StickerSet.short_name == short_name.lower()))
    if s is None:
        raise HTTPException(404, "没有这个贴纸包")
    return (await _sets_out(db, me, [s]))[0]


@router.get("/sets/{set_id}")
async def get_set(set_id: int, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    """聊天里点别人发的贴纸:看整包,决定要不要添加。"""
    return (await _sets_out(db, me, [await _set_or_404(db, set_id)]))[0]


class SetIn(BaseModel):
    title: str = Field(min_length=1, max_length=64)
    short_name: str = Field(default="", max_length=64)


@router.post("/sets")
async def create_set(body: SetIn, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "给贴纸包起个名字")
    await guard_text(db, title, "贴纸包名字")
    n = await db.scalar(select(func.count()).select_from(StickerSet)
                        .where(StickerSet.owner_id == me.id))
    if (n or 0) >= SETS_PER_USER:
        raise HTTPException(422, f"每人最多建 {SETS_PER_USER} 个贴纸包")
    short = body.short_name.strip()
    if short:
        if not _SHORT_RE.match(short):
            raise HTTPException(422, "短名 5–64 位,字母开头,只能用字母、数字和下划线")
        short = short.lower()
        if await db.scalar(select(StickerSet.id).where(StickerSet.short_name == short)):
            raise HTTPException(409, "这个短名已经被用了")
    else:
        short = "s" + secrets.token_hex(6)
    s = StickerSet(owner_id=me.id, short_name=short, title=title, is_official=False)
    db.add(s)
    await db.flush()
    # 建了就装上,面板里马上能用
    await db.execute(insert(UserStickerSet).values(user_id=me.id, set_id=s.id, position=0)
                     .on_conflict_do_nothing())
    await db.commit()
    return (await _sets_out(db, me, [s]))[0]


class SetPatch(BaseModel):
    title: str = Field(min_length=1, max_length=64)


@router.patch("/sets/{set_id}")
async def rename_set(set_id: int, body: SetPatch, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    s = await _own_set(db, set_id, me)
    await guard_text(db, body.title.strip(), "贴纸包名字")
    s.title = body.title.strip()
    await db.commit()
    return (await _sets_out(db, me, [s]))[0]


@router.delete("/sets/{set_id}")
async def delete_set(set_id: int, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    """删掉贴纸包。已经发出去的贴纸消息还在(图片是消息自己带着的),只是点开看不到这个包了。"""
    s = await _own_set(db, set_id, me)
    await db.delete(s)
    await db.commit()
    return {"ok": True}


class StickerIn(BaseModel):
    media_id: int
    emoji: str = Field(default="🙂", max_length=16)


@router.post("/sets/{set_id}/stickers")
async def add_sticker(set_id: int, body: StickerIn, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    s = await _own_set(db, set_id, me)
    mf = await db.get(MediaFile, body.media_id)
    if mf is None or mf.owner_id != me.id:
        raise HTTPException(404, "图片不存在,或者不是你上传的")
    if mf.kind != "sticker" or mf.status != "ready":
        raise HTTPException(422, "贴纸要用「贴纸」类型上传(PNG / WebP,自动缩到 512 像素)")
    n = await db.scalar(select(func.count()).select_from(Sticker).where(Sticker.set_id == s.id))
    if (n or 0) >= SET_MAX_STICKERS:
        raise HTTPException(422, f"一个贴纸包最多 {SET_MAX_STICKERS} 张")
    emoji = (body.emoji or "🙂").strip()[:16] or "🙂"
    st = Sticker(set_id=s.id, media_id=mf.id, emoji=emoji, position=int(n or 0))
    db.add(st)
    await db.commit()
    return sticker_out(st, mf)


@router.delete("/sets/{set_id}/stickers/{sticker_id}")
async def remove_sticker(set_id: int, sticker_id: int, me: User = Depends(social_user),
                         db: AsyncSession = Depends(get_db)):
    s = await _own_set(db, set_id, me)
    res = await db.execute(delete(Sticker).where(Sticker.id == sticker_id, Sticker.set_id == s.id))
    if res.rowcount != 1:
        raise HTTPException(404, "这张贴纸不在这个包里")
    await db.commit()
    return {"ok": True}


@router.post("/sets/{set_id}/install")
async def install(set_id: int, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    s = await _set_or_404(db, set_id)
    if s.is_official:
        return {"ok": True}
    n = await db.scalar(select(func.count()).select_from(UserStickerSet)
                        .where(UserStickerSet.user_id == me.id))
    if (n or 0) >= INSTALLED_MAX:
        raise HTTPException(422, f"最多添加 {INSTALLED_MAX} 个贴纸包,先移除几个不用的")
    # 新装的排最前(和 Telegram 一样)
    first = await db.scalar(select(func.min(UserStickerSet.position))
                            .where(UserStickerSet.user_id == me.id))
    await db.execute(insert(UserStickerSet).values(user_id=me.id, set_id=s.id,
                                                   position=(first or 0) - 1)
                     .on_conflict_do_nothing())
    await db.commit()
    return {"ok": True}


@router.delete("/sets/{set_id}/install")
async def uninstall(set_id: int, me: User = Depends(social_user),
                    db: AsyncSession = Depends(get_db)):
    await db.execute(delete(UserStickerSet).where(UserStickerSet.user_id == me.id,
                                                  UserStickerSet.set_id == set_id))
    await db.commit()
    return {"ok": True}


class OrderIn(BaseModel):
    set_ids: list[int] = Field(max_length=INSTALLED_MAX)


@router.put("/installed")
async def reorder(body: OrderIn, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    rows = {r.set_id: r for r in await db.scalars(select(UserStickerSet).where(
        UserStickerSet.user_id == me.id))}
    for i, sid in enumerate(body.set_ids):
        if sid in rows:
            rows[sid].position = i
    await db.commit()
    return {"ok": True}
