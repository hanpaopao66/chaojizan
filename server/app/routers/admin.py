import logging
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy import text as text_sql
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    DeliveryIssue,
    Merchant,
    MerchantStatus,
    PlatformFlag,
    RiderProfile,
    User,
    VerifyStatus,
    Withdrawal,
    WithdrawalStatus,
)
from ..schemas import (
    AdminFoodSafetyOut,
    AdminMerchantOut,
    AdminRiderProfileOut,
    AdminWithdrawalOut,
    BatchPaidIn,
    DeliveryIssueOut,
    DeliveryIssueResolveIn,
    AppealVerdictIn,
    FoodSafetyActionIn,
    PaidNoteIn,
    RejectIn,
)
from ..security import require_role

router = APIRouter(prefix="/admin", tags=["管理后台"])
logger = logging.getLogger("superz.admin")


def _to_out(shop: Merchant, owner: User) -> AdminMerchantOut:
    out = AdminMerchantOut.model_validate(shop)
    out.license_no = shop.license_no
    out.owner_name = owner.name
    out.owner_phone = owner.phone
    out.created_at = shop.created_at
    return out


@router.get("/merchants", response_model=list[AdminMerchantOut])
async def list_merchants(
    status: MerchantStatus | None = None,
    city: str = "",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Merchant, User)
        .join(User, User.id == Merchant.owner_id)
        .order_by(Merchant.created_at.desc())
        .limit(200)
    )
    if status is not None:
        query = query.where(Merchant.status == status)
    if city:
        query = query.where(Merchant.city == city)
    rows = await db.execute(query)
    outs = [_to_out(shop, owner) for shop, owner in rows]
    # 酒店业态的第二证照(特种行业许可证等),一次聚合查询回填
    hotel_ids = [o.id for o in outs if o.biz_type == "hotel"]
    if hotel_ids:
        from ..models import HotelProfile
        profiles = await db.scalars(
            select(HotelProfile).where(HotelProfile.merchant_id.in_(hotel_ids)))
        by_mid = {p.merchant_id: p for p in profiles}
        for out in outs:
            p = by_mid.get(out.id)
            if p is not None:
                out.special_license_no = p.special_license_no
                out.special_license_image_url = p.special_license_image_url
                out.hygiene_image_url = p.hygiene_image_url
    # 近 30 天经营质量(两条聚合 SQL,不逐店查询)
    late_rows = await db.execute(text_sql("""
        SELECT merchant_id, count(*) AS n FROM orders
        WHERE status = 'completed' AND ready_late
          AND created_at >= now() - interval '30 days'
        GROUP BY merchant_id"""))
    late_map = {r.merchant_id: r.n for r in late_rows}
    reject_rows = await db.execute(text_sql("""
        SELECT o.merchant_id, count(*) AS n FROM order_events e
        JOIN orders o ON o.id = e.order_id
        WHERE e.to_status = 'cancelled' AND e.actor_role = 'merchant'
          AND e.created_at >= now() - interval '30 days'
        GROUP BY o.merchant_id"""))
    reject_map = {r.merchant_id: r.n for r in reject_rows}
    for out in outs:
        out.ready_late_30d = late_map.get(out.id, 0)
        out.rejects_30d = reject_map.get(out.id, 0)
    return outs


async def _get_shop(db: AsyncSession, merchant_id: int) -> Merchant:
    shop = await db.get(Merchant, merchant_id)
    if shop is None:
        raise HTTPException(404, "商家不存在")
    return shop


@router.get("/stay-aftersales")
async def admin_stay_aftersales(
    status: str = "",
    merchant_id: int | None = None,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """住宿售后监控(平台不直接改判;异议走工单人工复核+手工冲账)。"""
    from ..models import StayAfterSale, StayAfterSaleStatus, StayOrder

    query = (
        select(StayAfterSale, StayOrder, Merchant)
        .join(StayOrder, StayOrder.id == StayAfterSale.stay_order_id)
        .join(Merchant, Merchant.id == StayAfterSale.merchant_id)
    )
    if status:
        try:
            query = query.where(
                StayAfterSale.status == StayAfterSaleStatus(status))
        except ValueError:
            raise HTTPException(422, "未知状态")
    if merchant_id:
        query = query.where(StayAfterSale.merchant_id == merchant_id)
    rows = (await db.execute(
        query.order_by(StayAfterSale.created_at.desc()).limit(200))).all()
    return [{
        "id": a.id,
        "kind": a.kind.value,
        "status": a.status.value,
        "order_no": o.order_no,
        "hotel": m.name,
        "merchant_id": m.id,
        "guest_name": o.guest_name,
        "total_cents": o.total_cents,
        "refund_cents": a.refund_cents,
        "penalty_cents": a.penalty_cents,
        "note": a.note,
        "merchant_note": a.merchant_note,
        "created_at": a.created_at.isoformat(),
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
    } for a, o, m in rows]


@router.get("/stay-orders")
async def admin_stay_orders(
    status: str = "",
    merchant_id: int | None = None,
    day: str = "",  # 按入住日筛(YYYY-MM-DD)
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """住宿订单查询:资金三行(房费-佣金-商家实收)与状态一屏看清。"""
    from datetime import date as _date

    from ..models import StayOrder
    from ..state_machine import STAY_STATUS_LABELS, StayOrderStatus

    query = select(StayOrder, Merchant).join(
        Merchant, Merchant.id == StayOrder.merchant_id)
    if status:
        try:
            query = query.where(StayOrder.status == StayOrderStatus(status))
        except ValueError:
            raise HTTPException(422, "未知状态")
    if merchant_id:
        query = query.where(StayOrder.merchant_id == merchant_id)
    if day:
        query = query.where(StayOrder.checkin_date == _date.fromisoformat(day))
    rows = (await db.execute(
        query.order_by(StayOrder.created_at.desc()).limit(200))).all()
    return [{
        "order_no": o.order_no,
        "hotel": m.name,
        "merchant_id": m.id,
        "room_type": o.room_type_name,
        "rooms_qty": o.rooms_qty,
        "checkin_date": str(o.checkin_date),
        "checkout_date": str(o.checkout_date),
        "nights": o.nights,
        "guest_name": o.guest_name,
        "status": o.status.value,
        "status_label": STAY_STATUS_LABELS[o.status],
        "total_cents": o.total_cents,
        "fee_cents": o.fee_cents,
        "net_cents": o.net_cents,
        "refund_cents": o.refund_cents,
        "created_at": o.created_at.isoformat(),
    } for o, m in rows]


@router.post("/merchants/{merchant_id}/approve", response_model=AdminMerchantOut)
async def approve(
    merchant_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _get_shop(db, merchant_id)
    if shop.status == MerchantStatus.approved:
        raise HTTPException(409, "该商家已经是通过状态")
    shop.status = MerchantStatus.approved
    shop.reject_reason = ""
    await db.commit()
    await db.refresh(shop)
    owner = await db.get(User, shop.owner_id)
    return _to_out(shop, owner)


@router.post("/merchants/{merchant_id}/reject", response_model=AdminMerchantOut)
async def reject(
    merchant_id: int,
    payload: RejectIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    shop = await _get_shop(db, merchant_id)
    shop.status = MerchantStatus.rejected
    shop.reject_reason = payload.reason
    shop.is_open = False  # 驳回即下线,防止先过审营业后再被驳回还挂在列表里
    await db.commit()
    await db.refresh(shop)
    owner = await db.get(User, shop.owner_id)
    return _to_out(shop, owner)


@router.post("/merchants/{merchant_id}/deposit", response_model=AdminMerchantOut)
async def set_merchant_deposit(
    merchant_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """按店调整应留保证金(分)。0 = 免保证金(老店信誉好可豁免);
    调高不追缴——只影响后续可提额,已提走的不回收。"""
    amount = payload.get("deposit_required_cents")
    if not isinstance(amount, int) or not (0 <= amount <= 1_000_000):
        raise HTTPException(422, "保证金金额需为 0 到 1,000,000 分之间的整数")
    shop = await _get_shop(db, merchant_id)
    shop.deposit_required_cents = amount
    await db.commit()
    await db.refresh(shop)
    owner = await db.get(User, shop.owner_id)
    return _to_out(shop, owner)


# ---------- 提现审核(骑手/商家共用同一套打款流程) ----------
def _withdrawal_out(w: Withdrawal, applicant: User) -> AdminWithdrawalOut:
    from ..services.crypto import decrypt

    out = AdminWithdrawalOut.model_validate(w)
    out.name = applicant.name
    out.phone = applicant.phone
    snap = w.account_snapshot or {}
    out.account_kind = snap.get("kind", "")
    out.account_holder = snap.get("holder_name", "")
    out.account_bank = snap.get("bank_name", "")
    # 完整账号仅管理端解密;解不开给空,后台显示尾号兜底
    out.account_no = (decrypt(snap["account_no_encrypted"])
                      if snap.get("account_no_encrypted") else "")
    if not out.account_no and snap.get("account_tail"):
        out.account_no = f"****{snap['account_tail']}"
    out.account_recently_changed = bool(snap.get("recently_changed"))
    return out


@router.get("/withdrawals", response_model=list[AdminWithdrawalOut])
async def list_withdrawals(
    status: WithdrawalStatus | None = None,
    role: str | None = None,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Withdrawal, User)
        .join(User, User.id == Withdrawal.user_id)
        .order_by(Withdrawal.created_at.desc())
        .limit(200)
    )
    if status is not None:
        query = query.where(Withdrawal.status == status)
    if role in ("rider", "merchant"):
        query = query.where(Withdrawal.role == role)
    rows = await db.execute(query)
    return [_withdrawal_out(w, applicant) for w, applicant in rows]


async def _get_pending(db: AsyncSession, withdrawal_id: int) -> Withdrawal:
    w = await db.get(Withdrawal, withdrawal_id, with_for_update=True)
    if w is None:
        raise HTTPException(404, "提现申请不存在")
    if w.status != WithdrawalStatus.pending:
        raise HTTPException(409, "该申请已处理过")
    return w


@router.post("/withdrawals/{withdrawal_id}/paid", response_model=AdminWithdrawalOut)
async def mark_paid(
    withdrawal_id: int,
    payload: PaidNoteIn | None = None,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """线下打款完成后点这里(可附打款凭证号)。接商家转账 API 后由回调自动触发。"""
    w = await _get_pending(db, withdrawal_id)
    w.status = WithdrawalStatus.paid
    w.paid_note = (payload.note if payload else "")[:200]
    w.processed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(w)
    return _withdrawal_out(w, await db.get(User, w.user_id))


@router.post("/withdrawals/batch-paid")
async def batch_mark_paid(
    payload: BatchPaidIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """批量标记打款(每周结算日一次打一批,凭证号留痕)。

    只处理 pending 的申请;返回实际处理数,已处理/不存在的 id 静默跳过。
    """
    done = 0
    paid_riders: list[tuple[int, int]] = []
    for wid in payload.ids[:200]:
        w = await db.get(Withdrawal, wid, with_for_update=True)
        if w is None or w.status != WithdrawalStatus.pending:
            continue
        w.status = WithdrawalStatus.paid
        w.paid_note = payload.note[:200]
        w.processed_at = datetime.now(timezone.utc)
        paid_riders.append((w.user_id, w.amount_cents))
        done += 1
    await db.commit()
    from ..services.push import push_to_user
    for rider_id, amount in paid_riders:
        await push_to_user(rider_id, "提现已打款",
                           f"¥{amount / 100:.2f} 已打款,请查收", {"type": "withdrawal"})
    return {"paid": done, "requested": len(payload.ids)}


@router.post("/withdrawals/t1-batch-paid")
async def t1_batch_paid(
    payload: dict | None = None,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """T+1 批量打款:昨天(北京时间)及更早申请的 pending 提现一键打款。

    对骑手的承诺:今天申请,明天到账,零手续费。今天刚申请的不在本批
    (给财务留出核对时间),明天的批次自然带上。
    """
    from zoneinfo import ZoneInfo

    today_bj = datetime.now(ZoneInfo("Asia/Shanghai")).replace(
        hour=0, minute=0, second=0, microsecond=0)
    note = ((payload or {}).get("note") or f"T+1批次-{today_bj:%Y%m%d}")[:200]
    rows = (await db.scalars(
        select(Withdrawal).where(
            Withdrawal.status == WithdrawalStatus.pending,
            Withdrawal.created_at < today_bj,
        ).with_for_update()
    )).all()
    # 灵工平台代发(桩):未接入返回 None,照旧人工;接入后批次号写进凭证
    from ..services.flexwork import submit_payout_batch
    users_by_id = {u.id: u for u in (await db.scalars(
        select(User).where(User.id.in_([w.user_id for w in rows] or [0])))).all()}
    batch_ref = await submit_payout_batch([
        {"user_id": w.user_id,
         "name": users_by_id[w.user_id].name if w.user_id in users_by_id else "",
         "phone": users_by_id[w.user_id].phone if w.user_id in users_by_id else "",
         "amount_cents": w.amount_cents}
        for w in rows if w.role == "rider"])
    if batch_ref:
        note = f"{note};灵工批次 {batch_ref}"[:200]
    total = 0
    for w in rows:
        w.status = WithdrawalStatus.paid
        w.paid_note = note
        w.processed_at = datetime.now(timezone.utc)
        total += w.amount_cents
    await db.commit()
    from ..services.push import push_to_user
    for w in rows:
        await push_to_user(w.user_id, "提现已打款",
                           f"¥{w.amount_cents / 100:.2f} 已打款(T+1 批次),请查收",
                           {"type": "withdrawal"})
    return {"paid": len(rows), "total_cents": total, "note": note}


@router.post("/withdrawals/{withdrawal_id}/failed", response_model=AdminWithdrawalOut)
async def mark_withdrawal_failed(
    withdrawal_id: int,
    payload: RejectIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """标记打款退票(银行退回/收款信息有误)。

    只允许从「已打款」进入:余额自动退回(余额是算出来的,failed 不计入已提现),
    推送申请人并自动生成客服工单跟进;旧申请留痕终结,申请人可重新发起。
    """
    from ..models import Ticket
    from ..services.push import push_to_user

    w = await db.get(Withdrawal, withdrawal_id, with_for_update=True)
    if w is None:
        raise HTTPException(404, "提现申请不存在")
    if w.status != WithdrawalStatus.paid:
        raise HTTPException(409, "只有已打款的申请才能标记退票")
    w.status = WithdrawalStatus.failed
    w.reject_reason = payload.reason
    w.processed_at = datetime.now(timezone.utc)
    applicant = await db.get(User, w.user_id)
    # 自动工单:退票必然需要人工跟进收款信息,别等用户自己来问
    db.add(Ticket(
        user_id=w.user_id,
        role=w.role,
        contact=applicant.phone if applicant else "",
        content=(f"[系统]提现 ¥{w.amount_cents / 100:.2f}(申请号 {w.id})打款被退回:"
                 f"{payload.reason}。金额已退回余额,请核对收款信息后重新申请;"
                 f"如需帮助请在此工单留言。"),
    ))
    await db.commit()
    await db.refresh(w)
    await push_to_user(
        w.user_id, "提现打款失败",
        f"¥{w.amount_cents / 100:.2f} 打款被退回({payload.reason}),"
        f"金额已退回余额。请核对收款信息后重新申请。",
        {"type": "withdrawal"})
    return _withdrawal_out(w, applicant)


@router.post("/withdrawals/{withdrawal_id}/reject", response_model=AdminWithdrawalOut)
async def reject_withdrawal(
    withdrawal_id: int,
    payload: RejectIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """驳回提现,冻结的余额自动退回(余额是算出来的,无需手动加回)。"""
    w = await _get_pending(db, withdrawal_id)
    w.status = WithdrawalStatus.rejected
    w.reject_reason = payload.reason
    w.processed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(w)
    return _withdrawal_out(w, await db.get(User, w.user_id))


# ---------- 配送异常仲裁 ----------

@router.get("/delivery-issues", response_model=list[DeliveryIssueOut])
async def list_delivery_issues(
    status: str | None = "open",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import Order as OrderModel
    query = (
        select(DeliveryIssue, User, OrderModel)
        .join(User, User.id == DeliveryIssue.rider_id)
        .join(OrderModel, OrderModel.id == DeliveryIssue.order_id)
        .order_by(DeliveryIssue.created_at.desc())
        .limit(200)
    )
    if status in ("open", "resolved"):
        query = query.where(DeliveryIssue.status == status)
    rows = await db.execute(query)
    out = []
    for issue, rider, order in rows:
        o = DeliveryIssueOut.model_validate(issue)
        o.rider_name, o.rider_phone = rider.name, rider.phone
        o.contact_phone = order.contact_phone
        o.address = order.address
        o.total_cents = order.total_cents
        o.order_status = order.status.value
        out.append(o)
    return out


@router.post("/delivery-issues/{issue_id}/resolve", response_model=DeliveryIssueOut)
async def resolve_delivery_issue(
    issue_id: int,
    payload: DeliveryIssueResolveIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """配送异常仲裁,三选一:

    - continue_delivery 已协调,继续配送(只关工单)
    - mark_delivered    用户原因(联系不上/地址错)按送达处理,骑手配送费照拿,
                        24 小时后自动完成结算
    - refund            骑手责任(餐损):订单立即完成结算(商家净额保留、骑手
                        配送费照拿——保障金/保险覆盖,不扣工资),用户全额退款
                        由平台先行赔付;补 AfterSale(fault=rider) 记录,
                        审计规则 6 的免冲账口径与售后仲裁一致
    """
    from datetime import datetime, timezone

    from ..models import AfterSale, AfterSaleStatus, OrderEvent
    from ..models import Order as OrderModel
    from ..services.push import push_to_user
    from ..services.settlement import settle_order
    from ..services.wechat_pay import request_refund
    from ..state_machine import OrderStatus
    from ..ws import manager

    issue = await db.get(DeliveryIssue, issue_id, with_for_update=True)
    if issue is None:
        raise HTTPException(404, "异常工单不存在")
    if issue.status != "open":
        raise HTTPException(409, "该工单已处理过")
    order = await db.get(OrderModel, issue.order_id, with_for_update=True)

    refunded = 0
    if payload.action == "mark_delivered":
        if order.status != OrderStatus.PICKED_UP:
            raise HTTPException(409, "订单不在配送中,不能按送达处理")
        order.status = OrderStatus.DELIVERED
        db.add(OrderEvent(order_id=order.id,
                          from_status=OrderStatus.PICKED_UP.value,
                          to_status=OrderStatus.DELIVERED.value,
                          actor_role="admin", actor_id=admin.id))
    elif payload.action == "refund":
        if order.status not in (OrderStatus.ACCEPTED, OrderStatus.READY,
                                OrderStatus.PICKED_UP):
            raise HTTPException(409, "订单状态不支持先行赔付")
        refunded = order.total_cents
        if refunded <= 0:
            raise HTTPException(409, "该订单已无可退金额")
        from_status = order.status
        order.status = OrderStatus.COMPLETED
        await settle_order(db, order)
        db.add(OrderEvent(order_id=order.id, from_status=from_status.value,
                          to_status=OrderStatus.COMPLETED.value,
                          actor_role="admin", actor_id=admin.id))
        existing_as = await db.scalar(
            select(AfterSale).where(AfterSale.order_id == order.id))
        if existing_as is None:
            db.add(AfterSale(
                order_id=order.id, customer_id=order.customer_id,
                merchant_id=order.merchant_id,
                reason=f"骑手上报配送异常({issue.kind}),平台仲裁先行赔付",
                images=[issue.photo_url] if issue.photo_url else [],
                fault="rider", status=AfterSaleStatus.accepted,
                reply=(payload.note or "配送责任,平台先行赔付")[:300],
                processed_at=datetime.now(timezone.utc)))
        order.refund_cents += refunded
        note = "配送异常,平台先行赔付"
        order.refund_note = (f"{order.refund_note};{note}"
                             if order.refund_note else note)
        await request_refund(db, order, refunded, "配送异常,平台先行赔付")

    issue.status = "resolved"
    issue.resolution = payload.action
    issue.resolve_note = payload.note.strip()
    issue.resolved_at = datetime.now(timezone.utc)
    await db.commit()

    await manager.broadcast(
        f"order:{order.order_no}",
        {"type": "order_status", "order_no": order.order_no,
         "status": order.status.value})
    if payload.action == "continue_delivery":
        await push_to_user(issue.rider_id, "异常已协调",
                           "平台已协调,请继续完成配送", {"order_no": order.order_no})
    elif payload.action == "mark_delivered":
        await push_to_user(order.customer_id, "订单已按送达处理",
                           "因联系不上/地址原因,平台已将订单按送达处理;有疑问请联系客服",
                           {"order_no": order.order_no})
        await push_to_user(issue.rider_id, "异常已处理",
                           "订单已按送达处理,配送费照常结算", {"order_no": order.order_no})
    else:
        await push_to_user(order.customer_id, "配送异常,平台先行赔付",
                           f"退款 ¥{refunded / 100:.2f} 将原路返回。给您添麻烦了。",
                           {"order_no": order.order_no})
        await push_to_user(issue.rider_id, "异常已处理(平台先行赔付)",
                           "用户已获赔付;按平台原则不扣你的工资,注意配送安全",
                           {"order_no": order.order_no})

    out = DeliveryIssueOut.model_validate(issue)
    rider = await db.get(User, issue.rider_id)
    out.rider_name, out.rider_phone = rider.name, rider.phone
    out.order_status = order.status.value
    out.total_cents = order.total_cents
    return out


# ---------- 骑手实名认证审核 ----------
def _rider_profile_out(p: RiderProfile, rider: User) -> AdminRiderProfileOut:
    # 审核后台也不给证号明文。管理员要核身份走人工工单并留痕 ——
    # 一个后台列表接口不该批量吐出几百个身份证号
    out = AdminRiderProfileOut(
        rider_id=p.rider_id,
        real_name=p.real_name,       # 后台看真名(审核需要),但证号仍不给
        health_cert_photo_url=p.health_cert_photo_url,
        status=p.status,
        reject_reason=p.reject_reason,
        id_verified=p.id_verified_at is not None,
    )
    out.rider_phone = rider.phone
    out.created_at = p.created_at
    return out


@router.get("/rider-profiles", response_model=list[AdminRiderProfileOut])
async def list_rider_profiles(
    status: VerifyStatus | None = None,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(RiderProfile, User)
        .join(User, User.id == RiderProfile.rider_id)
        .order_by(RiderProfile.created_at.desc())
        .limit(200)
    )
    if status is not None:
        query = query.where(RiderProfile.status == status)
    rows = (await db.execute(query)).all()

    # 近30天转单次数(考核参考):事件表是权威口径,Redis 日计数只管当天提示
    from datetime import datetime, timedelta, timezone

    from ..models import OrderEvent
    rider_ids = [p.rider_id for p, _ in rows]
    transfer_counts: dict[int, int] = {}
    if rider_ids:
        counted = await db.execute(
            select(OrderEvent.actor_id, func.count())
            .where(
                OrderEvent.to_status == "transferred",
                OrderEvent.actor_id.in_(rider_ids),
                OrderEvent.created_at
                > datetime.now(timezone.utc) - timedelta(days=30),
            )
            .group_by(OrderEvent.actor_id)
        )
        transfer_counts = dict(counted.all())

    # 近7天在线时长(分钟):运力规划参考
    from ..models import RiderSession
    online_map: dict[int, int] = {}
    if rider_ids:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        sessions = (await db.scalars(
            select(RiderSession).where(
                RiderSession.rider_id.in_(rider_ids),
                RiderSession.online_at > week_ago - timedelta(days=1)))).all()
        now_utc = datetime.now(timezone.utc)
        for sess in sessions:
            start = sess.online_at if sess.online_at.tzinfo else                 sess.online_at.replace(tzinfo=timezone.utc)
            end = sess.offline_at or now_utc
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            start = max(start, week_ago)
            if end > start:
                online_map[sess.rider_id] = online_map.get(sess.rider_id, 0) \
                    + int((end - start).total_seconds() // 60)

    # 上岗考试:每个骑手的最高分 + 是否有过通过 + 最近考试时间
    from ..models import RiderExam
    exam_map: dict[int, dict] = {}
    if rider_ids:
        exams = (await db.scalars(
            select(RiderExam).where(RiderExam.rider_id.in_(rider_ids)))).all()
        for e in exams:
            cur = exam_map.setdefault(
                e.rider_id, {"best": 0, "passed": False, "at": None})
            cur["best"] = max(cur["best"], e.score)
            cur["passed"] = cur["passed"] or e.passed
            if cur["at"] is None or e.created_at > cur["at"]:
                cur["at"] = e.created_at

    outs = []
    for p, rider in rows:
        out = _rider_profile_out(p, rider)
        out.transfer_count_30d = transfer_counts.get(p.rider_id, 0)
        out.online_7d_minutes = online_map.get(p.rider_id, 0)
        ex = exam_map.get(p.rider_id)
        if ex is not None:
            out.exam_passed = ex["passed"]
            out.exam_best_score = ex["best"]
            out.exam_at = ex["at"]
        outs.append(out)
    return outs


@router.get("/riders/{rider_id}/worklog")
async def rider_worklog_detail(
    rider_id: int,
    days: int = 14,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """某骑手的在线时长考勤明细(只读,不与结算挂钩,供运力规划)。

    按北京时间自然日拆分在线区间,给出每天累计分钟数与区间列表;
    未闭合区间计到当前时刻。返回区间总时长、日均、活跃天数。
    """
    from datetime import datetime, timedelta, timezone

    from ..models import RiderSession

    days = max(1, min(days, 90))
    now = datetime.now(timezone.utc)
    BJ = timezone(timedelta(hours=8))
    since = now - timedelta(days=days)

    sessions = (await db.scalars(
        select(RiderSession)
        .where(RiderSession.rider_id == rider_id,
               RiderSession.online_at > since - timedelta(days=1))
        .order_by(RiderSession.online_at))).all()

    per_day: dict[str, dict] = {}
    total_min = 0
    for s in sessions:
        start = s.online_at if s.online_at.tzinfo else \
            s.online_at.replace(tzinfo=timezone.utc)
        end = s.offline_at or now
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        start = max(start, since)
        if end <= start:
            continue
        # 归到北京时间自然日(跨零点的区间按开始日归集,足够运力规划用)
        day = (start.astimezone(BJ)).strftime("%Y-%m-%d")
        mins = int((end - start).total_seconds() // 60)
        total_min += mins
        d = per_day.setdefault(day, {"date": day, "minutes": 0, "sessions": []})
        d["minutes"] += mins
        d["sessions"].append({
            "online_at": start.astimezone(BJ).strftime("%H:%M"),
            "offline_at": (end.astimezone(BJ).strftime("%H:%M")
                           if s.offline_at else "在线中"),
            "minutes": mins,
        })

    days_list = sorted(per_day.values(), key=lambda x: x["date"], reverse=True)
    active_days = len(days_list)
    return {
        "rider_id": rider_id,
        "range_days": days,
        "total_minutes": total_min,
        "active_days": active_days,
        "avg_minutes_per_active_day": (
            total_min // active_days if active_days else 0),
        "days": days_list,
    }


async def _get_pending_profile(db: AsyncSession, rider_id: int) -> RiderProfile:
    p = await db.scalar(
        select(RiderProfile).where(RiderProfile.rider_id == rider_id).with_for_update()
    )
    if p is None:
        raise HTTPException(404, "认证记录不存在")
    return p


@router.post("/rider-profiles/{rider_id}/approve", response_model=AdminRiderProfileOut)
async def approve_rider(
    rider_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    p = await _get_pending_profile(db, rider_id)
    if p.status == VerifyStatus.approved:
        raise HTTPException(409, "该骑手已通过认证")
    p.status = VerifyStatus.approved
    p.reject_reason = ""
    await db.commit()
    await db.refresh(p)
    return _rider_profile_out(p, await db.get(User, rider_id))


@router.post("/rider-profiles/{rider_id}/reject", response_model=AdminRiderProfileOut)
async def reject_rider(
    rider_id: int,
    payload: RejectIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    p = await _get_pending_profile(db, rider_id)
    p.status = VerifyStatus.rejected
    p.reject_reason = payload.reason
    # 驳回即强制下线,防止已在线骑手继续接单
    rider = await db.get(User, rider_id)
    if rider:
        rider.is_online = False
    await db.commit()
    await db.refresh(p)
    return _rider_profile_out(p, rider)


# ---------- 平台数据看板 ----------
# 口径与商家对账一致:东八区分界;有效订单 = 非待支付且非已取消
_DASH_TODAY_SQL = text_sql(
    """
    SELECT count(*)                                  AS orders,
           coalesce(sum(total_cents), 0)             AS gmv,
           coalesce(sum(commission_cents), 0)        AS commission,
           count(DISTINCT merchant_id)               AS active_merchants,
           count(DISTINCT rider_id) FILTER (WHERE rider_id IS NOT NULL) AS active_riders
    FROM orders
    WHERE status NOT IN ('pending_payment', 'cancelled')
      AND date(created_at AT TIME ZONE 'Asia/Shanghai')
          = date(now() AT TIME ZONE 'Asia/Shanghai')
    """
)

_DASH_TREND_SQL = text_sql(
    """
    SELECT date(created_at AT TIME ZONE 'Asia/Shanghai') AS day,
           count(*)                       AS orders,
           coalesce(sum(total_cents), 0)  AS gmv
    FROM orders
    WHERE status NOT IN ('pending_payment', 'cancelled')
      AND created_at >= now() - interval '7 days'
    GROUP BY 1
    ORDER BY 1
    """
)

_DASH_NEW_USERS_SQL = text_sql(
    """
    SELECT count(*) FROM users
    WHERE date(created_at AT TIME ZONE 'Asia/Shanghai')
          = date(now() AT TIME ZONE 'Asia/Shanghai')
    """
)

# 体验指标(近 7 天):平均出餐时长(接单→出餐)、平均配送时长(取餐→送达)。
# 从 order_events 的状态流转时间戳算,单位秒
_DASH_TIMING_SQL = text_sql(
    """
    WITH spans AS (
      SELECT e1.order_id,
             extract(epoch FROM e2.created_at - e1.created_at) AS seconds,
             CASE WHEN e1.to_status = 'accepted' THEN 'prep' ELSE 'deliver' END AS kind
      FROM order_events e1
      JOIN order_events e2 ON e2.order_id = e1.order_id
       AND ((e1.to_status = 'accepted'  AND e2.to_status = 'ready')
         OR (e1.to_status = 'picked_up' AND e2.to_status = 'delivered'))
      WHERE e1.created_at >= now() - interval '7 days'
    )
    SELECT kind, round(avg(seconds)) AS avg_seconds, count(*) AS samples
    FROM spans WHERE seconds BETWEEN 0 AND 86400
    GROUP BY kind
    """
)

# 复购率(近 30 天):下过 ≥2 单(完成)的用户 / 下过 ≥1 单的用户
_DASH_REPURCHASE_SQL = text_sql(
    """
    WITH per_user AS (
      SELECT customer_id, count(*) AS n
      FROM orders
      WHERE status = 'completed' AND created_at >= now() - interval '30 days'
      GROUP BY customer_id
    )
    SELECT count(*) FILTER (WHERE n >= 2) AS repeat_users,
           count(*)                       AS buyers
    FROM per_user
    """
)


@router.get("/dashboard")
async def dashboard(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """平台运营看板:今日指标、7 日趋势、累计规模、待办数量。"""
    today = (await db.execute(_DASH_TODAY_SQL)).one()
    trend = [
        {"day": str(r.day), "orders": r.orders, "gmv": r.gmv}
        for r in await db.execute(_DASH_TREND_SQL)
    ]
    new_users = (await db.execute(_DASH_NEW_USERS_SQL)).scalar_one()

    timing = {"prep_avg_seconds": None, "deliver_avg_seconds": None}
    for r in await db.execute(_DASH_TIMING_SQL):
        timing[f"{'prep' if r.kind == 'prep' else 'deliver'}_avg_seconds"] = (
            int(r.avg_seconds))
    rep = (await db.execute(_DASH_REPURCHASE_SQL)).one()
    repurchase_rate = (
        round(rep.repeat_users / rep.buyers, 3) if rep.buyers else None)

    async def _count(stmt):
        return (await db.execute(stmt)).scalar_one()

    from sqlalchemy import func as sa_func

    from ..models import (
        AfterSale,
        AfterSaleStatus,
        AuditAlert,
        Order,
        Ticket,
        TicketStatus,
        UserRole,
    )

    totals = {
        "users": await _count(select(sa_func.count()).select_from(User)
                              .where(User.role == UserRole.customer)),
        "merchants": await _count(select(sa_func.count()).select_from(Merchant)),
        "riders": await _count(select(sa_func.count()).select_from(User)
                               .where(User.role == UserRole.rider)),
        "orders": await _count(select(sa_func.count()).select_from(Order)),
    }
    pending = {
        "merchants": await _count(
            select(sa_func.count()).select_from(Merchant)
            .where(Merchant.status == MerchantStatus.pending)),
        "riders": await _count(
            select(sa_func.count()).select_from(RiderProfile)
            .where(RiderProfile.status == VerifyStatus.pending)),
        "withdrawals": await _count(
            select(sa_func.count()).select_from(Withdrawal)
            .where(Withdrawal.status == WithdrawalStatus.pending)),
        "after_sales": await _count(
            select(sa_func.count()).select_from(AfterSale)
            .where(AfterSale.status == AfterSaleStatus.pending)),
        "tickets": await _count(
            select(sa_func.count()).select_from(Ticket)
            .where(Ticket.status == TicketStatus.open)),
    }
    # 住宿待办:待确认订单与待处理售后(到店无房 2 小时红线,必须看得见)
    from ..models import StayAfterSale, StayAfterSaleStatus, StayOrder
    from ..state_machine import StayOrderStatus
    pending["stay_orders"] = await _count(
        select(sa_func.count()).select_from(StayOrder)
        .where(StayOrder.status == StayOrderStatus.PAID))
    pending["stay_aftersales"] = await _count(
        select(sa_func.count()).select_from(StayAfterSale)
        .where(StayAfterSale.status == StayAfterSaleStatus.pending))
    # 近 3 天的账务告警——账不平是最高优先级,红条置顶
    recent_alerts = (
        await db.scalars(
            select(AuditAlert)
            .where(AuditAlert.created_at
                   >= datetime.now(timezone.utc) - timedelta(days=3))
            .order_by(AuditAlert.created_at.desc())
            .limit(20)
        )
    ).all()
    return {
        "today": {
            "orders": today.orders,
            "gmv_cents": today.gmv,
            "commission_cents": today.commission,
            "active_merchants": today.active_merchants,
            "active_riders": today.active_riders,
            "new_users": new_users,
        },
        "trend_7d": trend,
        # 体验指标:出餐/配送时长(秒,近 7 天均值)、30 天复购率
        "experience": {**timing, "repurchase_rate_30d": repurchase_rate},
        "totals": totals,
        "pending": pending,
        "audit_alerts": [
            {
                "check": a.check_name,
                "detail": a.detail,
                "created_at": a.created_at.isoformat(),
            }
            for a in recent_alerts
        ],
    }


# ---------- 账务自检 ----------
@router.post("/audit/run")
async def trigger_audit(admin: User = Depends(require_role("admin"))):
    """手动触发一次账务自检(平时由每日 04:00 定时任务执行)。"""
    from ..services.audit import run_audit

    problems = await run_audit()
    return {"problems": len(problems), "detail": problems}


@router.post("/audit/backfill")
async def trigger_backfill(admin: User = Depends(require_role("admin"))):
    """对缺账的历史完成订单补记账(幂等,结算功能上线前的老单)。"""
    from ..services.audit import backfill_legacy_refund_records, backfill_missing_earnings

    fixed = await backfill_missing_earnings()
    fixed += await backfill_legacy_refund_records()
    return {"backfilled": fixed}


# ---------- 售后仲裁(客服判责) ----------


@router.get("/after-sales")
async def list_after_sales(
    days: int = 7,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """近 N 天售后申请全量(客服仲裁视角:带举证图、判责方、订单金额)。"""
    from ..models import AfterSale
    from ..models import Order as OrderModel

    since = datetime.now(timezone.utc) - timedelta(days=min(days, 30))
    rows = await db.execute(
        select(AfterSale, OrderModel)
        .join(OrderModel, OrderModel.id == AfterSale.order_id)
        .where(AfterSale.created_at >= since)
        .order_by(AfterSale.created_at.desc())
        .limit(200)
    )
    return [{
        "id": a.id,
        "order_no": o.order_no,
        "customer_id": a.customer_id,
        "reason": a.reason,
        "images": a.images,
        "status": a.status.value,
        "fault": a.fault,
        "reply": a.reply,
        "total_cents": o.total_cents,
        "delivery_fee_cents": o.delivery_fee_cents,
        "refund_cents": o.refund_cents,
        "created_at": a.created_at,
    } for a, o in rows]


@router.post("/after-sales/{after_sale_id}/rider-fault")
async def after_sale_rider_fault(
    after_sale_id: int,
    payload: RejectIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """判骑手责任(洒餐/丢餐等配送事故):平台先行赔付全额(含配送费)。

    钱的走向:商家无责,净额保留;骑手不扣工资(骑手保障金/保险覆盖,
    见公开账本 rider_fund 计提行);损失由平台承担。
    """
    from ..models import AfterSale, AfterSaleStatus
    from ..models import Order as OrderModel
    from ..services.push import push_to_user
    from ..services.wechat_pay import request_refund

    a = await db.get(AfterSale, after_sale_id, with_for_update=True)
    if a is None:
        raise HTTPException(404, "售后申请不存在")
    if a.status == AfterSaleStatus.accepted:
        raise HTTPException(409, "该申请已退款,如需补退请走工单人工处理")
    order = await db.get(OrderModel, a.order_id)
    # total_cents 在缺货部分退款时已同步扣减,此处即"用户当前净付金额",全额赔付
    refund_amount = order.total_cents
    if refund_amount <= 0:
        raise HTTPException(409, "该订单已无可退金额")
    a.status = AfterSaleStatus.accepted
    a.fault = "rider"
    a.reply = (payload.reason or "配送责任,平台先行赔付")[:300]
    a.processed_at = datetime.now(timezone.utc)
    order.refund_cents += refund_amount
    order.refund_note = (
        f"{order.refund_note};骑手责任,平台先行赔付(含配送费)"
        if order.refund_note else "骑手责任,平台先行赔付(含配送费)"
    )
    await request_refund(db, order, refund_amount, "骑手责任,平台先行赔付")
    await db.commit()
    await push_to_user(
        a.customer_id, "售后已通过(平台先行赔付)",
        f"退款 ¥{refund_amount / 100:.2f} 将原路返回,含配送费。给您添麻烦了。",
        {"order_no": order.order_no},
    )
    return {"refunded_cents": refund_amount, "fault": "rider"}


@router.post("/users/{user_id}/after-sale-ban")
async def set_after_sale_ban(
    user_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """恶意售后黑名单开关:禁/解禁自助售后(仍可走客服工单,不剥夺申诉权)。"""
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    target.after_sale_banned = bool(payload.get("banned", True))
    await db.commit()
    return {"user_id": user_id, "after_sale_banned": target.after_sale_banned}


# ---------- 平台运行时开关 ----------

_KNOWN_FLAGS = {
    "weather_surcharge",    # 恶劣天气配送加价(on/off),加价全归骑手
    "night_curfew",         # 平台深夜保护窗(on/off):窗口内停止接新单
    "night_curfew_hours",   # 保护窗时段 "HH:MM-HH:MM",没配默认 01:00-06:00
    "alcohol_curfew",       # 酒类禁售时段开关(on/off):窗口内含酒订单拒单
    "alcohol_curfew_hours", # 禁售时段 "HH:MM-HH:MM",没配默认 22:00-08:00
    "weather_shutdown",     # 极端天气停运(on/off):停接新单+兜底取消线缩短+三端横幅
    # 食安培训现在是**默认必需**(123 号令第二十九条,有罚则),
    # 不再有"要不要强制"这个开关。留下的只是给存量骑手的宽限截止日:
    # ISO 日期,窗口内未完成培训的照常上线但带提醒;过期或写错都硬卡。
    # 写错也硬卡是刻意的 —— 配置错误不该让合规卡点形同虚设
    "rider_training_grace_until",
    "open_cities",          # 开城清单(逗号分隔城市名,空=全部开放)
    # 要求骑手持健康证的城市(逗号分隔)。**默认空 = 都不要求** ——
    # 国家层面不要求送餐员持健康证(不属于"直接接触入口食品的人员",
    # 四川已明确取消),只有查证过本地有规章的城市才加进来。
    # 判据是"查到了本地条文",不是"别的平台都要"
    "health_cert_cities",
    "marketing",            # 营销总开关(默认关):新客券/邀请/生日/复购/上新
    "screen_show_gmv",      # 公开大屏是否展示交易额(缺省=展示,off=接口不下发金额)
}


@router.get("/flags")
async def list_flags(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.scalars(select(PlatformFlag))).all()
    current = {r.key: r.value for r in rows}
    defaults = {"night_curfew_hours": "01:00-06:00",
                "screen_show_gmv": "on"}  # 大屏金额缺省展示,与 /screen 口径一致
    return {k: current.get(k, defaults.get(k, "off")) for k in _KNOWN_FLAGS}


@router.post("/flags/{key}")
async def set_flag(
    key: str,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if key not in _KNOWN_FLAGS:
        raise HTTPException(404, "未知开关")
    value = str(payload.get("value", "")).strip()
    if key in ("open_cities", "health_cert_cities"):
        # 逗号分隔城市清单(空=不限制);顺手归一化中文逗号与空白
        value = ",".join(
            c.strip() for c in value.replace("，", ",").split(",")
            if c.strip())[:200]
    elif key == "rider_training_grace_until":
        # 宽限截止日:ISO 日期或空(空=立即生效)。
        # 写错**不能**当"没配置"处理 —— 运行时 _parse_grace 解析失败会硬卡,
        # 但那时候管理员已经以为自己设好了。在入口就拦下
        if value:
            from datetime import date as _date
            try:
                _date.fromisoformat(value)
            except ValueError:
                raise HTTPException(422, "宽限截止日要写成 YYYY-MM-DD,或留空表示立即生效")
    elif key in ("night_curfew_hours", "alcohol_curfew_hours"):
        if not re.fullmatch(
                r"([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d", value):
            raise HTTPException(422, "时段格式:HH:MM-HH:MM(支持跨天,如 23:00-05:00)")
    elif value not in ("on", "off"):
        raise HTTPException(422, "value 只能是 on/off")
    flag = await db.get(PlatformFlag, key)
    old_value = flag.value if flag is not None else ""
    if flag is None:
        db.add(PlatformFlag(key=key, value=value))
    else:
        flag.value = value

    # 变更留痕(治理透明):白名单键在透明中心时间线公开,原因选填一并展示
    from ..models import FlagHistory
    db.add(FlagHistory(
        key=key, old_value=old_value, new_value=value,
        reason=str(payload.get("reason", "")).strip()[:200]))

    # 停运开关联动:自动挂/撤三端横幅公告 + 提醒在线骑手注意安全
    if key == "weather_shutdown":
        from ..models import Announcement, UserRole
        from ..services.push import push_to_user

        # 记录切换时刻:停运前后 1 小时的送达超时不赔(services/eta.py)
        from ..redis_client import get_redis
        from ..services.eta import WEATHER_TOGGLE_KEY
        await get_redis().set(
            WEATHER_TOGGLE_KEY,
            datetime.now(timezone.utc).isoformat(timespec="seconds"))

        title = "极端天气临时停运"
        if value == "on":
            db.add(Announcement(
                audience="all", title=title,
                content="因极端天气,平台暂停接新单,已有订单会尽力履约;"
                        "骑手请注意安全,恢复时间以本公告撤下为准。"))
        else:
            for a in await db.scalars(
                    select(Announcement).where(
                        Announcement.title == title,
                        Announcement.is_active.is_(True))):
                a.is_active = False
        await db.commit()
        if value == "on":
            riders = (await db.scalars(
                select(User.id).where(User.role == UserRole.rider,
                                      User.is_online.is_(True)).limit(200))).all()
            for rid in riders:
                await push_to_user(rid, "极端天气,注意安全",
                                   "平台已暂停接新单;在途订单不急,安全第一",
                                   {"type": "weather"})
        return {key: value}

    await db.commit()
    return {key: value}


# ---------- 食品安全投诉(红线通道,标红加急) ----------

FS_AUTO_SUSPEND_COUNT = 3   # 30 天内成立 N 起 → 自动停业待人工审核


def _fs_record(report, action: str, note: str, admin_id: int | None) -> None:
    """处置留痕(监管检查可导出)。JSONB 重新赋值才会被 ORM 跟踪。"""
    from datetime import datetime, timezone
    report.actions = [*(report.actions or []), {
        "action": action,
        "note": note[:300],
        "admin_id": admin_id,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }]


async def _fs_out(db: AsyncSession, report) -> AdminFoodSafetyOut:
    from ..models import Order as OrderModel
    out = AdminFoodSafetyOut.model_validate(report)
    shop = await db.get(Merchant, report.merchant_id)
    if shop:
        out.merchant_name = shop.name
        out.merchant_is_open = shop.is_open
    customer = await db.get(User, report.customer_id)
    if customer:
        out.customer_phone = customer.phone  # 管理后台看真号,方便回访
    order = await db.get(OrderModel, report.order_id)
    if order:
        out.order_total_cents = order.total_cents
        out.order_items = order.items
    return out


@router.get("/food-safety", response_model=list[AdminFoodSafetyOut])
async def list_food_safety(
    status: str | None = None,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import FoodSafetyReport
    query = (select(FoodSafetyReport)
             .order_by(FoodSafetyReport.created_at.desc()).limit(200))
    if status:
        query = query.where(FoodSafetyReport.status == status)
    reports = (await db.scalars(query)).all()
    return [await _fs_out(db, r) for r in reports]


@router.get("/food-safety.csv")
async def export_food_safety(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """处置留痕导出(监管检查用):逐条投诉 + 全部处置动作。"""
    import csv
    import io
    import json as json_mod

    from fastapi.responses import Response

    from ..models import FoodSafetyReport

    reports = (await db.scalars(
        select(FoodSafetyReport).order_by(FoodSafetyReport.created_at))).all()
    shops = {m.id: m.name for m in await db.scalars(select(Merchant).where(
        Merchant.id.in_({r.merchant_id for r in reports})))} if reports else {}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["投诉ID", "订单号", "商家", "类型", "描述", "状态",
                     "提交时间", "结案时间", "处置留痕"])
    for r in reports:
        writer.writerow([
            r.id, r.order_no, shops.get(r.merchant_id, r.merchant_id),
            r.kind, r.description, r.status,
            r.created_at.isoformat(timespec="seconds"),
            r.resolved_at.isoformat(timespec="seconds") if r.resolved_at else "",
            json_mod.dumps(r.actions or [], ensure_ascii=False),
        ])
    return Response(
        content="﻿" + buf.getvalue(),  # BOM 防 Excel 乱码
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 "attachment; filename=food_safety_reports.csv"})


async def _fs_get_open(db: AsyncSession, report_id: int, statuses=("open",)):
    from ..models import FoodSafetyReport
    report = await db.get(FoodSafetyReport, report_id, with_for_update=True)
    if report is None:
        raise HTTPException(404, "食安投诉不存在")
    if report.status not in statuses:
        raise HTTPException(409, "该投诉当前状态不支持此操作")
    return report


@router.post("/food-safety/{report_id}/confirm", response_model=AdminFoodSafetyOut)
async def confirm_food_safety(
    report_id: int,
    payload: FoodSafetyActionIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """投诉成立:先行全额退款(含配送费,fault=platform 平台垫付,不冲商家账,
    追责走线下);30 天内第 3 起成立自动暂停营业待人工审核。
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func as sa_func

    from ..models import AfterSale, AfterSaleStatus, FoodSafetyReport
    from ..models import Order as OrderModel
    from ..services.push import push_to_user
    from ..services.wechat_pay import request_refund

    report = await _fs_get_open(db, report_id)
    order = await db.get(OrderModel, report.order_id, with_for_update=True)
    now = datetime.now(timezone.utc)

    refunded = order.total_cents
    if refunded > 0:
        # 先退款再累计 refund_cents:微信通道按 total+已退 反推原始支付总额
        await request_refund(db, order, refunded, "食品安全投诉成立,平台先行全额退款")
        order.refund_cents += refunded
        note = "食安投诉成立,全额退款(含配送费)"
        order.refund_note = (f"{order.refund_note};{note}"
                             if order.refund_note else note)
        # 审计规则 6 豁免口径:fault=platform 平台垫付,不冲商家/骑手账
        existing_as = await db.scalar(
            select(AfterSale).where(AfterSale.order_id == order.id))
        if existing_as is None:
            db.add(AfterSale(
                order_id=order.id, customer_id=order.customer_id,
                merchant_id=order.merchant_id,
                reason=f"食品安全投诉({report.kind})",
                images=report.images,
                fault="platform", status=AfterSaleStatus.accepted,
                reply=(payload.note or "食安投诉成立,平台先行全额退款")[:300],
                processed_at=now))

    report.status = "confirmed"
    report.resolved_at = now
    _fs_record(report, "confirmed",
               payload.note or f"投诉成立,先行退款 ¥{refunded / 100:.2f}", admin.id)

    # 30 天内成立数(含本起)≥3 → 自动停业待人工审核。
    # 排除本单再 +1:防 autoflush 把刚置为 confirmed 的当前工单重复计数
    confirmed_30d = await db.scalar(
        select(sa_func.count(FoodSafetyReport.id)).where(
            FoodSafetyReport.merchant_id == report.merchant_id,
            FoodSafetyReport.id != report.id,
            FoodSafetyReport.status == "confirmed",
            FoodSafetyReport.created_at > now - timedelta(days=30))) + 1
    shop = await db.get(Merchant, report.merchant_id)
    auto_suspended = False
    if confirmed_30d >= FS_AUTO_SUSPEND_COUNT and shop and shop.is_open:
        shop.is_open = False
        # **置闸门,不然商家自己就能开回来**:PATCH 的营业校验只拦
        # 非 approved 的店,而自动停业不改 status
        shop.food_safety_hold = True
        shop.hold_reason = "food_safety"
        auto_suspended = True
        _fs_record(report, "auto_suspend",
                   f"30 天内第 {confirmed_30d} 起食安投诉成立,自动暂停营业待人工审核",
                   None)
    await db.commit()
    await db.refresh(report)

    await push_to_user(report.customer_id, "食安投诉已处理",
                       f"你的食品安全投诉已核实成立,¥{refunded / 100:.2f} 全额退款"
                       f"(含配送费)已原路退回。感谢监督,平台已同步整改要求",
                       {"type": "order", "order_no": report.order_no},
                       record_skip=True)
    if shop:
        body = ("30 天内多起食品安全投诉成立,店铺已被暂停营业,"
                "请联系平台客服提交整改材料复核" if auto_suspended else
                f"订单 {report.order_no[-6:]} 的食品安全投诉经核实成立,"
                f"请立即自查后厨与食材;累计成立将暂停营业")
        await push_to_user(shop.owner_id, "食品安全整改通知", body,
                           {"type": "order", "order_no": report.order_no},
                           record_skip=True)
    return await _fs_out(db, report)


@router.post("/food-safety/{report_id}/dismiss", response_model=AdminFoodSafetyOut)
async def dismiss_food_safety(
    report_id: int,
    payload: FoodSafetyActionIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """投诉不成立:不动资金,留痕说明理由(会推送给用户)。"""
    from datetime import datetime, timezone

    from ..services.push import push_to_user

    if len(payload.note.strip()) < 2:
        raise HTTPException(422, "驳回必须填写理由(会展示给用户)")
    report = await _fs_get_open(db, report_id)
    report.status = "dismissed"
    report.resolved_at = datetime.now(timezone.utc)
    _fs_record(report, "dismissed", payload.note.strip(), admin.id)
    await db.commit()
    await db.refresh(report)
    await push_to_user(report.customer_id, "食安投诉处理结果",
                       f"经核实,你的食品安全投诉暂未采纳:{payload.note.strip()};"
                       f"如有异议请联系客服补充材料",
                       {"type": "order", "order_no": report.order_no},
                       record_skip=True)
    return await _fs_out(db, report)


@router.post("/food-safety/{report_id}/take-down-dish",
             response_model=AdminFoodSafetyOut)
async def food_safety_take_down_dish(
    report_id: int,
    payload: FoodSafetyActionIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """一键下架涉事菜品(is_on_sale=false),处置留痕。"""
    from ..models import Dish
    from ..services.push import push_to_user

    if not payload.dish_id:
        raise HTTPException(422, "请指定要下架的菜品")
    report = await _fs_get_open(db, report_id, statuses=("open", "confirmed"))
    dish = await db.get(Dish, payload.dish_id)
    if dish is None or dish.merchant_id != report.merchant_id:
        raise HTTPException(404, "菜品不存在或不属于涉事商家")
    dish.is_on_sale = False
    _fs_record(report, "dish_off",
               f"下架菜品「{dish.name}」(id={dish.id}):{payload.note}", admin.id)
    await db.commit()
    await db.refresh(report)
    shop = await db.get(Merchant, report.merchant_id)
    if shop:
        await push_to_user(shop.owner_id, "菜品已被平台下架",
                           f"因食品安全投诉,「{dish.name}」已被平台下架;"
                           f"整改完成后可联系客服申请恢复",
                           {"type": "order", "order_no": report.order_no},
                           record_skip=True)
    return await _fs_out(db, report)


@router.post("/food-safety/{report_id}/suspend-merchant",
             response_model=AdminFoodSafetyOut)
async def food_safety_suspend_merchant(
    report_id: int,
    payload: FoodSafetyActionIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """暂停商家营业并置食安闸门(商家自己开不回来),附整改原因推送商家。"""
    from ..services.push import push_to_user

    if len(payload.note.strip()) < 2:
        raise HTTPException(422, "请填写整改原因(会推送给商家)")
    report = await _fs_get_open(db, report_id, statuses=("open", "confirmed"))
    shop = await db.get(Merchant, report.merchant_id)
    if shop is None:
        raise HTTPException(404, "商家不存在")
    shop.is_open = False
    shop.food_safety_hold = True
    shop.hold_reason = "food_safety"
    _fs_record(report, "suspend", payload.note.strip(), admin.id)
    await db.commit()
    await db.refresh(report)
    await push_to_user(shop.owner_id, "店铺已被暂停营业",
                       f"因食品安全问题,店铺已被平台暂停营业。整改原因:"
                       f"{payload.note.strip()};完成整改后联系平台客服复核恢复",
                       {"type": "order", "order_no": report.order_no},
                       record_skip=True)
    return await _fs_out(db, report)


@router.post("/merchants/{merchant_id}/food-safety-hold/release")
async def release_food_safety_hold(
    merchant_id: int,
    payload: FoodSafetyActionIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """食安整改复核通过:解除停业闸门(商家自己重新开店)。

    **只解闸门不替商家开店** —— 什么时候恢复营业是商家的决定,
    平台只负责确认整改到位。
    """
    from ..services.push import push_to_user

    if len(payload.note.strip()) < 2:
        raise HTTPException(422, "请填写复核结论(会推送给商家)")
    shop = await db.get(Merchant, merchant_id)
    if shop is None:
        raise HTTPException(404, "商家不存在")
    if not shop.food_safety_hold:
        raise HTTPException(409, "该店没有食安停业闸门")
    shop.food_safety_hold = False
    shop.hold_reason = ""
    await db.commit()
    await push_to_user(
        shop.owner_id, "食安整改复核通过",
        f"{payload.note.strip()};你现在可以在店铺页重新开始营业",
        {"type": "shop"}, record_skip=True)
    return {"ok": True}


@router.get("/merchants/license-alerts")
async def license_alerts(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """证照待处理队列:快到期、已过期、已因过期停业的店,一屏看全。

    审核员从这里进,而不是靠推送找人 —— 推送是给商家的,
    平台侧要的是"今天有几家该跟进",能排序、能一次看完。

    排序按紧急程度倒序(overdue → expired → last → urgent → soon):
    已经停业的那几家最该先处理,他们每多停一天就是真金白银的损失。
    """
    from datetime import date, timedelta

    from ..services.licenses import GRACE_DAYS, days_left, stage

    today = date.today()
    rows = (await db.scalars(
        select(Merchant).where(
            Merchant.license_expires_at.is_not(None),
            Merchant.license_expires_at <= today + timedelta(days=30),
            Merchant.status == MerchantStatus.approved,
        ))).all()
    order = {"overdue": 0, "expired": 1, "last": 2, "urgent": 3, "soon": 4}
    items = [{
        "id": s.id, "name": s.name, "city": s.city, "address": s.address,
        "owner_id": s.owner_id,
        "license_no": s.license_no,
        "license_subject": s.license_subject,
        # 主体名称与店名不一致很正常(店招「赞小碗」/ 证上是公司全称),
        # 但**营业执照与行业资质两张证的主体必须一致** —— 一并给出来让人核
        "business_license_no": s.business_license_no,
        "expires_at": s.license_expires_at,
        "days_left": days_left(s.license_expires_at, today),
        "stage": stage(s.license_expires_at, today),
        "held": s.food_safety_hold,
        "is_open": s.is_open,
    } for s in rows]
    items.sort(key=lambda x: (order.get(x["stage"], 9), x["days_left"] or 0))
    return {
        "grace_days": GRACE_DAYS,
        "items": items,
        "note": "过期后有 %d 天宽限期照常接单;期满自动停业,"
                "核验新证后走食安闸门的解除接口恢复。" % GRACE_DAYS,
    }


@router.get("/rider-appeals")
async def list_rider_appeals(
    status: str = "pending",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """骑手申诉队列。**证据是系统自己附的**,审核员看的是同一份数据 ——
    不用两边各说各话。"""
    from ..models import RiderAppeal

    rows = (await db.execute(
        select(RiderAppeal, User.name, User.phone)
        .join(User, User.id == RiderAppeal.rider_id)
        .where(RiderAppeal.status == status)
        .order_by(RiderAppeal.id))).all()
    return [{
        "id": r.id, "order_no": r.order_no, "kind": r.kind,
        "reason": r.reason, "photo_url": r.photo_url,
        "evidence": r.evidence,
        "rider_name": name,
        # 手机号打码:队列是给审核用的,不是通讯录
        "rider_phone": f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7
        else "",
        "created_at": r.created_at,
    } for r, name, phone in rows]


@router.post("/rider-appeals/{appeal_id}/resolve")
async def resolve_rider_appeal(
    appeal_id: int,
    payload: AppealVerdictIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """核定申诉。accept=true 判为非骑手责任。

    **成立不加分也不补钱** —— 平台没有骑手评分体系,所以没有分可加;
    补偿是另一条线(超时判赔已经由平台自动承担,见 eta.compensate_if_late)。
    成立的意义是这条记录上写着不怪他,以及平台据此去看商家出餐这一环。
    """
    from ..models import RiderAppeal
    from ..services.push import push_to_user

    row = await db.get(RiderAppeal, appeal_id)
    if row is None or row.status != "pending":
        raise HTTPException(404, "申诉不存在或已处理")
    accept = payload.accept
    row.status = "accepted" if accept else "rejected"
    row.verdict_note = payload.note.strip()[:200]
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await push_to_user(
        row.rider_id,
        "申诉已核定:" + ("非你的责任" if accept else "未采纳"),
        f"{row.order_no}:{row.verdict_note}",
        {"type": "appeal"}, record_skip=True)
    return {"ok": True, "status": row.status}


@router.get("/rider-feedback")
async def list_rider_feedback(
    status: str = "open",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """骑手意见队列(针对平台本身,不是针对某一单)。

    最老的排在最前 —— 按新到旧排的话,积压的老意见会永远沉底,
    而"提了没人理"正是这个通道最容易死掉的方式。
    """
    from ..models import RiderFeedback

    rows = (await db.execute(
        select(RiderFeedback, User.name)
        .join(User, User.id == RiderFeedback.rider_id)
        .where(RiderFeedback.status == status)
        .order_by(RiderFeedback.id).limit(200))).all()
    return [{
        "id": r.id, "kind": r.kind, "content": r.content,
        "status": r.status, "reply": r.reply,
        "rider_name": name, "created_at": r.created_at,
    } for r, name in rows]


@router.post("/rider-feedback/{feedback_id}/reply")
async def reply_rider_feedback(
    feedback_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """回复一条意见。

    **回复是这个功能的全部意义。** 只存不回的话,这张表就是一个
    许愿池 —— 骑手提过一次没人理,以后连提都懒得提。
    所以回复必须推送出去,并进他的消息中心(骑手在马路上,
    推送那一下没看到就找不回来了)。

    没有"已关闭":关闭是平台单方面宣布这件事结束。
    """
    from ..models import RiderFeedback
    from ..services.push import push_to_user

    reply = str(payload.get("reply") or "").strip()
    if len(reply) < 2:
        raise HTTPException(422, "回复不能为空 —— 空回复比不回复更伤人")
    row = await db.get(RiderFeedback, feedback_id)
    if row is None:
        raise HTTPException(404, "反馈不存在")
    row.reply = reply[:1000]
    row.status = "replied"
    row.replied_at = datetime.now(timezone.utc)
    await db.commit()
    await push_to_user(
        row.rider_id, "你的意见有回复了", reply[:200],
        {"type": "rider_feedback", "id": row.id}, record_skip=True)
    return {"ok": True, "status": row.status}


@router.get("/license-renewals")
async def list_license_renewals(
    status: str = "pending",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """续证核验队列。带上店里现在那张证,方便并排比对主体是否一致。"""
    from ..models import LicenseRenewal

    rows = (await db.execute(
        select(LicenseRenewal, Merchant)
        .join(Merchant, Merchant.id == LicenseRenewal.merchant_id)
        .where(LicenseRenewal.status == status)
        .order_by(LicenseRenewal.id))).all()
    return [{
        "id": r.id, "merchant_id": r.merchant_id, "shop_name": m.name,
        "shop_address": m.address,
        "held": m.food_safety_hold,
        "new": {
            "license_no": r.license_no,
            "license_image_url": r.license_image_url,
            "license_expires_at": r.license_expires_at,
            "business_license_no": r.business_license_no,
            "license_subject": r.license_subject,
        },
        # 现用的那张:主体名称/证号变没变,一眼能看出来
        "current": {
            "license_no": m.license_no,
            "license_image_url": m.license_image_url,
            "license_expires_at": m.license_expires_at,
            "business_license_no": m.business_license_no,
            "license_subject": m.license_subject,
        },
        "created_at": r.created_at,
    } for r, m in rows]


@router.post("/license-renewals/{renewal_id}/approve")
async def approve_license_renewal(
    renewal_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """核验通过:替换店里的资质,清提醒水位,并解除因过期置的停业闸门。

    **清 license_notified 是必须的** —— 不清的话新证到期前 30 天那次
    提醒会被旧水位去重掉,而那恰恰是最有用的一次(续证要跑审批流程,
    提前一个月才来得及)。
    """
    from ..models import LicenseRenewal
    from ..services.push import push_to_user

    row = await db.get(LicenseRenewal, renewal_id)
    if row is None or row.status != "pending":
        raise HTTPException(404, "续证记录不存在或已处理")
    shop = await db.get(Merchant, row.merchant_id)
    if shop is None:
        raise HTTPException(404, "商家不存在")

    shop.license_no = row.license_no
    shop.license_image_url = row.license_image_url
    shop.license_expires_at = row.license_expires_at
    if row.business_license_no:
        shop.business_license_no = row.business_license_no
    if row.license_subject:
        shop.license_subject = row.license_subject
    shop.license_notified = []
    # 因证过期落的闸,证换了就该解 —— 这正是"人工核验后恢复"的那一步。
    # **只解闸门不替商家开店**:什么时候恢复营业是商家的决定
    # **只解自己落的那道闸**。因食安投诉成立被停业的店,交一张新证不该解封 ——
    # 那两件事没有关系,混在一起就是"食安停业形同虚设"的又一种写法
    unheld = False
    if shop.food_safety_hold and shop.hold_reason == "license_expired":
        shop.food_safety_hold = False
        shop.hold_reason = ""
        unheld = True
    row.status = "approved"
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await push_to_user(
        shop.owner_id, "新证已核验通过",
        f"食品经营许可证已更新,有效期至 {row.license_expires_at}。"
        + ("店铺停业闸门已解除,你可以在店铺页重新开始营业。" if unheld else ""),
        {"type": "shop"}, record_skip=True)
    return {"ok": True, "unheld": unheld}


@router.post("/license-renewals/{renewal_id}/reject")
async def reject_license_renewal(
    renewal_id: int,
    payload: FoodSafetyActionIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """核验不通过。原因原样推给商家 —— 不说清楚商家只能反复瞎传。"""
    from ..models import LicenseRenewal
    from ..services.push import push_to_user

    if len(payload.note.strip()) < 2:
        raise HTTPException(422, "请填写不通过的原因(会推送给商家)")
    row = await db.get(LicenseRenewal, renewal_id)
    if row is None or row.status != "pending":
        raise HTTPException(404, "续证记录不存在或已处理")
    row.status = "rejected"
    row.reject_reason = payload.note.strip()[:200]
    row.reviewed_at = datetime.now(timezone.utc)
    shop = await db.get(Merchant, row.merchant_id)
    await db.commit()
    if shop is not None:
        await push_to_user(
            shop.owner_id, "续证材料未通过",
            f"{row.reject_reason};请修正后重新提交",
            {"type": "shop"}, record_skip=True)
    return {"ok": True}


# ---------- 内容审核(先发后审队列 + 敏感词库维护) ----------

@router.get("/content-reviews")
async def list_content_reviews(
    status: str = "pending",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import ContentReview
    query = (select(ContentReview)
             .order_by(ContentReview.created_at.desc()).limit(200))
    if status:
        query = query.where(ContentReview.status == status)
    rows = (await db.scalars(query)).all()
    return [{
        "id": r.id, "kind": r.kind, "ref_id": r.ref_id, "url": r.url,
        "status": r.status, "note": r.note,
        "created_at": r.created_at.isoformat(),
    } for r in rows]


async def _cr_get_pending(db: AsyncSession, review_id: int):
    from ..models import ContentReview
    r = await db.get(ContentReview, review_id, with_for_update=True)
    if r is None:
        raise HTTPException(404, "审核记录不存在")
    if r.status != "pending":
        raise HTTPException(409, "该记录已处理过")
    return r


@router.post("/content-reviews/{review_id}/approve")
async def approve_content(
    review_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    r = await _cr_get_pending(db, review_id)
    r.status = "approved"
    r.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@router.post("/content-reviews/{review_id}/reject")
async def reject_content(
    review_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """驳回:按类型隐藏图片(评价图移除/菜品图清空/头像清空)并通知发布者。"""
    from ..models import Dish, Review
    from ..services.push import push_to_user

    note = str(payload.get("note", "")).strip()
    if len(note) < 2:
        raise HTTPException(422, "驳回必须填写原因(会通知发布者)")
    r = await _cr_get_pending(db, review_id)
    r.status = "rejected"
    r.note = note[:200]
    r.reviewed_at = datetime.now(timezone.utc)

    notify_uid = None
    if r.kind == "review":
        review = await db.get(Review, r.ref_id)
        if review is not None:
            review.image_urls = [u for u in (review.image_urls or [])
                                 if u != r.url]
            notify_uid = review.customer_id
    elif r.kind == "dish":
        dish = await db.get(Dish, r.ref_id)
        if dish is not None and dish.image_url == r.url:
            dish.image_url = ""
            shop = await db.get(Merchant, dish.merchant_id)
            notify_uid = shop.owner_id if shop else None
    elif r.kind == "avatar":
        target = await db.get(User, r.ref_id)
        if target is not None and target.avatar_url == r.url:
            target.avatar_url = ""
            notify_uid = target.id
    await db.commit()
    if notify_uid:
        await push_to_user(notify_uid, "图片未通过审核",
                           f"你上传的图片经审核不符合发布规范已被移除:{note};"
                           f"如有疑问请联系客服",
                           {"type": "moderation"}, record_skip=True)
    return {"ok": True}


@router.get("/moderation-words")
async def list_moderation_words(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import ModerationWord
    rows = (await db.scalars(
        select(ModerationWord).order_by(ModerationWord.id.desc()))).all()
    return [{"id": w.id, "word": w.word, "category": w.category} for w in rows]


@router.post("/moderation-words")
async def add_moderation_word(
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import ModerationWord
    from ..services.moderation import invalidate_cache

    word = str(payload.get("word", "")).strip()
    if not (1 <= len(word) <= 50):
        raise HTTPException(422, "词长需在 1-50 字符")
    existing = await db.scalar(
        select(ModerationWord).where(ModerationWord.word == word))
    if existing:
        raise HTTPException(409, "该词已在库中")
    db.add(ModerationWord(
        word=word, category=str(payload.get("category", "other"))[:20]))
    await db.commit()
    invalidate_cache()
    return {"ok": True}


@router.delete("/moderation-words/{word_id}")
async def delete_moderation_word(
    word_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import ModerationWord
    from ..services.moderation import invalidate_cache

    w = await db.get(ModerationWord, word_id)
    if w is None:
        raise HTTPException(404, "词不存在")
    await db.delete(w)
    await db.commit()
    invalidate_cache()
    return {"ok": True}


# ---------- 防刷单风控(只标记不拦截,人工复核) ----------

@router.get("/risk-orders")
async def list_risk_orders(
    status: str = "",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """风控标记单:status 空=待复核(标记了但没结论),confirmed/cleared 查已复核。"""
    from ..models import Order as OrderModel
    query = (select(OrderModel)
             .where(OrderModel.risk_flags.is_not(None))
             .order_by(OrderModel.created_at.desc()).limit(200))
    rows = [o for o in (await db.scalars(query)).all()
            if (o.risk_flags or {}).get("status", "") == status]
    shops = {m.id: m.name for m in await db.scalars(select(Merchant).where(
        Merchant.id.in_({o.merchant_id for o in rows})))} if rows else {}
    users_map = {u.id: u for u in await db.scalars(select(User).where(
        User.id.in_({o.customer_id for o in rows})))} if rows else {}
    return [{
        "id": o.id, "order_no": o.order_no,
        "merchant_name": shops.get(o.merchant_id, o.merchant_id),
        "customer_id": o.customer_id,
        "customer_phone": getattr(users_map.get(o.customer_id), "phone", ""),
        "customer_risk_level": getattr(
            users_map.get(o.customer_id), "risk_level", ""),
        "total_cents": o.total_cents, "order_status": o.status.value,
        "hits": (o.risk_flags or {}).get("hits", []),
        "risk_status": (o.risk_flags or {}).get("status", ""),
        "created_at": o.created_at.isoformat(),
    } for o in rows]


@router.post("/risk-orders/{order_id}/verdict")
async def risk_verdict(
    order_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """复核结论:confirmed=确认刷单(剔出月售/排行) / cleared=误报解除。
    不动资金、不封号——刷单的商业惩罚是失去销量口碑,不是没收真钱。"""
    from ..models import Order as OrderModel
    verdict = str(payload.get("verdict", ""))
    if verdict not in ("confirmed", "cleared"):
        raise HTTPException(422, "verdict 只能是 confirmed / cleared")
    order = await db.get(OrderModel, order_id, with_for_update=True)
    if order is None or not order.risk_flags:
        raise HTTPException(404, "订单不存在或无风控标记")
    order.risk_flags = {**order.risk_flags, "status": verdict}
    await db.commit()
    return {"ok": True, "status": verdict}


@router.post("/users/{user_id}/risk-level")
async def set_user_risk_level(
    user_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """反作弊分级处置(可回滚):level="" 解除 / limit 限制领券补贴 / frozen 冻结待复核。

    绝不静默:reason 会展示给用户,用户可申诉。不没收真钱、不封下单——
    误伤优先放行,惩罚只落在营销权益上(与刷单商业惩罚一致的克制)。
    """
    level = str(payload.get("level", ""))
    reason = str(payload.get("reason", "")).strip()[:200]
    if level not in ("", "limit", "frozen"):
        raise HTTPException(422, "level 只能是 空/limit/frozen")
    target = await db.get(User, user_id, with_for_update=True)
    if target is None:
        raise HTTPException(404, "用户不存在")
    old = target.risk_level
    target.risk_level = level
    target.risk_note = reason if level else ""
    # 处置留痕:透明中心按月聚合公示(只有计数,绝无个案)
    from ..models import RiskActionLog
    db.add(RiskActionLog(user_id=user_id, from_level=old, to_level=level))
    await db.commit()
    logger.info("风控分级处置 user=%s %s->%s reason=%s by admin=%s",
                user_id, old or "normal", level or "normal", reason, admin.id)
    return {"ok": True, "user_id": user_id, "risk_level": level,
            "previous": old}


@router.get("/reviews/flagged")
async def list_flagged_reviews(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """疑似刷评(标记待复核,未自动删):供后台人工判断。"""
    from ..models import Review
    rows = (await db.scalars(
        select(Review).where(Review.flagged.is_(True), Review.hidden.is_(False))
        .order_by(Review.created_at.desc()).limit(100))).all()
    return [{"id": r.id, "merchant_id": r.merchant_id,
             "customer_id": r.customer_id, "rating": r.merchant_rating,
             "comment": r.comment, "flag_reason": r.flag_reason,
             "created_at": r.created_at.isoformat()} for r in rows]


# ---------- 运力看板 + 配送改派 ----------

@router.get("/dispatch-overview")
async def dispatch_overview(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """运力总览:在线骑手(位置)/待抢单/在途单/近2小时下单热力点。
    只看不派——处置动作走 reassign 接口。位置数据仅管理员可见。"""
    import json as json_mod

    from ..models import Order, UserRole
    from ..redis_client import RIDER_LOC_KEY, get_redis
    from ..state_machine import GRABBABLE_STATUSES
    from ..state_machine import OrderStatus as OS

    now = datetime.now(timezone.utc)

    riders = (await db.scalars(
        select(User).where(User.role == UserRole.rider,
                           User.is_online.is_(True)).limit(200))).all()
    redis = get_redis()
    rider_rows = []
    active_counts = dict((await db.execute(
        select(text_sql("rider_id"), func.count())
        .select_from(text_sql("orders"))
        .where(text_sql("rider_id IS NOT NULL"),
               text_sql("status IN ('accepted','ready','picked_up')"))
        .group_by(text_sql("rider_id")))).all())
    for r in riders:
        loc = await redis.hgetall(RIDER_LOC_KEY.format(rider_id=r.id))
        rider_rows.append({
            "id": r.id, "name": r.name, "phone": r.phone,
            "lat": float(loc["lat"]) if loc.get("lat") else None,
            "lng": float(loc["lng"]) if loc.get("lng") else None,
            "active_orders": active_counts.get(r.id, 0),
        })

    pool_orders = (await db.scalars(
        select(Order).where(
            Order.rider_id.is_(None), Order.status.in_(GRABBABLE_STATUSES),
            Order.pickup.is_(False), Order.parent_order_no == "")
        .order_by(Order.created_at).limit(100))).all()
    # 在途单按**最新优先**取,不是最早优先。
    #
    # 运力看板要回答的是「现在有多少单在跑」,而按 created_at 升序 + limit 100
    # 会在在途量超过 100 时**把最新的单挤出去** —— 调度员盯着看板,
    # 却看不到刚派出去的单(实测库里在途 116 单、接口只回 100)。
    # 这是本项目吃过多次的 LIMIT 截断:排序方向选错,截断就截在了要看的那一头
    in_flight = list(reversed((await db.scalars(
        select(Order).where(
            Order.rider_id.is_not(None),
            Order.status.in_([OS.ACCEPTED, OS.READY, OS.PICKED_UP]),
            Order.parent_order_no == "")
        .order_by(Order.created_at.desc()).limit(100))).all()))

    shops = {m.id: m for m in await db.scalars(select(Merchant).where(
        Merchant.id.in_({o.merchant_id for o in [*pool_orders, *in_flight]})))}
    rider_names = {u.id: u.name for u in await db.scalars(select(User).where(
        User.id.in_({o.rider_id for o in in_flight if o.rider_id})))}

    def order_row(o, with_rider=False):
        shop = shops.get(o.merchant_id)
        pool_since = o.rider_pool_since or o.created_at
        if pool_since.tzinfo is None:
            pool_since = pool_since.replace(tzinfo=timezone.utc)
        row = {
            "id": o.id, "order_no": o.order_no, "status": o.status.value,
            "merchant_name": shop.name if shop else "",
            "merchant_lat": shop.lat if shop else None,
            "merchant_lng": shop.lng if shop else None,
            "drop_lat": o.lat, "drop_lng": o.lng,
            "tip_cents": o.tip_cents,
            "wait_minutes": int((now - pool_since).total_seconds() // 60),
        }
        if with_rider:
            row["rider_id"] = o.rider_id
            row["rider_name"] = rider_names.get(o.rider_id, "")
        return row

    heat = (await db.execute(text_sql(
        "SELECT lat, lng FROM orders WHERE created_at > now() - interval "
        "'2 hours' AND pickup = false LIMIT 500"))).all()

    _ = json_mod  # 保留占位(结构化返回无需手工序列化)
    return {
        "stats": {
            "riders_online": len(rider_rows),
            "pool": len(pool_orders),
            "in_flight": len(in_flight),
            "stuck": sum(1 for o in pool_orders
                         if order_row(o)["wait_minutes"] >= 10),
        },
        "riders": rider_rows,
        "pool": [order_row(o) for o in pool_orders],
        "in_flight": [order_row(o, with_rider=True) for o in in_flight],
        "heat": [{"lat": h[0], "lng": h[1]} for h in heat],
    }


@router.post("/orders/{order_no}/reassign")
async def reassign_order(
    order_no: str,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """配送改派:rider_id 空=释放回池(原骑手不计免责次数),
    传 rider_id=指定改派给在线骑手。PICKED_UP 的单餐在人手上,不可改派。"""
    from sqlalchemy import update as sa_update

    from ..models import Order, OrderEvent, RiderProfile, UserRole, VerifyStatus
    from ..services.push import push_to_user
    from ..state_machine import OrderStatus as OS

    order = await db.scalar(
        select(Order).where(Order.order_no == order_no).with_for_update())
    if order is None:
        raise HTTPException(404, "订单不存在")
    if order.self_delivery:
        raise HTTPException(409, "商家自配送订单不走骑手,不能改派")
    if order.status == OS.PICKED_UP:
        raise HTTPException(409, "骑手已取餐(餐在人手上),不能改派;请走配送异常仲裁")
    if order.status not in (OS.ACCEPTED, OS.READY):
        raise HTTPException(409, "订单当前状态不支持改派")
    if order.parent_order_no:
        raise HTTPException(409, "追加单随原单配送,请改派原单")

    target_id = payload.get("rider_id")
    old_rider = order.rider_id
    now = datetime.now(timezone.utc)

    if target_id:
        target = await db.get(User, int(target_id))
        if target is None or target.role != UserRole.rider:
            raise HTTPException(404, "目标骑手不存在")
        profile = await db.scalar(select(RiderProfile).where(
            RiderProfile.rider_id == target.id))
        if profile is None or profile.status != VerifyStatus.approved:
            raise HTTPException(409, "目标骑手未通过实名认证")
        if not target.is_online:
            raise HTTPException(409, "目标骑手不在线")
        active = await db.scalar(
            select(func.count(Order.id)).where(
                Order.rider_id == target.id,
                Order.status.in_([OS.ACCEPTED, OS.READY, OS.PICKED_UP]),
                Order.parent_order_no == ""))
        if active >= 3:
            raise HTTPException(409, f"目标骑手手头已有 {active} 单在途(上限 3)")
        order.rider_id = target.id
        note = f"平台改派给骑手#{target.id}"
    else:
        order.rider_id = None
        order.rider_pool_since = now
        order.no_rider_alerted_at = None
        note = "平台释放回抢单池"

    # 追加单骑手跟随
    await db.execute(
        sa_update(Order)
        .where(Order.parent_order_no == order_no)
        .values(rider_id=order.rider_id))
    db.add(OrderEvent(
        order_id=order.id, from_status=order.status.value,
        to_status="reassigned", actor_role="admin", actor_id=admin.id,
        note=note))
    await db.commit()

    if old_rider and old_rider != order.rider_id:
        await push_to_user(old_rider, "订单已由平台协调改派",
                           f"订单 {order.order_no[-6:]} 已由平台协调处理,"
                           f"无需再配送;此次不计入你的转单次数",
                           {"type": "order", "order_no": order.order_no})
    if target_id and order.rider_id:
        await push_to_user(order.rider_id, "平台给你派了一单",
                           f"订单 {order.order_no[-6:]} 已协调由你配送,"
                           f"请在「我的配送」查看",
                           {"type": "order", "order_no": order.order_no})
    return {"ok": True, "rider_id": order.rider_id}


# ---------- 骑手装备发放 ----------

@router.get("/rider-gear")
async def list_rider_gear(
    status: str = "requested",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import RiderGear
    query = (select(RiderGear, User)
             .join(User, User.id == RiderGear.rider_id)
             .order_by(RiderGear.created_at.desc()).limit(200))
    if status:
        query = query.where(RiderGear.status == status)
    rows = (await db.execute(query)).all()
    labels = {"helmet": "头盔", "box": "保温餐箱", "raincoat": "雨衣"}
    return [{
        "id": g.id, "rider_id": g.rider_id, "rider_phone": u.phone,
        "item": g.item, "item_label": labels.get(g.item, g.item),
        "status": g.status, "note": g.note,
        "created_at": g.created_at.isoformat(),
    } for g, u in rows]


@router.post("/rider-gear/{gear_id}/issue")
async def issue_rider_gear(
    gear_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import RiderGear
    from ..services.push import push_to_user
    g = await db.get(RiderGear, gear_id, with_for_update=True)
    if g is None:
        raise HTTPException(404, "申领记录不存在")
    if g.status != "requested":
        raise HTTPException(409, "该申领已处理过")
    g.status = "issued"
    g.note = str(payload.get("note", ""))[:200]
    g.issued_at = datetime.now(timezone.utc)
    await db.commit()
    await push_to_user(g.rider_id, "装备已发放",
                       f"你申领的装备已安排发放{':' + g.note if g.note else ''};"
                       f"详情见钱包页装备申领记录",
                       {"type": "gear"}, record_skip=True)
    return {"ok": True}


# ---------- 骑手事故跟进(红色加急) ----------

@router.get("/rider-accidents")
async def list_rider_accidents(
    status: str = "open",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import RiderAccident
    query = (select(RiderAccident, User)
             .join(User, User.id == RiderAccident.rider_id)
             .order_by(RiderAccident.created_at.desc()).limit(100))
    if status:
        query = query.where(RiderAccident.status == status)
    rows = (await db.execute(query)).all()
    return [{
        "id": a.id, "rider_id": a.rider_id, "rider_phone": u.phone,
        "severity": a.severity, "description": a.description,
        "photos": a.photos, "status": a.status, "actions": a.actions,
        "lat": a.lat, "lng": a.lng,
        "created_at": a.created_at.isoformat(),
    } for a, u in rows]


@router.post("/rider-accidents/{accident_id}/update")
async def update_rider_accident(
    accident_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """跟进/结案(SOP 见 docs/RIDER_SOP.md),处置留痕。"""
    from ..models import RiderAccident
    status = str(payload.get("status", ""))
    note = str(payload.get("note", "")).strip()
    if status not in ("following", "closed"):
        raise HTTPException(422, "status 只支持 following / closed")
    if len(note) < 2:
        raise HTTPException(422, "请填写跟进/结案说明(留痕)")
    acc = await db.get(RiderAccident, accident_id, with_for_update=True)
    if acc is None:
        raise HTTPException(404, "事故记录不存在")
    acc.status = status
    acc.actions = [*(acc.actions or []), {
        "status": status, "note": note[:300], "admin_id": admin.id,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }]
    await db.commit()
    return {"ok": True}


# ---------- 超时赔付统计(只统计不追责,供改进) ----------

@router.get("/eta-compensations")
async def list_eta_compensations(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """近 100 笔超时安抚券:note 里带超时分钟与归因(商家出餐慢/配送慢/等待久)。"""
    from ..models import Coupon
    rows = (await db.execute(
        select(Coupon, User.phone)
        .join(User, User.id == Coupon.user_id)
        .where(Coupon.source.like("eta:%"))
        .order_by(Coupon.created_at.desc()).limit(100))).all()
    return [{
        "id": c.id, "user_phone": phone,
        "order_no": c.source.removeprefix("eta:"),
        "amount_cents": c.amount_cents, "note": c.note,
        "used": bool(c.used_order_no),
        "created_at": c.created_at.isoformat(),
    } for c, phone in rows]


# ---------- 多城市运营 ----------

@router.get("/cities")
async def list_cities(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """已有商家的城市清单(含未标注数量)+ 当前开城清单。"""
    from ..services.flags import open_cities
    rows = (await db.execute(
        select(Merchant.city, func.count(Merchant.id))
        .group_by(Merchant.city))).all()
    return {
        "cities": [{"city": c or "(未标注)", "merchants": n}
                   for c, n in sorted(rows, key=lambda r: -r[1])],
        "open_cities": await open_cities(db) or [],
    }


@router.post("/merchants/{merchant_id}/city")
async def set_merchant_city(
    merchant_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """人工改商家城市(逆地理失败/解析错时兜底)。"""
    shop = await db.get(Merchant, merchant_id)
    if shop is None:
        raise HTTPException(404, "商家不存在")
    shop.city = str(payload.get("city", "")).strip()[:20]
    await db.commit()
    return {"id": merchant_id, "city": shop.city}


@router.post("/merchants/{merchant_id}/category")
async def set_merchant_category(
    merchant_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """人工改商家品类(商家错归类时纠错,白名单见 categories.py)。"""
    from ..categories import MERCHANT_CATEGORIES

    category = str(payload.get("category", ""))
    if category not in MERCHANT_CATEGORIES:
        raise HTTPException(422, "未知品类")
    shop = await db.get(Merchant, merchant_id)
    if shop is None:
        raise HTTPException(404, "商家不存在")
    shop.category = category
    await db.commit()
    return {"id": merchant_id, "category": category}


@router.post("/riders/{rider_id}/city")
async def set_rider_city(
    rider_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """人工改骑手城市(跨城搬家/解析错时兜底)。"""
    from ..models import UserRole
    rider = await db.get(User, rider_id)
    if rider is None or rider.role != UserRole.rider:
        raise HTTPException(404, "骑手不存在")
    rider.city = str(payload.get("city", "")).strip()[:20]
    await db.commit()
    return {"id": rider_id, "city": rider.city}


@router.get("/orders/{order_no}/messages")
async def admin_order_messages(
    order_no: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """仲裁调取聊天记录(留档 7 天后仍可查)。"""
    from ..models import Message, Order
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None:
        raise HTTPException(404, "订单不存在")
    rows = (await db.scalars(
        select(Message).where(Message.order_id == order.id)
        .order_by(Message.created_at).limit(500))).all()
    return [{"id": m.id, "from": m.sender_role, "to": m.receiver_role,
             "kind": m.kind, "content": m.content,
             "created_at": m.created_at.isoformat()} for m in rows]


# ---------- 分账管理(二清收口) ----------

@router.post("/merchants/{merchant_id}/sub-mchid")
async def set_sub_mchid(
    merchant_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """登记微信特约商户号与分账就绪标记(进件+接收方绑定完成后打开)。

    ready=True 后该店新支付的订单走 profit_sharing 口径(货款不经平台)。
    """
    shop = await db.get(Merchant, merchant_id)
    if shop is None:
        raise HTTPException(404, "商家不存在")
    sub_mchid = str(payload.get("sub_mchid", "")).strip()[:32]
    ready = bool(payload.get("ready", False))
    if ready and not sub_mchid:
        raise HTTPException(422, "先填特约商户号才能打开分账就绪")
    shop.sub_mchid = sub_mchid
    shop.ps_ready = ready
    await db.commit()
    return {"id": merchant_id, "sub_mchid": sub_mchid, "ps_ready": ready}


@router.get("/profit-sharing")
async def list_profit_sharing(
    status: str = "",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """分账台账(近 200 条):pending 待渠道/重试,failed 需人工介入。"""
    from ..models import ProfitSharingRecord
    query = (select(ProfitSharingRecord, Merchant.name)
             .join(Merchant, Merchant.id == ProfitSharingRecord.merchant_id)
             .order_by(ProfitSharingRecord.created_at.desc()).limit(200))
    if status:
        query = query.where(ProfitSharingRecord.status == status)
    rows = (await db.execute(query)).all()
    return [{
        "id": r.id, "order_no": r.order_no, "merchant": name,
        "sub_mchid": r.sub_mchid, "net_cents": r.net_cents,
        "commission_cents": r.commission_cents, "status": r.status,
        "attempts": r.attempts, "note": r.note,
        "created_at": r.created_at.isoformat(),
    } for r, name in rows]


# ---------- 骑手 SOS(红色加急,5 分钟回访) ----------

@router.get("/rider-emergencies")
async def list_rider_emergencies(
    status: str = "open",
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import RiderEmergency
    query = (select(RiderEmergency, User)
             .join(User, User.id == RiderEmergency.rider_id)
             .order_by(RiderEmergency.created_at.desc()).limit(100))
    if status:
        query = query.where(RiderEmergency.status == status)
    rows = (await db.execute(query)).all()
    return [{
        "id": e.id, "rider_id": e.rider_id, "rider_phone": u.phone,
        "lat": e.lat, "lng": e.lng, "note": e.note, "status": e.status,
        "actions": e.actions, "created_at": e.created_at.isoformat(),
    } for e, u in rows]


@router.post("/rider-emergencies/{sos_id}/update")
async def update_rider_emergency(
    sos_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """跟进/结案(SOP:5 分钟回电,确认安全前每 10 分钟跟进),处置留痕。"""
    from ..models import RiderEmergency
    status = str(payload.get("status", ""))
    note = str(payload.get("note", "")).strip()
    if status not in ("following", "closed"):
        raise HTTPException(422, "status 只支持 following / closed")
    if len(note) < 2:
        raise HTTPException(422, "请填写跟进/结案说明(留痕)")
    sos = await db.get(RiderEmergency, sos_id, with_for_update=True)
    if sos is None:
        raise HTTPException(404, "求助记录不存在")
    sos.status = status
    sos.actions = [*(sos.actions or []), {
        "status": status, "note": note[:300], "admin_id": admin.id,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }]
    await db.commit()
    return {"ok": True}


# ---------- 营销:券批次管理 ----------

@router.post("/coupon-batches")
async def create_coupon_batch(
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """创建券批次。trigger:newcomer 注册自动发 / manual 定向补偿发。

    **birthday / winback / referral 已移出平台侧**(#115):那三个是营销,
    营销的钱该商家出——平台立场是不靠补贴换增长。商家在自己的店铺
    设置里建同名批次即可(POST /merchants/me/coupon-batches)。
    存量的平台批次跑完即止,不受影响。
    """
    from ..models import CouponBatch
    name = str(payload.get("name", "")).strip()[:50]
    trigger = str(payload.get("trigger", "manual"))
    try:
        amount = int(payload.get("amount_cents", 0))
        min_spend = int(payload.get("min_spend_cents", 0))
        valid_days = int(payload.get("valid_days", 7))
        total = int(payload.get("total", 0))
    except (TypeError, ValueError):
        raise HTTPException(422, "金额/天数/总量需为整数")
    if not name:
        raise HTTPException(422, "请填写批次名称")
    if trigger in ("birthday", "winback", "referral"):
        raise HTTPException(
            422, "生日券/复购券/新客推荐券由商家自建(成本商家承担),"
                 "平台不再建这三类批次")
    if trigger not in ("newcomer", "manual"):
        raise HTTPException(422, "trigger 不合法")
    if not 1 <= amount <= 5000:
        raise HTTPException(422, "面额需在 0.01-50 元之间(补贴要克制)")
    if not 1 <= total <= 100000:
        raise HTTPException(422, "总量需在 1-100000 之间")
    if not 1 <= valid_days <= 90 or min_spend < 0:
        raise HTTPException(422, "有效期 1-90 天,门槛不能为负")
    batch = CouponBatch(name=name, trigger=trigger, amount_cents=amount,
                        min_spend_cents=min_spend, valid_days=valid_days,
                        total=total)
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return {"id": batch.id}


@router.get("/coupon-batches")
async def list_coupon_batches(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """批次列表+转化统计:发了多少/用了多少/带来多少单。"""
    from ..models import Coupon, CouponBatch
    batches = (await db.scalars(
        select(CouponBatch).order_by(CouponBatch.created_at.desc())
        .limit(100))).all()
    used_rows = (await db.execute(
        select(Coupon.batch_id, func.count(Coupon.id))
        .where(Coupon.batch_id.isnot(None), Coupon.used_order_no != "")
        .group_by(Coupon.batch_id))).all()
    used_map = dict(used_rows)
    return [{
        "id": b.id, "name": b.name, "trigger": b.trigger,
        "amount_cents": b.amount_cents, "min_spend_cents": b.min_spend_cents,
        "valid_days": b.valid_days, "total": b.total, "issued": b.issued,
        "used": used_map.get(b.id, 0), "active": b.active,
        "created_at": b.created_at.isoformat(),
    } for b in batches]


@router.post("/coupon-batches/{batch_id}/toggle")
async def toggle_coupon_batch(
    batch_id: int,
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from ..models import CouponBatch
    batch = await db.get(CouponBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    batch.active = bool(payload.get("active", not batch.active))
    await db.commit()
    return {"id": batch_id, "active": batch.active}


@router.post("/coupons/issue")
async def issue_coupon_directed(
    payload: dict,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """按手机号定向发券(客服补偿场景)。每人每批次一张。"""
    from ..models import CouponBatch, UserRole
    from ..services.coupons import issue_from_batch
    from ..services.push import push_to_user
    phone = str(payload.get("phone", "")).strip()
    batch = await db.get(CouponBatch, int(payload.get("batch_id", 0)))
    if batch is None:
        raise HTTPException(404, "批次不存在")
    # 券只发用户端账号(同手机号可能另有商家/骑手账号)
    target = await db.scalar(select(User).where(
        User.phone == phone, User.role == UserRole.customer))
    if target is None:
        raise HTTPException(404, "该手机号没有注册过用户端")
    coupon = await issue_from_batch(
        db, batch, target.id,
        note=str(payload.get("note", "")).strip()[:60] or batch.name)
    if coupon is None:
        raise HTTPException(409, "没发出去:已领过/批次停用/预算发完")
    await db.commit()
    await push_to_user(target.id, "收到一张优惠券",
                       f"{batch.name}:{batch.amount_cents / 100:g} 元,"
                       f"{batch.valid_days} 天内有效,下单自动可选",
                       {"type": "coupon"}, record_skip=True)
    return {"ok": True, "coupon_id": coupon.id}


@router.get("/referrals")
async def list_referrals(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """邀请关系与转化漏斗:填码数/已奖励(=首单完成)数/发券数。"""
    from ..models import Coupon, Referral
    total = await db.scalar(select(func.count(Referral.id)))
    rewarded = await db.scalar(select(func.count(Referral.id)).where(
        Referral.status == "rewarded"))
    coupons = await db.scalar(select(func.count(Coupon.id)).where(
        Coupon.source.like("referral:%")))
    rows = (await db.execute(
        select(Referral, User.phone)
        .join(User, User.id == Referral.inviter_id)
        .order_by(Referral.created_at.desc()).limit(100))).all()
    return {
        "funnel": {"claimed": total, "rewarded": rewarded,
                   "coupons_issued": coupons},
        "recent": [{
            "id": r.id, "inviter_phone": phone, "status": r.status,
            "created_at": r.created_at.isoformat(),
        } for r, phone in rows],
    }


# ---------------------------------------------------------------------------
# 明厨亮灶首帧核验(#155/#157)
#
# 这一步**不能省**。行业里「摄像头对着天花板」的乱象,就是因为没人看过一眼
# 就把标识发出去了。平台在列表页标「有明厨亮灶」而实际是天花板,
# 用户因此下单出了事 —— 食品安全法第一百三十一条,平台负连带责任。
#
# 人工要看两件事,缺一不可:
#   ① 镜头对的是不是加工制作的关键环节(操作台/灶台/备餐/洗消);
#   ② **有没有拍到不该拍的**(休息区/更衣/卫生间/顾客面部)——
#      后厨里站着的也是劳动者,这条和第一条一样重要。
# ---------------------------------------------------------------------------


@router.get("/kitchen-cams/pending")
async def list_pending_kitchen_cams(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """待核验的明厨亮灶接入申请。"""
    from ..services import kitchen_cam as kc

    rows = (await db.scalars(
        select(Merchant)
        .where(Merchant.kitchen_cam_status == kc.STATUS_PENDING)
        .order_by(Merchant.id.desc()).limit(100))).all()
    return {
        "items": [{
            "merchant_id": m.id, "name": m.name, "address": m.address,
            "url": m.kitchen_cam_url, "vendor": m.kitchen_cam_vendor,
            "shot_url": m.kitchen_cam_shot_url,
            "notified": m.kitchen_cam_notified,
        } for m in rows],
        # 核验清单随接口下发,避免审核员凭印象判
        "checklist_pass": kc.SHOULD_COVER,
        "checklist_reject": kc.MUST_NOT_COVER,
        "how_to": "自己打开播放地址看一眼。两件事都要看:"
                  "镜头对的是不是操作区;有没有拍到不该拍的。"
                  "拍到休息区/更衣/卫生间/顾客面部的一律退回",
    }


class KitchenCamReviewIn(BaseModel):
    approve: bool
    reason: str = Field(default="", max_length=200)


@router.post("/kitchen-cams/{merchant_id}/review")
async def review_kitchen_cam(
    merchant_id: int,
    payload: KitchenCamReviewIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """核验通过/退回。

    退回时**必须写理由** —— 商家要知道该怎么调镜头才能过,
    否则他只会反复提交。这也是法规里平台"提供技术支持"的一部分。
    """
    from ..services import kitchen_cam as kc

    shop = await db.get(Merchant, merchant_id, with_for_update=True)
    if shop is None:
        raise HTTPException(404, "店铺不存在")
    if shop.kitchen_cam_status != kc.STATUS_PENDING:
        raise HTTPException(409, "该店铺不在待核验状态")

    from ..services.push import push_to_user

    if payload.approve:
        shop.kitchen_cam_status = kc.STATUS_ACTIVE
        shop.kitchen_cam_verified_at = datetime.now(timezone.utc)
        shop.kitchen_cam_reason = ""
        shop.kitchen_cam_note = "核验通过,顾客可以看到「有明厨亮灶」"
        shop.kitchen_cam_ok_streak = 1
        shop.kitchen_cam_fail_streak = 0
        await push_to_user(
            shop.owner_id, "明厨亮灶已通过核验",
            "顾客在列表里能看到你的店标着「有明厨亮灶」了",
            {"type": "kitchen_cam"})
    else:
        if not payload.reason.strip():
            raise HTTPException(422, "退回必须写明理由 —— "
                                     "商家要知道镜头该怎么调才能过")
        shop.kitchen_cam_status = kc.STATUS_NONE
        shop.kitchen_cam_reason = "rejected"
        shop.kitchen_cam_note = payload.reason.strip()[:200]
        await push_to_user(
            shop.owner_id, "明厨亮灶未通过核验",
            f"{payload.reason.strip()[:80]};调整后可以再提交",
            {"type": "kitchen_cam"})

    await db.commit()
    return {"merchant_id": shop.id, "status": shop.kitchen_cam_status,
            "note": shop.kitchen_cam_note}


# ---------------------------------------------------------------------------
# 食安培训:通知存量骑手(#167 的过渡动作)
# ---------------------------------------------------------------------------


class TrainingRolloutIn(BaseModel):
    #: 宽限截止日(ISO)。空 = 立即生效,没做培训的当场上不了线
    grace_until: str = Field(default="", max_length=10)
    #: 只统计不推送(先看看影响面有多大)
    dry_run: bool = False


@router.post("/riders/training-rollout")
async def training_rollout(
    payload: TrainingRolloutIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """把食安培训要求推给全体存量骑手。

    ## 为什么不是"直接给他们补一条培训记录"

    培训记录是**法定记录**(123 号令第二十九条,保存不少于二年,
    监管可以调取)。给没培训过的人补一条"已通过",是在伪造一份
    随时可能被查的合规记录 —— 一旦被查出来,平台面对的不是
    "没培训"的处罚,而是"造假"。

    **所以这里做的是通知 + 设窗口,让人真去做那三分钟。**

    ## grace_until 的语义

    - 传日期:窗口内没做培训的骑手照常上线,每次上线带一条提醒;
    - 传空:立即生效 —— 没做培训的下次上线就会被拦。

    立即生效是合规上最干净的,但会让一批骑手当天跑不了单。
    传日期给几天缓冲更稳妥,由调用方决定。
    """
    from ..models import RiderExam, RiderProfile
    from ..services.push import push_to_user

    trained = select(RiderExam.rider_id).where(RiderExam.passed.is_(True))
    rows = (await db.execute(
        select(RiderProfile.rider_id, User.name)
        .join(User, User.id == RiderProfile.rider_id)
        .where(RiderProfile.status == VerifyStatus.approved,
               RiderProfile.rider_id.notin_(trained)))).all()

    grace = payload.grace_until.strip()
    if grace:
        from datetime import date as _date
        try:
            _date.fromisoformat(grace)
        except ValueError:
            raise HTTPException(422, "宽限截止日要写成 YYYY-MM-DD")

    if not payload.dry_run:
        flag = await db.get(PlatformFlag, "rider_training_grace_until")
        # 空串 = 解析不出日期 = 立即生效(_parse_grace 解析失败即硬卡,
        # 这是刻意的:配置错误不该让合规卡点形同虚设)
        if flag is None:
            db.add(PlatformFlag(key="rider_training_grace_until", value=grace))
        else:
            flag.value = grace
        await db.commit()

        body = (f"请在 {grace} 前完成(三分钟)" if grace
                else "现在需要先完成才能上线(三分钟)")
        for rider_id, _name in rows:
            await push_to_user(
                rider_id, "需要完成一次食品安全培训",
                f"这是监管对平台的要求,不是给你加的规矩 —— {body}。"
                "「我的」→ 上岗培训,答错有讲解、可以重来",
                {"type": "training"})

    return {
        "pending": len(rows),
        "grace_until": grace or None,
        "dry_run": payload.dry_run,
        "note": ("已通知全体未完成培训的骑手" if not payload.dry_run
                 else "只统计未推送"),
        "why_not_backfill": "培训记录是法定记录(保存≥2 年、监管可调取),"
                            "给没培训的人补一条「已通过」是伪造合规记录 —— "
                            "查出来面对的不是「没培训」的处罚,是「造假」",
    }
