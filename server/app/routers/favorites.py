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
    first_time = existing is None
    if first_time:  # 幂等:重复收藏不报错
        db.add(Favorite(user_id=user.id, merchant_id=merchant_id))
        await db.commit()

    out = {"favorited": True}
    # **发券在收藏提交之后、独立事务里做**。放在同一个事务里的话,
    # 发券路径上任何异常都会把 session 打进 need-rollback 状态,
    # 外面那句 commit 直接 500 —— 收藏本身反而被发券搞挂了,
    # 与"收藏永远不失败"的意图正好相反
    if first_time:
        coupon = await _issue_favorite_coupon(db, merchant_id, user)
        if coupon is not None:
            out["coupon"] = {
                "amount_cents": coupon.amount_cents,
                "min_spend_cents": coupon.min_spend_cents,
                "note": coupon.note,
            }
    return out


async def _issue_favorite_coupon(db: AsyncSession, merchant_id: int,
                                 user: User):
    """收藏有礼:成本商家承担、总量即预算封顶(与其余商家券同口径)。

    ## 风控闸门与其余 5 条自动发券路径对齐

    这条路径的攻击成本是全平台最低的 —— 注册一个号 + 一次 POST,
    不用下单、不用花一分钱。没有闸门的话,一批小号就能把商家整个
    批次预算搬空,而商家在后台只看到"券发完了"。所以三道全上:
    - 营销总开关:平台唯一的应急刹车,其余自动发券路径都认它;
    - risk_level:被风控标记的账号,主动领券已经拒了,这里不能是后门;
    - 同设备多账号:与新客券同款判定。

    去重键用 **favorite:{店}:{人}** 而不是批次级 —— 批次级的话
    商家换一批券,老用户取关再收藏就能再拿一张,反而奖励反复取关的人。

    发不出来(没建批次/发完了/已领过/被闸门拦下)一律静默:
    收藏是用户动作,不该被商家的营销配置或平台风控搞出报错。
    """
    import logging

    from ..models import Coupon, CouponBatch
    from ..services.flags import marketing_on

    logger = logging.getLogger(__name__)
    try:
        if user.risk_level in ("limit", "frozen"):
            return None
        if not await marketing_on(db):
            return None
        batch = await db.scalar(
            select(CouponBatch).where(
                CouponBatch.merchant_id == merchant_id,
                CouponBatch.trigger == "favorite",
                CouponBatch.active.is_(True)))
        if batch is None:
            return None
        from ..services.coupons import _device_has_other_account
        if await _device_has_other_account(db, user):
            logger.info("收藏券跳过(同设备多账号): user=%s", user.id)
            return None
        # 一店一人一张:换批次也不再发,取关再收藏同样不再发
        source = f"favorite:{merchant_id}:{user.id}"
        if await db.scalar(select(Coupon.id).where(Coupon.source == source)):
            return None
        coupon = await issue_favorite(db, batch, user.id, source)
        if coupon is not None:
            await db.commit()
            return coupon
        return None
    except Exception:
        logger.exception("收藏发券失败 user=%s shop=%s", user.id, merchant_id)
        try:
            await db.rollback()   # 不 rollback 的话后续请求会撞 PendingRollback
        except Exception:
            pass
        return None


async def issue_favorite(db: AsyncSession, batch, user_id: int, source: str):
    """按自定义 source 发一张批次券(预算封顶用同一条条件 UPDATE)。"""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from ..models import Coupon, CouponBatch

    taken = (await db.execute(
        update(CouponBatch)
        .where(CouponBatch.id == batch.id,
               CouponBatch.issued < CouponBatch.total)
        .values(issued=CouponBatch.issued + 1)
        .returning(CouponBatch.id))).first()
    if taken is None:
        return None  # 发完了
    coupon = Coupon(
        user_id=user_id,
        amount_cents=batch.amount_cents,
        min_spend_cents=batch.min_spend_cents,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=batch.valid_days),
        source=source,
        batch_id=batch.id,
        note="收藏有礼",
        funder="merchant",
        merchant_id=batch.merchant_id,
    )
    db.add(coupon)
    return coupon


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
