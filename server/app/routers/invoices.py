"""平台服务费发票:商家按自然月索取(外卖佣金 + 团购核销服务费)。

金额由系统聚合(佣金冲账负数行直接求和 = 净口径),商家不能自填;
只能申请已结束的自然月,一个月一张,金额为 0 不开。
管理员在后台线下开电子普票后回填 PDF 链接,商家端可查可下载。
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    InvoiceRequest,
    Merchant,
    MerchantEarning,
    User,
    VoucherPurchase,
    VoucherPurchaseStatus,
)
from ..security import require_role
from ..services.push import push_to_user

router = APIRouter(tags=["发票"])

CN_TZ = ZoneInfo("Asia/Shanghai")


class InvoiceApplyIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")  # 如 2026-06
    title: str = Field(min_length=2, max_length=100)
    tax_no: str = Field(min_length=6, max_length=30)
    email: str = Field(min_length=5, max_length=100, pattern=r".+@.+\..+")


class InvoiceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    period: str
    amount_cents: int
    title: str
    tax_no: str
    email: str
    status: str
    file_url: str
    note: str
    created_at: datetime
    processed_at: datetime | None


class AdminInvoiceOut(InvoiceOut):
    merchant_name: str = ""
    owner_phone: str = ""


def _period_bounds_utc(period: str) -> tuple[datetime, datetime]:
    """自然月边界(北京时间)转 UTC,聚合口径与商家对账/公开账本一致。"""
    year, month = int(period[:4]), int(period[5:7])
    start = datetime(year, month, 1, tzinfo=CN_TZ)
    end = (datetime(year + 1, 1, 1, tzinfo=CN_TZ) if month == 12
           else datetime(year, month + 1, 1, tzinfo=CN_TZ))
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _period_ended(period: str) -> bool:
    now_cn = datetime.now(CN_TZ)
    return period < f"{now_cn.year:04d}-{now_cn.month:02d}"


async def _month_fee(db: AsyncSession, merchant_id: int, period: str) -> dict:
    start, end = _period_bounds_utc(period)
    commission = await db.scalar(
        select(sa_func.coalesce(sa_func.sum(MerchantEarning.commission_cents), 0))
        .where(MerchantEarning.merchant_id == merchant_id,
               MerchantEarning.created_at >= start,
               MerchantEarning.created_at < end))
    voucher_fee = await db.scalar(
        select(sa_func.coalesce(sa_func.sum(VoucherPurchase.commission_cents), 0))
        .where(VoucherPurchase.merchant_id == merchant_id,
               VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
               VoucherPurchase.redeemed_at >= start,
               VoucherPurchase.redeemed_at < end))
    return {"period": period, "commission_cents": commission,
            "voucher_fee_cents": voucher_fee,
            "total_cents": commission + voucher_fee}


async def _my_shop(db: AsyncSession, user: User) -> Merchant:
    shop = await db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if shop is None:
        raise HTTPException(404, "还没开店")
    return shop


@router.get("/invoices/summary")
async def invoice_summary(
    period: str,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """某月可开票金额(佣金+团购服务费,冲账负数行已抵减)。"""
    if not (len(period) == 7 and period[4] == "-"):
        raise HTTPException(422, "月份格式应为 YYYY-MM")
    shop = await _my_shop(db, user)
    fee = await _month_fee(db, shop.id, period)
    existing = await db.scalar(
        select(InvoiceRequest.id).where(
            InvoiceRequest.merchant_id == shop.id,
            InvoiceRequest.period == period))
    return {**fee, "requested": existing is not None,
            "period_ended": _period_ended(period),
            "title": shop.invoice_title, "tax_no": shop.invoice_tax_no,
            "email": shop.invoice_email}


@router.get("/invoices/mine", response_model=list[InvoiceOut])
async def my_invoices(
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _my_shop(db, user)
    result = await db.scalars(
        select(InvoiceRequest).where(InvoiceRequest.merchant_id == shop.id)
        .order_by(InvoiceRequest.period.desc()).limit(36))
    return list(result)


@router.post("/invoices", response_model=InvoiceOut)
async def apply_invoice(
    payload: InvoiceApplyIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    """申请开票。抬头信息同时存回商家资料(下次自动带出)。"""
    if not _period_ended(payload.period):
        raise HTTPException(422, "只能为已结束的自然月开票(当月账还在变)")
    shop = await _my_shop(db, user)
    existing = await db.scalar(
        select(InvoiceRequest.id).where(
            InvoiceRequest.merchant_id == shop.id,
            InvoiceRequest.period == payload.period))
    if existing:
        raise HTTPException(409, "该月已申请过开票,处理进度见开票记录")
    fee = await _month_fee(db, shop.id, payload.period)
    if fee["total_cents"] <= 0:
        raise HTTPException(422, "该月平台服务费为 0,没有可开票金额")
    shop.invoice_title = payload.title.strip()
    shop.invoice_tax_no = payload.tax_no.strip()
    shop.invoice_email = payload.email.strip()
    invoice = InvoiceRequest(
        merchant_id=shop.id,
        period=payload.period,
        amount_cents=fee["total_cents"],
        title=shop.invoice_title,
        tax_no=shop.invoice_tax_no,
        email=shop.invoice_email,
    )
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice


# ---------- 管理端开票 ----------

@router.get("/admin/invoices", response_model=list[AdminInvoiceOut])
async def list_invoices(
    status: str | None = "pending",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = (select(InvoiceRequest, Merchant, User)
             .join(Merchant, Merchant.id == InvoiceRequest.merchant_id)
             .join(User, User.id == Merchant.owner_id)
             .order_by(InvoiceRequest.created_at.desc()).limit(200))
    if status in ("pending", "issued", "rejected"):
        query = query.where(InvoiceRequest.status == status)
    rows = await db.execute(query)
    out = []
    for invoice, shop, owner in rows:
        o = AdminInvoiceOut.model_validate(invoice)
        o.merchant_name, o.owner_phone = shop.name, owner.phone
        out.append(o)
    return out


class InvoiceIssueIn(BaseModel):
    file_url: str = Field(min_length=5, max_length=300)
    note: str = Field(default="", max_length=200)


@router.post("/admin/invoices/{invoice_id}/issue", response_model=AdminInvoiceOut)
async def issue_invoice(
    invoice_id: int,
    payload: InvoiceIssueIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """线下开好电子普票后回填 PDF 链接,商家端即可下载。"""
    invoice = await db.get(InvoiceRequest, invoice_id, with_for_update=True)
    if invoice is None:
        raise HTTPException(404, "开票申请不存在")
    if invoice.status != "pending":
        raise HTTPException(409, "该申请已处理过")
    invoice.status = "issued"
    invoice.file_url = payload.file_url.strip()
    invoice.note = payload.note.strip()
    invoice.processed_at = datetime.now(timezone.utc)
    shop = await db.get(Merchant, invoice.merchant_id)
    await db.commit()
    await db.refresh(invoice)
    await push_to_user(shop.owner_id, "发票已开具",
                       f"{invoice.period} 平台服务费发票"
                       f"(¥{invoice.amount_cents / 100:.2f})已开具,"
                       f"可在对账页开票记录中下载",
                       {"type": "invoice"})
    out = AdminInvoiceOut.model_validate(invoice)
    out.merchant_name = shop.name
    return out


@router.post("/admin/invoices/{invoice_id}/reject", response_model=AdminInvoiceOut)
async def reject_invoice(
    invoice_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """驳回(抬头/税号有误等);商家改好资料可重新申请该月。"""
    reason = (payload.get("reason") or "").strip()
    if len(reason) < 2:
        raise HTTPException(422, "驳回必须填写原因(会展示给商家)")
    invoice = await db.get(InvoiceRequest, invoice_id, with_for_update=True)
    if invoice is None:
        raise HTTPException(404, "开票申请不存在")
    if invoice.status != "pending":
        raise HTTPException(409, "该申请已处理过")
    # 驳回即删除记录:该月可重新申请(唯一约束不挡道),原因走推送告知
    period, amount, shop_id = invoice.period, invoice.amount_cents, invoice.merchant_id
    shop = await db.get(Merchant, shop_id)
    await db.delete(invoice)
    await db.commit()
    await push_to_user(shop.owner_id, "开票申请被退回",
                       f"{period} 开票申请被退回:{reason}。修改抬头信息后可重新申请",
                       {"type": "invoice"})
    return AdminInvoiceOut(
        id=invoice_id, period=period, amount_cents=amount,
        title="", tax_no="", email="", status="rejected", file_url="",
        note=reason, created_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc), merchant_name=shop.name)
