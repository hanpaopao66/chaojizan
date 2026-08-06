"""商家账号解析:一个 merchant-role 用户能操作哪家店。

层次(从窄到宽):
- **店主**:自己拥有的店(Merchant.owner_id)。
- **店员**:被单店授权(merchant_staff)。店员是门店雇的,不进品牌层。
- **品牌 owner**:名下品牌的全部门店。
- **品牌 manager**:品牌里被授权的那几家(shop_ids;空 = 全部门店)。

运营端点(接单/出餐/估清/看单)用 operable_shop,允许店员;
敏感端点(提现/改价/改设置/收款账户)用 owned_shop,店员一律拒。

## 连锁怎么接进来的

`resolve_shop(db, user, merchant_id)` 是**唯一的入口**:
- 不传 merchant_id → 退化成"我的唯一一家店"(单店商家的老行为,一字不变);
- 传了 → 校验这个人对这家店到底有没有权限。

一号一店的假设原先散在 80 多处调用点里,把判定收敛到这一个函数,
是为了让"漏一处就是越权(A 店店长能改 B 店的价)"这件事只可能发生在
一个地方 —— 而不是每加一个端点就多一次机会。
"""
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Brand, BrandMember, Merchant, MerchantStaff, User


async def _brand_scope(db: AsyncSession, user: User) -> tuple[list[int], bool]:
    """这个人通过品牌能管到哪些店。返回 (门店 id 列表, 是否品牌 owner)。

    列表为空且不是 owner = 与品牌无关。
    owner 的范围是"名下品牌的全部门店",所以用 brand_id 查而不是列 id。
    """
    owned_brands = list(await db.scalars(
        select(Brand.id).where(Brand.owner_id == user.id)))
    if owned_brands:
        ids = list(await db.scalars(
            select(Merchant.id).where(Merchant.brand_id.in_(owned_brands))))
        return ids, True
    member = await db.scalar(
        select(BrandMember).where(BrandMember.user_id == user.id))
    if member is None:
        return [], False
    if member.shop_ids:
        # 授权范围内的店,但必须仍属于这个品牌(店被划走后授权自动失效)
        ids = list(await db.scalars(
            select(Merchant.id).where(
                Merchant.id.in_([int(i) for i in member.shop_ids]),
                Merchant.brand_id == member.brand_id)))
    else:
        ids = list(await db.scalars(
            select(Merchant.id).where(Merchant.brand_id == member.brand_id)))
    return ids, member.role == "owner"


async def my_shops(db: AsyncSession, user: User) -> list[Merchant]:
    """这个人能操作的全部门店(自己的店 + 品牌授权范围 + 被授权的店员店)。
    单店商家返回一个元素的列表。"""
    brand_ids, _ = await _brand_scope(db, user)
    staff_ids = list(await db.scalars(
        select(MerchantStaff.merchant_id).where(
            MerchantStaff.user_id == user.id)))
    rows = await db.scalars(
        select(Merchant).where(
            or_(Merchant.owner_id == user.id,
                Merchant.id.in_(brand_ids or [-1]),
                Merchant.id.in_(staff_ids or [-1])))
        .order_by(Merchant.id))
    return list(rows)


async def resolve_shop(
    db: AsyncSession, user: User, merchant_id: int | None = None,
    *, need_owner: bool = False,
) -> tuple[Merchant | None, bool]:
    """解析这个请求要操作哪家店,并校验权限。返回 (店, 是否具备店主级权限)。

    [merchant_id] 不传 = 单店商家的老行为(取我唯一的那家店);
    传了 = 连锁场景显式指定门店,**必须过权限校验**。
    [need_owner] True 时店员一律拒(提现/改价/改设置这类)。
    """
    brand_ids, brand_owner = await _brand_scope(db, user)

    if merchant_id is None:
        own = await db.scalar(
            select(Merchant).where(Merchant.owner_id == user.id))
        if own is not None:
            return own, True
        # 品牌成员没指定门店时不猜:连锁下"我的店"是有歧义的,
        # 让客户端显式选一家(总部视角的门店选择器就是干这个的)
        if brand_ids:
            return None, False
        if need_owner:
            return None, False
        link = await db.scalar(
            select(MerchantStaff).where(MerchantStaff.user_id == user.id))
        if link is not None:
            return await db.get(Merchant, link.merchant_id), False
        return None, False

    shop = await db.get(Merchant, merchant_id)
    if shop is None:
        return None, False
    if shop.owner_id == user.id:
        return shop, True
    if shop.id in brand_ids:
        # 品牌 owner 与被授权的 manager 都算店主级权限(改价/改设置);
        # 提现等资金动作另有 owner_id 校验,品牌层不绕过那道
        return shop, True
    if not need_owner:
        link = await db.scalar(
            select(MerchantStaff).where(
                MerchantStaff.user_id == user.id,
                MerchantStaff.merchant_id == shop.id))
        if link is not None:
            return shop, False
    return None, False


async def operable_shop(
    db: AsyncSession, user: User, merchant_id: int | None = None,
) -> tuple[Merchant | None, bool]:
    """运营端点用:允许店员。签名兼容老调用(不传 merchant_id)。"""
    return await resolve_shop(db, user, merchant_id)


async def owned_shop(
    db: AsyncSession, user: User, merchant_id: int | None = None,
) -> Merchant | None:
    """敏感端点用:店员一律拒,只有店主/品牌授权者拿得到店。"""
    shop, is_owner = await resolve_shop(db, user, merchant_id,
                                        need_owner=True)
    return shop if is_owner else None
