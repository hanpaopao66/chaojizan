"""食品安全投诉(食安红线通道)。

与普通售后的区别:不经商家、直达平台,管理后台标红加急处理。
处置动作(先行全额退款/下架涉事菜品/暂停商家营业)在 routers/admin.py。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import FoodSafetyReport, Order, User
from ..schemas import FoodSafetyIn, FoodSafetyOut
from ..security import require_role
from ..state_machine import OrderStatus

logger = logging.getLogger("superz.food_safety")

router = APIRouter(prefix="/food-safety", tags=["食品安全"])


@router.post("", response_model=FoodSafetyOut)
async def submit_report(
    payload: FoodSafetyIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """提交食安投诉:必须拍照举证,可附医疗凭证。

    已送达/已完成的订单才能提(吃到了才谈得上食安问题);
    同一订单一次,平台专人加急处理,不经商家。
    """
    order = await db.scalar(
        select(Order).where(Order.order_no == payload.order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.status not in (OrderStatus.DELIVERED, OrderStatus.COMPLETED):
        raise HTTPException(409, "订单送达后才能提交食品安全投诉;配送中的问题请走售后或联系客服")
    existing = await db.scalar(
        select(FoodSafetyReport.id).where(
            FoodSafetyReport.order_id == order.id))
    if existing:
        raise HTTPException(409, "该订单已提交过食品安全投诉,平台正在加急处理")
    if not [u for u in payload.images if u.strip()]:
        raise HTTPException(422, "食安投诉必须拍照举证(问题食品照片)")
    report = FoodSafetyReport(
        order_id=order.id,
        order_no=order.order_no,
        customer_id=user.id,
        merchant_id=order.merchant_id,
        kind=payload.kind,
        description=payload.description.strip(),
        images=payload.images,
        medical_urls=payload.medical_urls,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    logger.warning("食安投诉: order=%s merchant=%s kind=%s",
                   order.order_no, order.merchant_id, payload.kind)
    return report


@router.get("/mine", response_model=list[FoodSafetyOut])
async def my_reports(
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(FoodSafetyReport)
        .where(FoodSafetyReport.customer_id == user.id)
        .order_by(FoodSafetyReport.created_at.desc())
        .limit(50)
    )
    return list(result)


@router.get("/order/{order_no}", response_model=FoodSafetyOut | None)
async def report_of_order(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """订单详情页查本单的食安投诉状态(没有返回 null)。"""
    return await db.scalar(
        select(FoodSafetyReport).where(
            FoodSafetyReport.order_no == order_no,
            FoodSafetyReport.customer_id == user.id))
