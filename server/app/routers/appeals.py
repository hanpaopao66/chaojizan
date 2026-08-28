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
    OrderEvent,
    Review,
    User,
)
from ..security import require_role
from ..state_machine import OrderStatus
from ..services.push import push_to_user
from ..services.staff import owned_shop

router = APIRouter(tags=["判责申诉"])

APPEAL_WINDOW = timedelta(hours=72)

#: 申诉改判退款的备注前缀。**审计靠它认出"这笔多退的钱是平台认亏"** ——
#: 分摊单本来是"商家 + 骑手 + 退款 == 用户实付",平台补退之后这个等式
#: 会多出一块,不认得它的话审计每次改判都报一条假红灯。
#: 定义在这里,services/audit.py 从这儿读,不另抄一份。
APPEAL_REFUND_NOTE = "申诉改判:平台承担,原路退回"

_TYPE_LABELS = {
    "after_sale": "售后判责",
    "delivery_issue": "配送异常裁决",
    "review": "差评",
    "cancel_split": "取消订单的判责分摊",
}


class AppealIn(BaseModel):
    target_type: Literal["after_sale", "delivery_issue", "review",
                         "cancel_split"]
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


def appeal_cutoff(now: datetime | None = None) -> datetime:
    """窗口起点:比这个时刻更早的裁决已经申诉不了了。

    给 SQL 的 WHERE 用 —— 数「还有几单来得及申诉」时不可能对每一行调
    [within_window]。**它和 [within_window] 必须严格互为反面**,
    不然商家端角标说有 2 单可申诉,点进去提交却被 422 挡回来。
    """
    return (now or datetime.now(timezone.utc)) - APPEAL_WINDOW


def within_window(decided_at: datetime | None,
                  now: datetime | None = None) -> bool:
    """这条裁决还在申诉窗口里吗。

    `decided_at` 为空 = 还没判过责,没有东西可申诉。

    ⚠️ 数据库取出来的 datetime 可能是 naive 的,**一律当 UTC 解读** ——
    当成本地时间的话东八区会凭空多出 8 小时窗口,
    前端放行、后端 422。
    """
    if decided_at is None:
        return False
    if decided_at.tzinfo is None:
        decided_at = decided_at.replace(tzinfo=timezone.utc)
    return decided_at > appeal_cutoff(now)


# 旧名保留:本文件内三处校验都在用
_within_window = within_window


async def _validate_target(db: AsyncSession, user: User, payload: AppealIn):
    """校验目标存在、归属申诉人、确属可申诉的裁决且在时限内。"""
    if payload.target_type == "after_sale":
        if user.role.value != "merchant":
            raise HTTPException(403, "售后判责只有商家可以申诉")
        a = await db.get(AfterSale, payload.target_id)
        shop = await owned_shop(db, user)
        if a is None or shop is None or a.merchant_id != shop.id:
            raise HTTPException(404, "售后记录不存在")
        if a.status.value != "accepted" or a.fault == "rider":
            raise HTTPException(409, "只有判商家责任的已退款售后才需要申诉")
        if not _within_window(a.processed_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    elif payload.target_type == "delivery_issue":
        # 骑手申诉判他责的(先行赔付),用户申诉判**用户**责的(按送达处理)。
        #
        # 用户这一侧以前是空的,而那恰恰是最不公平的一格:骑手报「联系不上
        # 顾客」、平台判 mark_delivered,于是用户付了全款、一口没吃到,
        # **连说话的地方都没有**。判谁责,谁就该能申诉 —— 这是对称的,
        # 不该只对骑手成立。
        issue = await db.get(DeliveryIssue, payload.target_id)
        if issue is None:
            raise HTTPException(404, "异常记录不存在")
        if issue.status != "resolved":
            raise HTTPException(409, "这条异常还没有裁决结果")
        if user.role.value == "rider":
            if issue.rider_id != user.id:
                raise HTTPException(404, "异常记录不存在")
            if issue.resolution != "refund":
                raise HTTPException(409, "只有判骑手责任(先行赔付)的裁决才需要申诉")
        elif user.role.value == "customer":
            order = await db.get(Order, issue.order_id)
            if order is None or order.customer_id != user.id:
                raise HTTPException(404, "异常记录不存在")
            if issue.resolution != "mark_delivered":
                raise HTTPException(409, "只有判用户责任(按送达处理)的裁决才需要申诉")
        else:
            raise HTTPException(403, "配送异常裁决只有当事的骑手或用户可以申诉")
        if not _within_window(issue.resolved_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    elif payload.target_type == "cancel_split":
        # 出餐后取消的分摊是**系统按口径自动判的**,没有人看过。
        # 自动判责必须配一个能找人的口子,否则"谁的问题谁负责"里的
        # 「谁的问题」就成了系统单方面说了算。
        if user.role.value != "customer":
            raise HTTPException(403, "取消分摊只有下单的用户可以申诉")
        order = await db.get(Order, payload.target_id)
        if order is None or order.customer_id != user.id:
            raise HTTPException(404, "订单不存在")
        if order.status != OrderStatus.CANCELLED:
            raise HTTPException(409, "这一单没有被取消,没有分摊结果可申诉")
        from ..services.liability import SPLIT_EARNING_NOTE
        went_split = await db.scalar(select(MerchantEarning.id).where(
            MerchantEarning.order_id == order.id,
            MerchantEarning.kind == EarningKind.earning,
            MerchantEarning.note.like(SPLIT_EARNING_NOTE + "%")))
        if went_split is None:
            raise HTTPException(409, "这一单是全额退款,没有分摊,不需要申诉")
        # 窗口从**取消那一刻**起算,取订单事件里那条,别拿 updated_at 凑合
        cancelled_at = await db.scalar(
            select(OrderEvent.created_at)
            .where(OrderEvent.order_id == order.id,
                   OrderEvent.to_status == OrderStatus.CANCELLED.value)
            .order_by(OrderEvent.created_at.desc()).limit(1))
        if not _within_window(cancelled_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    else:  # review
        if user.role.value != "merchant":
            raise HTTPException(403, "差评只有商家可以申诉")
        review = await db.get(Review, payload.target_id)
        shop = await owned_shop(db, user)
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
    user: User = Depends(require_role("rider", "merchant", "customer")),
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
    user: User = Depends(require_role("rider", "merchant", "customer")),
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
    summary = f"{review.merchant_rating} 星差评:{review.comment[:60]}"
    # 自动附配送证据:接单/出餐/送达时间线摆在审核员面前 ——
    # 配送超时导致的差评不该商家背,但商家自己举证不到平台的数据
    order = await db.get(Order, review.order_id)
    if order is not None:
        from ..models import OrderEvent
        events: dict[str, datetime] = {}
        for e in await db.scalars(
                select(OrderEvent).where(OrderEvent.order_id == order.id)
                .order_by(OrderEvent.created_at)):
            events.setdefault(e.to_status, e.created_at)

        def hhmm(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (dt + timedelta(hours=8)).strftime("%H:%M")

        parts = []
        if "accepted" in events:
            parts.append(f"接单 {hhmm(events['accepted'])}")
        if "ready" in events:
            parts.append(f"出餐 {hhmm(events['ready'])}"
                         + ("(出餐超时)" if order.ready_late else ""))
        if "delivered" in events:
            delivered = events["delivered"]
            note = f"送达 {hhmm(delivered)}"
            eta = order.eta_at
            if eta is not None:
                if eta.tzinfo is None:
                    eta = eta.replace(tzinfo=timezone.utc)
                if delivered.tzinfo is None:
                    delivered = delivered.replace(tzinfo=timezone.utc)
                late = int((delivered - eta).total_seconds() // 60)
                if late > 0:
                    note += f"(比预计晚 {late} 分钟"
                    note += ",出餐正常,系配送/等待因素)" \
                        if not order.ready_late else ")"
            parts.append(note)
        if parts:
            summary += " | 配送证据:" + "、".join(parts)
    return summary


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
        if appeal.role == "customer":
            # 用户申诉的是「按送达处理」那类裁决:他付了全款、一口没吃到。
            # 改判就得把钱退回去,只说一句"记录消除"对他毫无意义。
            order = await db.get(Order, issue.order_id, with_for_update=True)
            borne = (max(order.food_cents + order.packing_fee_cents
                         - order.discount_cents, 0) - order.refund_cents)
            if borne > 0:
                from ..services.wechat_pay import request_refund
                await request_refund(db, order, borne, APPEAL_REFUND_NOTE)
            issue.resolve_note = (f"{issue.resolve_note};申诉改判:非用户责任"
                                  )[:300]
            await push_to_user(
                appeal.user_id, "申诉成立",
                f"复核认定这一单不是你的责任,¥{borne / 100:.2f} 已原路退回"
                if borne > 0 else "复核认定这一单不是你的责任",
                {"type": "appeal"})
        else:
            await push_to_user(appeal.user_id, "申诉成立(已为你正名)",
                               "复核认定该次配送异常非你的责任,责任记录已消除",
                               {"type": "appeal"})
    elif appeal.target_type == "cancel_split":
        # 改判 = 平台认定这一单不该由用户承担。
        #
        # **不向商家和骑手追款。** 他们各自把该做的做完了(餐做好了、路跑了),
        # 把已经发出去的钱要回来,等于让他们为平台的一次判断失误买单 ——
        # 与既有立场「改判平台认亏」一致(见本函数 docstring)。
        # 所以这笔由平台掏,走退款通道原路退给用户。
        #
        # 若复核认定确属**商家**责任,那是另一条路径(售后冲账),
        # 不在这里混着做 —— 一个动作只做一件事,账才查得清。
        order = await db.get(Order, appeal.target_id, with_for_update=True)
        borne = (max(order.food_cents + order.packing_fee_cents
                     - order.discount_cents, 0)
                 + order.delivery_fee_cents + order.tip_cents
                 - order.refund_cents)
        if borne <= 0:
            raise HTTPException(409, "这一单用户没有承担任何金额,无可改判")
        from ..services.wechat_pay import request_refund
        await request_refund(db, order, borne, APPEAL_REFUND_NOTE)
        order.cancel_reason = (f"{order.cancel_reason};申诉改判:非用户责任,"
                               f"平台承担")[:200]
        await push_to_user(
            appeal.user_id, "申诉成立",
            f"复核认定这一单不该由你承担,¥{borne / 100:.2f} 已原路退回",
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
