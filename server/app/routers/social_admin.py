"""社区治理:聊天举报、处罚、申诉、数据 `/admin/social/…`(DEV-PROMPTS-40 #368 聊天部分、#370)。

视频的审核、下架、视频申诉、视频 / 评论 / 弹幕举报在 routers/video_admin.py(同一个前缀);
这里是对**人和会话**的那一半。判定都在 services/sanctions.py 和 services/chat_moderation.py。

硬规矩(tests/e2e_social_moderation.py 每条都先红后绿):
- **S8**:后台看会话消息只有 `GET /admin/social/chat-messages?report_id=…` 一个口子,
  不带举报单号 403;只给举报单里那几条 ± 5 条;每次查看写一行留痕,次数进透明中心;
- **S6**:处罚带 §5.11 原因代码(X999 要写说明);申诉由另一名审核员处理(同一人 403);
- 7 天内 3 个不同的人举报同一个对象的举报单排在队列最前(escalated)。
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import SocialSanction, User, VideoReport
from ..security import require_role
from ..services import chat_moderation as cm
from ..services import community_stats
from ..services import sanctions

router = APIRouter(prefix="/admin/social", tags=["社区治理"])

admin_only = require_role("admin")


# ---------------- 聊天举报 ----------------

@router.get("/chat-reports")
async def chat_reports(status: Literal["open", "handled", "all"] = "open",
                       limit: int = Query(100, ge=1, le=500),
                       admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    """举报队列:7 天内 3 个不同的人举报同一个对象的(escalated)排最前,其余按时间先后。
    **不含消息内容、不含举报人**。"""
    items = await cm.queue(db, status, limit)
    return {"items": items, "count": len(items)}


@router.get("/chat-reports/{report_id}")
async def chat_report(report_id: int, admin: User = Depends(admin_only),
                      db: AsyncSession = Depends(get_db)):
    """举报单详情:对象、对象身上的处罚、同一对象的其他待处理举报、这张单被谁看过。
    **不含消息内容** —— 要看消息走 /admin/social/chat-messages(会留痕)。"""
    return await cm.detail(db, await cm.get_report(db, report_id))


@router.get("/chat-messages")
async def chat_messages(report_id: int | None = None, admin: User = Depends(admin_only),
                        db: AsyncSession = Depends(get_db)):
    """看被举报的消息(S8)。**必须带举报单号**;只给举报单里那几条和前后各 5 条;每次都留痕。

    故意只收 report_id 一个参数:会话号、seq 都从举报单里取,不接受调用方传 ——
    传进来的 chat_id / seqs 一律不理,范围永远是举报单定的那个。
    """
    if report_id is None:
        raise HTTPException(403, "查看会话里的消息必须带举报单号(S8:只能在举报范围内查看)")
    r = await cm.get_report(db, report_id)
    out = await cm.view_messages(db, admin, r)
    await db.commit()
    return out


class HandleIn(BaseModel):
    #: dismiss 不成立 / delete_messages 删被举报的消息 / mute 禁言 / ban_chat 封群、频道 /
    #: ban_account 封号 / warn 警告
    action: Literal["dismiss", "delete_messages", "mute", "ban_chat", "ban_account", "warn"]
    reason_code: str = ""
    #: 给当事人看的说明(系统通知、处罚记录、被挡时的 403 里都带)
    note: str = Field(default="", max_length=500)
    note_internal: str = Field(default="", max_length=500)
    #: 禁言多少小时(1–720)
    hours: int | None = None
    #: 封号 / 封群多少天(1–3650);permanent=true 时不用填
    days: int | None = None
    permanent: bool = False
    #: 处罚谁(默认是被举报的人);必须是这张举报单涉及的人
    user_id: int | None = None
    #: 禁言 / 封号 / 封群 / 警告的同时把被举报的消息删掉
    also_delete: bool = False


@router.post("/chat-reports/{report_id}/handle")
async def handle_chat_report(report_id: int, body: HandleIn,
                             admin: User = Depends(admin_only),
                             db: AsyncSession = Depends(get_db)):
    """处理一张举报单。处罚要带原因代码(X999 写说明);当事人收到系统通知、可以申诉(S6)。"""
    r = await cm.get_report(db, report_id, lock=True)
    out = await cm.handle(db, admin, r, action=body.action, reason_code=body.reason_code,
                          note=body.note, note_internal=body.note_internal, hours=body.hours,
                          days=body.days, permanent=body.permanent, user_id=body.user_id,
                          also_delete=body.also_delete)
    await db.commit()
    return out


# ---------------- 处罚记录 ----------------

@router.get("/sanctions")
async def list_sanctions(status: Literal["all", "active", "expired", "revoked", "done"] = "all",
                         action: str = "", target_type: str = "", reason_code: str = "",
                         appeal: Literal["", "none", "open", "upheld", "overturned"] = "",
                         target_id: int | None = None, before: int | None = None,
                         limit: int = Query(50, ge=1, le=200),
                         admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    """处置记录(筛选;按新到旧,`before` 翻页)。"""
    q = cm.sanctions_query(status=status, action=action, target_type=target_type,
                           reason_code=reason_code, appeal=appeal, target_id=target_id,
                           before=before)
    rows = list(await db.scalars(q.limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": await cm.sanction_items(db, rows, admin),
            "next_before": rows[-1].id if more and rows else None}


class SanctionIn(BaseModel):
    target_type: Literal["user", "chat"]
    target_id: int
    #: 直接处置不支持删消息(删消息要走聊天举报单,S8 的范围由举报单定)
    action: Literal["mute", "ban_chat", "ban_account", "warn"]
    reason_code: str
    note: str = Field(default="", max_length=500)
    note_internal: str = Field(default="", max_length=500)
    hours: int | None = None
    days: int | None = None
    permanent: bool = False
    #: 从视频 / 评论 / 弹幕举报过来的(处罚发评论、弹幕的人)
    video_report_id: int | None = None


@router.post("/sanctions")
async def create_sanction(body: SanctionIn, admin: User = Depends(admin_only),
                          db: AsyncSession = Depends(get_db)):
    """直接处置一个人或一个会话:比如评论、弹幕被举报,删掉之后再禁言发的人(禁言同时挡评论和弹幕)。"""
    if body.video_report_id is not None and await db.get(VideoReport, body.video_report_id) \
            is None:
        raise HTTPException(404, "举报不存在")
    until = sanctions.compute_until(body.action, hours=body.hours, days=body.days,
                                    permanent=body.permanent)
    s = await sanctions.impose(
        db, admin, target_type=body.target_type, target_id=body.target_id, action=body.action,
        reason_code=body.reason_code, note=body.note, note_internal=body.note_internal,
        until=until, report_kind="video" if body.video_report_id else "",
        report_id=body.video_report_id)
    await db.commit()
    return (await cm.sanction_items(db, [s], admin))[0]


class RevokeIn(BaseModel):
    note: str = Field(max_length=300)


@router.post("/sanctions/{sanction_id}/revoke")
async def revoke_sanction(sanction_id: int, body: RevokeIn, admin: User = Depends(admin_only),
                          db: AsyncSession = Depends(get_db)):
    """撤销(限制立即解除,当事人收到通知)。当事人已经申诉的,要在「申诉」里由另一名审核员处理。"""
    s = await _locked(db, sanction_id)
    await sanctions.revoke(db, admin, s, body.note)
    await db.commit()
    return (await cm.sanction_items(db, [s], admin))[0]


async def _locked(db: AsyncSession, sanction_id: int) -> SocialSanction:
    s = await db.scalar(select(SocialSanction).where(SocialSanction.id == sanction_id)
                        .with_for_update().execution_options(populate_existing=True))
    if s is None:
        raise HTTPException(404, "没有这条处罚")
    return s


# ---------------- 社区申诉(对人和会话的处罚)----------------

@router.get("/social-appeals")
async def social_appeals(status: Literal["open", "resolved", "all"] = "open",
                         limit: int = Query(100, ge=1, le=500),
                         admin: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    """申诉。`you_decided_original` 为真的,你不能处理(必须换人复核,S6)。申诉单号就是处罚编号。"""
    q = select(SocialSanction)
    if status == "open":
        q = q.where(SocialSanction.appeal_status == "open").order_by(SocialSanction.appealed_at)
    elif status == "resolved":
        q = q.where(SocialSanction.appeal_status.in_(("upheld", "overturned"))).order_by(
            SocialSanction.appeal_resolved_at.desc())
    else:
        q = q.where(SocialSanction.appeal_status != "").order_by(SocialSanction.id.desc())
    rows = list(await db.scalars(q.limit(limit)))
    items = await cm.sanction_items(db, rows, admin)
    return {"items": [{"appeal": {"id": x["id"], "status": x["appeal"]["status"],
                                  "text": x["appeal"]["text"],
                                  "appealed_at": x["appeal"]["appealed_at"]},
                       "sanction": x, "you_decided_original": x["you_decided"]}
                      for x in items]}


class AppealResolveIn(BaseModel):
    overturn: bool
    #: 复核结论(给当事人看)
    note: str = Field(default="", max_length=500)
    note_internal: str = Field(default="", max_length=500)


@router.post("/social-appeals/{appeal_id}/resolve")
async def resolve_social_appeal(appeal_id: int, body: AppealResolveIn,
                                admin: User = Depends(admin_only),
                                db: AsyncSession = Depends(get_db)):
    """维持 / 撤销。**处理人等于原处罚人 → 403**(S6);撤销即解除限制并通知当事人。"""
    s = await _locked(db, appeal_id)
    await sanctions.resolve_appeal(db, admin, s, overturn=body.overturn, note=body.note,
                                   note_internal=body.note_internal)
    await db.commit()
    return {"id": s.id, "appeal_status": s.appeal_status,
            "sanction": (await cm.sanction_items(db, [s], admin))[0]}


# ---------------- 数据 ----------------

@router.get("/community-stats")
async def community_stats_view(days: int = Query(30, ge=1, le=90),
                               admin: User = Depends(admin_only),
                               db: AsyncSession = Depends(get_db)):
    """每天:消息数、活跃会话数、投稿量、审核结论数、审核中位时长、举报量、处置量(北京时间分天)。"""
    return await community_stats.daily(db, days)
