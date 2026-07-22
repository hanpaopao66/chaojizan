"""客服工单:三端任何角色 → 平台真人。

产品里所有「联系平台客服」的承诺(售后申诉/发票/认证疑问)落点都在这。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Ticket, TicketStatus, User
from ..schemas import AdminTicketOut, TicketIn, TicketOut, TicketReplyIn
from ..security import get_current_user, require_role
from ..services.push import push_to_user

router = APIRouter(tags=["客服工单"])

MAX_OPEN_TICKETS = 3

# FAQ 自助分流:提工单前先给自助答案 + 直达入口(action 供客户端跳转)。
# 配置化:平台改文案不发版可后续挪到 platform_flags,MVP 先内置。
_FAQ = [
    {"q": "怎么退款?退款多久到账?",
     "a": "未接单或商家超时未出餐,可在订单页「自助退款」即时全额退回原路;"
          "已出餐/配送中的退款涉及餐损,请提交工单人工处理。mock 渠道即时到账,"
          "微信原路退回 1-3 个工作日。", "action": "order"},
    {"q": "怎么开发票?",
     "a": "在「我的-发票」对已完成订单申请电子发票,抬头可存。", "action": "invoice"},
    {"q": "想改配送地址 / 加菜怎么办?",
     "a": "骑手取餐前可在订单页「改地址」(每单一次);商家出餐前可「加菜」"
          "随原单一起送。", "action": "order"},
    {"q": "骑手一直没接单怎么办?",
     "a": "可在订单页加「加急小费」(全归骑手)提高接单意愿;长时间无人接"
          "平台会自动取消并全额退款。", "action": "order"},
    {"q": "对判责/差评有异议?",
     "a": "商家和骑手可在对应记录旁「申诉」,平台复核可改判。", "action": "appeal"},
]


@router.get("/support/faq")
async def support_faq():
    """常见问题自助分流:提工单前先看这里,能自助的直接给入口。"""
    return {"faq": _FAQ}


@router.post("/tickets", response_model=TicketOut)
async def submit_ticket(
    payload: TicketIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    open_count = await db.scalar(
        select(sa_func.count()).select_from(Ticket).where(
            Ticket.user_id == user.id, Ticket.status == TicketStatus.open
        )
    )
    if open_count >= MAX_OPEN_TICKETS:
        raise HTTPException(
            429, f"你有 {open_count} 个工单还没回复,请等平台处理后再提交"
        )
    from ..services.moderation import guard_text
    await guard_text(db, payload.content, "工单内容")
    ticket = Ticket(
        user_id=user.id,
        role=user.role.value,
        contact=payload.contact.strip() or user.phone,
        content=payload.content.strip(),
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return ticket


@router.get("/tickets/mine", response_model=list[TicketOut])
async def my_tickets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(Ticket)
        .where(Ticket.user_id == user.id)
        .order_by(Ticket.created_at.desc())
        .limit(50)
    )
    return list(result)


# ---------- 平台处理 ----------
@router.get("/admin/tickets", response_model=list[AdminTicketOut])
async def list_tickets(
    status: TicketStatus | None = None,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Ticket, User.phone)
        .join(User, User.id == Ticket.user_id)
        .order_by(Ticket.created_at.desc())
        .limit(200)
    )
    if status is not None:
        query = query.where(Ticket.status == status)
    rows = (await db.execute(query)).all()
    out = []
    for ticket, phone in rows:
        item = AdminTicketOut.model_validate(ticket)
        item.user_phone = phone
        out.append(item)
    return out


async def _get_ticket(db: AsyncSession, ticket_id: int) -> Ticket:
    ticket = await db.get(Ticket, ticket_id, with_for_update=True)
    if ticket is None:
        raise HTTPException(404, "工单不存在")
    return ticket


@router.post("/admin/tickets/{ticket_id}/reply", response_model=TicketOut)
async def reply_ticket(
    ticket_id: int,
    payload: TicketReplyIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket(db, ticket_id)
    if ticket.status == TicketStatus.closed:
        raise HTTPException(409, "工单已关闭,不能再回复")
    ticket.reply = payload.reply.strip()
    ticket.status = TicketStatus.replied
    ticket.replied_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ticket)
    await push_to_user(
        ticket.user_id, "客服回复",
        ticket.reply[:50], {"ticket_id": ticket.id},
    )
    return ticket


@router.post("/admin/tickets/{ticket_id}/close", response_model=TicketOut)
async def close_ticket(
    ticket_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket(db, ticket_id)
    ticket.status = TicketStatus.closed
    await db.commit()
    await db.refresh(ticket)
    return ticket
