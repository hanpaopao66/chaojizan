"""拼单(共享购物车):发起人开车 → 同伴输码加菜 → 发起人锁单一次性支付。

最简结算模式:订单归发起人,AA 线下自行解决——平台不碰代收分账
(资金合规红线)。拼单态只存 Redis(cart:{code},2 小时 TTL),
未成单的车不落库;下单时原子关车。起送价/满减按合车总额算(天然优势)。
"""
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Dish, Merchant, MerchantStatus, User
from ..redis_client import get_redis
from ..security import require_role
from ..ws import manager

router = APIRouter(prefix="/group-carts", tags=["拼单"])

TTL_SECONDS = 7200
_KEY = "cart:{code}"


async def _load_cart(code: str) -> dict:
    raw = await get_redis().get(_KEY.format(code=code))
    if raw is None:
        raise HTTPException(404, "拼单码不存在或已过期(有效期 2 小时)")
    return json.loads(raw)


async def _save_cart(cart: dict) -> None:
    # 保存不重置 TTL:2 小时从开车起算,别让一直加菜的车永生
    redis = get_redis()
    key = _KEY.format(code=cart["code"])
    ttl = await redis.ttl(key)
    await redis.set(key, json.dumps(cart, ensure_ascii=False),
                    ex=ttl if ttl and ttl > 0 else TTL_SECONDS)


async def _broadcast(cart: dict, event: str) -> None:
    await manager.broadcast(f"cart:{cart['code']}",
                            {"type": "cart", "event": event, "cart": cart})


def _view(cart: dict, user_id: int) -> dict:
    return {**cart, "me": user_id, "is_owner": cart["owner_id"] == user_id,
            "total_cents": sum(i["price_cents"] * i["quantity"]
                               for i in cart["items"])}


@router.post("")
async def open_cart(
    payload: dict,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """开拼单:生成 6 位拼单码(2 小时有效)。"""
    merchant = await db.get(Merchant, int(payload.get("merchant_id", 0)))
    if (merchant is None or not merchant.is_open
            or merchant.status != MerchantStatus.approved):
        raise HTTPException(409, "商家不存在或已打烊")
    code = f"{secrets.randbelow(10**6):06d}"
    cart = {
        "code": code, "merchant_id": merchant.id,
        "merchant_name": merchant.name,
        "owner_id": user.id, "locked": False,
        "members": {str(user.id): user.name or "发起人"},
        "items": [],
    }
    await get_redis().set(_KEY.format(code=code),
                          json.dumps(cart, ensure_ascii=False),
                          ex=TTL_SECONDS)
    return _view(cart, user.id)


@router.post("/{code}/join")
async def join_cart(
    code: str,
    user: User = Depends(require_role("customer")),
):
    cart = await _load_cart(code)
    if cart["locked"]:
        raise HTTPException(409, "发起人已锁单去结算,下次早点来")
    if str(user.id) not in cart["members"]:
        if len(cart["members"]) >= 10:
            raise HTTPException(409, "这车人满了(最多 10 人)")
        cart["members"][str(user.id)] = user.name or f"伙伴{len(cart['members'])}"
        await _save_cart(cart)
        await _broadcast(cart, "join")
    return _view(cart, user.id)


@router.get("/{code}")
async def get_cart(
    code: str,
    user: User = Depends(require_role("customer")),
):
    cart = await _load_cart(code)
    if str(user.id) not in cart["members"]:
        raise HTTPException(403, "先输码加入这车拼单")
    return _view(cart, user.id)


@router.post("/{code}/items")
async def set_item(
    code: str,
    payload: dict,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """改自己的菜:quantity 为绝对份数,0 = 移除。只能动自己点的。"""
    cart = await _load_cart(code)
    if str(user.id) not in cart["members"]:
        raise HTTPException(403, "先输码加入这车拼单")
    if cart["locked"]:
        raise HTTPException(409, "发起人已锁单,不能再改菜;有遗漏让发起人解锁")
    dish_id = int(payload.get("dish_id", 0))
    quantity = int(payload.get("quantity", 0))
    if not 0 <= quantity <= 99:
        raise HTTPException(422, "份数需在 0-99 之间")
    dish = await db.scalar(select(Dish).where(
        Dish.id == dish_id, Dish.merchant_id == cart["merchant_id"]))
    if dish is None or not dish.is_on_sale:
        raise HTTPException(422, "菜品不存在或已下架")
    cart["items"] = [i for i in cart["items"]
                     if not (i["uid"] == user.id and i["dish_id"] == dish_id)]
    if quantity > 0:
        cart["items"].append({
            "uid": user.id, "by": cart["members"][str(user.id)],
            "dish_id": dish_id, "name": dish.name,
            "price_cents": dish.price_cents, "quantity": quantity,
        })
    await _save_cart(cart)
    await _broadcast(cart, "items")
    return _view(cart, user.id)


@router.post("/{code}/lock")
async def lock_cart(
    code: str,
    payload: dict,
    user: User = Depends(require_role("customer")),
):
    """锁单(仅发起人):锁后不可改,去结算;locked=false 可解锁。"""
    cart = await _load_cart(code)
    if cart["owner_id"] != user.id:
        raise HTTPException(403, "只有发起人能锁单/解锁")
    cart["locked"] = bool(payload.get("locked", True))
    await _save_cart(cart)
    await _broadcast(cart, "lock")
    return _view(cart, user.id)


async def consume_cart_for_order(code: str, user_id: int) -> dict:
    """下单时原子关车(GETDEL):返回车内容;校验发起人与锁定态。"""
    redis = get_redis()
    raw = await redis.getdel(_KEY.format(code=code))
    if raw is None:
        raise HTTPException(404, "拼单码不存在或已过期")
    cart = json.loads(raw)
    if cart["owner_id"] != user_id:
        # 不是发起人,车放回去
        await redis.set(_KEY.format(code=code),
                        raw if isinstance(raw, str) else raw.decode(),
                        ex=TTL_SECONDS)
        raise HTTPException(403, "只有发起人能用拼单车下单")
    if not cart["locked"]:
        await redis.set(_KEY.format(code=code),
                        raw if isinstance(raw, str) else raw.decode(),
                        ex=TTL_SECONDS)
        raise HTTPException(409, "请先锁单再去结算(锁后同伴不能再改菜)")
    await manager.broadcast(f"cart:{code}",
                            {"type": "cart", "event": "ordered", "cart": cart})
    return cart
