"""处罚:一处查、一处判、一处写(DEV-PROMPTS-40 #368 聊天部分,S6)。

**所有执行点都调这里的 [check_user] / [check_chat]**,不要在别处自己查 social_sanctions ——
「生效中」的口径(没撤销、没到期、只有三种限制类会挡人)写两份迟早一份漏掉到期或撤销。

执行点(每个都落在真实的写路径上,文档 docs/COMMUNITY-GOVERNANCE.md §2 同一张表,
tests/unit/test_sanctions.py 对着比):

| 执行点 | 在哪 | 被谁挡 |
|---|---|---|
| message | chat_store.send / forward / edit | ban_account、mute;会话被 ban_chat |
| comment | video_talk.post_comment | ban_account、mute |
| danmaku | video_talk.post_danmaku | ban_account、mute |
| create_chat | chat_store.create_chat / private_chat(新建时) | ban_account |
| join | chat_store.join_by_invite / join_public | ban_account;会话被 ban_chat |
| video_submit | services/video.submit | ban_account |
| call | services/calls._invite | ban_account |
| social_write | routers/social.social_user(其余全部社交写接口) | ban_account |

被挡时一律 403,`detail` 是 [restriction_detail] 的形状:原因代码、中文标签、说明、到期时间、
能不能申诉 —— 客户端照着它提示用户,不用自己拼话。

处罚种类:
- mute 禁言(必须限时,1–720 小时):不能发消息、评论、弹幕;
- ban_chat 封群 / 频道(限时或永久):成员不能发言、不能再加入,公开发现(搜索、@链接、非成员预览)里消失;
- ban_account 封号(限时或永久):社交相关的写操作全拒;能登录、看自己的数据、注销、申诉;
- delete_messages 删消息、warn 警告:一次性的,记下来是为了能申诉、能公示。

**申诉换人**(S6):处理申诉的人不能是作出处罚的人(403),和视频、小程序同一条规矩。
申诉成立 = 撤销 = 限制立即解除 + 通知当事人;有待处理的申诉时管理员不能绕过申诉直接撤销(409),
免得「原处罚人自己把申诉结了」。
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (RESTRICTIVE_ACTIONS, SANCTION_ACTIONS, Chat, SocialSanction, User)
from .admin_audit import log_admin_action
from .video import REASON_CODES, reason_ok

ACTION_LABELS = {
    "delete_messages": "删除消息", "mute": "禁言", "ban_chat": "封禁群 / 频道",
    "ban_account": "封号", "warn": "警告",
}
STATUS_LABELS = {"active": "生效中", "expired": "已到期", "revoked": "已撤销", "done": "已执行"}
APPEAL_LABELS = {"": "未申诉", "open": "申诉处理中", "upheld": "维持原处罚",
                 "overturned": "申诉成立,已撤销"}

#: 每个执行点被哪几种「对人」的处罚挡住(见模块注释的表)
BLOCKED_BY: dict[str, tuple[str, ...]] = {
    "message": ("ban_account", "mute"),
    "comment": ("ban_account", "mute"),
    "danmaku": ("ban_account", "mute"),
    "create_chat": ("ban_account",),
    "join": ("ban_account",),
    "video_submit": ("ban_account",),
    # 音乐(DEV-PROMPTS-41 #378):开通音乐人、建作品、加歌、提交审核。
    # 评论用上面的 comment 点(禁言也该管得住歌曲评论)
    "music_submit": ("ban_account",),
    "call": ("ban_account",),
    "social_write": ("ban_account",),
}
#: 会话被 ban_chat 时挡哪几个执行点(发言、加入)
CHAT_POINTS = ("speak", "join")

#: 禁言只能限时;要长期限制就封号(封号有「永久」)
MUTE_MAX_HOURS = 720
BAN_MAX_DAYS = 3650
APPEAL_MIN, APPEAL_MAX = 5, 500

#: 封号期间**还能用**的写接口(默认全拒,只放行这几个):申诉、导出自己的数据、读(断线补齐 / 已读 /
#: 换媒体地址)、只有自己看得见的设置、自我保护(拉黑、退群)、删自己的观看历史。
#: 新加的社交写接口不在这里就会被封号挡住 —— 默认值站在「挡」这一边。
ACCOUNT_BAN_ALLOWED: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/social/v1/sanctions/{sanction_id}/appeal"),
    ("POST", "/video/v1/videos/{vid}/appeal"),
    # 导出自己的数据(S5):封号不能拿走用户对自己数据的权利
    ("POST", "/chat/v1/export"),
    ("POST", "/chat/v1/sync"),
    ("POST", "/chat/v1/dialogs/{chat_id}/read"),
    ("POST", "/social/v1/notifications/read"),
    ("POST", "/media/v1/sign"),
    ("PATCH", "/chat/v1/dialogs/{chat_id}"),
    ("PATCH", "/social/v1/me"),
    ("PATCH", "/social/v1/me/tags-badges"),
    ("PATCH", "/video/v1/me/settings"),
    ("POST", "/social/v1/blocks"),
    ("DELETE", "/social/v1/blocks/{user_id}"),
    ("POST", "/chat/v1/chats/{chat_id}/leave"),
    ("POST", "/chat/v1/reports"),
    ("POST", "/video/v1/reports"),
    ("DELETE", "/video/v1/me/history"),
    ("DELETE", "/video/v1/me/history/{vid}"),
    # 音乐(#378):申诉、举报、清空自己的最近播放、只有自己看得见的设置。
    # 发歌、发评论、建歌单一律不放行。收听上报不在这里 —— 它不挂 social_user
    # (没登录也能听,M5),这一层根本走不到它
    ("POST", "/music/v1/studio/releases/{rid}/appeal"),
    ("POST", "/music/v1/reports"),
    ("DELETE", "/music/v1/me/history"),
    ("PUT", "/music/v1/me/settings"),
})

_BJ = timezone(timedelta(hours=8))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def bj_text(dt: datetime) -> str:
    """北京时间,给人看的:2026 年 9 月 13 日 10:00。"""
    b = dt.astimezone(_BJ)
    return f"{b.year} 年 {b.month} 月 {b.day} 日 {b:%H:%M}"


# ---------------- 纯函数(单测锁住)----------------

def compute_until(action: str, *, hours: int | None = None, days: int | None = None,
                  permanent: bool = False, now: datetime | None = None) -> datetime | None:
    """这次处罚到什么时候。禁言必须限时;封号、封群限时或永久;一次性的处罚没有到期时间。"""
    now = now or now_utc()
    if action == "mute":
        if permanent:
            raise HTTPException(422, f"禁言只能限时(1–{MUTE_MAX_HOURS} 小时);要长期限制请封号")
        if not isinstance(hours, int) or not 1 <= hours <= MUTE_MAX_HOURS:
            raise HTTPException(422, f"禁言时长是 1–{MUTE_MAX_HOURS} 小时")
        return now + timedelta(hours=hours)
    if action in ("ban_account", "ban_chat"):
        if permanent:
            return None
        if not isinstance(days, int) or not 1 <= days <= BAN_MAX_DAYS:
            raise HTTPException(422, f"封禁天数是 1–{BAN_MAX_DAYS} 天,或者选「永久」")
        return now + timedelta(days=days)
    if action in ("delete_messages", "warn"):
        return None
    raise HTTPException(422, f"没有这种处罚:{action}")


def status_of(s: SocialSanction, now: datetime | None = None) -> str:
    """active 生效中 / expired 已到期 / revoked 已撤销 / done 一次性处罚已执行。"""
    now = now or now_utc()
    if s.revoked_at is not None:
        return "revoked"
    if s.action not in RESTRICTIVE_ACTIONS:
        return "done"
    if s.until is not None and s.until <= now:
        return "expired"
    return "active"


def is_live(s: SocialSanction, now: datetime | None = None) -> bool:
    return status_of(s, now) == "active"


def duration_of(action: str, until: datetime | None, created_at: datetime | None) -> str:
    """「24 小时」「7 天」「永久」;一次性的处罚是空串。透明中心和后台列表用。"""
    if action not in RESTRICTIVE_ACTIONS:
        return ""
    if until is None:
        return "永久"
    # 到期时间和记录时间差几毫秒(先算到期、再落库),按整小时取整
    hours = max(1, round((until - created_at).total_seconds() / 3600)) if created_at else 0
    if action != "mute" and hours and hours % 24 == 0:
        return f"{hours // 24} 天"
    return f"{hours} 小时"


def duration_text(s: SocialSanction) -> str:
    return duration_of(s.action, s.until, s.created_at)


_PRIORITY = {"ban_account": 0, "ban_chat": 1, "mute": 2}


def strongest(rows: list[SocialSanction]) -> SocialSanction | None:
    """同时有好几条生效的,拿最重的那条说话:封号 > 封群 > 禁言;同种里永久的、到期晚的在前。

    **必须显式排**:同时生效的可能不止一条(先禁言 24 小时、又封号 7 天),
    随手 `scalar()` 拿到哪条算哪条,提示给用户的到期时间就可能是短的那条。
    """
    if not rows:
        return None
    far = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(rows, key=lambda s: (_PRIORITY.get(s.action, 9),
                                       -(s.until or far).timestamp(), -s.id))[0]


def restriction_message(s: SocialSanction, *, party: bool, chat_type: str | None = None) -> str:
    label = REASON_CODES.get(s.reason_code, s.reason_code)
    why = f"原因:{label}" + (f"({s.note})" if party and s.note else "")
    if s.action == "mute":
        return (f"你被禁言到 {bj_text(s.until)},{why}。期间不能发消息、评论和发弹幕。"
                "有异议可以申诉。") if s.until else f"你被禁言了,{why}。有异议可以申诉。"
    if s.action == "ban_account":
        head = "你的账号被永久封禁" if s.until is None else f"你的账号被封禁到 {bj_text(s.until)}"
        return (f"{head},{why}。期间不能发消息、评论、弹幕、投稿,也不能建群、加群、打电话;"
                "可以查看自己的数据、注销账号和申诉。")
    what = "频道" if chat_type == "channel" else "群"
    head = f"这个{what}被平台永久封禁" if s.until is None else \
        f"这个{what}被平台封禁到 {bj_text(s.until)}"
    tail = (f"你是{what}主,有异议可以申诉。" if party
            else f"{what}主可以申诉。")
    return f"{head},{why}。期间不能发言、不能加入,也不会出现在搜索里。{tail}"


def restriction_detail(s: SocialSanction, *, point: str, party: bool,
                       chat_type: str | None = None) -> dict:
    """被挡时 403 的 detail(客户端按它提示用户;形状写在 COMMUNITY-GOVERNANCE.md §3)。

    `party` = 看的人是不是当事人:会话被封时群里的普通成员也会被挡,但他不是当事人 ——
    不给他看写给群主的说明,也不告诉他「你可以申诉」。
    """
    appealable = party and s.revoked_at is None and s.appeal_status == ""
    return {
        "error": "sanctioned",
        "message": restriction_message(s, party=party, chat_type=chat_type),
        "sanction_id": s.id,
        "scope": s.target_type,
        "point": point,
        "action": s.action,
        "action_label": ACTION_LABELS[s.action],
        "reason_code": s.reason_code,
        "reason_label": REASON_CODES.get(s.reason_code, ""),
        "note": s.note if party else "",
        "until": iso(s.until),
        "permanent": s.until is None,
        "can_appeal": appealable,
        "appeal_status": s.appeal_status if party else "",
        "appeal_path": f"/social/v1/sanctions/{s.id}/appeal" if appealable else None,
    }


def context_seqs(reported: list[int], *, floor: int, last_seq: int, radius: int = 5) -> list[int]:
    """S8 的查看范围:举报单里那几条和前后各 radius 条(按 seq),
    不越过举报人当时的可见下限 `floor`(不含),不超过会话最新一条。纯函数。"""
    out: set[int] = set()
    for s in reported or []:
        for x in range(int(s) - radius, int(s) + radius + 1):
            if floor < x <= last_seq:
                out.add(x)
    return sorted(out)


# ---------------- 查 ----------------

async def live_rows(db: AsyncSession, *, user_id: int | None = None, chat_id: int | None = None,
                    actions: tuple[str, ...] = RESTRICTIVE_ACTIONS,
                    now: datetime | None = None) -> list[SocialSanction]:
    """此刻生效的限制类处罚(对这个人的和 / 或对这个会话的)。"""
    now = now or now_utc()
    who = []
    if user_id:
        who.append(and_(SocialSanction.target_type == "user", SocialSanction.target_id == user_id))
    if chat_id:
        who.append(and_(SocialSanction.target_type == "chat", SocialSanction.target_id == chat_id))
    if not who:
        return []
    return list(await db.scalars(select(SocialSanction).where(
        or_(*who), SocialSanction.revoked_at.is_(None), SocialSanction.action.in_(actions),
        or_(SocialSanction.until.is_(None), SocialSanction.until > now))
        .order_by(SocialSanction.id.desc())))


async def check_user(db: AsyncSession, user_id: int, point: str) -> None:
    """这个人此刻能不能做这件事(见 BLOCKED_BY)。被挡 → 403 + restriction_detail。"""
    s = strongest(await live_rows(db, user_id=user_id, actions=BLOCKED_BY[point]))
    if s is not None:
        raise HTTPException(403, detail=restriction_detail(s, point=point, party=True))


async def chat_ban(db: AsyncSession, chat_id: int) -> SocialSanction | None:
    return strongest(await live_rows(db, chat_id=chat_id, actions=("ban_chat",)))


async def check_chat(db: AsyncSession, chat: Chat, viewer_id: int, point: str) -> None:
    """会话被封时:不能发言(speak)、不能加入(join)。"""
    assert point in CHAT_POINTS, point
    s = await chat_ban(db, chat.id)
    if s is not None:
        raise HTTPException(403, detail=restriction_detail(
            s, point=point, party=chat.owner_id == viewer_id, chat_type=chat.type))


async def banned_chat_ids(db: AsyncSession, chat_ids) -> dict[int, SocialSanction]:
    """一批会话里哪些此刻被封(会话列表一次查完,不 N+1)。"""
    ids = [int(i) for i in dict.fromkeys(chat_ids) if i]
    if not ids:
        return {}
    now = now_utc()
    rows = list(await db.scalars(select(SocialSanction).where(
        SocialSanction.target_type == "chat", SocialSanction.target_id.in_(ids),
        SocialSanction.action == "ban_chat", SocialSanction.revoked_at.is_(None),
        or_(SocialSanction.until.is_(None), SocialSanction.until > now))))
    out: dict[int, list] = {}
    for s in rows:
        out.setdefault(s.target_id, []).append(s)
    return {cid: strongest(lst) for cid, lst in out.items()}


def ban_brief(s: SocialSanction | None, chat_type: str | None = None) -> dict | None:
    """会话卡片、会话事件里的「被平台封禁」提示(给群里所有人看,不带写给群主的说明)。"""
    if s is None:
        return None
    return {"sanction_id": s.id, "reason_code": s.reason_code,
            "reason_label": REASON_CODES.get(s.reason_code, ""), "until": iso(s.until),
            "permanent": s.until is None,
            "message": restriction_message(s, party=False, chat_type=chat_type)}


async def party_id(db: AsyncSession, s: SocialSanction) -> int | None:
    """当事人:对人的是那个人;对会话的是**当前的**群主 / 频道主。"""
    if s.target_type == "user":
        return s.target_id
    chat = await db.get(Chat, s.target_id)
    return chat.owner_id if chat is not None else None


# ---------------- 写 ----------------

async def _notify(db: AsyncSession, user_id: int | None, title: str, text: str, action: str,
                  s: SocialSanction) -> None:
    if not user_id:
        return
    from .social_notify import system
    await system(db, user_id, title, text, action=action, reason_code=s.reason_code,
                 extra={"sanction_id": s.id, "until": iso(s.until),
                        "sanction_action": s.action})


async def _chat_label(db: AsyncSession, chat_id: int | None) -> str:
    chat = await db.get(Chat, chat_id) if chat_id else None
    if chat is None:
        return "会话"
    if chat.type == "private":
        return "一个私聊"
    return f"{'频道' if chat.type == 'channel' else '群'}「{chat.title}」"


async def impose(db: AsyncSession, admin: User, *, target_type: str, target_id: int, action: str,
                 reason_code: str, note: str = "", note_internal: str = "",
                 until: datetime | None = None, chat_id: int | None = None,
                 seqs: list[int] | None = None, report_kind: str = "",
                 report_id: int | None = None) -> SocialSanction:
    """记一条处罚并通知当事人。**只改库不提交**(和业务同一个事务,见 admin_audit)。

    删消息本身(清正文、发删除事件)由调用方先做(chat_store.wipe_as_platform),
    这里只记账 —— 写消息表只能走 chat_store(S10)。
    """
    reason_ok(reason_code, note)
    if action not in SANCTION_ACTIONS:
        raise HTTPException(422, f"没有这种处罚:{action}")
    if (target_type == "chat") != (action == "ban_chat"):
        raise HTTPException(422, "封群 / 频道的对象是会话,其余处罚的对象是人")
    chat_type = None
    if target_type == "user":
        from .social import SOCIAL_ROLES
        u = await db.get(User, target_id)
        if u is None or u.role not in SOCIAL_ROLES:
            raise HTTPException(404, "没有这个用户")
        if u.deleted_at is not None and action in RESTRICTIVE_ACTIONS:
            raise HTTPException(409, "这个账号已经注销了")
    elif target_type == "chat":
        chat = await db.get(Chat, target_id)
        if chat is None or chat.deleted_at is not None:
            raise HTTPException(404, "会话不存在或已解散")
        if chat.type not in ("group", "channel"):
            raise HTTPException(422, "只有群和频道能封;私聊请对人禁言或封号")
        chat_type = chat.type
        chat_id = chat.id
    else:
        raise HTTPException(422, "处罚对象只能是 user 或 chat")
    s = SocialSanction(target_type=target_type, target_id=target_id, action=action,
                       reason_code=reason_code, note=(note or "").strip()[:500],
                       note_internal=(note_internal or "").strip()[:500], until=until,
                       chat_id=chat_id, seqs=sorted({int(x) for x in seqs or []}),
                       admin_id=admin.id, report_kind=report_kind, report_id=report_id,
                       created_at=now_utc())
    db.add(s)
    await db.flush()
    label = REASON_CODES[reason_code]
    extra = f":{s.note}" if s.note else ""
    who = await party_id(db, s)
    if action == "mute":
        await _notify(db, who, "你被禁言了",
                      f"因「{label}」被禁言到 {bj_text(until)}{extra}。期间不能发消息、评论和发弹幕。"
                      "有异议可以申诉(每次处罚申诉一次,由另一名审核员复核)", "sanction_mute", s)
    elif action == "ban_account":
        till = "永久封禁" if until is None else f"封禁到 {bj_text(until)}"
        await _notify(db, who, "账号被封禁",
                      f"你的账号因「{label}」被{till}{extra}。期间社交功能只能看、不能写;"
                      "可以查看自己的数据、注销账号和申诉", "sanction_ban_account", s)
    elif action == "ban_chat":
        what = "频道" if chat_type == "channel" else "群"
        till = "永久封禁" if until is None else f"封禁到 {bj_text(until)}"
        await _notify(db, who, f"你的{what}被封禁",
                      f"{await _chat_label(db, chat_id)}因「{label}」被{till}{extra}。"
                      f"期间成员不能发言、不能加入,{what}也不会出现在搜索里。有异议可以申诉",
                      "sanction_ban_chat", s)
        from .rt_events import append_chat_event
        await append_chat_event(db, chat_id, "chat", {"platform_ban": ban_brief(s, chat_type)})
    elif action == "delete_messages":
        await _notify(db, who, "消息被删除",
                      f"你在{await _chat_label(db, chat_id)}里的 {len(s.seqs)} 条消息因「{label}」"
                      f"被删除{extra}。有异议可以申诉", "sanction_delete_messages", s)
    else:
        await _notify(db, who, "收到一次警告",
                      f"因「{label}」收到一次警告{extra}。再犯可能被禁言或封号;有异议可以申诉",
                      "sanction_warn", s)
    await log_admin_action(db, admin, f"sanction.{action}", target_type=target_type,
                           target_id=target_id,
                           detail={"sanction_id": s.id, "reason_code": reason_code,
                                   "until": iso(until), "report_kind": report_kind,
                                   "report_id": report_id})
    return s


async def _lifted(db: AsyncSession, s: SocialSanction) -> None:
    """撤销之后:封群的,告诉群里的人解封了(公开发现、发言、加入按查询自动恢复)。"""
    if s.action == "ban_chat":
        from .rt_events import append_chat_event
        chat = await db.get(Chat, s.target_id)
        if chat is not None and chat.deleted_at is None:
            await append_chat_event(db, chat.id, "chat", {"platform_ban": None})


async def revoke(db: AsyncSession, admin: User, s: SocialSanction, note: str) -> SocialSanction:
    """管理员撤销(发现处罚错了)。有待处理的申诉时不能绕过申诉:申诉必须换人处理(S6)。"""
    if s.revoked_at is not None:
        raise HTTPException(409, "这条处罚已经撤销了")
    if s.appeal_status == "open":
        raise HTTPException(409, "当事人已经申诉了,请在「申诉」里处理(必须由另一名审核员复核)")
    note = (note or "").strip()
    if len(note) < 2:
        raise HTTPException(422, "写一句撤销的理由(会告诉当事人)")
    s.revoked_at, s.revoked_by, s.revoke_note = now_utc(), admin.id, note[:300]
    await _lifted(db, s)
    await _notify(db, await party_id(db, s), "处罚已撤销",
                  f"你的「{ACTION_LABELS[s.action]}」处罚已被撤销:{note}", "sanction_revoked", s)
    await log_admin_action(db, admin, "sanction.revoke", target_type=s.target_type,
                           target_id=s.target_id, detail={"sanction_id": s.id})
    return s


async def appeal(db: AsyncSession, user: User, s: SocialSanction, text: str) -> SocialSanction:
    """当事人申诉:一次处罚只能申诉一次,理由 5–500 字;由另一名审核员处理(S6)。"""
    if await party_id(db, s) != user.id:
        raise HTTPException(404, "没有这条处罚")
    if s.revoked_at is not None:
        raise HTTPException(409, "这条处罚已经撤销了,不用申诉")
    if s.appeal_status:
        raise HTTPException(409, "每个处罚只能申诉一次")
    text = (text or "").strip()
    if not APPEAL_MIN <= len(text) <= APPEAL_MAX:
        raise HTTPException(422, f"申诉理由写 {APPEAL_MIN}–{APPEAL_MAX} 个字")
    s.appeal_status, s.appeal_text, s.appealed_at = "open", text, now_utc()
    return s


async def resolve_appeal(db: AsyncSession, admin: User, s: SocialSanction, *, overturn: bool,
                         note: str, note_internal: str = "") -> SocialSanction:
    """处理申诉。**作出处罚的人不能处理对它的申诉**(S6)—— 自己复核自己等于没有申诉。"""
    if s.appeal_status != "open":
        raise HTTPException(409 if s.appeal_status else 404,
                            "这条申诉已经处理过了" if s.appeal_status else "没有这条申诉")
    if s.admin_id is not None and s.admin_id == admin.id:
        raise HTTPException(403, "原处罚是你作出的,申诉必须由另一名审核员处理")
    note = (note or "").strip()
    if len(note) < 2:
        raise HTTPException(422, "写一句复核结论(会给当事人看)")
    now = now_utc()
    s.appeal_status = "overturned" if overturn else "upheld"
    s.appeal_admin_id, s.appeal_resolved_at = admin.id, now
    s.appeal_note, s.appeal_note_internal = note[:500], (note_internal or "").strip()[:500]
    if overturn and s.revoked_at is None:
        s.revoked_at, s.revoked_by, s.revoke_note = now, admin.id, f"申诉成立:{note}"[:300]
        await _lifted(db, s)
    what = ACTION_LABELS[s.action]
    await _notify(db, await party_id(db, s), "申诉结果",
                  (f"你对「{what}」的申诉成立,处罚已撤销" + (
                      "(删掉的消息无法恢复)" if s.action == "delete_messages" else "")
                   if overturn else f"你对「{what}」的申诉经另一名审核员复核,维持原处罚")
                  + f":{note}", "sanction_appeal_" + s.appeal_status, s)
    await log_admin_action(db, admin, "sanction.appeal." + ("overturn" if overturn else "uphold"),
                           target_type=s.target_type, target_id=s.target_id,
                           detail={"sanction_id": s.id})
    return s


# ---------------- 输出 ----------------

def party_out(s: SocialSanction, now: datetime | None = None) -> dict:
    """当事人自己看的(不带内部备注、不带处理人是谁)。"""
    st = status_of(s, now)
    return {
        "id": s.id, "target_type": s.target_type,
        "chat_id": s.chat_id if s.target_type == "user" else s.target_id,
        "action": s.action, "action_label": ACTION_LABELS[s.action],
        "reason_code": s.reason_code, "reason_label": REASON_CODES.get(s.reason_code, ""),
        "note": s.note, "until": iso(s.until),
        "permanent": s.action in RESTRICTIVE_ACTIONS and s.until is None,
        "duration": duration_text(s), "seqs": list(s.seqs or []),
        "status": st, "status_label": STATUS_LABELS[st],
        "created_at": iso(s.created_at), "revoked_at": iso(s.revoked_at),
        "revoke_note": s.revoke_note,
        "appeal": {"status": s.appeal_status, "status_label": APPEAL_LABELS[s.appeal_status],
                   "text": s.appeal_text, "appealed_at": iso(s.appealed_at),
                   "note": s.appeal_note, "resolved_at": iso(s.appeal_resolved_at)},
        "can_appeal": s.revoked_at is None and s.appeal_status == "",
    }


async def mine(db: AsyncSession, user_id: int) -> dict:
    """我的处罚:对我这个人的 + 对我当群主 / 频道主的会话的。生效中的和历史分开。"""
    owned = select(Chat.id).where(Chat.owner_id == user_id)
    rows = list(await db.scalars(select(SocialSanction).where(or_(
        and_(SocialSanction.target_type == "user", SocialSanction.target_id == user_id),
        and_(SocialSanction.target_type == "chat", SocialSanction.target_id.in_(owned))))
        .order_by(SocialSanction.id.desc()).limit(200)))
    now = now_utc()
    items = [party_out(s, now) for s in rows]
    return {"active": [x for x in items if x["status"] == "active"],
            "history": [x for x in items if x["status"] != "active"]}


# ---------------- 注销再注册:处罚跟着手机号走 ----------------

async def park_for_carryover(db: AsyncSession, user: User) -> int:
    """注销时:还生效的禁言 / 封号记下 HMAC(手机号 + 角色)。在释放手机号**之前**调。"""
    from .crypto import pseudonym
    rows = await live_rows(db, user_id=user.id, actions=("mute", "ban_account"))
    if not rows:
        return 0
    key = pseudonym(user.phone, user.role.value)
    for s in rows:
        s.carry_key = key
    return len(rows)


async def restore_carried(db: AsyncSession, user: User) -> int:
    """注册时:这个号上次注销时还有没到期的处罚,**原样挪到新账号上**(同一行改对象,
    不复制 —— 透明中心数处罚条数不会因为注销再注册多出一条;申诉状态也跟着走,不能借此再申诉一次)。"""
    from .crypto import pseudonym
    key = pseudonym(user.phone, user.role.value)
    rows = list(await db.scalars(select(SocialSanction).where(
        SocialSanction.carry_key == key)))
    if not rows:
        return 0
    await db.flush()  # 新账号要先有 id
    now = now_utc()
    moved = 0
    for s in rows:
        s.carry_key = None
        if not is_live(s, now):
            continue
        s.carried_from = s.target_id
        s.target_id = user.id
        moved += 1
    return moved
