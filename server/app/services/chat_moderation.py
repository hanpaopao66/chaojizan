"""聊天举报:提交、队列、S8 查看、处置(DEV-PROMPTS-40 #368 聊天部分)。

**S8 管理员看私聊要留痕**,落在这几条上(tests/e2e_social_moderation.py 逐条先红后绿):

1. 看会话里的消息只有一个入口 [view_messages],**必须带举报单号**(路由不带就 403);
2. 范围只有举报单里那几条和前后各 5 条(sanctions.context_seqs),不越过举报人当时的可见下限 ——
   公开群 / 频道也按同一个口径,不因为「反正是公开的」就放宽;
3. 每次查看同一个事务里写一行 admin_chat_views(谁、哪张举报单、哪个会话、哪些 seq、什么时候)
   + 一条管理员操作留痕;次数按月进透明中心(不含会话、不含内容);
4. 媒体(被举报的是图片、视频时)给的是**绑定这张举报单**的签名地址,1 小时有效,
   只对落在上面那个范围里的媒体有效(routers/media.get_file 按举报单重新判)。

举报的「对象」(subject)是被举报的那个人或那个会话,「7 天内 3 个不同的人举报同一个对象」按它数:
一个人给十个陌生人发骚扰私信,十个私聊各是一张举报单,对象都是他。
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (AdminChatView, Chat, ChatMessage, ChatReport, SocialProfile,
                      SocialSanction, User)
from . import sanctions
from .admin_audit import log_admin_action
from .social import SOCIAL_ROLES, display_name
from .video import REASON_CODES

#: 7 天内 3 个不同的人举报同一个对象 → escalated,排在队列最前(和视频举报同一个口径)
ESCALATE_USERS = 3
ESCALATE_WINDOW = timedelta(days=7)
#: S8:举报单里那几条的前后各几条
CONTEXT = 5
#: 举报整个会话、没指定消息时,带上举报人当时能看到的最近几条(被举报的就是这几条)
CHAT_REPORT_RECENT = 10
#: 一张举报单最多带几条
REPORT_SEQS_MAX = 20
#: 举报单绑定的媒体地址多久失效
MEDIA_GRANT_SECONDS = 3600

OPEN = ("open", "escalated")
STATUS_LABELS = {"open": "待处理", "escalated": "待处理(多人举报)", "actioned": "已处置",
                 "dismissed": "不成立"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------- 提交 ----------------

async def file_report(db: AsyncSession, reporter: User, *, target_type: str,
                      chat_id: int | None, seqs: list[int], user_id: int | None,
                      reason_code: str, note: str) -> ChatReport:
    """记一张举报单。只收举报人**当时看得到**的消息;对象按「谁发的 / 举报谁 / 哪个会话」定。"""
    from .chat_view import can_read_chat, visible_floor

    chat = None
    floor = 0
    if chat_id is not None:
        chat = await db.get(Chat, chat_id)
        if chat is None or chat.deleted_at is not None:
            raise HTTPException(404, "会话不存在")
        ok, member = await can_read_chat(db, chat, reporter.id)
        if not ok:
            raise HTTPException(403, "你不在这个会话里")
        # 公开群 / 频道不加入也能看:可见下限按 0 算(和消息分页同一个口径)
        floor = visible_floor(chat, member) if member is not None else 0
    elif target_type in ("chat", "message"):
        raise HTTPException(422, "缺少会话")
    wanted = sorted({int(s) for s in seqs or [] if int(s) > floor})[:REPORT_SEQS_MAX]
    msgs: list[ChatMessage] = []
    if chat is not None and wanted:
        msgs = list(await db.scalars(select(ChatMessage).where(
            ChatMessage.chat_id == chat.id, ChatMessage.seq.in_(wanted),
            ChatMessage.deleted_at.is_(None), ChatMessage.kind != "service")
            .order_by(ChatMessage.seq)))
    subject_type, subject_id = "", None
    if target_type == "message":
        if not msgs:
            raise HTTPException(404, "要举报的消息不存在或已删除")
        first = msgs[0]
        if first.as_chat or first.sender_id is None:
            subject_type, subject_id = "chat", chat.id
        else:
            subject_type, subject_id = "user", first.sender_id
    elif target_type == "user":
        if user_id is None:
            raise HTTPException(422, "缺少用户")
        target = await db.get(User, user_id)
        if target is None or target.role not in SOCIAL_ROLES:
            raise HTTPException(404, "没有这个用户")
        subject_type, subject_id = "user", user_id
        # 举报人从某个会话里举报这个人:只收他在这个会话里发的那几条
        msgs = [m for m in msgs if m.sender_id == user_id and not m.as_chat]
    elif target_type == "chat":
        subject_type, subject_id = "chat", chat.id
        if not msgs:
            # 举报整个会话:被举报的就是举报人此刻能看到的最近几条
            msgs = list(reversed(list(await db.scalars(select(ChatMessage).where(
                ChatMessage.chat_id == chat.id, ChatMessage.seq > floor,
                ChatMessage.deleted_at.is_(None), ChatMessage.kind != "service")
                .order_by(ChatMessage.seq.desc()).limit(CHAT_REPORT_RECENT)))))
    else:
        raise HTTPException(422, "只能举报会话、消息或用户")
    if subject_type == "user" and subject_id == reporter.id:
        raise HTTPException(422, "不能举报自己")
    now = now_utc()
    row = ChatReport(reporter_id=reporter.id, target_type=target_type,
                     chat_id=chat.id if chat is not None else None,
                     seqs=[m.seq for m in msgs], user_id=user_id, reason_code=reason_code,
                     note=(note or "").strip()[:500], status="open", decision={},
                     subject_type=subject_type, subject_id=subject_id, context_floor=floor,
                     created_at=now)
    db.add(row)
    await db.flush()
    since = now - ESCALATE_WINDOW
    n = await db.scalar(select(func.count(func.distinct(ChatReport.reporter_id))).where(
        ChatReport.subject_type == subject_type, ChatReport.subject_id == subject_id,
        ChatReport.created_at >= since))
    if (n or 0) >= ESCALATE_USERS:
        await db.execute(update(ChatReport).where(
            ChatReport.subject_type == subject_type, ChatReport.subject_id == subject_id,
            ChatReport.status == "open").values(status="escalated")
            .execution_options(synchronize_session=False))
        row.status = "escalated"
    return row


# ---------------- 后台:列表与详情(不含消息内容)----------------

async def people_brief(db: AsyncSession, ids) -> dict[int, dict]:
    """后台里的人:名字、@用户名、注册时间。**不带手机号** —— 处置用不着它。"""
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))}
    profiles = {p.user_id: p for p in await db.scalars(
        select(SocialProfile).where(SocialProfile.user_id.in_(ids)))}
    out = {}
    for uid, u in users.items():
        p = profiles.get(uid)
        out[uid] = {"id": uid, "name": "已注销用户" if u.deleted_at else display_name(u),
                    "username": p.username if p else None,
                    "deleted": u.deleted_at is not None,
                    "role": u.role.value, "created_at": iso(u.created_at)}
    return out


def chat_brief(chat: Chat | None) -> dict | None:
    if chat is None:
        return None
    return {"id": chat.id, "type": chat.type,
            "title": "私聊" if chat.type == "private" else chat.title,
            "username": chat.username, "member_count": chat.member_count,
            "owner_id": chat.owner_id, "deleted": chat.deleted_at is not None}


async def reporters_7d(db: AsyncSession, rows: list[ChatReport]) -> dict[tuple, int]:
    """近 7 天(按现在算)举报同一个对象的不同人数,一次查完整页。"""
    keys = {(r.subject_type, r.subject_id) for r in rows if r.subject_type and r.subject_id}
    if not keys:
        return {}
    got = (await db.execute(
        select(ChatReport.subject_type, ChatReport.subject_id,
               func.count(func.distinct(ChatReport.reporter_id)))
        .where(or_(*[and_(ChatReport.subject_type == t, ChatReport.subject_id == i)
                     for t, i in keys]),
               ChatReport.created_at >= now_utc() - ESCALATE_WINDOW)
        .group_by(ChatReport.subject_type, ChatReport.subject_id))).all()
    return {(t, i): int(n) for t, i, n in got}


async def report_items(db: AsyncSession, rows: list[ChatReport]) -> list[dict]:
    """队列里的一行。**不带举报人是谁**(举报人对被举报的一方永远匿名,后台也不需要)。"""
    chat_ids = {r.chat_id for r in rows if r.chat_id} | \
        {r.subject_id for r in rows if r.subject_type == "chat" and r.subject_id}
    chats = {c.id: c for c in await db.scalars(select(Chat).where(Chat.id.in_(chat_ids)))} \
        if chat_ids else {}
    ppl = await people_brief(db, [r.subject_id for r in rows if r.subject_type == "user"])
    counts = await reporters_7d(db, rows)
    out = []
    for r in rows:
        if r.subject_type == "user":
            subject = {"type": "user", **(ppl.get(r.subject_id) or {"id": r.subject_id})}
        elif r.subject_type == "chat":
            subject = {"type": "chat", **(chat_brief(chats.get(r.subject_id)) or
                                          {"id": r.subject_id})}
        else:
            subject = None
        out.append({
            "id": r.id, "target_type": r.target_type, "status": r.status,
            "status_label": STATUS_LABELS.get(r.status, r.status),
            "escalated": r.status == "escalated" or (r.decision or {}).get("escalated", False),
            "reason_code": r.reason_code, "reason_label": REASON_CODES.get(r.reason_code, ""),
            "note": r.note, "chat": chat_brief(chats.get(r.chat_id)) if r.chat_id else None,
            "subject": subject, "seq_count": len(r.seqs or []),
            "reporters_7d": counts.get((r.subject_type, r.subject_id), 0),
            "created_at": iso(r.created_at), "handled_at": iso(r.handled_at),
            "handled_by": r.handled_by, "decision": r.decision or {},
        })
    return out


async def queue(db: AsyncSession, status: str, limit: int) -> list[dict]:
    """待处理的:多人举报的(escalated)排最前,其余按时间先后;处理过的:新的在前。"""
    q = select(ChatReport)
    if status == "open":
        q = q.where(ChatReport.status.in_(OPEN)).order_by(
            (ChatReport.status == "escalated").desc(), ChatReport.id)
    elif status == "handled":
        q = q.where(ChatReport.status.in_(("actioned", "dismissed"))).order_by(
            ChatReport.id.desc())
    else:
        q = q.order_by((ChatReport.status == "escalated").desc(), ChatReport.id.desc())
    rows = list(await db.scalars(q.limit(max(1, min(limit, 500)))))
    return await report_items(db, rows)


async def get_report(db: AsyncSession, report_id: int, *, lock: bool = False) -> ChatReport:
    q = select(ChatReport).where(ChatReport.id == report_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    r = await db.scalar(q)
    if r is None:
        raise HTTPException(404, "举报不存在")
    return r


async def detail(db: AsyncSession, r: ChatReport) -> dict:
    """举报单详情:对象是谁、他身上现在有哪些处罚、同一对象还有哪些没处理的举报、
    这张单被谁看过。**不含任何消息内容** —— 要看消息得走 [view_messages](会留痕)。"""
    item = (await report_items(db, [r]))[0]
    subject_sanctions: list[dict] = []
    if r.subject_type in ("user", "chat") and r.subject_id:
        rows = list(await db.scalars(select(SocialSanction).where(
            SocialSanction.target_type == r.subject_type,
            SocialSanction.target_id == r.subject_id).order_by(SocialSanction.id.desc())
            .limit(20)))
        now = now_utc()
        subject_sanctions = [{"id": s.id, "action": s.action,
                              "action_label": sanctions.ACTION_LABELS[s.action],
                              "reason_code": s.reason_code, "status": sanctions.status_of(s, now),
                              "until": iso(s.until), "created_at": iso(s.created_at)}
                             for s in rows]
    related = list(await db.scalars(select(ChatReport.id).where(
        ChatReport.subject_type == r.subject_type, ChatReport.subject_id == r.subject_id,
        ChatReport.status.in_(OPEN), ChatReport.id != r.id).order_by(ChatReport.id)
        .limit(50))) if r.subject_type else []
    views = list(await db.scalars(select(AdminChatView).where(AdminChatView.report_id == r.id)
                                  .order_by(AdminChatView.id)))
    admins = await people_brief(db, [v.admin_id for v in views])
    # 能对谁下什么处罚(处置对象必须和这张举报单有关,见 handle)
    return {
        "report": item,
        "subject_sanctions": subject_sanctions,
        "related_open": related,
        "views": [{"id": v.id, "admin": admins.get(v.admin_id) or {"id": v.admin_id},
                   "chat_id": v.chat_id, "seqs": v.seqs, "at": iso(v.created_at)}
                  for v in views],
        "can_view_messages": bool(r.chat_id and r.seqs),
        "messages_path": f"/admin/social/chat-messages?report_id={r.id}"
        if r.chat_id and r.seqs else None,
        "candidates": await candidates(db, r),
    }


async def candidates(db: AsyncSession, r: ChatReport) -> dict:
    """这张举报单能处罚的人 / 会话:被举报的人、被举报消息的发送人、会话的群主。"""
    users: set[int] = set()
    if r.subject_type == "user" and r.subject_id:
        users.add(r.subject_id)
    if r.user_id:
        users.add(r.user_id)
    chat = await db.get(Chat, r.chat_id) if r.chat_id else None
    if chat is not None and r.seqs:
        users |= {uid for uid in await db.scalars(select(ChatMessage.sender_id).where(
            ChatMessage.chat_id == chat.id, ChatMessage.seq.in_(r.seqs),
            ChatMessage.as_chat.is_(False))) if uid}
    if chat is not None and chat.type in ("group", "channel") and chat.owner_id:
        users.add(chat.owner_id)
    ppl = await people_brief(db, users)
    return {"users": [ppl[u] for u in sorted(users) if u in ppl and ppl[u]["role"] in
                      ("customer", "bot")],
            "chat": chat_brief(chat) if chat is not None and chat.type in ("group", "channel")
            else None}


# ---------------- S8:看被举报的消息(留痕)----------------

def window_of(r: ChatReport, chat: Chat) -> list[int]:
    return sanctions.context_seqs(r.seqs or [], floor=r.context_floor or 0,
                                  last_seq=chat.last_seq or 0, radius=CONTEXT)


def _media_out(items: list | None, admin_id: int, report_id: int) -> list[dict]:
    from .media import report_signed_url
    out = []
    for it in items or []:
        mid = it.get("id")
        if not mid:
            continue
        out.append({"id": mid, "kind": it.get("kind"), "name": it.get("name") or "",
                    "size": it.get("size"), "w": it.get("w"), "h": it.get("h"),
                    "duration_ms": it.get("duration_ms"), "mime": it.get("mime"),
                    "url": it.get("public_url") or report_signed_url(mid, admin_id, report_id),
                    "thumb": report_signed_url(mid, admin_id, report_id, True)
                    if it.get("has_thumb") else None})
    return out


def _summary(m: ChatMessage) -> dict:
    """不是文字的消息,给审核员看的摘要(位置、名片、投票题目……)。"""
    ex = m.extra or {}
    out = {}
    for k in ("location", "contact", "dice", "sticker", "service", "call"):
        if ex.get(k):
            out[k] = ex[k]
    if m.forward:
        out["forward"] = m.forward
    return out


async def view_messages(db: AsyncSession, admin: User, r: ChatReport) -> dict:
    """**唯一**能在后台看到会话消息的地方(S8)。范围 = 举报单里那几条 ± 5 条;每次都留痕。"""
    if not r.chat_id:
        return {"report_id": r.id, "chat": None, "reported_seqs": [], "seqs": [],
                "messages": [], "audit": None,
                "note": "这张举报单没有指定会话,按 S8 不能查看任何消息;请依据用户资料处置"}
    chat = await db.get(Chat, r.chat_id)
    if chat is None:
        raise HTTPException(404, "会话不存在")
    seqs = window_of(r, chat)
    msgs = list(await db.scalars(select(ChatMessage).where(
        ChatMessage.chat_id == chat.id, ChatMessage.seq.in_(seqs or [-1]))
        .order_by(ChatMessage.seq))) if seqs else []
    shown = [m.seq for m in msgs]
    view = AdminChatView(admin_id=admin.id, report_id=r.id, chat_id=chat.id, seqs=shown,
                         created_at=now_utc())
    db.add(view)
    await log_admin_action(db, admin, "chat_report.view_messages", target_type="chat_report",
                           target_id=r.id, detail={"chat_id": chat.id, "seqs": shown})
    await db.flush()
    senders = await people_brief(db, [m.sender_id for m in msgs if m.sender_id])
    reported = set(r.seqs or [])
    return {
        "report_id": r.id,
        "chat": chat_brief(chat),
        "reported_seqs": sorted(reported),
        "seqs": shown,
        "messages": [{
            "seq": m.seq,
            "sender": None if m.as_chat else senders.get(m.sender_id),
            "as_chat": m.as_chat,
            "kind": m.kind,
            "text": m.text or "",
            "media": _media_out(m.media, admin.id, r.id),
            "extra": _summary(m),
            "reply_to_seq": m.reply_to_seq,
            "created_at": iso(m.created_at),
            "edited_at": iso(m.edited_at),
            "deleted": m.deleted_at is not None,
            "reported": m.seq in reported,
        } for m in msgs],
        "audit": {"id": view.id, "at": iso(view.created_at),
                  "notice": "本次查看已记录(谁、哪张举报单、哪些消息、什么时候),"
                            "查看次数按月在透明中心公示"},
    }


async def media_in_window(db: AsyncSession, report_id: int, media_id: int) -> bool:
    """举报单绑定的媒体地址:这个媒体在不在那张单的 S8 范围里(不在就不给看)。"""
    r = await db.get(ChatReport, report_id)
    if r is None or not r.chat_id:
        return False
    chat = await db.get(Chat, r.chat_id)
    if chat is None:
        return False
    seqs = window_of(r, chat)
    if not seqs:
        return False
    row = await db.scalar(select(ChatMessage.id).where(
        ChatMessage.chat_id == chat.id, ChatMessage.seq.in_(seqs),
        ChatMessage.deleted_at.is_(None), ChatMessage.media.contains([{"id": media_id}]))
        .limit(1))
    return row is not None


# ---------------- 处置 ----------------

HANDLE_ACTIONS = ("dismiss", "delete_messages", "mute", "ban_chat", "ban_account", "warn")


async def handle(db: AsyncSession, admin: User, r: ChatReport, *, action: str, reason_code: str,
                 note: str, note_internal: str, hours: int | None, days: int | None,
                 permanent: bool, user_id: int | None, also_delete: bool) -> dict:
    """处理一张举报单。处置对象必须和这张单有关(被举报的人、被举报消息的发送人、群主 / 会话),
    不能借一张举报单去处罚不相干的人。只结这一张 —— 同一个人的别的举报,证据各不相同,各自处理。"""
    from .chat_store import lock_chat, wipe_as_platform

    if r.status not in OPEN:
        raise HTTPException(409, "这条举报已经处理过了")
    if action not in HANDLE_ACTIONS:
        raise HTTPException(422, f"没有这种处置:{action}")
    was_escalated = r.status == "escalated"
    now = now_utc()
    created: list[SocialSanction] = []
    resolution = "举报不成立"
    if action != "dismiss":
        from .video import reason_ok
        reason_ok(reason_code, note)
        cand = await candidates(db, r)
        cand_users = {u["id"] for u in cand["users"]}
        until = sanctions.compute_until(action, hours=hours, days=days, permanent=permanent,
                                        now=now)
        if action == "delete_messages" or also_delete:
            if not r.chat_id or not r.seqs:
                raise HTTPException(422, "这张举报单没有指定消息,没有可删的")
            chat = await lock_chat(db, r.chat_id)
            gone = await wipe_as_platform(db, chat, r.seqs)
            by_sender: dict[tuple[str, int], list[int]] = {}
            for seq, sender, as_chat in gone:
                key = ("chat", chat.id) if as_chat or not sender else ("user", sender)
                by_sender.setdefault(key, []).append(seq)
            for (ttype, tid), seqs in by_sender.items():
                if ttype == "chat":
                    # 以会话名义发的(频道帖子、匿名发言):当事人是群主,处罚记在群主头上
                    if not chat.owner_id:
                        continue
                    ttype, tid = "user", chat.owner_id
                created.append(await sanctions.impose(
                    db, admin, target_type=ttype, target_id=tid, action="delete_messages",
                    reason_code=reason_code, note=note, note_internal=note_internal,
                    chat_id=chat.id, seqs=seqs, report_kind="chat", report_id=r.id))
            if action == "delete_messages" and not gone:
                raise HTTPException(409, "被举报的消息已经不在了(可能已被删除)")
        if action in ("mute", "ban_account", "warn"):
            target = user_id or (r.subject_id if r.subject_type == "user" else None)
            if target is None:
                raise HTTPException(422, "这张举报单的对象是会话,要处罚人请指定 user_id")
            if target not in cand_users:
                raise HTTPException(422, "处罚对象必须是这张举报单涉及的人"
                                         "(被举报的人、被举报消息的发送人或群主)")
            created.append(await sanctions.impose(
                db, admin, target_type="user", target_id=target, action=action,
                reason_code=reason_code, note=note, note_internal=note_internal, until=until,
                chat_id=r.chat_id, report_kind="chat", report_id=r.id))
        elif action == "ban_chat":
            if cand["chat"] is None:
                raise HTTPException(422, "只有群和频道能封;私聊请对人禁言或封号")
            created.append(await sanctions.impose(
                db, admin, target_type="chat", target_id=cand["chat"]["id"], action="ban_chat",
                reason_code=reason_code, note=note, note_internal=note_internal, until=until,
                report_kind="chat", report_id=r.id))
        main = created[-1] if created else None
        label = REASON_CODES[reason_code]
        if main is not None:
            dur = sanctions.duration_text(main)
            resolution = (f"已{sanctions.ACTION_LABELS[main.action]}"
                          + (f" {dur}" if dur else "") + f":{label}")
    r.status = "dismissed" if action == "dismiss" else "actioned"
    r.handled_by, r.handled_at = admin.id, now
    r.decision = {"action": action, "reason_code": reason_code if action != "dismiss" else "",
                  "sanction_ids": [s.id for s in created], "resolution": resolution[:300],
                  # 结案后 status 变成 actioned / dismissed,多人举报这件事记在这里(队列、统计要看)
                  "escalated": was_escalated}
    await log_admin_action(db, admin, f"chat_report.{action}", target_type="chat_report",
                           target_id=r.id,
                           detail={"reason_code": reason_code,
                                   "sanction_ids": [s.id for s in created]})
    return {"id": r.id, "status": r.status, "resolution": resolution,
            "sanction_ids": [s.id for s in created]}


# ---------------- 后台列表里的处罚 ----------------

async def sanction_items(db: AsyncSession, rows: list[SocialSanction],
                         viewer: User | None = None) -> list[dict]:
    """处置记录的一行(后台看的:带内部备注、处理人、来源举报单)。"""
    now = now_utc()
    uids = {s.target_id for s in rows if s.target_type == "user"} | \
        {s.admin_id for s in rows if s.admin_id} | \
        {s.appeal_admin_id for s in rows if s.appeal_admin_id} | \
        {s.revoked_by for s in rows if s.revoked_by}
    ppl = await people_brief(db, uids)
    chat_ids = {s.target_id for s in rows if s.target_type == "chat"} | \
        {s.chat_id for s in rows if s.chat_id}
    chats = {c.id: c for c in await db.scalars(select(Chat).where(Chat.id.in_(chat_ids)))} \
        if chat_ids else {}
    out = []
    for s in rows:
        st = sanctions.status_of(s, now)
        target = ({"type": "user", **(ppl.get(s.target_id) or {"id": s.target_id})}
                  if s.target_type == "user"
                  else {"type": "chat", **(chat_brief(chats.get(s.target_id)) or
                                           {"id": s.target_id})})
        out.append({
            "id": s.id, "target_type": s.target_type, "target": target,
            "action": s.action, "action_label": sanctions.ACTION_LABELS[s.action],
            "reason_code": s.reason_code, "reason_label": REASON_CODES.get(s.reason_code, ""),
            "note": s.note, "note_internal": s.note_internal,
            "until": iso(s.until),
            "permanent": s.action in ("mute", "ban_chat", "ban_account") and s.until is None,
            "duration": sanctions.duration_text(s),
            "status": st, "status_label": sanctions.STATUS_LABELS[st],
            "chat": chat_brief(chats.get(s.chat_id)) if s.chat_id else None,
            "seqs": list(s.seqs or []),
            "admin": ppl.get(s.admin_id) if s.admin_id else None,
            "report": {"kind": s.report_kind, "id": s.report_id} if s.report_kind else None,
            "revoked_at": iso(s.revoked_at),
            "revoked_by": ppl.get(s.revoked_by) if s.revoked_by else None,
            "revoke_note": s.revoke_note,
            "appeal": {"status": s.appeal_status,
                       "status_label": sanctions.APPEAL_LABELS[s.appeal_status],
                       "text": s.appeal_text, "appealed_at": iso(s.appealed_at),
                       "note": s.appeal_note, "note_internal": s.appeal_note_internal,
                       "admin": ppl.get(s.appeal_admin_id) if s.appeal_admin_id else None,
                       "resolved_at": iso(s.appeal_resolved_at)},
            "carried_from": s.carried_from,
            "created_at": iso(s.created_at),
            "you_decided": viewer is not None and s.admin_id == viewer.id,
        })
    return out


def sanctions_query(*, status: str = "all", action: str = "", target_type: str = "",
                    reason_code: str = "", appeal: str = "", target_id: int | None = None,
                    before: int | None = None):
    """处置记录的筛选(纯 SQL 条件,分页按 id 倒序)。"""
    now = now_utc()
    q = select(SocialSanction)
    live = and_(SocialSanction.revoked_at.is_(None),
                SocialSanction.action.in_(("mute", "ban_chat", "ban_account")),
                or_(SocialSanction.until.is_(None), SocialSanction.until > now))
    if status == "active":
        q = q.where(live)
    elif status == "expired":
        q = q.where(SocialSanction.revoked_at.is_(None),
                    SocialSanction.action.in_(("mute", "ban_chat", "ban_account")),
                    SocialSanction.until.is_not(None), SocialSanction.until <= now)
    elif status == "revoked":
        q = q.where(SocialSanction.revoked_at.is_not(None))
    elif status == "done":
        q = q.where(SocialSanction.revoked_at.is_(None),
                    SocialSanction.action.in_(("delete_messages", "warn")))
    if action:
        q = q.where(SocialSanction.action == action)
    if target_type:
        q = q.where(SocialSanction.target_type == target_type)
    if reason_code:
        q = q.where(SocialSanction.reason_code == reason_code)
    if appeal == "none":
        q = q.where(SocialSanction.appeal_status == "")
    elif appeal:
        q = q.where(SocialSanction.appeal_status == appeal)
    if target_id:
        q = q.where(SocialSanction.target_id == target_id)
    if before:
        q = q.where(SocialSanction.id < before)
    return q.order_by(SocialSanction.id.desc())
