"""拼单(共享购物车):发起人开车 → 同伴输码加菜 → 发起人锁单一次性支付。

最简结算模式:订单归发起人,AA 线下自行解决——平台不碰代收分账
(资金合规红线)。拼单态只存 Redis(cart:{code},2 小时 TTL),
未成单的车不落库;下单时原子关车。起送价/满减按合车总额算(天然优势)。
"""
import json
import secrets
from datetime import datetime, timezone

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


#: 拼单里一道菜的备注(「不要香菜」)最多几个字
NOTE_MAX = 30

#: 整车的备注拼成一句(order_note_for)最多几个字。下单时它接在用户自己写的订单备注
#: 后面(App 里限 100 字),订单备注一共 200 —— 两边加起来不超,下单时就不会截掉谁的。
#: 超了在**加菜那一下**就说,不等到下单时悄悄截断
GROUP_NOTE_MAX = 99


def line_key(uid: int, dish_id: int, choices: list, note: str) -> tuple:
    """车里的一行 = 谁、哪道菜、选了哪些规格、写了什么备注。
    规格按集合比(先后顺序不算不同),老车里的行没有这两个字段,按空的算。"""
    return (uid, dish_id, tuple(sorted(choices or [])), (note or "").strip())


@router.post("/{code}/items")
async def set_item(
    code: str,
    payload: dict,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """改自己的菜:quantity 为某一行的绝对份数,0 = 移除。只能动自己点的。

    一行由(菜, 规格, 备注)确定:同一道菜选了不同规格、写了不同备注是不同的行。
    规格和普通下单同一套校验(orders.resolve_options):必选组要选、单选组最多一项、
    选项得是这道菜真有的;单价按限时折扣和选中的规格加价**在服务端重算**,
    客户端传价无效。备注在下单时并进订单备注(orders.py),后厨看得到。
    """
    cart = await _load_cart(code)
    if str(user.id) not in cart["members"]:
        raise HTTPException(403, "先输码加入这车拼单")
    if cart["locked"]:
        raise HTTPException(409, "发起人已锁单,不能再改菜;有遗漏让发起人解锁")
    dish_id = int(payload.get("dish_id", 0))
    quantity = int(payload.get("quantity", 0))
    if not 0 <= quantity <= 99:
        raise HTTPException(422, "份数需在 0-99 之间")
    choices = payload.get("choices") or []
    if (not isinstance(choices, list) or len(choices) > 20
            or not all(isinstance(c, str) and 0 < len(c) <= 20 for c in choices)):
        raise HTTPException(422, "规格格式不对")
    note = str(payload.get("note") or "").strip()
    if len(note) > NOTE_MAX:
        raise HTTPException(422, f"备注最多 {NOTE_MAX} 个字")
    dish = await db.scalar(select(Dish).where(
        Dish.id == dish_id, Dish.merchant_id == cart["merchant_id"]))
    if dish is None or not dish.is_on_sale:
        raise HTTPException(422, "菜品不存在或已下架")
    key = line_key(user.id, dish_id, choices, note)
    cart["items"] = [
        i for i in cart["items"]
        if line_key(i["uid"], i["dish_id"], i.get("choices"), i.get("note")) != key]
    if quantity > 0:
        if dish.sold_out_today:
            raise HTTPException(409, f"「{dish.name}」今日已售罄")
        from .orders import resolve_options

        price = dish.price_cents
        if (dish.flash_price_cents is not None and dish.flash_until is not None
                and dish.flash_until > datetime.now(timezone.utc)):
            price = dish.flash_price_cents
        try:
            unit, display = resolve_options(
                dish.name, price, dish.options or [], choices)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        cart["items"].append({
            "uid": user.id, "by": cart["members"][str(user.id)],
            "dish_id": dish_id,
            # 展示名带规格「油泼扯面(大份+微辣)」,和订单快照同一个写法
            "name": display,
            "price_cents": unit, "quantity": quantity,
            "choices": list(choices), "note": note,
        })
        if note and len(order_note_for(cart)) > GROUP_NOTE_MAX:
            raise HTTPException(
                422, f"这车拼单的备注加起来超过 {GROUP_NOTE_MAX} 个字了,写短一点")
    await _save_cart(cart)
    await _broadcast(cart, "items")
    return _view(cart, user.id)


def order_note_for(cart: dict) -> str:
    """把车里各道菜的备注拼成一句,并进订单备注(订单只有一份备注,后厨看的就是它)。

    只写菜(带规格)和备注,**不写是谁点的**:订单备注商家和骑手都看得到,
    同伴的昵称原来只在这车人之间可见,不该因为写了句「不要香菜」就给到商家。
    同一道菜两个人写了不同的备注,后厨照样分得清是两份。
    """
    parts = [f"{i['name']}:{i['note']}"
             for i in cart.get("items", []) if (i.get("note") or "").strip()]
    return ("拼单备注 " + ";".join(parts)) if parts else ""


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
