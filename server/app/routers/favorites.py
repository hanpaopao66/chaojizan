"""收藏店铺(用户端)。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Favorite, Merchant, MerchantStatus, User
from ..schemas import MerchantOut
from ..security import require_role

router = APIRouter(prefix="/favorites", tags=["收藏"])


@router.get("/ids", response_model=list[int])
async def favorite_ids(
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """收藏的店铺 id 列表(店铺页判断心形状态用,轻量)。"""
    result = await db.scalars(
        select(Favorite.merchant_id).where(Favorite.user_id == user.id)
    )
    return list(result)


@router.get("", response_model=list[MerchantOut])
async def my_favorites(
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(Merchant)
        .join(Favorite, Favorite.merchant_id == Merchant.id)
        .where(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
        .limit(100)
    )
    return [row[0] for row in rows]


@router.post("/{merchant_id}")
async def add_favorite(
    merchant_id: int,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.get(Merchant, merchant_id)
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "商家不存在")
    existing = await db.scalar(
        select(Favorite).where(
            Favorite.user_id == user.id, Favorite.merchant_id == merchant_id
        )
    )
    if existing is None:  # 幂等:重复收藏不报错
        db.add(Favorite(user_id=user.id, merchant_id=merchant_id))
        await db.commit()
    return {"favorited": True}


@router.delete("/{merchant_id}")
async def remove_favorite(
    merchant_id: int,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        delete(Favorite).where(
            Favorite.user_id == user.id, Favorite.merchant_id == merchant_id
        )
    )
    await db.commit()
    return {"favorited": False}
