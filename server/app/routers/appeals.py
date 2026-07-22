"""判责申诉:骑手/商家对平台单方裁决的复核通道。

可申诉的三类目标(72 小时内、每个目标一次):
- after_sale     商家申诉「商家责任」售后判责
- delivery_issue 骑手申诉「骑手责任先行赔付」裁决
- review         商家申诉恶意差评

改判的钱怎么走(平台认亏,不追用户款——用户拿到的退款不倒找):
- after_sale 改判  → merchant_earnings 补一条 adjustment 正向行,恢复被冲净额
                     (账本 net == food - 0 恒等式成立,witness 可验)
- delivery_issue 改判 → 对应 AfterSale.fault: rider → platform(骑手消责正名,
                        审计规则 6 的先行赔付豁免口径同步认 platform)
- review 改判      → 差评 hidden,评分聚合同步扣减
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    AfterSale,
    Appeal,
    DeliveryIssue,
    EarningKind,
    Merchant,
    MerchantEarning,
    Order,
    Review,
    User,
)
from ..security import require_role
from ..services.push import push_to_user

router = APIRouter(tags=["判责申诉"])

APPEAL_WINDOW = timedelta(hours=72)

_TYPE_LABELS = {
    "after_sale": "售后判责",
    "delivery_issue": "配送异常裁决",
    "review": "差评",
}


class AppealIn(BaseModel):
    target_type: Literal["after_sale", "delivery_issue", "review"]
    target_id: int
    reason: str = Field(min_length=5, max_length=500)
    images: list[str] = Field(default=[], max_length=6)


class AppealOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    target_type: str
    target_id: int
    reason: str
    images: list = []
    status: str
    resolve_note: str
    created_at: datetime
    resolved_at: datetime | None


class AdminAppealOut(AppealOut):
    role: str = ""
    name: str = ""
    phone: str = ""
    target_summary: str = ""   # 被申诉裁决的现场信息,复核不用翻库


class AppealResolveIn(BaseModel):
    result: Literal["upheld", "overturned"]
    note: str = Field(default="", max_length=300)


def _within_window(decided_at: datetime | None) -> bool:
    if decided_at is None:
        return False
    if decided_at.tzinfo is None:
        decided_at = decided_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - decided_at < APPEAL_WINDOW


async def _validate_target(db: AsyncSession, user: User, payload: AppealIn):
    """校验目标存在、归属申诉人、确属可申诉的裁决且在时限内。"""
    if payload.target_type == "after_sale":
        if user.role.value != "merchant":
            raise HTTPException(403, "售后判责只有商家可以申诉")
        a = await db.get(AfterSale, payload.target_id)
        shop = await db.scalar(
            select(Merchant).where(Merchant.owner_id == user.id))
        if a is None or shop is None or a.merchant_id != shop.id:
            raise HTTPException(404, "售后记录不存在")
        if a.status.value != "accepted" or a.fault == "rider":
            raise HTTPException(409, "只有判商家责任的已退款售后才需要申诉")
        if not _within_window(a.processed_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    elif payload.target_type == "delivery_issue":
        if user.role.value != "rider":
            raise HTTPException(403, "配送异常裁决只有骑手可以申诉")
        issue = await db.get(DeliveryIssue, payload.target_id)
        if issue is None or issue.rider_id != user.id:
            raise HTTPException(404, "异常记录不存在")
        if issue.status != "resolved" or issue.resolution != "refund":
            raise HTTPException(409, "只有判骑手责任(先行赔付)的裁决才需要申诉")
        if not _within_window(issue.resolved_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    else:  # review
        if user.role.value != "merchant":
            raise HTTPException(403, "差评只有商家可以申诉")
        review = await db.get(Review, payload.target_id)
        shop = await db.scalar(
            select(Merchant).where(Merchant.owner_id == user.id))
        if review is None or shop is None or review.merchant_id != shop.id:
            raise HTTPException(404, "评价不存在")
        if review.hidden:
            raise HTTPException(409, "该评价已被隐藏,无需申诉")
        if review.merchant_rating > 3:
            raise HTTPException(409, "只有 3 星及以下的差评可以申诉")
        if not _within_window(review.created_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")


@router.post("/appeals", response_model=AppealOut)
async def submit_appeal(
    payload: AppealIn,
    user: User = Depends(require_role("rider", "merchant")),
    db: AsyncSession = Depends(get_db),
):
    await _validate_target(db, user, payload)
    existing = await db.scalar(
        select(Appeal.id).where(
            Appeal.target_type == payload.target_type,
            Appeal.target_id == payload.target_id))
    if existing:
        raise HTTPException(409, "该裁决已申诉过,平台复核结果为准")
    appeal = Appeal(
        user_id=user.id,
        role=user.role.value,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason.strip(),
        images=payload.images,
    )
    db.add(appeal)
    await db.commit()
    await db.refresh(appeal)
    return appeal


@router.get("/appeals/mine", response_model=list[AppealOut])
async def my_appeals(
    user: User = Depends(require_role("rider", "merchant")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(Appeal).where(Appeal.user_id == user.id)
        .order_by(Appeal.created_at.desc()).limit(50))
    return list(result)


# ---------- 管理端复核 ----------

async def _target_summary(db: AsyncSession, appeal: Appeal) -> str:
    if appeal.target_type == "after_sale":
        a = await db.get(AfterSale, appeal.target_id)
        if a is None:
            return "(记录不存在)"
        order = await db.get(Order, a.order_id)
        return (f"售后判商家责 订单#{order.order_no[-6:]} "
                f"退款 ¥{order.refund_cents / 100:.2f}:{a.reason[:40]}")
    if appeal.target_type == "delivery_issue":
        issue = await db.get(DeliveryIssue, appeal.target_id)
        if issue is None:
            return "(记录不存在)"
        return (f"配送异常判骑手责 订单#{issue.order_no[-6:]} "
                f"kind={issue.kind}:{issue.note[:40]}")
    review = await db.get(Review, appeal.target_id)
    if review is None:
        return "(记录不存在)"
    return f"{review.merchant_rating} 星差评:{review.comment[:60]}"


@router.get("/admin/appeals", response_model=list[AdminAppealOut])
async def list_appeals(
    status: str | None = "open",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = (select(Appeal, User).join(User, User.id == Appeal.user_id)
             .order_by(Appeal.created_at.desc()).limit(200))
    if status in ("open", "upheld", "overturned"):
        query = query.where(Appeal.status == status)
    rows = await db.execute(query)
    out = []
    for appeal, applicant in rows:
        o = AdminAppealOut.model_validate(appeal)
        o.role, o.name, o.phone = appeal.role, applicant.name, applicant.phone
        o.target_summary = await _target_summary(db, appeal)
        out.append(o)
    return out


async def _overturn(db: AsyncSession, appeal: Appeal, note: str) -> None:
    """改判动作。平台认亏:用户已得的退款不追回。"""
    if appeal.target_type == "after_sale":
        a = await db.get(AfterSale, appeal.target_id, with_for_update=True)
        earning = await db.scalar(select(MerchantEarning).where(
            MerchantEarning.order_id == a.order_id,
            MerchantEarning.kind == EarningKind.earning))
        already = await db.scalar(select(MerchantEarning.id).where(
            MerchantEarning.order_id == a.order_id,
            MerchantEarning.kind == EarningKind.adjustment))
        if earning is None or already:
            raise HTTPException(409, "该订单无可恢复的净额或已调整过")
        db.add(MerchantEarning(
            merchant_id=earning.merchant_id,
            order_id=earning.order_id,
            order_no=earning.order_no,
            food_cents=earning.net_cents,   # 调整行口径:net == food - 0,账本恒等
            commission_cents=0,
            net_cents=earning.net_cents,
            kind=EarningKind.adjustment,
            note=f"申诉改判,恢复商家净额:{note or '复核认定商家无责'}",
        ))
        a.fault = "platform"  # 责任转平台承担,审计豁免口径同步
        a.reply = (f"{a.reply};申诉改判:商家无责" if a.reply else "申诉改判:商家无责")[:300]
        await push_to_user(appeal.user_id, "申诉成立",
                           f"售后判责已改判,净额 ¥{earning.net_cents / 100:.2f} 已恢复入账",
                           {"type": "appeal"})
    elif appeal.target_type == "delivery_issue":
        issue = await db.get(DeliveryIssue, appeal.target_id, with_for_update=True)
        a = await db.scalar(select(AfterSale).where(
            AfterSale.order_id == issue.order_id, AfterSale.fault == "rider")
            .with_for_update())
        if a is not None:
            a.fault = "platform"
            a.reply = (f"{a.reply};骑手申诉改判:非骑手责任"
                       if a.reply else "骑手申诉改判:非骑手责任")[:300]
        issue.resolve_note = (f"{issue.resolve_note};申诉改判:非骑手责任"
                              if issue.resolve_note else "申诉改判:非骑手责任")[:300]
        await push_to_user(appeal.user_id, "申诉成立(已为你正名)",
                           "复核认定该次配送异常非你的责任,责任记录已消除",
                           {"type": "appeal"})
    else:  # review
        review = await db.get(Review, appeal.target_id, with_for_update=True)
        if review.hidden:
            raise HTTPException(409, "该评价已隐藏")
        review.hidden = True
        shop = await db.get(Merchant, review.merchant_id, with_for_update=True)
        shop.rating_sum = max(0, shop.rating_sum - review.merchant_rating)
        shop.rating_count = max(0, shop.rating_count - 1)
        await push_to_user(appeal.user_id, "申诉成立",
                           "该条差评已隐藏,不再计入店铺评分",
                           {"type": "appeal"})


@router.post("/admin/appeals/{appeal_id}/resolve", response_model=AdminAppealOut)
async def resolve_appeal(
    appeal_id: int,
    payload: AppealResolveIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    appeal = await db.get(Appeal, appeal_id, with_for_update=True)
    if appeal is None:
        raise HTTPException(404, "申诉不存在")
    if appeal.status != "open":
        raise HTTPException(409, "该申诉已复核过")
    if payload.result == "overturned":
        await _overturn(db, appeal, payload.note)
    else:
        await push_to_user(
            appeal.user_id, "申诉复核结果",
            f"经复核维持原判({_TYPE_LABELS[appeal.target_type]})。"
            f"{payload.note or '如有新证据可通过客服工单反馈'}",
            {"type": "appeal"})
    appeal.status = payload.result
    appeal.resolve_note = payload.note.strip()
    appeal.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(appeal)
    applicant = await db.get(User, appeal.user_id)
    out = AdminAppealOut.model_validate(appeal)
    out.role, out.name, out.phone = appeal.role, applicant.name, applicant.phone
    out.target_summary = await _target_summary(db, appeal)
    return out
