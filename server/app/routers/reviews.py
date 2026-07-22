from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Merchant, Order, Review, User
from ..schemas import ReplyIn, ReviewIn, ReviewOut
from ..security import require_role
from ..state_machine import OrderStatus

router = APIRouter(tags=["评价"])


def _mask_name(name: str) -> str:
    """姓名脱敏:保留首字,其余打星。"""
    if not name:
        return "匿名用户"
    return name[0] + "*" * max(len(name) - 1, 2)


def _to_out(review: Review, customer_name: str) -> ReviewOut:
    out = ReviewOut.model_validate(review)
    # 真匿名:任何视角都是"匿名用户"(平台后台走 DB,不经此序列化)
    out.customer_name = ("匿名用户" if review.is_anonymous
                         else _mask_name(customer_name))
    return out


async def _detect_review_abuse(db, customer_id: int, order) -> str | None:
    """刷评疑似识别(只标记不删):同店近30天高频评价、下单到评价间隔异常。"""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    # ① 同一用户对同店近 30 天 ≥3 条评价
    same_shop = await db.scalar(
        select(func.count(Review.id)).where(
            Review.customer_id == customer_id,
            Review.merchant_id == order.merchant_id,
            Review.created_at > now - timedelta(days=30)))
    if (same_shop or 0) >= 3:
        return "同店高频评价"
    # ② 下单到评价间隔异常短(< 5 分钟,正常吃完再评远不止)
    created = order.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if now - created < timedelta(minutes=5):
        return "下单到评价间隔异常"
    return None


@router.post("/orders/{order_no}/review", response_model=ReviewOut)
async def create_review(
    order_no: str,
    payload: ReviewIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.status != OrderStatus.COMPLETED:
        raise HTTPException(409, "订单完成后才能评价")
    existing = await db.scalar(select(Review).where(Review.order_id == order.id))
    if existing:
        raise HTTPException(409, "这一单已经评价过了")

    # 文本同步拦截敏感词;图片先发后审(下方入审核队列)
    from ..services.moderation import guard_text, submit_images
    await guard_text(db, payload.comment, "评价")

    # 刷评识别:命中疑似规则只标记待复核,绝不自动删/隐藏(误伤优先放行)
    flag_reason = await _detect_review_abuse(db, user.id, order)

    review = Review(
        order_id=order.id,
        customer_id=user.id,
        merchant_id=order.merchant_id,
        rider_id=order.rider_id,
        merchant_rating=payload.merchant_rating,
        rider_rating=payload.rider_rating if order.rider_id else None,
        comment=payload.comment.strip(),
        image_urls=payload.image_urls[:6],
        tags=payload.tags,
        is_anonymous=payload.is_anonymous,
        flagged=bool(flag_reason),
        flag_reason=flag_reason or "",
    )
    db.add(review)
    # 商家评分聚合原子累加,并发评价不丢数
    await db.execute(
        update(Merchant)
        .where(Merchant.id == order.merchant_id)
        .values(
            rating_sum=Merchant.rating_sum + payload.merchant_rating,
            rating_count=Merchant.rating_count + 1,
        )
    )
    await db.flush()
    await submit_images(db, "review", review.id, payload.image_urls[:6])
    await db.commit()
    await db.refresh(review)
    return _to_out(review, user.name)


@router.get("/orders/{order_no}/review", response_model=ReviewOut)
async def get_order_review(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    review = await db.scalar(select(Review).where(Review.order_id == order.id))
    if review is None:
        raise HTTPException(404, "还没有评价")
    return _to_out(review, user.name)


# ---------- 商家侧:查看 + 回复 ----------
@router.get("/merchants/me/reviews", response_model=list[ReviewOut])
async def my_shop_reviews(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    rows = await db.execute(
        select(Review, User.name)
        .join(User, User.id == Review.customer_id)
        .where(Review.merchant_id == shop.id)
        .order_by(Review.created_at.desc())
        .limit(100)
    )
    return [_to_out(review, name) for review, name in rows]


@router.post("/merchants/me/reviews/{review_id}/reply", response_model=ReviewOut)
async def reply_review(
    review_id: int,
    payload: ReplyIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家回复评价(可修改,回复对所有用户可见)。"""
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    review = await db.get(Review, review_id)
    if shop is None or review is None or review.merchant_id != shop.id:
        raise HTTPException(404, "评价不存在")
    first_reply = not review.reply  # 修改回复不重复推,只有首次回复触达
    review.reply = payload.reply.strip()
    await db.commit()
    await db.refresh(review)
    if first_reply:
        from ..services.push import notify_review_reply

        await notify_review_reply(review.customer_id, shop.name, review.reply)
    customer = await db.get(User, review.customer_id)
    return _to_out(review, customer.name if customer else "")


@router.get("/merchants/{merchant_id}/reviews", response_model=list[ReviewOut])
async def merchant_reviews(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """店铺评价列表(公开,姓名脱敏)。"""
    rows = await db.execute(
        select(Review, User.name)
        .join(User, User.id == Review.customer_id)
        .where(Review.merchant_id == merchant_id, Review.hidden.is_(False))
        .order_by(Review.created_at.desc())
        .limit(50)
    )
    return [_to_out(review, name) for review, name in rows]


APPEND_WINDOW_DAYS = 7


@router.post("/reviews/{review_id}/append", response_model=ReviewOut)
async def append_review(
    review_id: int,
    payload: dict,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """追评:首评后 7 天内一次(文字+图,过审核);匿名评价的追评继承匿名。"""
    from datetime import datetime, timedelta, timezone
    review = await db.get(Review, review_id, with_for_update=True)
    if review is None or review.customer_id != user.id:
        raise HTTPException(404, "评价不存在")
    if review.append_at is not None:
        raise HTTPException(409, "已经追评过了(一单一次)")
    created = review.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created > timedelta(
            days=APPEND_WINDOW_DAYS):
        raise HTTPException(409, f"首评超过 {APPEND_WINDOW_DAYS} 天,追评通道已关闭")
    content = str(payload.get("content", "")).strip()[:500]
    images = [str(u).strip() for u in (payload.get("images") or [])
              if str(u).strip()][:6]
    if not content and not images:
        raise HTTPException(422, "追评内容不能为空")
    from ..services.moderation import guard_text, submit_images
    if content:
        await guard_text(db, content, "追评")
    review.append_content = content
    review.append_images = images
    review.append_at = datetime.now(timezone.utc)
    await db.commit()
    if images:
        await submit_images(db, "review", review.id, images)
    await db.refresh(review)
    return _to_out(review, user.name)


@router.post("/merchants/me/reviews/{review_id}/append-reply",
             response_model=ReviewOut)
async def reply_append(
    review_id: int,
    payload: ReplyIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """商家回复追评(一次,可修改)。"""
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    review = await db.get(Review, review_id, with_for_update=True)
    if shop is None or review is None or review.merchant_id != shop.id:
        raise HTTPException(404, "评价不存在")
    if review.append_at is None:
        raise HTTPException(409, "这条评价还没有追评")
    from ..services.moderation import guard_text
    await guard_text(db, payload.reply, "商家回复")
    review.append_reply = payload.reply.strip()
    await db.commit()
    await db.refresh(review)
    customer = await db.get(User, review.customer_id)
    return _to_out(review, customer.name if customer else "")
