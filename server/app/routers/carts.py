"""云端购物车:按 用户×商家 存一份未提交购物车,跨设备续用。

只存"选了什么"(dish_id/choices/quantity),展示价与可用性一律以
进店时的当前菜单为准——商家改价/下架/估清由结算页按现价校验并提示,
购物车本身不冻结价格。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Cart, Merchant, User
from ..schemas import CartIn, CartOut
from ..security import require_role

router = APIRouter(prefix="/cart", tags=["购物车"])


@router.get("/{merchant_id}", response_model=CartOut)
async def get_cart(
    merchant_id: int,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """取该店的云端购物车(没有则返回空)。"""
    cart = await db.scalar(
        select(Cart).where(Cart.user_id == user.id,
                           Cart.merchant_id == merchant_id))
    return CartOut(merchant_id=merchant_id,
                   items=cart.items if cart else [])


@router.put("/{merchant_id}", response_model=CartOut)
async def put_cart(
    merchant_id: int,
    payload: CartIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """整份覆盖保存(客户端购物车变更时防抖上报)。空 items = 清空该店购物车。"""
    if await db.get(Merchant, merchant_id) is None:
        raise HTTPException(404, "商家不存在")
    items = [it.model_dump() for it in payload.items]
    if not items:
        await db.execute(
            Cart.__table__.delete().where(Cart.user_id == user.id,
                                          Cart.merchant_id == merchant_id))
        await db.commit()
        return CartOut(merchant_id=merchant_id, items=[])
    # upsert:同 用户×商家 存一份,覆盖 items(唯一键冲突则更新)
    stmt = insert(Cart).values(
        user_id=user.id, merchant_id=merchant_id, items=items)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_cart_user_merchant",
        set_={"items": items, "updated_at": func.now()})
    await db.execute(stmt)
    await db.commit()
    return CartOut(merchant_id=merchant_id, items=items)
