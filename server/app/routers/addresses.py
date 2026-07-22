from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Address, User
from ..schemas import AddressIn, AddressOut, AddressPatch
from ..security import require_role

router = APIRouter(prefix="/addresses", tags=["收货地址"])


async def _unset_default(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(Address).where(Address.user_id == user_id).values(is_default=False)
    )


@router.get("", response_model=list[AddressOut])
async def list_addresses(
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(Address)
        .where(Address.user_id == user.id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
    )
    return list(result)


@router.post("", response_model=AddressOut)
async def create_address(
    payload: AddressIn,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    count = len((await db.scalars(select(Address.id).where(Address.user_id == user.id))).all())
    if count >= 20:
        raise HTTPException(409, "地址最多保存 20 个")
    if payload.is_default:
        await _unset_default(db, user.id)
    addr = Address(user_id=user.id, **payload.model_dump())
    if count == 0:
        addr.is_default = True  # 第一个地址自动设为默认
    db.add(addr)
    await db.commit()
    await db.refresh(addr)
    return addr


@router.patch("/{address_id}", response_model=AddressOut)
async def update_address(
    address_id: int,
    payload: AddressPatch,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    addr = await db.get(Address, address_id)
    if addr is None or addr.user_id != user.id:
        raise HTTPException(404, "地址不存在")
    changes = payload.model_dump(exclude_none=True)
    if changes.get("is_default"):
        await _unset_default(db, user.id)
    for field, value in changes.items():
        setattr(addr, field, value)
    await db.commit()
    await db.refresh(addr)
    return addr


@router.delete("/{address_id}", status_code=204)
async def delete_address(
    address_id: int,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    addr = await db.get(Address, address_id)
    if addr is None or addr.user_id != user.id:
        raise HTTPException(404, "地址不存在")
    await db.delete(addr)
    await db.commit()
