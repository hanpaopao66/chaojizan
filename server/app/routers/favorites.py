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
    coupon = None
    if existing is None:  # 幂等:重复收藏不报错
        db.add(Favorite(user_id=user.id, merchant_id=merchant_id))
        # 收藏有礼:商家建了 favorite 券批次就发一张。
        # 只在**第一次**收藏时发 —— issue_from_batch 的 source 是
        # batch:{id}:{user},取关再收藏也拿不到第二张
        coupon = await _issue_favorite_coupon(db, merchant_id, user.id)
        await db.commit()
    out = {"favorited": True}
    if coupon is not None:
        out["coupon"] = {
            "amount_cents": coupon.amount_cents,
            "min_spend_cents": coupon.min_spend_cents,
            "note": coupon.note,
        }
    return out


async def _issue_favorite_coupon(db: AsyncSession, merchant_id: int,
                                 user_id: int):
    """收藏有礼:成本商家承担、总量即预算封顶(与其余商家券同口径)。
    发不出来(没建批次/发完了/已领过)一律静默,收藏本身不能失败。"""
    from ..models import CouponBatch
    from ..services.coupons import issue_from_batch

    try:
        batch = await db.scalar(
            select(CouponBatch).where(
                CouponBatch.merchant_id == merchant_id,
                CouponBatch.trigger == "favorite",
                CouponBatch.active.is_(True)))
        if batch is None:
            return None
        return await issue_from_batch(db, batch, user_id, note="收藏有礼")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("收藏发券失败")
        return None


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
