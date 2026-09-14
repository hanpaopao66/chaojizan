"""信用分:本人明细、走客服工单的申诉、后台复核(公式和判据在 services/credit.py)。

顾客、商家、骑手三种角色同一组接口,按登录的角色算自己那一份:

- `GET  /credit/me`         本人看的完整明细(分数、每一项加减分和记录、申诉入口、公式)。每次现算。
                            商家是**店主本人**(分数记在店主名下,和处置同一个主体),店员、品牌经理 404;
- `GET  /credit/me/brief`   「我的」「店铺」页那一行用的分数和等级(走缓存);
- `POST /credit/me/appeals` 原来的申诉通道接不上时,走客服工单申诉一条扣分记录;
- `GET  /admin/credit/appeals`、`POST /admin/credit/appeals/{id}/resolve`:客服复核;
- `GET  /admin/users/{user_id}/credit`:客服处理申诉时看明细。

公式公开在 `/transparency/credit?role=`(routers/transparency.py),和这里算分用的是同一份常量。
交易对方看到的分数和等级不从这里出,由 routers/orders.py 的订单列表和订单详情带上 ——
那是它进响应体仅有的两个口子。
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import CreditAppeal, User
from ..security import require_role
from ..services import credit
from ..services.push import push_to_user

router = APIRouter(tags=["信用分"])

_ROLES = credit.ROLES


@router.get("/credit/me")
async def my_credit(user: User = Depends(require_role(*_ROLES)),
                    db: AsyncSession = Depends(get_db)):
    role, uid = await credit.subject_of(db, user)
    return await credit.breakdown(db, role, uid)


@router.get("/credit/me/brief")
async def my_credit_brief(user: User = Depends(require_role(*_ROLES)),
                          db: AsyncSession = Depends(get_db)):
    role, uid = await credit.subject_of(db, user)
    return (await credit.briefs_for(db, role, [uid]))[uid]


class CreditAppealIn(BaseModel):
    kind: Literal["delivery_fault", "after_sale_fault", "violation"]
    record_id: int
    # 工单正文 500 字,前面要留出「【信用分申诉】哪一条记录」那一截
    reason: str = Field(min_length=5, max_length=400)


@router.post("/credit/me/appeals")
async def submit_credit_appeal(payload: CreditAppealIn,
                               user: User = Depends(require_role(*_ROLES)),
                               db: AsyncSession = Depends(get_db)):
    appeal, ticket = await credit.submit_ticket_appeal(
        db, user, payload.kind, payload.record_id, payload.reason)
    try:
        await db.commit()
    except IntegrityError:
        # 两个请求同时提同一条:唯一约束挡住后一个
        await db.rollback()
        raise HTTPException(409, "这一条已经申诉过了,以平台的复核结论为准")
    await credit.invalidate(user.id)
    return {"id": appeal.id, "status": appeal.status, "ticket_id": ticket.id,
            "note": "已转给平台客服,回复在「联系平台客服」里看得到。"
                    "申诉成立的话,这一条不再计分,分数马上重算。"}


# ---------- 后台 ----------


class CreditAppealResolveIn(BaseModel):
    result: Literal["upheld", "overturned"]
    note: str = Field(min_length=2, max_length=300)


def _appeal_out(a: CreditAppeal, role: str = "") -> dict:
    return {"id": a.id, "user_id": a.user_id, "role": role,
            "role_label": credit.ROLE_LABELS.get(role, role),
            "kind": a.kind, "kind_label": credit.kind_label(role, a.kind) if role else a.kind,
            "record_id": a.record_id, "ticket_id": a.ticket_id, "reason": a.reason,
            "status": a.status, "resolve_note": a.resolve_note,
            "created_at": a.created_at, "resolved_at": a.resolved_at}


def _role_of(user: User | None) -> str:
    return str(getattr(user.role, "value", user.role)) if user is not None else ""


@router.get("/admin/credit/appeals")
async def list_credit_appeals(status: str | None = "open",
                              admin: User = Depends(require_role("admin")),
                              db: AsyncSession = Depends(get_db)):
    q = (select(CreditAppeal, User).join(User, User.id == CreditAppeal.user_id)
         .order_by(CreditAppeal.created_at.desc()).limit(200))
    if status in ("open", "upheld", "overturned"):
        q = q.where(CreditAppeal.status == status)
    return [_appeal_out(a, _role_of(u)) for a, u in (await db.execute(q)).all()]


@router.post("/admin/credit/appeals/{appeal_id}/resolve")
async def resolve_credit_appeal(appeal_id: int, payload: CreditAppealResolveIn,
                                admin: User = Depends(require_role("admin")),
                                db: AsyncSession = Depends(get_db)):
    appeal = await credit.resolve_ticket_appeal(db, admin, appeal_id, payload.result,
                                                payload.note)
    await db.commit()
    await credit.invalidate(appeal.user_id)
    won = appeal.status == "overturned"
    await push_to_user(
        appeal.user_id, "信用分申诉有结果了",
        ("申诉成立,这一条不再计入信用分,分数已经重算。" if won
         else "复核后维持原判,这一条继续计分。") + appeal.resolve_note,
        {"type": "credit"}, record_skip=True)
    return _appeal_out(appeal, _role_of(await db.get(User, appeal.user_id)))


@router.get("/admin/users/{user_id}/credit")
async def user_credit(user_id: int, admin: User = Depends(require_role("admin")),
                      db: AsyncSession = Depends(get_db)):
    """客服处理申诉时看的明细(和本人看到的是同一份)。"""
    target = await db.get(User, user_id)
    if target is None or _role_of(target) not in _ROLES:
        raise HTTPException(404, "这个账号没有信用分(只有顾客、商家、骑手有)")
    role, uid = await credit.subject_of(db, target)
    return await credit.breakdown(db, role, uid)
