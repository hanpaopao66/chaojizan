"""商家子账号解析:一个 merchant-role 用户能操作哪家店。

- 店主:自己拥有的店(owner_id)。
- 店员:被授权的店(merchant_staff)。
运营端点(接单/出餐/估清/看单)用 operable_shop 解析店铺,允许店员;
敏感端点(提现/改价/改设置/收款账户)仍按 Merchant.owner_id 鉴权,
店员非店主自然被拒——无需额外改动那些端点。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Merchant, MerchantStaff, User


async def operable_shop(db: AsyncSession, user: User) -> tuple[Merchant | None, bool]:
    """返回 (可操作的店, 是否店主)。店员返回 (店, False);都不是返回 (None, False)。"""
    own = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if own is not None:
        return own, True
    link = await db.scalar(
        select(MerchantStaff).where(MerchantStaff.user_id == user.id))
    if link is not None:
        shop = await db.get(Merchant, link.merchant_id)
        return shop, False
    return None, False
