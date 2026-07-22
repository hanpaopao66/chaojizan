"""团购券:商家发券 → 用户购买 → 到店核销 → 透明分账。

三场景愿景的第二块。资金姿态与外卖一致:
- 服务费 2% 只在核销时收——券没被使用,平台一分不赚
- 未使用的券随时全额退(对用户友好,商家资金也没被占用:钱在核销前不算商家的)
- 支付走与外卖同一入口语义(mock/微信),超时 15 分钟自动关闭回补库存
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import (
    Merchant,
    MerchantStatus,
    User,
    Voucher,
    VoucherPurchase,
    VoucherPurchaseStatus,
)
from ..ratelimit import check_rate_limit
from ..schemas import (
    VoucherIn,
    VoucherOut,
    VoucherPatch,
    VoucherPurchaseOut,
    VoucherRedeemIn,
)
from ..security import require_role

router = APIRouter(prefix="/vouchers", tags=["团购券"])

ACTIVE_HOLD = (VoucherPurchaseStatus.pending_payment, VoucherPurchaseStatus.paid,
               VoucherPurchaseStatus.redeemed)


async def _my_shop(db: AsyncSession, user: User) -> Merchant:
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "还没有已过审的店铺")
    return shop


def _deal_out(v: Voucher, shop: Merchant | None = None) -> VoucherOut:
    out = VoucherOut.model_validate(v)
    if shop is not None:
        out.merchant_name = shop.name
        out.merchant_logo = shop.logo_url
    return out


def _purchase_out(p: VoucherPurchase, v: Voucher | None = None,
                  shop: Merchant | None = None) -> VoucherPurchaseOut:
    out = VoucherPurchaseOut.model_validate(p)
    if v is not None:
        out.title = v.title
    if shop is not None:
        out.merchant_name = shop.name
        out.merchant_address = shop.address
        out.merchant_lat = shop.lat
        out.merchant_lng = shop.lng
    # 过期是查询时判定的视图状态,不物理改写(核销接口同样会拒绝过期券)
    if (p.status == VoucherPurchaseStatus.paid and p.expires_at is not None
            and p.expires_at < datetime.now(timezone.utc)):
        out.expired = True
    return out


# ---------- 商家侧 ----------
@router.post("", response_model=VoucherOut)
async def create_voucher(
    payload: VoucherIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_shop(db, user)
    if payload.sell_price_cents >= payload.face_value_cents:
        raise HTTPException(422, "售价必须低于面值,否则用户没有理由买券")
    voucher = Voucher(merchant_id=shop.id, **payload.model_dump())
    db.add(voucher)
    await db.commit()
    await db.refresh(voucher)
    # 收藏触达:上新券推给收藏了本店的用户(每店每天最多一条,失败不影响发券)
    from ..services.push import notify_favorites

    await notify_favorites(
        db, shop.id, shop.name,
        f"你收藏的「{shop.name}」上新团购券",
        f"{voucher.title}:¥{voucher.sell_price_cents / 100:g} "
        f"抵 ¥{voucher.face_value_cents / 100:g},未使用随时全额退")
    return _deal_out(voucher, shop)


@router.get("/mine", response_model=list[VoucherOut])
async def my_vouchers(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_shop(db, user)
    rows = await db.scalars(
        select(Voucher).where(Voucher.merchant_id == shop.id)
        .order_by(Voucher.created_at.desc()))
    return [_deal_out(v, shop) for v in rows]


@router.patch("/{voucher_id}", response_model=VoucherOut)
async def update_voucher(
    voucher_id: int,
    payload: VoucherPatch,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_shop(db, user)
    voucher = await db.get(Voucher, voucher_id)
    if voucher is None or voucher.merchant_id != shop.id:
        raise HTTPException(404, "券不存在")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(voucher, field, value)
    await db.commit()
    await db.refresh(voucher)
    return _deal_out(voucher, shop)


# ---------- 用户侧 ----------
@router.get("", response_model=list[VoucherOut])
async def list_deals(db: AsyncSession = Depends(get_db)):
    """在售团购(已过审商家的上架券,还有库存)。"""
    rows = await db.execute(
        select(Voucher, Merchant)
        .join(Merchant, Merchant.id == Voucher.merchant_id)
        .where(Voucher.is_active.is_(True), Voucher.total_count > 0,
               Merchant.status == MerchantStatus.approved)
        .order_by(Voucher.sold_count.desc())
        .limit(100))
    return [_deal_out(v, shop) for v, shop in rows]


@router.post("/{voucher_id}/purchase", response_model=VoucherPurchaseOut)
async def purchase(
    voucher_id: int,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit("voucher", str(user.id), 10)
    voucher = await db.get(Voucher, voucher_id)
    if voucher is None or not voucher.is_active:
        raise HTTPException(409, "该团购已下架")
    held = await db.scalar(
        select(sa_func.count(VoucherPurchase.id)).where(
            VoucherPurchase.voucher_id == voucher_id,
            VoucherPurchase.customer_id == user.id,
            VoucherPurchase.status.in_(ACTIVE_HOLD)))
    if held >= voucher.per_user_limit:
        raise HTTPException(409, f"每人限购 {voucher.per_user_limit} 张")
    # 条件 UPDATE 扣库存,与外卖菜品同一防超卖手法
    result = await db.execute(
        update(Voucher)
        .where(Voucher.id == voucher_id, Voucher.total_count > 0)
        .values(total_count=Voucher.total_count - 1,
                sold_count=Voucher.sold_count + 1))
    if result.rowcount == 0:
        raise HTTPException(409, "手慢了,已售罄")
    p = VoucherPurchase(
        purchase_no=uuid.uuid4().hex[:20],
        voucher_id=voucher_id,
        merchant_id=voucher.merchant_id,
        customer_id=user.id,
        sell_price_cents=voucher.sell_price_cents,
        face_value_cents=voucher.face_value_cents,
        code=f"{secrets.randbelow(10**12):012d}",
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _purchase_out(p, voucher)


@router.post("/purchases/{purchase_no}/pay/mock", response_model=VoucherPurchaseOut)
async def pay_mock(
    purchase_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """模拟支付(与外卖同语义;微信支付联调时替换为统一下单+回调)。幂等。"""
    p = await db.scalar(
        select(VoucherPurchase)
        .where(VoucherPurchase.purchase_no == purchase_no).with_for_update())
    if p is None or p.customer_id != user.id:
        raise HTTPException(404, "购买记录不存在")
    if p.status == VoucherPurchaseStatus.paid:
        return _purchase_out(p)
    if p.status != VoucherPurchaseStatus.pending_payment:
        raise HTTPException(409, "该券不是待支付状态")
    voucher = await db.get(Voucher, p.voucher_id)
    p.status = VoucherPurchaseStatus.paid
    p.paid_at = datetime.now(timezone.utc)
    p.expires_at = p.paid_at + timedelta(days=voucher.valid_days)
    await db.commit()
    await db.refresh(p)
    return _purchase_out(p, voucher)


@router.get("/purchases/mine", response_model=list[VoucherPurchaseOut])
async def my_purchases(
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(VoucherPurchase, Voucher, Merchant)
        .join(Voucher, Voucher.id == VoucherPurchase.voucher_id)
        .join(Merchant, Merchant.id == VoucherPurchase.merchant_id)
        .where(VoucherPurchase.customer_id == user.id)
        .order_by(VoucherPurchase.created_at.desc())
        .limit(100))
    return [_purchase_out(p, v, shop) for p, v, shop in rows]


@router.post("/purchases/{purchase_no}/refund", response_model=VoucherPurchaseOut)
async def refund_purchase(
    purchase_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """未使用的券随时全额退——不玩「过期不退」的把戏。

    模拟通道即时退;微信联调后走真实原路退回(券款在核销前不属于商家,
    平台也没收服务费,退款没有任何冲账负担)。
    """
    p = await db.scalar(
        select(VoucherPurchase)
        .where(VoucherPurchase.purchase_no == purchase_no).with_for_update())
    if p is None or p.customer_id != user.id:
        raise HTTPException(404, "券不存在")
    if p.status != VoucherPurchaseStatus.paid:
        raise HTTPException(409, "只有已购未使用的券可以退款")
    p.status = VoucherPurchaseStatus.refunded
    p.refund_note = "用户申请退款(未使用,全额)"
    # 库存回补,别人还能买
    await db.execute(update(Voucher).where(Voucher.id == p.voucher_id)
                     .values(total_count=Voucher.total_count + 1,
                             sold_count=Voucher.sold_count - 1))
    await db.commit()
    await db.refresh(p)
    return _purchase_out(p)


# ---------- 核销(商家) ----------
@router.post("/redeem", response_model=VoucherPurchaseOut)
async def redeem(
    payload: VoucherRedeemIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """输码核销:核验归属/状态/有效期 → 落定分账(净额 = 售价 - 2% 服务费)。"""
    shop = await _my_shop(db, user)
    p = await db.scalar(
        select(VoucherPurchase)
        .where(VoucherPurchase.code == payload.code.strip()).with_for_update())
    if p is None or p.merchant_id != shop.id:
        raise HTTPException(404, "券码不存在或不属于本店")
    if p.status == VoucherPurchaseStatus.redeemed:
        raise HTTPException(409, "该券已核销过,不能重复使用")
    if p.status != VoucherPurchaseStatus.paid:
        raise HTTPException(409, "该券未支付或已退款")
    if p.expires_at is not None and p.expires_at < datetime.now(timezone.utc):
        raise HTTPException(409, "该券已过期")
    p.status = VoucherPurchaseStatus.redeemed
    p.redeemed_at = datetime.now(timezone.utc)
    p.commission_cents = int(
        Decimal(p.sell_price_cents) * Decimal(str(settings.voucher_commission_rate)))
    p.net_cents = p.sell_price_cents - p.commission_cents
    await db.commit()
    await db.refresh(p)
    voucher = await db.get(Voucher, p.voucher_id)
    return _purchase_out(p, voucher)
