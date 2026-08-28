"""到店排队的接口。

三组:商家配桌型和叫号台、用户取号看位、公开的队列现状(不登录也能看)。

**这里没有的接口,比有的更要紧**:没有「把某个号往前挪」、没有「持券优先」、
没有「付费插队」。规则和理由写在 services/queue.py 的模块注释里。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (Merchant, MerchantStatus, QueueEvent, QueueTableType,
                      QueueTicket, QueueTicketStatus, User)
from ..ratelimit import check_rate_limit
from ..security import get_current_user, require_role
from ..services import queue as q
from ..services.staff import operable_shop

router = APIRouter(prefix="/queue", tags=["到店排队"])


async def _my_shop(db: AsyncSession, user: User) -> Merchant:
    """商家侧统一入口。

    **operable_shop 返回的是 (店, 是不是店主) 元组,而且可能是 None** ——
    当成单个对象用的话,连锁品牌一来就会静默拿错店:叫号台显示的是
    另一家分店的队,而两边都不报错。这个坑项目里已经踩过一次。

    叫号台允许店员操作(operable 而不是 owned):真实门店里叫号的是迎宾,
    不会是老板本人。
    """
    shop, _is_owner = await operable_shop(db, user)
    if shop is None or shop.status != MerchantStatus.approved:
        raise HTTPException(404, "还没有已过审的店铺")
    return shop


# ---------- 出参 ----------


def _type_out(t: QueueTableType, waiting: int = 0, cap: int = 0) -> dict:
    return {
        "id": t.id, "name": t.name,
        "seats_min": t.seats_min, "seats_max": t.seats_max,
        "table_count": t.table_count, "turn_minutes": t.turn_minutes,
        "is_active": t.is_active,
        "waiting": waiting,
        "cap": cap,
        "wait_upper_minutes": q.wait_upper_minutes(
            waiting, t.table_count, t.turn_minutes),
    }


def _ticket_out(t: QueueTicket, ahead: int | None = None,
                tt: QueueTableType | None = None) -> dict:
    out = {
        # id 给申诉用:申诉表单就挂在号的详情页上,target_id 填的是它
        "id": t.id,
        "ticket_no": t.ticket_no, "merchant_id": t.merchant_id,
        "party_size": t.party_size, "status": t.status.value,
        "passed_count": t.passed_count,
        "table_type": tt.name if tt else None,
        "called_at": t.called_at.isoformat() if t.called_at else None,
        "seated_at": t.seated_at.isoformat() if t.seated_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    if ahead is not None:
        out["ahead"] = ahead
        out["wait_upper_minutes"] = q.wait_upper_minutes(
            ahead, tt.table_count if tt else 1, tt.turn_minutes if tt else 0)
        out["wait_basis"] = q.WAIT_BASIS
    return out


# ---------- 商家:配桌型 ----------


class TableTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    seats_min: int = Field(ge=1, le=50)
    seats_max: int = Field(ge=1, le=50)
    table_count: int = Field(ge=1, le=500)
    turn_minutes: int = Field(default=45,
                              ge=q.TURN_MINUTES_RANGE[0],
                              le=q.TURN_MINUTES_RANGE[1])
    is_active: bool = True


class SettingIn(BaseModel):
    enabled: bool
    cap_multiplier: int = Field(default=3, ge=q.CAP_MULTIPLIER_RANGE[0],
                                le=q.CAP_MULTIPLIER_RANGE[1])
    defer_tables: int = Field(default=3, ge=q.DEFER_TABLES_RANGE[0],
                              le=q.DEFER_TABLES_RANGE[1])
    notify_ahead: int = Field(default=3, ge=q.NOTIFY_AHEAD_RANGE[0],
                              le=q.NOTIFY_AHEAD_RANGE[1])


@router.get("/settings")
async def read_settings(user: User = Depends(require_role("merchant")),
                        db: AsyncSession = Depends(get_db)):
    shop = await _my_shop(db, user)
    s = await q.get_setting(db, shop.id)
    await db.commit()
    return {
        "enabled": s.enabled, "cap_multiplier": s.cap_multiplier,
        "defer_tables": s.defer_tables, "notify_ahead": s.notify_ahead,
        # 平台规则,一并回给商家端展示 —— 免得商家以为这些也能改
        "call_grace_seconds": q.grace_seconds(),
        "max_defers": q.MAX_DEFERS,
        "platform_rules": [
            "取号免费开放,买券/会员都不能插队",
            f"叫号后不足 {q.grace_seconds()} 秒不能标过号",
            f"过号 {q.MAX_DEFERS} 次转「待恢复」,不是作废",
        ],
    }


@router.put("/settings")
async def write_settings(payload: SettingIn,
                         user: User = Depends(require_role("merchant")),
                         db: AsyncSession = Depends(get_db)):
    shop = await _my_shop(db, user)
    s = await q.get_setting(db, shop.id)
    s.enabled = payload.enabled
    s.cap_multiplier = payload.cap_multiplier
    s.defer_tables = payload.defer_tables
    s.notify_ahead = payload.notify_ahead
    await db.commit()
    return await read_settings(user, db)


@router.get("/table-types")
async def list_table_types(user: User = Depends(require_role("merchant")),
                           db: AsyncSession = Depends(get_db)):
    shop = await _my_shop(db, user)
    rows = (await db.scalars(select(QueueTableType).where(
        QueueTableType.merchant_id == shop.id).order_by(
        QueueTableType.seats_max, QueueTableType.id))).all()
    return [_type_out(t) for t in rows]


@router.post("/table-types")
async def create_table_type(payload: TableTypeIn,
                            user: User = Depends(require_role("merchant")),
                            db: AsyncSession = Depends(get_db)):
    if payload.seats_min > payload.seats_max:
        raise HTTPException(422, "最少人数不能大于最多人数")
    shop = await _my_shop(db, user)
    t = QueueTableType(merchant_id=shop.id, **payload.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _type_out(t)


@router.patch("/table-types/{type_id}")
async def update_table_type(type_id: int, payload: TableTypeIn,
                            user: User = Depends(require_role("merchant")),
                            db: AsyncSession = Depends(get_db)):
    if payload.seats_min > payload.seats_max:
        raise HTTPException(422, "最少人数不能大于最多人数")
    shop = await _my_shop(db, user)
    t = await db.get(QueueTableType, type_id)
    if t is None or t.merchant_id != shop.id:
        raise HTTPException(404, "没有这个桌型")
    for k, v in payload.model_dump().items():
        setattr(t, k, v)
    await db.commit()
    return _type_out(t)


# ---------- 公开:这家店现在排得怎么样(不用登录) ----------


@router.get("/merchants/{merchant_id}")
async def shop_queue(merchant_id: int, db: AsyncSession = Depends(get_db)):
    """店铺页的排队卡片。不登录也能看 —— 要不要去,得先看得到。"""
    shop = await db.get(Merchant, merchant_id)
    if shop is None:
        raise HTTPException(404, "没有这家店")
    s = await q.get_setting(db, merchant_id)
    day = q.beijing_today()
    types = (await db.scalars(select(QueueTableType).where(
        QueueTableType.merchant_id == merchant_id,
        QueueTableType.is_active.is_(True),
    ).order_by(QueueTableType.seats_max, QueueTableType.id))).all()
    out = []
    for t in types:
        waiting = int(await db.scalar(
            select(func.count()).select_from(QueueTicket).where(
                QueueTicket.table_type_id == t.id,
                QueueTicket.day == day,
                QueueTicket.status == QueueTicketStatus.waiting,
            )) or 0)
        out.append(_type_out(t, waiting,
                             q.issue_cap(t.table_count, s.cap_multiplier)))
    await db.commit()
    return {
        "merchant_id": merchant_id, "enabled": s.enabled,
        "table_types": out,
        "wait_basis": q.WAIT_BASIS,
        "rules": {
            "defer_tables": s.defer_tables,
            "max_defers": q.MAX_DEFERS,
            "call_grace_seconds": q.grace_seconds(),
            "text": (f"叫到号没到,顺延 {s.defer_tables} 桌,号还在;"
                     f"顺延 {q.MAX_DEFERS} 次转「待恢复」,到店找商家恢复,"
                     f"不作废。商家叫号后不足 "
                     f"{q.grace_seconds()} 秒不能标你过号。"),
        },
        "no_priority": "取号免费,买券、会员、任何付费都不能插队。",
    }


# ---------- 用户:取号 / 看位 / 取消 ----------


class TakeIn(BaseModel):
    party_size: int = Field(ge=1, le=50)


@router.post("/merchants/{merchant_id}/take")
async def take(merchant_id: int, payload: TakeIn, request: Request,
               user: User = Depends(require_role("customer")),
               db: AsyncSession = Depends(get_db)):
    """取号。

    **限流按人不按 IP**:一家人在同一个 Wi-Fi 下各自取号是正常的,
    按 IP 限会误伤;而滥用的形态是同一个人反复取号取消,按人限才拦得住。
    """
    await check_rate_limit("queue_take", str(user.id), 10)
    shop = await db.get(Merchant, merchant_id)
    if shop is None:
        raise HTTPException(404, "没有这家店")
    try:
        ticket = await q.take_ticket(db, shop, user.id, payload.party_size)
    except q.QueueError as e:
        await db.rollback()
        raise HTTPException(409, str(e))
    tt = await db.get(QueueTableType, ticket.table_type_id)
    ahead = await q.ahead_of(db, ticket)
    await db.commit()
    return _ticket_out(ticket, ahead, tt)


@router.get("/tickets/mine")
async def my_tickets(user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """我今天的号(含已结束的,方便对着看发生过什么)。"""
    rows = (await db.scalars(select(QueueTicket).where(
        QueueTicket.customer_id == user.id,
        QueueTicket.day == q.beijing_today(),
    ).order_by(QueueTicket.id.desc()))).all()
    out = []
    for t in rows:
        tt = await db.get(QueueTableType, t.table_type_id)
        ahead = (await q.ahead_of(db, t)
                 if t.status == QueueTicketStatus.waiting else None)
        out.append(_ticket_out(t, ahead, tt))
    return out


@router.post("/tickets/{ticket_no}/cancel")
async def cancel(ticket_no: str, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    t = await db.scalar(select(QueueTicket).where(
        QueueTicket.ticket_no == ticket_no))
    if t is None or t.customer_id != user.id:
        raise HTTPException(404, "没有这个号")
    try:
        await q.cancel_ticket(db, t, "customer", user.id)
    except q.QueueError as e:
        await db.rollback()
        raise HTTPException(409, str(e))
    await db.commit()
    return _ticket_out(t)


@router.get("/tickets/{ticket_no}/events")
async def ticket_events(ticket_no: str,
                        user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """这个号经历过什么。

    **对当事人开放,不是只给管理员看** —— 公示里写着「没人能把号往前挪」,
    用户得能自己查这句话在自己这个号上成不成立,否则那只是一句口号。
    """
    t = await db.scalar(select(QueueTicket).where(
        QueueTicket.ticket_no == ticket_no))
    if t is None:
        raise HTTPException(404, "没有这个号")
    allowed = t.customer_id == user.id
    if not allowed and user.role.value == "merchant":
        shop = await _my_shop(db, user)
        allowed = shop.id == t.merchant_id
    if not allowed and user.role.value != "admin":
        raise HTTPException(403, "只有这个号的当事人能看")
    rows = (await db.scalars(select(QueueEvent).where(
        QueueEvent.ticket_id == t.id).order_by(QueueEvent.id))).all()
    return [{"action": e.action, "actor_role": e.actor_role,
             "detail": e.detail,
             "at": e.created_at.isoformat() if e.created_at else None}
            for e in rows]


# ---------- 商家:叫号台 ----------


@router.get("/desk")
async def desk(user: User = Depends(require_role("merchant")),
               db: AsyncSession = Depends(get_db)):
    """叫号台:每条队的队头几个 + 已叫号待到店的。"""
    shop = await _my_shop(db, user)
    day = q.beijing_today()
    types = (await db.scalars(select(QueueTableType).where(
        QueueTableType.merchant_id == shop.id,
        QueueTableType.is_active.is_(True),
    ).order_by(QueueTableType.seats_max, QueueTableType.id))).all()
    out = []
    for t in types:
        waiting = (await db.scalars(select(QueueTicket).where(
            QueueTicket.table_type_id == t.id, QueueTicket.day == day,
            QueueTicket.status == QueueTicketStatus.waiting,
        ).order_by(QueueTicket.sort_key).limit(10))).all()
        called = (await db.scalars(select(QueueTicket).where(
            QueueTicket.table_type_id == t.id, QueueTicket.day == day,
            QueueTicket.status.in_((QueueTicketStatus.called,
                                    QueueTicketStatus.pending_restore)),
        ).order_by(QueueTicket.called_at))).all()
        out.append({
            "table_type": _type_out(t, len(waiting)),
            "waiting": [_ticket_out(x) for x in waiting],
            "called": [dict(_ticket_out(x),
                            can_pass=q.can_pass(x.called_at))
                       for x in called],
        })
    await db.commit()
    return {"queues": out, "call_grace_seconds": q.grace_seconds()}


async def _merchant_ticket(db: AsyncSession, user: User,
                           ticket_no: str) -> QueueTicket:
    shop = await _my_shop(db, user)
    t = await db.scalar(select(QueueTicket).where(
        QueueTicket.ticket_no == ticket_no))
    if t is None or t.merchant_id != shop.id:
        raise HTTPException(404, "没有这个号")
    return t


@router.post("/tickets/{ticket_no}/call")
async def call_next(ticket_no: str,
                    user: User = Depends(require_role("merchant")),
                    db: AsyncSession = Depends(get_db)):
    t = await _merchant_ticket(db, user, ticket_no)
    try:
        await q.call_ticket(db, t, user.id)
    except q.QueueError as e:
        await db.rollback()
        raise HTTPException(409, str(e))
    await db.commit()
    return _ticket_out(t)


@router.post("/tickets/{ticket_no}/pass")
async def mark_passed(ticket_no: str,
                      user: User = Depends(require_role("merchant")),
                      db: AsyncSession = Depends(get_db)):
    t = await _merchant_ticket(db, user, ticket_no)
    try:
        note = await q.pass_ticket(db, t, user.id)
    except q.QueueError as e:
        await db.rollback()
        raise HTTPException(409, str(e))
    await db.commit()
    return dict(_ticket_out(t), result=note)


@router.post("/tickets/{ticket_no}/restore")
async def restore(ticket_no: str,
                  user: User = Depends(require_role("merchant")),
                  db: AsyncSession = Depends(get_db)):
    t = await _merchant_ticket(db, user, ticket_no)
    try:
        await q.restore_ticket(db, t, user.id)
    except q.QueueError as e:
        await db.rollback()
        raise HTTPException(409, str(e))
    await db.commit()
    return _ticket_out(t)


@router.post("/tickets/{ticket_no}/seat")
async def seat(ticket_no: str,
               user: User = Depends(require_role("merchant")),
               db: AsyncSession = Depends(get_db)):
    """入座。队列往前走一格,顺带把两段式提醒的前一段发出去。"""
    t = await _merchant_ticket(db, user, ticket_no)
    try:
        await q.seat_ticket(db, t, user.id)
    except q.QueueError as e:
        await db.rollback()
        raise HTTPException(409, str(e))
    await db.flush()
    await q.notify_near(db, t.table_type_id, t.day)
    await db.commit()
    return _ticket_out(t)
