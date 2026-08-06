"""商家账号解析:一个 merchant-role 用户能操作哪家店。

层次(从窄到宽):
- **店主**:自己拥有的店(Merchant.owner_id)。
- **店员**:被单店授权(merchant_staff)。店员是门店雇的,不进品牌层。
- **品牌 owner**:名下品牌的全部门店。
- **品牌 manager**:品牌里被授权的那几家(shop_ids;空 = 全部门店)。

运营端点(接单/出餐/估清/看单)用 operable_shop,允许店员;
敏感端点(提现/改价/改设置/收款账户)用 owned_shop,店员一律拒。

## 连锁怎么接进来的

`resolve_shop(db, user, merchant_id)` 是**唯一的入口**,按这个顺序定店:
1. 显式传了 merchant_id → 用它;
2. 没传 → 读请求头 X-Shop-Id(客户端的门店选择器写的);
3. 还是没有 → 退化成"我的唯一一家店"(单店商家的老行为,一字不变);
4. 名下不止一家却没说是哪家 → **不猜,直接拒**。

拿到店之后一律走完整的权限校验 —— 所以第 2 步那个头只是"选哪家",
不是"有权限",伪造别家的 id 只会拿到 404。

一号一店的假设原先散在 80 多处调用点里,把判定收敛到这一个函数,
是为了让"漏一处就是越权(A 店店长能改 B 店的价)"这件事只可能发生在
一个地方 —— 而不是每加一个端点就多一次机会。

三档权限,按用途选:
- `operable_shop` 运营(接单/出餐/估清/看单):店员可以;
- `owned_shop`   店主级(改价/改设置/开放接口):店员拒,品牌授权者放行;
- `money_shop`   资金(钱包/提现/对账明细):**只认店铺登记的 owner 本人**,
  品牌层也不放行 —— 运营授权不等于可以把店里的钱提到自己卡上。
"""
from contextvars import ContextVar

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Brand, BrandMember, Merchant, MerchantStaff, User

# 当前请求选中的门店(来自 X-Shop-Id 头,由 main.py 的中间件写入)。
#
# **为什么用请求头而不是给 33 个端点各加一个 query 参数**:
# 连锁只是换了"这次操作哪家店",端点的语义一个都没变。
# 用头的话客户端在 API 客户端里设一次就够,服务端在权限解析这一处读,
# 端点签名一行不用改 —— 改 33 处签名的那个版本,漏一处就是一个
# 「切了门店但这个页面还在改老店」的 bug。
#
# 安全上这个头只是**选择**不是授权:resolve_shop 拿到它之后照样
# 走完整的权限校验,伪造一个别家的 id 只会拿到 404。
current_shop_id: ContextVar[int | None] = ContextVar(
    "current_shop_id", default=None)


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

    [merchant_id] 不传 = 先看请求头选了哪家(连锁),没有则退回
    "我唯一的那家店"(单店商家的老行为);
    传了 = 显式指定门店,**必须过权限校验**。
    [need_owner] True 时店员一律拒(提现/改价/改设置这类)。
    """
    if merchant_id is None:
        merchant_id = current_shop_id.get()
    brand_ids, brand_owner = await _brand_scope(db, user)

    if merchant_id is None:
        own = list(await db.scalars(
            select(Merchant).where(Merchant.owner_id == user.id)
            .order_by(Merchant.id).limit(2)))
        if len(own) == 1:
            return own[0], True
        # **名下不止一家店却没说是哪家:不猜。**
        # 老写法是 db.scalar(...),不带 ORDER BY —— 返回哪一家由数据库
        # 心情决定。单店时永远只有一个候选所以看不出问题,连锁一来就变成
        # 「切了门店,改的还是另一家的菜单和价格」,而且改成功了、没有报错。
        # 宁可 404 让客户端显式选,也不要静默改错店。
        if len(own) > 1:
            return None, False
        # 品牌成员(自己不拥有店)同理,让客户端走门店选择器
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


async def money_shop(
    db: AsyncSession, user: User, merchant_id: int | None = None,
) -> Merchant | None:
    """**资金动作专用**:必须是店铺登记的那个 owner 本人,品牌层不放行。

    与 owned_shop 的区别只有一句 `shop.owner_id == user.id`,但这一句
    是钱的边界。品牌 manager 在 owned_shop 里算"店主级权限"(能改价、
    改设置),那是运营授权;**运营授权不等于可以把店里的钱提到自己卡上**。

    具体的坑:钱包余额是按 `merchant_id` 算出来的(整店营收),而已提现
    是按 `user_id` 减的。这两个 id 一旦不是同一个人,就同时出两个洞 ——
    manager 能把整店余额提到自己的收款账户,而且店主那边的已提现不计入
    manager 的可提额度,两个人各提一次全额。所以资金路径只认 owner。
    """
    shop = await owned_shop(db, user, merchant_id)
    if shop is None or shop.owner_id != user.id:
        return None
    return shop
