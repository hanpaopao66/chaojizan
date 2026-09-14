"""判责申诉:骑手/商家对平台单方裁决的复核通道。

可申诉的目标(72 小时内、每个目标一次;完整的表见 [AppealIn]):
- after_sale       商家申诉「商家责任」售后判责(含配送异常「到店未出餐」「餐品不齐」判商家责任
                   时记的那条售后 —— services/delivery_fault)
- after_sale_rider 骑手申诉「骑手责任」售后判责(admin.after_sale_rider_fault)—— 和商家那条对齐
- delivery_issue   骑手申诉「判骑手责任」的配送异常裁决(用户申诉判用户原因的)
- review           商家申诉恶意差评

改判的钱怎么走(用户拿到的退款不倒找):
- after_sale 改判  → **只撤销判责**:AfterSale.fault merchant → cleared(models.AFTER_SALE_FAULT_CLEARED),
                     信用分那一条不再计分;**被冲的净额不补回**(2026-09-14 拍板「平台没有钱」:
                     原来补一条 adjustment 正向行、平台认亏,停了;顾客拿到的退款也不追回,
                     所以这笔钱照旧是商家出的)。食安投诉成立记的那条同样(admin.confirm_food_safety)
- after_sale_rider / delivery_issue 改判 → 对应 AfterSale.fault: rider → platform
                     (骑手消责正名,审计规则 6 的免冲账口径同步认 platform);判责时从骑手
                     扣的加回去、保障金池出的回池(services/rider_fault)—— 错判由平台认
- after_sale_rejected 改判(顾客) → 按商家同意的口径:退餐费、商家冲账、判商家责任;
                     跑腿单没有商家 → 判骑手责任(rider_fault.judge_after_sale),平台不出钱
- review 改判      → 差评 hidden,评分聚合同步扣减
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    AfterSale,
    AfterSaleStatus,
    Appeal,
    DeliveryIssue,
    EarningKind,
    Merchant,
    MerchantEarning,
    Order,
    OrderEvent,
    QueueEvent,
    QueueTicket,
    Review,
    RiskActionLog,
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
    "after_sale_rider": "售后判骑手责任",
    "delivery_issue": "配送异常裁决",
    "review": "差评",
    "cancel_split": "取消订单的判责分摊",
    "review_hidden": "评价被隐藏",
    "after_sale_rejected": "售后被拒绝",
    "risk_flag": "账号被风控限制",
    "queue_pass": "排队被过号",
}


class AppealIn(BaseModel):
    target_type: Literal["after_sale", "after_sale_rider", "delivery_issue", "review",
                         "cancel_split", "review_hidden",
                         "after_sale_rejected", "risk_flag", "queue_pass"]
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
    target_label: str = ""     # 申诉的是哪一类裁决(_TYPE_LABELS),后台照着显示,不另写一份


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
        # 显式传这条售后的门店:不传的话走 X-Shop-Id /「我唯一的那家店」,连锁店主在
        # 「我的信用分」里申诉另一家门店的售后判责会被判成 404(权限照样完整校验)
        shop = await owned_shop(db, user, a.merchant_id) if a is not None else None
        if a is None or shop is None or a.merchant_id != shop.id:
            raise HTTPException(404, "售后记录不存在")
        if a.status.value != "accepted" or a.fault != "merchant":
            # 判骑手责任的是骑手的事;平台认赔的(历史)、改判过的,商家都没有要撤销的判责
            raise HTTPException(409, "只有判商家责任的已退款售后才需要申诉")
        if not _within_window(a.processed_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    elif payload.target_type == "after_sale_rider":
        # 售后仲裁判骑手责任(admin.after_sale_rider_fault)。以前骑手只有信用分工单一条路,
        # 商家那边的售后判责却有这条 72 小时的原通道 —— 同一种判决,一方能走原通道、另一方
        # 不能,就是不对称。这条和商家的 after_sale 对齐:同一个时限、同一个一次、同一个复核
        if user.role.value != "rider":
            raise HTTPException(403, "售后判骑手责任只有这一单的骑手可以申诉")
        a = await db.get(AfterSale, payload.target_id)
        order = await db.get(Order, a.order_id) if a is not None else None
        if a is None or order is None or order.rider_id != user.id:
            raise HTTPException(404, "售后记录不存在")
        if a.status != AfterSaleStatus.accepted or a.fault != "rider":
            raise HTTPException(409, "只有判骑手责任的售后才需要申诉")
        via_issue = await db.scalar(select(DeliveryIssue.id).where(
            DeliveryIssue.order_id == a.order_id, DeliveryIssue.resolution == "refund").limit(1))
        if via_issue is not None:
            # 配送异常裁成退款时顺手补的那条售后:判责记在配送异常上(信用分也记在那儿),
            # 在那条上申诉 —— 两条都开的话同一次判决能申诉两遍
            raise HTTPException(409, "这一单的判责记在配送异常上,请在那条配送异常上申诉")
        if not _within_window(a.processed_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    elif payload.target_type == "delivery_issue":
        # 骑手申诉判他责的(裁成退款),用户申诉判**用户**责的(按送达处理)。
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
                raise HTTPException(409, "只有判骑手责任的退款裁决才需要申诉")
            from ..services.delivery_fault import refund_fault
            if refund_fault(issue.kind) != "rider":
                # 到店未出餐、餐品不齐裁成退款判的是商家责任(商家在售后判责那条通道申诉)
                raise HTTPException(409, "这一次判的是商家责任,不算你的,不需要申诉")
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
    elif payload.target_type == "risk_flag":
        # `admin.set_user_risk_level` 的 docstring 写着「reason 会展示给用户,
        # **用户可申诉**」—— 但申诉的 target_type 里一直没有它,
        # 界面上那个「申请复核」点进去是人工工单,没有确定的结论。
        # 声称有的通道必须真的存在。
        #
        # 锚在 RiskActionLog 上而不是 user_id 上:每次处置一行,所以
        # 「这次标记」和「上次标记」是两个可以各自申诉的目标 ——
        # 挂在 user_id 上的话唯一约束会让一个人一辈子只能申诉一次。
        # **不限角色。** 风控处置接口接受任何 user_id,商家和骑手的账号
        # 一样会被限制、被冻结,而冻结对他们是断收入。
        # 只开给顾客的话,恰恰是把最受影响的两类人挡在外面 ——
        # 这条通道的判据是「是不是本人」,不是「是什么角色」。
        pass
        log = await db.get(RiskActionLog, payload.target_id)
        if log is None or log.user_id != user.id:
            raise HTTPException(404, "没有这条处置记录")
        if not log.to_level:
            raise HTTPException(409, "这条是解除限制的记录,不需要申诉")
        if user.risk_level != log.to_level:
            raise HTTPException(409, "这条处置已经不在生效中")
        if not _within_window(log.created_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    elif payload.target_type == "queue_pass":
        # 排队分配的是**没法补发的东西** —— 一个晚上的位子。
        # 商家标过号是个单方面动作,不给用户说话的地方的话,
        # 「顺延 N 桌」就成了一个随手清队列的按钮。
        #
        # 锚在号上:一个号一次申诉。窗口从**最后一次过号**起算。
        if user.role.value != "customer":
            raise HTTPException(403, "只有取号的本人可以申诉过号")
        ticket = await db.get(QueueTicket, payload.target_id)
        if ticket is None or ticket.customer_id != user.id:
            raise HTTPException(404, "没有这个号")
        if ticket.passed_count <= 0:
            raise HTTPException(409, "这个号没有被过号")
        last_pass = await db.scalar(
            select(func.max(QueueEvent.created_at)).where(
                QueueEvent.ticket_id == ticket.id, QueueEvent.action == "pass"))
        if not _within_window(last_pass):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    elif payload.target_type == "after_sale_rejected":
        # 商家**同意**售后(自己赔钱)一直有结构化申诉;商家**拒绝**售后
        # (用户一分拿不到)用户只能看到一句「如有异议可联系平台客服」——
        # 而售后一单一次,被拒之后连重提都不行。
        # 判谁责谁能申诉,这条现在只对一半的人成立,这里补另一半。
        if user.role.value != "customer":
            raise HTTPException(403, "售后被拒只有申请售后的用户可以申诉")
        a = await db.get(AfterSale, payload.target_id)
        if a is None:
            raise HTTPException(404, "售后记录不存在")
        order = await db.get(Order, a.order_id)
        if order is None or order.customer_id != user.id:
            raise HTTPException(404, "售后记录不存在")
        if a.status != AfterSaleStatus.rejected:
            raise HTTPException(409, "只有被拒绝的售后才需要申诉")
        if not _within_window(a.processed_at):
            raise HTTPException(422, "已超过 72 小时申诉时限")
    elif payload.target_type == "review_hidden":
        # 商家申诉差评成立 → 评价被隐藏、店铺评分加回去。
        # **写评价的人对这个结果一直没有说话的地方**,而这是平台在两个
        # 当事人之间做的单方面裁决 —— 一方能申诉、另一方连通知都收不到,
        # 不叫公平。这一条把另一半补上。
        if user.role.value != "customer":
            raise HTTPException(403, "评价被隐藏只有写这条评价的人可以申诉")
        review = await db.get(Review, payload.target_id)
        if review is None or review.customer_id != user.id:
            raise HTTPException(404, "评价不存在")
        if not review.hidden:
            raise HTTPException(409, "这条评价没有被隐藏")
        # 窗口从**评价被隐藏那一刻**起算 —— 也就是商家那条申诉的复核时刻
        hid_at = await db.scalar(
            select(Appeal.resolved_at).where(
                Appeal.target_type == "review", Appeal.target_id == review.id,
                Appeal.status == "overturned"))
        if not _within_window(hid_at):
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
    if appeal.target_type in ("after_sale", "after_sale_rider", "after_sale_rejected"):
        a = await db.get(AfterSale, appeal.target_id)
        if a is None:
            return "(记录不存在)"
        order = await db.get(Order, a.order_id)
        head = {"after_sale": "售后判商家责", "after_sale_rider": "售后判骑手责",
                "after_sale_rejected": "售后被商家拒绝"}[appeal.target_type]
        if appeal.target_type == "after_sale_rejected" and order is not None:
            from ..services.errand import is_errand
            if is_errand(order):
                # 跑腿没有商家,拒的是平台;改判成立 = 判骑手责任(扣骑手的钱),复核的人得知道
                head = "跑腿售后被平台驳回(改判成立即判骑手责任)"
        return (f"{head} 订单#{order.order_no[-6:]} "
                f"退款 ¥{order.refund_cents / 100:.2f}:{a.reason[:40]}")
    if appeal.target_type == "delivery_issue":
        issue = await db.get(DeliveryIssue, appeal.target_id)
        if issue is None:
            return "(记录不存在)"
        from ..services.delivery_fault import fault_of
        who = {"customer": "顾客原因", "rider": "骑手责", "merchant": "商家责"}.get(
            fault_of(issue.kind, issue.resolution), "未判责")
        return (f"配送异常判{who} 订单#{issue.order_no[-6:]} "
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
        o.target_label = _TYPE_LABELS.get(appeal.target_type, appeal.target_type)
        out.append(o)
    return out


async def _undo_rider_fault(db: AsyncSession, order_id: int, why: str) -> str:
    """骑手责任改判成立:判责时从骑手扣的加回去、保障金池出的回池(services/rider_fault)。
    返回推送里接在后面的那一句(没扣过钱的老裁决返回空串)。"""
    from ..services import rider_fault
    order = await db.get(Order, order_id, with_for_update=True)
    back = await rider_fault.undo(db, order, why=why) if order is not None else None
    if back is None:
        return ""
    return (f";判责时扣的 ¥{back.rider_total / 100:.2f} 已退回你的收入"
            if back.rider_total else "")


async def _overturn(db: AsyncSession, appeal: Appeal, note: str,
                    admin_id: int | None = None) -> None:
    """改判动作。用户已得的退款不追回;每一支的钱怎么走见模块抬头。

    [admin_id] 只有需要**留痕操作人**的分支用得上(queue_pass 的位置还原) ——
    那一步会改动队列,谁批的必须记下来才能复核。
    """
    if appeal.target_type == "after_sale":
        # 2026-09-14 起:改判只撤销判责、信用分那一条不再计分,**被冲的净额不补回**
        # (平台没有钱;顾客拿到的退款也不追回)。原来这里补一条 adjustment 正向行、平台认亏
        from ..models import AFTER_SALE_FAULT_CLEARED
        a = await db.get(AfterSale, appeal.target_id, with_for_update=True)
        if a.fault != "merchant":
            raise HTTPException(409, "这笔售后现在不是商家责任,没有可以撤销的判责")
        a.fault = AFTER_SALE_FAULT_CLEARED
        a.reply = (f"{a.reply};申诉改判:商家无责(钱不动)"
                   if a.reply else "申诉改判:商家无责(钱不动)")[:300]
        await _note_food_safety_overturn(db, a.order_id, note)
        await push_to_user(appeal.user_id, "申诉成立",
                           "售后判责已改判为商家无责,信用分那一条不再计分。这笔退款的钱不补回:"
                           "顾客拿到的不追回,平台也不出这笔钱",
                           {"type": "appeal"})
    elif appeal.target_type == "after_sale_rider":
        # 和配送异常判骑手责任改判同一个写法:判责从骑手转走(骑手消责正名),信用分那一条
        # 跟着不再计分;判责时从骑手扣的那部分加回去、保障金池出的那部分回池(services/rider_fault)
        a = await db.get(AfterSale, appeal.target_id, with_for_update=True)
        a.fault = "platform"
        a.reply = (f"{a.reply};骑手申诉改判:非骑手责任"
                   if a.reply else "骑手申诉改判:非骑手责任")[:300]
        back = await _undo_rider_fault(db, a.order_id, "售后判骑手责任申诉成立")
        await push_to_user(appeal.user_id, "申诉成立(已为你正名)",
                           "复核认定这笔售后不是你的责任,责任记录已消除,信用分那一条不再计分"
                           + back,
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
            # 退顾客为餐付的钱(services/refund_calc,配送费和小费照归骑手)
            from ..services.refund_calc import goods_unrefunded_cents
            borne = await goods_unrefunded_cents(db, order)
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
            back = await _undo_rider_fault(db, issue.order_id, "配送异常判骑手责任申诉成立")
            await push_to_user(appeal.user_id, "申诉成立(已为你正名)",
                               "复核认定该次配送异常非你的责任,责任记录已消除" + back,
                               {"type": "appeal"})
    elif appeal.target_type == "risk_flag":
        # 改判 = 平台认定这次限制不成立,当场解除。
        # 顺手补一条解除的留痕 —— 处置有痕,撤销也要有痕,
        # 否则公示里的「限制/解除各多少」会少算一次解除。
        target = await db.get(User, appeal.user_id, with_for_update=True)
        old_level = target.risk_level
        target.risk_level = ""
        target.risk_note = ""
        db.add(RiskActionLog(user_id=target.id, from_level=old_level,
                             to_level=""))
        await push_to_user(
            appeal.user_id, "申诉成立,账号限制已解除",
            f"复核认定这次限制不成立,已解除,相关权益恢复。"
            f"{note or ''}",
            {"type": "appeal"})
    elif appeal.target_type == "queue_pass":
        # 改判 = 平台认定这次过号不成立。
        #
        # **能还原就还原,还不了就照实说。** 队还在(同一天、号还在排),
        # 就撤销那次过号、还回过号前的位置 —— 这是 sort_key 唯一一条
        # 会变小的路径,而且只能还原到留痕里记着的那个值,平台自己也
        # 没有把谁挪到任意位置的能力。
        #
        # 队散了就补不回来了。排队分配的是一个晚上的位子,**这东西没法补发**,
        # 不像退款那样能拿钱找齐。这时候不拿一句含糊话盖过去:
        # 直说位置补不回来,判决本身计入商家的记录(和「提前点出餐」
        # 同一条立场 —— 只标不罚,治理靠数据)。
        from ..services import queue as q
        ticket = await db.get(QueueTicket, appeal.target_id,
                              with_for_update=True)
        restored = False
        if ticket is not None:
            restored = await q.undo_pass(db, ticket, admin_id)
        await push_to_user(
            appeal.user_id, "申诉成立",
            ("复核认定这次过号不成立,你的位置已还原。" if restored else
             "复核认定这次过号不成立。当时那条队已经散了,位置补不回来 —— "
             "这次判决计入商家的排队记录。")
            + (note or ""),
            {"type": "appeal"})
    elif appeal.target_type == "after_sale_rejected":
        # 改判 = 平台认定这笔售后本来就该成立。那就**按商家同意的口径**走:
        # 退款给用户、商家冲账。
        #
        # 这里**确实向商家追款**,和 cancel_split 那条(不追商家骑手)不一样,
        # 因为性质不同:那边商家把餐做好了、没做错事;这边是平台认定商家
        # 当初就该赔而他拒了。谁的问题谁负责 —— 判成商家的问题,就该商家出。
        #
        # 商家不服可以再申诉(走既有的 after_sale 那条)。两条的
        # target_type 不同,唯一约束各管各的,所以最多两轮,不会来回拉锯。
        a = await db.get(AfterSale, appeal.target_id, with_for_update=True)
        if a.status != AfterSaleStatus.rejected:
            # 被拒之后又按别的路径处理过(比如后台已经判了骑手责任、退过款):再按「售后被拒」
            # 改判一次就是退第二遍
            raise HTTPException(409, "这笔售后已经按别的路径处理过了,不能再按「售后被拒」改判")
        order = await db.get(Order, a.order_id, with_for_update=True)
        from ..services.errand import is_errand
        if is_errand(order):
            await _overturn_errand_rejected(db, appeal, a, order, note, admin_id)
            return
        from ..services.settlement import reverse_merchant_earning
        from ..services.wechat_pay import request_refund
        # 和「商家同意售后」同一个口径(services/refund_calc)。原来「菜 + 打包 − 满减 − 已退」
        # 会把缺货部分退款减两次、还把平台券抵掉的钱当现金退
        from ..services.refund_calc import goods_unrefunded_cents
        refundable = await goods_unrefunded_cents(db, order)
        if refundable > 0:
            await request_refund(db, order, refundable,
                                 "售后申诉改判:平台认定应当受理")
        await reverse_merchant_earning(
            db, order, f"售后申诉改判,商家应赔:{note or '复核认定售后成立'}")
        a.status = AfterSaleStatus.accepted
        a.fault = "merchant"
        a.processed_at = datetime.now(timezone.utc)   # 商家的申诉窗口从这里起算
        a.reply = (f"{a.reply};用户申诉改判:售后成立")[:300]
        await push_to_user(
            appeal.user_id, "申诉成立",
            f"复核认定这笔售后应当受理,¥{refundable / 100:.2f} 已原路退回",
            {"type": "appeal"})
        shop = await db.get(Merchant, a.merchant_id)
        if shop is not None:
            await push_to_user(
                shop.owner_id, "一笔被你拒绝的售后被改判",
                f"顾客提出申诉,平台复核后认定应当受理。{note}"
                f"(如不认同,72 小时内可再申诉)",
                {"type": "appeal"})
    elif appeal.target_type == "review_hidden":
        review = await db.get(Review, appeal.target_id, with_for_update=True)
        if not review.hidden:
            raise HTTPException(409, "这条评价已经是显示状态")
        review.hidden = False
        shop = await db.get(Merchant, review.merchant_id, with_for_update=True)
        shop.rating_sum += review.merchant_rating
        shop.rating_count += 1
        await push_to_user(appeal.user_id, "申诉成立,评价已恢复",
                           f"复核认定你的评价应当保留,已重新显示在店铺页,"
                           f"并重新计入评分。{note}",
                           {"type": "appeal"})
        # 商家也要被告知 —— 他那条申诉的结果被推翻了,不能只通知赢的一方
        # (这正是上一轮的毛病,不能在对称的位置再犯一次)
        shop_owner = await db.get(Merchant, review.merchant_id)
        await push_to_user(
            shop_owner.owner_id, "一条已隐藏的评价被恢复",
            f"顾客对隐藏结果提出申诉,平台复核后决定恢复显示。{note}",
            {"type": "appeal"})
    elif appeal.target_type == "cancel_split":
        # 改判 = 平台认定这一单不该由用户承担。
        #
        # **不向商家和骑手追款。** 他们各自把该做的做完了(餐做好了、路跑了),
        # 把已经发出去的钱要回来,等于让他们为平台的一次判断失误买单。
        # 所以这笔由平台掏,走退款通道原路退给用户。
        #
        # ⚠️ 2026-09-14「平台没有钱」拍板时,这一支(和顾客「按送达处理」改判那一支)
        # 没在要改的清单里,照旧是平台出钱 —— 要不要改、改成谁出,还没定。
        #
        # 若复核认定确属**商家**责任,那是另一条路径(售后冲账),
        # 不在这里混着做 —— 一个动作只做一件事,账才查得清。
        order = await db.get(Order, appeal.target_id, with_for_update=True)
        # 他承担的 = 实付里还没退回的钱(services/refund_calc):不含平台券抵掉的部分,
        # 也不会把之前的缺货退款减两次
        from ..services.refund_calc import unrefunded_paid_cents
        borne = await unrefunded_paid_cents(db, order)
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
        # **写评价的人必须被告知,而且要知道自己能申诉。**
        #
        # 原来这里只通知申诉人(商家)。于是发生的事是:用户写的评价从店铺页
        # 消失了、店铺评分涨回去了,而他一无所知 —— 平台在两个当事人之间
        # 做了单方面裁决,只告诉了赢的那一方。
        await push_to_user(
            review.customer_id, "你的一条评价被隐藏了",
            f"商家就这条评价提出申诉,平台复核后认定应当隐藏。"
            f"理由:{note or '复核认定该评价不成立'}。"
            f"如果你不认同,72 小时内可以申诉,平台会再核一次。",
            {"type": "review_hidden", "review_id": review.id})


async def _note_food_safety_overturn(db: AsyncSession, order_id: int, note: str) -> None:
    """食安投诉成立记的那条售后判责被商家申诉改判:在投诉的处置留痕里记一笔。

    投诉本身照旧是「成立」(顾客那边拿到的退款不追回),自动停业的 30 天计数不再算它
    (admin.confirm_food_safety 按判责方 cleared 排除)。"""
    from ..models import FoodSafetyReport
    report = await db.scalar(select(FoodSafetyReport).where(
        FoodSafetyReport.order_id == order_id, FoodSafetyReport.status == "confirmed")
        .with_for_update())
    if report is None:
        return
    report.actions = [*(report.actions or []), {
        "action": "appeal_overturned",
        "note": f"商家申诉改判:商家无责(钱不动){(':' + note) if note else ''}"[:300],
        "admin_id": None,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }]


async def _overturn_errand_rejected(db: AsyncSession, appeal: Appeal, a: AfterSale,
                                    order: Order, note: str, admin_id: int | None) -> None:
    """跑腿单「售后被拒」改判成立:**判骑手责任**(2026-09-14 起)。

    跑腿没有商家,平台认定这笔售后应当受理,就只可能是骑手的问题。以前这里退了商品款、
    判责记成「商家」—— 可跑腿没有商家入账可冲,退出去的钱其实是平台出的。现在照售后仲裁
    判骑手责任走(rider_fault.judge_after_sale:顾客全额退款、这单骑手收入冲回、平台服务费
    不收),骑手 72 小时内可以在 after_sale_rider 申诉。
    """
    from ..services import rider_fault
    if order.rider_id is None or order.total_cents <= 0:
        raise HTTPException(409, "这一单没有骑手或者已经没有可退的钱,判不了骑手责任")
    reason = (f"{a.reply};顾客申诉改判:判骑手责任({note or '复核认定售后应当受理'})"
              if a.reply else f"顾客申诉改判:判骑手责任({note or '复核认定售后应当受理'})")
    refunded, split = await rider_fault.judge_after_sale(
        db, a, order, reason=reason, actor_role="admin", actor_id=admin_id)
    await push_to_user(
        appeal.user_id, "申诉成立",
        f"复核认定这笔售后应当受理,判为骑手责任,¥{refunded / 100:.2f} 已原路退回(含跑腿费)",
        {"type": "appeal"})
    from ..services import credit
    await push_to_user(
        order.rider_id, "一笔跑腿售后判为骑手责任",
        f"订单 {order.order_no[-6:]} 的售后,顾客申诉后平台复核认定应当受理,判为骑手责任,"
        f"顾客已全额退款。{rider_fault.rider_push_text(split)}。"
        f"这次记为骑手责任(信用分 −{credit.FAULT_POINTS}),"
        "不认同可以在 72 小时内申诉(「我的信用分」里这一条旁边),改判成立扣的钱退回",
        {"order_no": order.order_no}, record_skip=True)


#: 结论会改信用分扣分项的那几类申诉(services/credit.py 的 ORIGINAL_CHANNEL,
#: 加上顾客的「售后被拒」—— 它改判成立就是店主的一条扣分)
_CREDIT_TARGETS = ("delivery_issue", "after_sale", "after_sale_rider", "after_sale_rejected")


async def _target_order(db: AsyncSession, appeal: Appeal) -> Order | None:
    """被申诉的那条配送异常 / 售后记录是哪一单。"""
    if appeal.target_type == "delivery_issue":
        issue = await db.get(DeliveryIssue, appeal.target_id)
        return await db.get(Order, issue.order_id) if issue else None
    a = await db.get(AfterSale, appeal.target_id)
    return await db.get(Order, a.order_id) if a else None


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
        await _overturn(db, appeal, payload.note, admin.id)
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
    if appeal.target_type in _CREDIT_TARGETS:
        # 配送异常、售后判责的申诉有结论了:改判的那一条不再扣信用分(判顾客原因的、判骑手
        # 责任的、判商家责任的都走这里);「售后被拒」改判成立反过来是店主多了一条扣分。
        # 这一单三方的缓存都打掉,提交之后再打(见 services/credit.py)
        from ..services import credit
        await credit.invalidate(appeal.user_id)
        await credit.invalidate_order(db, await _target_order(db, appeal))
    applicant = await db.get(User, appeal.user_id)
    out = AdminAppealOut.model_validate(appeal)
    out.role, out.name, out.phone = appeal.role, applicant.name, applicant.phone
    out.target_summary = await _target_summary(db, appeal)
    out.target_label = _TYPE_LABELS.get(appeal.target_type, appeal.target_type)
    return out
