"""视频的业务逻辑:投稿、改稿、提交、审核、申诉、硬币、卡片、注销级联、清扫(DEV-PROMPTS-40 #357–#368)。

路由(routers/video.py、routers/video_admin.py)只取当前用户、调这里、提交;判定都在这里。
互动(赞、币、藏、分享、播放、关注)在 video_interact.py,评论和弹幕在 video_talk.py,
推荐 / 搜索在 video_feed.py,转码在 video_media.py。

**线上版本和待审版本分开**(§5.8):
- 还没发布过的稿件(draft / rejected / failed)直接改行上的字段和分 P;
- 已经有线上版本的(published / scheduled)再改,内容字段进 `pending_changes["fields"]`,
  分 P 的目标清单进 `pending_changes["parts"]`,**线上那一版一个字不动**,审核通过才搬过去;
- 可见性、弹幕 / 评论开关、定时发布时间不是「内容」,改了立即生效,不用重审。
"""
import asyncio
import hashlib
import hmac
import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import (CoinLedger, CommentVote, Danmaku, FavFolder, FavItem, Follow, MediaFile,
                      Merchant, MerchantStatus, SearchTermUser, SocialBlock, SocialContact,
                      SocialNotification, SocialProfile, User, UserIdentity, UserRole, Video,
                      VideoCoin, VideoComment, VideoDecision, VideoLike, VideoNotInterested,
                      VideoPart, VideoReport, VideoShare, VideoStatDay, VideoUserSetting,
                      VideoViewDay, WatchHistory, WatchLater)
from ..state_machine import TransitionError
from . import storage
from . import video_state as vs
from .rt_events import after_commit, append_user_event
from .social import display_name, ensure_profile, privacy_of, rule_allows

logger = logging.getLogger("superz.video")

# ---------------- 常量(公开写进 docs/VIDEO-API.md)----------------

#: 分区
ZONES: dict[str, str] = {
    "life": "生活", "food": "美食", "shop_visit": "探店", "game": "游戏", "knowledge": "知识",
    "tech": "科技", "music": "音乐", "dance": "舞蹈", "film": "影视", "animal": "动物圈",
    "sports": "运动", "car": "汽车", "fashion": "时尚", "funny": "搞笑", "travel": "旅行",
}

#: 原因代码(§5.11,审核、处罚、举报共用一张表)
REASON_CODES: dict[str, str] = {
    "C101": "骚扰、辱骂", "C102": "垃圾广告、引流", "C103": "诈骗", "C104": "色情、低俗",
    "C105": "暴力、血腥", "C106": "违法违规(赌博、毒品、枪支等)",
    "C107": "侵犯隐私(未经同意公开他人信息)", "C108": "冒充他人或官方", "C109": "未成年人不宜",
    "V201": "视频侵权(未经授权搬运)", "V202": "标题 / 封面与内容不符",
    "V203": "画质或内容不完整(黑屏、无声、静止)", "V204": "分区选错",
    "V205": "未声明合作(挂店铺却选了「无合作」)", "V206": "危险行为",
    "X999": "其他(必须写说明)",
}

TITLE_MAX = 80
DESC_MAX = 2000
TAGS_MAX = 10
TAG_MAX = 20
#: 单个视频最多 10 P(D8)
PARTS_MAX = 10
#: 每人每天最多建 10 个稿件(D8)
DAILY_CREATE_MAX = 10
#: 硬币(D13):投稿过审 +2,每天从过审拿到的最多 10 枚;每日首次 +1
APPROVAL_COINS = 2
APPROVAL_DAILY_CAP = 10
DAILY_COINS = 1
#: 每个视频每人最多投几枚:自制 2、转载 1
COIN_MAX = {"original": 2, "repost": 1}
#: 硬币流水的全部原因(S4:只有前两个会「凭空」产生硬币,后两个是转手)
COIN_REASONS = {"daily": "每日首次打开视频", "video_approved": "投稿过审",
                "coin_give": "投币", "coin_receive": "收到投币"}
MINTING_REASONS = ("daily", "video_approved")
#: 删除的稿件 30 天后清媒体(§5.8)
PURGE_AFTER = timedelta(days=30)

PUBLIC_BASE = "https://chaojizan.cc"

#: 内容字段:已发布的稿件改了要重新审核(§5.8)
CONTENT_FIELDS = ("title", "description", "zone", "tags", "copyright", "source_url", "shop_id",
                  "shop_collab", "cover_media_id")
#: 设置字段:改了立即生效
SETTING_FIELDS = ("visibility", "allow_danmaku", "allow_comments", "scheduled_at")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def bj_day(now: datetime | None = None) -> date:
    """北京日期。用户说的「今天」是北京的今天。"""
    return ((now or utcnow()) + timedelta(hours=8)).date()


def bj_midnight(day: date) -> datetime:
    """北京某天零点对应的 UTC 时刻。"""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(hours=8)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def new_vid() -> str:
    """`sv` + 10 位 base58 随机(D19):不暴露投稿量,也不冒用 BV 号。"""
    return "sv" + "".join(secrets.choice(_B58) for _ in range(10))


VID_RE = re.compile(r"^sv[1-9A-HJ-NP-Za-km-z]{10}$")


def reason_ok(code: str, note: str) -> None:
    """处罚、驳回必须带原因代码;选 X999 必须写说明(S6)。"""
    if code not in REASON_CODES:
        raise HTTPException(422, "原因代码不存在(见 §5.11)")
    if code == "X999" and len((note or "").strip()) < 5:
        raise HTTPException(422, "选「X999 其他」必须写明原因(至少 5 个字)")


# ---------------- 判权 ----------------

def is_admin(user: User | None) -> bool:
    return user is not None and user.role == UserRole.admin


def can_view(v: Video | None, user: User | None) -> bool:
    """这个人能不能看这个稿件(D10:审核中只有 UP 主和审核员能看)。"""
    if v is None or v.deleted_at is not None or v.status == "deleted":
        return False
    if user is not None and (user.id == v.uploader_id or is_admin(user)):
        return True
    return v.status == "published" and v.visibility in ("public", "unlisted")


def listed(v: Video) -> bool:
    """出现在推荐、搜索、空间里:已发布、公开、没删。unlisted 只能拿链接看。"""
    return v.status == "published" and v.visibility == "public" and v.deleted_at is None


def is_live(v: Video) -> bool:
    """有线上版本(再改就要走待审)。"""
    return v.status in vs.LIVE_STATUSES


async def get_video(db: AsyncSession, vid: str, *, lock: bool = False) -> Video:
    if not VID_RE.fullmatch(vid or ""):
        raise HTTPException(404, "视频不存在或已删除")
    q = select(Video).where(Video.vid == vid)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    v = await db.scalar(q)
    if v is None or v.deleted_at is not None:
        raise HTTPException(404, "视频不存在或已删除")
    return v


async def viewable(db: AsyncSession, vid: str, user: User | None, *, lock: bool = False) -> Video:
    v = await get_video(db, vid, lock=lock)
    if not can_view(v, user):
        # 没有、没权限、还在审 —— 一律 404,不告诉你「有这个视频但你看不了」
        raise HTTPException(404, "视频不存在或已删除")
    return v


async def own_video(db: AsyncSession, vid: str, user: User, *, lock: bool = True) -> Video:
    v = await get_video(db, vid, lock=lock)
    if v.uploader_id != user.id:
        raise HTTPException(404, "视频不存在或已删除")
    return v


async def require_realname(db: AsyncSession, user: User) -> None:
    """发视频要完成实名认证(D11)。聊天、评论、弹幕只需要手机号账号。"""
    ok = await db.scalar(select(UserIdentity.id).where(UserIdentity.user_id == user.id))
    if ok is None:
        raise HTTPException(403, "发视频要先完成实名认证(我的 → 设置 → 实名认证)")


# ---------------- 人和卡片 ----------------

async def people(db: AsyncSession, viewer_id: int | None, ids) -> dict[int, dict]:
    """一批人的简卡(UP 主、评论作者、互动消息里的人)。**不含手机号**(S2)。

    头像按对方的隐私「谁能看到我的头像」过滤;对方拉黑了我的,头像不给(S7)。
    """
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))}
    profiles = {p.user_id: p for p in await db.scalars(
        select(SocialProfile).where(SocialProfile.user_id.in_(ids)))}
    they_have_me: set[int] = set()
    blocked_me: set[int] = set()
    if viewer_id:
        they_have_me = set(await db.scalars(select(SocialContact.owner_id).where(
            SocialContact.owner_id.in_(ids), SocialContact.contact_id == viewer_id)))
        blocked_me = set(await db.scalars(select(SocialBlock.user_id).where(
            SocialBlock.user_id.in_(ids), SocialBlock.blocked_id == viewer_id)))
    out: dict[int, dict] = {}
    for uid in ids:
        u = users.get(uid)
        if u is None:
            continue
        p = profiles.get(uid)
        gone = u.deleted_at is not None
        avatar_ok = not gone and (uid == viewer_id or (
            uid not in blocked_me and rule_allows(
                privacy_of(p)["avatar"], same=False, viewer_is_contact=uid in they_have_me,
                blocked=False)))
        out[uid] = {"id": uid, "name": "已注销用户" if gone else display_name(u),
                    "username": None if gone or p is None else p.username,
                    "avatar": (u.avatar_url or "") if avatar_ok else ""}
    return out


def video_brief(v: Video) -> dict:
    """互动消息、流水里引用视频用的最小形状。"""
    return {"vid": v.vid, "title": v.title, "cover": v.cover_url or ""}


def card(v: Video, up: dict | None) -> dict:
    """视频卡片(推荐 / 热门 / 搜索 / 空间 / 收藏 / 历史共用一个形状)。"""
    return {
        "vid": v.vid,
        "title": v.title,
        "cover": v.cover_url or "",
        "duration_ms": v.duration_ms,
        "is_vertical": v.is_vertical,
        "zone": v.zone,
        "zone_name": ZONES.get(v.zone, ""),
        "tags": list(v.tags or []),
        "views": v.views,
        "likes": v.likes,
        "coins": v.coins,
        "favorites": v.favorites,
        "shares": v.shares,
        "danmaku_count": v.danmaku_count,
        "comment_count": v.comment_count,
        "published_at": iso(v.published_at),
        "collab": bool(v.shop_id and v.shop_collab),
        "uploader": up or {"id": v.uploader_id, "name": "", "username": None, "avatar": ""},
    }


async def cards(db: AsyncSession, viewer_id: int | None, videos: list[Video]) -> list[dict]:
    ups = await people(db, viewer_id, [v.uploader_id for v in videos])
    return [card(v, ups.get(v.uploader_id)) for v in videos]


# ---------------- 播放地址(带绑定用户的签名)----------------
#
# 网页版的 <video> 带不了 Authorization 头 —— 和媒体下载地址同一个办法(services/media.signed_url):
# 地址带 `?u=<用户>&e=<到期>&s=<签名>`,签名绑定用户,**播放时照样按这个用户重新判权**,
# 稿件删了、下架了、改成私密了,旧地址立刻失效。签名不含清晰度,切清晰度不用重新签。
# 公开稿件没登录也能看:不带签名的地址对公开稿件直接放行。

def _vod_key() -> bytes:
    return hashlib.sha256(f"superz-vod-url:{settings.jwt_secret}".encode()).digest()


def vod_sig(vid: str, part_id: int, user_id: int, exp: int) -> str:
    return hmac.new(_vod_key(), f"{vid}:{part_id}:{user_id}:{exp}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def check_vod_sig(vid: str, part_id: int, user_id: int, exp: int, sig: str) -> bool:
    import time
    if exp < time.time():
        return False
    return hmac.compare_digest(vod_sig(vid, part_id, user_id, exp), sig or "")


def vod_query(vid: str, part_id: int, viewer_id: int | None) -> str:
    if not viewer_id:
        return ""
    from .media import url_expiry
    exp = url_expiry()
    return f"?u={viewer_id}&e={exp}&s={vod_sig(vid, part_id, viewer_id, exp)}"


def part_out(v: Video, p: VideoPart, viewer_id: int | None) -> dict:
    q = vod_query(v.vid, p.id, viewer_id)
    base = f"/video/v1/vod/{v.vid}/{p.id}"
    sp = p.sprite or None
    return {
        "id": p.id, "idx": p.idx, "title": p.title, "status": p.status,
        "duration_ms": p.duration_ms, "w": p.w, "h": p.h,
        "renditions": [{"q": r["q"], "w": r["w"], "h": r["h"], "size": r.get("size", 0),
                        "bitrate": r.get("bitrate", 0), "url": f"{base}/{r['q']}.mp4{q}"}
                       for r in (p.renditions or [])],
        "sprite": {"interval_ms": sp["interval_ms"], "cols": sp["cols"], "rows": sp["rows"],
                   "w": sp["w"], "h": sp["h"], "count": sp["count"],
                   "urls": [f"{base}/sprite/{i}.jpg{q}" for i in range(len(sp["keys"]))]}
        if sp else None,
    }


async def parts_of(db: AsyncSession, v: Video) -> list[VideoPart]:
    return list(await db.scalars(select(VideoPart).where(VideoPart.video_id == v.id)
                                 .order_by(VideoPart.idx, VideoPart.id)))


def live_parts(parts: list[VideoPart]) -> list[VideoPart]:
    return [p for p in parts if p.live]


def version_parts(v: Video, parts: list[VideoPart]) -> list[VideoPart]:
    """「下一版」的分 P:还没发布过的稿件是全部;已发布的是待审清单(没动过分 P 就是线上那几 P)。"""
    if not is_live(v) and v.status != "removed":
        return parts
    by_id = {p.id: p for p in parts}
    pc = v.pending_changes or {}
    if "parts" in pc:
        return [by_id[int(x["id"])] for x in pc["parts"] if int(x["id"]) in by_id]
    return live_parts(parts)


def visible_parts(v: Video, parts: list[VideoPart], user: User | None) -> list[VideoPart]:
    """详情页给这个人看哪几 P:有线上版本的给线上那几 P(UP 主自己也一样,改动在创作中心看);
    从没发布过的只有 UP 主和审核员看得到,给全部。"""
    lives = live_parts(parts)
    if lives or v.status in ("published", "scheduled", "removed"):
        return lives
    if user is not None and (user.id == v.uploader_id or is_admin(user)):
        return parts
    return []


async def shop_card(db: AsyncSession, shop_id: int | None) -> dict | None:
    if not shop_id:
        return None
    m = await db.get(Merchant, shop_id)
    if m is None:
        return None
    return {"id": m.id, "name": m.name, "logo": m.logo_url or ""}


async def follow_counts(db: AsyncSession, user_id: int) -> tuple[int, int]:
    fans = await db.scalar(select(func.count()).select_from(Follow)
                           .where(Follow.followee_id == user_id))
    following = await db.scalar(select(func.count()).select_from(Follow)
                                .where(Follow.follower_id == user_id))
    return int(fans or 0), int(following or 0)


async def detail(db: AsyncSession, v: Video, viewer: User | None) -> dict:
    """视频详情(#361)。播放地址按看的人签好。"""
    parts = await parts_of(db, v)
    vid_parts = visible_parts(v, parts, viewer)
    viewer_id = viewer.id if viewer is not None else None
    ups = await people(db, viewer_id, [v.uploader_id])
    up = dict(ups.get(v.uploader_id) or {"id": v.uploader_id, "name": "", "username": None,
                                         "avatar": ""})
    fans, _ = await follow_counts(db, v.uploader_id)
    up["fans"] = fans
    up["followed"] = bool(viewer_id and await db.get(Follow, (viewer_id, v.uploader_id)))
    out = card(v, up)
    out.update({
        "description": v.description,
        "copyright": v.copyright,
        "source_url": v.source_url,
        "status": v.status,
        "status_label": vs.STATUS_LABELS.get(v.status, v.status),
        "visibility": v.visibility,
        "allow_danmaku": v.allow_danmaku,
        "allow_comments": v.allow_comments,
        "shop": await shop_card(db, v.shop_id),
        "shop_collab": v.shop_collab,
        "link": f"{PUBLIC_BASE}/v/{v.vid}",
        "parts": [part_out(v, p, viewer_id) for p in vid_parts],
        "is_owner": viewer_id == v.uploader_id,
        "me": await my_state(db, viewer_id, v) if viewer_id else None,
    })
    return out


async def my_state(db: AsyncSession, user_id: int, v: Video) -> dict:
    liked = await db.get(VideoLike, (v.id, user_id)) is not None
    coin = await db.get(VideoCoin, (v.id, user_id))
    folders = list(await db.scalars(select(FavItem.folder_id).where(
        FavItem.user_id == user_id, FavItem.video_id == v.id)))
    later = await db.get(WatchLater, (user_id, v.id)) is not None
    h = await db.get(WatchHistory, (user_id, v.id))
    prof = await db.get(SocialProfile, user_id)
    return {"liked": liked, "coins": coin.amount if coin else 0,
            "coin_max": COIN_MAX.get(v.copyright, 1), "favorited": bool(folders),
            "folder_ids": sorted(folders), "watch_later": later,
            "coin_balance": prof.coins if prof else 0,
            "progress": {"part_idx": h.part_idx, "position_ms": h.position_ms,
                         "duration_ms": h.duration_ms, "watched_at": iso(h.watched_at)}
            if h else None}


# ---------------- 创作中心的视图 ----------------

def pending_out(v: Video) -> dict | None:
    pc = v.pending_changes
    if not pc:
        return None
    return {"state": pc.get("state"),
            "state_label": vs.PENDING_LABELS.get(pc.get("state"), ""),
            "fields": pc.get("fields") or {},
            "parts": pc.get("parts"),
            "submitted_at": pc.get("submitted_at"),
            "reject_code": pc.get("reject_code", ""),
            "reject_label": REASON_CODES.get(pc.get("reject_code", ""), ""),
            "reject_note": pc.get("reject_note", ""),
            "fail_reason": pc.get("fail_reason", "")}


def creator_card(v: Video) -> dict:
    """创作中心稿件列表的一行。"""
    out = card(v, None)
    out.pop("uploader")
    out.update({
        "status": v.status,
        "status_label": vs.STATUS_LABELS.get(v.status, v.status),
        "visibility": v.visibility,
        "reject_code": v.reject_code,
        "reject_label": REASON_CODES.get(v.reject_code, ""),
        "reject_note": v.reject_note,
        "fail_reason": v.fail_reason,
        "scheduled_at": iso(v.scheduled_at),
        "submitted_at": iso(v.submitted_at),
        "created_at": iso(v.created_at),
        "pending": pending_out(v),
    })
    return out


def _cover_preview(media_id: int | None, viewer_id: int) -> str | None:
    if not media_id:
        return None
    from .media import signed_url
    return signed_url(media_id, viewer_id)


async def creator_detail(db: AsyncSession, v: Video, viewer: User) -> dict:
    """UP 主(和审核员)看的完整稿件:线上版本 + 待审改动 + 每 P 的转码状态 + 审核记录。"""
    parts = await parts_of(db, v)
    out = creator_card(v)
    out.update({
        "description": v.description, "copyright": v.copyright, "source_url": v.source_url,
        "allow_danmaku": v.allow_danmaku, "allow_comments": v.allow_comments,
        "shop": await shop_card(db, v.shop_id), "shop_id": v.shop_id,
        "shop_collab": v.shop_collab,
        "cover_media_id": v.cover_media_id,
        "cover_preview": v.cover_url or _cover_preview(v.cover_media_id, viewer.id),
        "link": f"{PUBLIC_BASE}/v/{v.vid}",
        "parts": [{**part_out(v, p, viewer.id), "live": p.live, "error": p.error,
                   "cover_candidates": [{"media_id": m, "url": _cover_preview(m, viewer.id)}
                                        for m in (p.cover_media_ids or [])]}
                  for p in parts],
        "version_part_ids": [p.id for p in version_parts(v, parts)],
        "decisions": await decisions_out(db, v, for_admin=is_admin(viewer)),
    })
    pc = out["pending"]
    if pc and pc["fields"].get("cover_media_id"):
        pc["cover_preview"] = _cover_preview(pc["fields"]["cover_media_id"], viewer.id)
    return out


DECISION_LABELS = {
    "approve": "审核通过", "reject": "驳回", "approve_changes": "改动审核通过",
    "reject_changes": "改动被驳回", "remove": "下架", "appeal": "申诉",
    "appeal_upheld": "申诉维持原结论", "appeal_overturned": "申诉成立,已撤销原结论",
}
APPEALABLE = ("reject", "reject_changes", "remove")


async def decisions_out(db: AsyncSession, v: Video, *, for_admin: bool) -> list[dict]:
    rows = list(await db.scalars(select(VideoDecision).where(VideoDecision.video_id == v.id)
                                 .order_by(VideoDecision.id)))
    appealed = {d.appeal_of for d in rows if d.action == "appeal"}
    resolved = {d.appeal_of for d in rows if d.action in ("appeal_upheld", "appeal_overturned")}
    out = []
    for d in rows:
        item = {"id": d.id, "action": d.action, "action_label": DECISION_LABELS.get(d.action, ""),
                "reason_code": d.reason_code, "reason_label": REASON_CODES.get(d.reason_code, ""),
                "note": d.note, "appeal_of": d.appeal_of, "created_at": iso(d.created_at),
                "can_appeal": d.action in APPEALABLE and d.id not in appealed,
                "appeal_state": ("resolved" if d.id in resolved else "open")
                if d.action == "appeal" else None}
        if for_admin:
            item["note_internal"] = d.note_internal
            item["actor_id"] = d.actor_id
        out.append(item)
    return out


async def emit_video_event(db: AsyncSession, v: Video) -> None:
    """稿件状态变了,告诉 UP 主的所有设备(创作中心实时刷新)。"""
    await append_user_event(db, v.uploader_id, "video",
                            {"vid": v.vid, "status": v.status,
                             "status_label": vs.STATUS_LABELS.get(v.status, v.status),
                             "pending": (v.pending_changes or {}).get("state"),
                             "fail_reason": v.fail_reason, "reject_code": v.reject_code})


def _transition(v: Video, target: str, role: str) -> None:
    try:
        vs.transition(v, target, role)
    except TransitionError as e:
        raise HTTPException(403 if e.forbidden else 409, e.message) from e


def _pending(v: Video, target: str | None, role: str, **extra) -> None:
    try:
        vs.set_pending_state(v, target, role, **extra)
    except TransitionError as e:
        raise HTTPException(403 if e.forbidden else 409, e.message) from e


# ---------------- 投稿:建稿、改稿、分 P、提交 ----------------

_URL_RE = re.compile(r"^https?://[^\s]{3,290}$")


async def clean_fields(db: AsyncSession, user: User, body: dict,
                       v: Video | None = None) -> dict:
    """校验客户端送来的字段(只处理送了的)。返回规范化之后的值。"""
    out: dict = {}
    if "title" in body and body["title"] is not None:
        t = " ".join(str(body["title"]).split())
        if len(t) > TITLE_MAX:
            raise HTTPException(422, f"标题最多 {TITLE_MAX} 字")
        out["title"] = t
    if "description" in body and body["description"] is not None:
        d = str(body["description"]).strip()
        if len(d) > DESC_MAX:
            raise HTTPException(422, f"简介最多 {DESC_MAX} 字")
        out["description"] = d
    if "zone" in body and body["zone"] is not None:
        if body["zone"] not in ZONES:
            raise HTTPException(422, "没有这个分区")
        out["zone"] = body["zone"]
    if "tags" in body and body["tags"] is not None:
        tags = []
        for t in body["tags"]:
            t = str(t).strip().lstrip("#")
            if not t:
                continue
            if len(t) > TAG_MAX:
                raise HTTPException(422, f"每个标签最多 {TAG_MAX} 字")
            if t not in tags:
                tags.append(t)
        if len(tags) > TAGS_MAX:
            raise HTTPException(422, f"标签最多 {TAGS_MAX} 个")
        out["tags"] = tags
    if "copyright" in body and body["copyright"] is not None:
        if body["copyright"] not in COIN_MAX:
            raise HTTPException(422, "请选择自制或转载")
        out["copyright"] = body["copyright"]
    if "source_url" in body and body["source_url"] is not None:
        s = str(body["source_url"]).strip()
        if s and not _URL_RE.fullmatch(s):
            raise HTTPException(422, "转载来源要填 http(s) 开头的链接")
        out["source_url"] = s
    if "visibility" in body and body["visibility"] is not None:
        if body["visibility"] not in ("public", "unlisted", "private"):
            raise HTTPException(422, "可见性只能是 公开 / 不公开(仅链接可看)/ 私密")
        out["visibility"] = body["visibility"]
    for k in ("allow_danmaku", "allow_comments"):
        if k in body and body[k] is not None:
            out[k] = bool(body[k])
    if "shop_id" in body:
        sid = body["shop_id"]
        if sid:
            m = await db.get(Merchant, int(sid))
            if m is None or m.status != MerchantStatus.approved:
                raise HTTPException(422, "只能挂本平台正常营业的店铺")
            out["shop_id"] = m.id
        else:
            out["shop_id"] = None
            out["shop_collab"] = None
    if "shop_collab" in body and "shop_collab" not in out:
        out["shop_collab"] = None if body["shop_collab"] is None else bool(body["shop_collab"])
    if "scheduled_at" in body:
        at = body["scheduled_at"]
        if at:
            if isinstance(at, str):
                try:
                    at = datetime.fromisoformat(at.replace("Z", "+00:00"))
                except ValueError as e:
                    raise HTTPException(422, "定时发布时间格式不对") from e
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            now = utcnow()
            if at < now + timedelta(minutes=5) or at > now + timedelta(days=30):
                raise HTTPException(422, "定时发布要设在 5 分钟之后、30 天之内")
            out["scheduled_at"] = at
        else:
            out["scheduled_at"] = None
    if "cover_media_id" in body:
        mid = body["cover_media_id"]
        if mid:
            mf = await db.get(MediaFile, int(mid))
            if (mf is None or mf.owner_id != user.id or mf.kind != "cover"
                    or mf.purpose != "video" or mf.status != "ready"):
                raise HTTPException(422, "封面要用自己上传的封面图,或者自动截取的三帧之一")
            out["cover_media_id"] = mf.id
        else:
            out["cover_media_id"] = None
    # 内容审核:标题、简介、标签都过屏蔽词(#369)
    from .moderation import guard_text
    if out.get("title"):
        await guard_text(db, out["title"], "标题")
    if out.get("description"):
        await guard_text(db, out["description"], "简介")
    for t in out.get("tags") or []:
        await guard_text(db, t, "标签")
    return out


def _json_field(k: str, val):
    if isinstance(val, datetime):
        return val.isoformat()
    return val


async def create_draft(db: AsyncSession, user: User, body: dict) -> Video:
    """建稿件(草稿)。每人每天最多 10 个(D8),要实名(D11)。"""
    await require_realname(db, user)
    since = bj_midnight(bj_day())
    n = await db.scalar(select(func.count()).select_from(Video).where(
        Video.uploader_id == user.id, Video.created_at >= since))
    if (n or 0) >= DAILY_CREATE_MAX:
        raise HTTPException(429, f"每人每天最多投稿 {DAILY_CREATE_MAX} 个,明天再来")
    fields = await clean_fields(db, user, body)
    for _ in range(5):
        vid = new_vid()
        if await db.scalar(select(Video.id).where(Video.vid == vid)) is None:
            break
    v = Video(vid=vid, uploader_id=user.id, status="draft", tags=[], views=0, likes=0, coins=0,
              favorites=0, shares=0, danmaku_count=0, comment_count=0, title="", description="",
              zone="", copyright="original", source_url="", visibility="public",
              allow_danmaku=True, allow_comments=True, cover_url="", reject_code="",
              reject_note="", fail_reason="", is_vertical=False, duration_ms=0,
              created_at=utcnow())
    for k, val in fields.items():
        setattr(v, k, val)
    db.add(v)
    await db.flush()
    return v


async def edit(db: AsyncSession, user: User, v: Video, body: dict) -> None:
    """改稿。没发布过的直接改;已发布的内容改动进待审(线上不变),设置立即生效。"""
    if v.status in ("removed", "deleted"):
        raise HTTPException(409, "稿件已下架,不能修改;有异议可以申诉")
    fields = await clean_fields(db, user, body, v)
    parts_body = body.get("parts")
    content = {k: fields[k] for k in CONTENT_FIELDS if k in fields}
    settings_ = {k: fields[k] for k in SETTING_FIELDS if k in fields}
    if "scheduled_at" in settings_ and v.status == "published":
        raise HTTPException(409, "已经发布了,不能再设定时发布")
    if v.status == "scheduled" and "scheduled_at" in settings_ and settings_["scheduled_at"] is None:
        # 过审了在等定时发布,又把时间清掉 = 现在就发。不能真清成空:清扫按时间推进,空的永远等不到
        settings_["scheduled_at"] = utcnow()
    busy_unpublished = v.status in ("processing", "reviewing")
    busy_pending = vs.pending_state(v) in ("processing", "reviewing")
    if (content or parts_body is not None) and (busy_unpublished or busy_pending):
        raise HTTPException(409, "稿件正在转码 / 审核,等结果出来再改")
    for k, val in settings_.items():
        setattr(v, k, val)
    if not content and parts_body is None:
        return
    parts = await parts_of(db, v)
    if parts_body is not None:
        wanted = _clean_parts_order(parts_body, parts)
    if is_live(v):
        pc = dict(v.pending_changes or {})
        if vs.pending_state(v) is None or vs.pending_state(v) in ("rejected", "failed"):
            _pending(v, "editing", "uploader")
            pc = dict(v.pending_changes)
        merged = dict(pc.get("fields") or {})
        for k, val in content.items():
            # 改回和线上一样的值 = 这一项不算改动
            if _json_field(k, val) == _json_field(k, getattr(v, k)):
                merged.pop(k, None)
            else:
                merged[k] = _json_field(k, val)
        pc["fields"] = merged
        if parts_body is not None:
            pc["parts"] = wanted
        if not merged and "parts" not in pc:
            _pending(v, None, "uploader")   # 全改回去了 = 没有改动
            return
        vs.store_pending(v, pc)
        return
    # 还没发布过:直接改
    if v.status in ("rejected", "failed"):
        _transition(v, "draft", "uploader")
    for k, val in content.items():
        setattr(v, k, val)
    if parts_body is not None:
        by_id = {p.id: p for p in parts}
        for i, x in enumerate(wanted):
            p = by_id[x["id"]]
            p.idx = i
            if x.get("title"):
                p.title = x["title"]
        _derive(v, [by_id[x["id"]] for x in wanted])


def _clean_parts_order(parts_body, parts: list[VideoPart]) -> list[dict]:
    """PATCH 里的 parts:[{"id": …, "title": …}],给出下一版全部分 P 的顺序和标题。"""
    by_id = {p.id: p for p in parts}
    out, seen = [], set()
    for x in parts_body:
        try:
            pid = int(x["id"])
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, "分 P 清单格式不对") from e
        if pid not in by_id or pid in seen:
            raise HTTPException(422, "分 P 清单里有不属于这个稿件的分 P")
        seen.add(pid)
        title = " ".join(str(x.get("title") or by_id[pid].title).split())[:TITLE_MAX]
        out.append({"id": pid, "title": title})
    if not out:
        raise HTTPException(422, "至少要有 1 P")
    if len(out) > PARTS_MAX:
        raise HTTPException(422, f"一个视频最多 {PARTS_MAX} P")
    missing = [p for p in parts if p.id not in seen and not p.live]
    if missing and not any(p.live for p in parts):
        raise HTTPException(422, "清单里要列出全部分 P(删分 P 请用删除接口)")
    return out


def _derive(v: Video, parts: list[VideoPart]) -> None:
    """竖屏判定以第一 P 为准(宽 < 高);时长是各 P 之和。"""
    ready = [p for p in parts if p.status == "ready"]
    if parts and parts[0].status == "ready" and parts[0].w and parts[0].h:
        v.is_vertical = parts[0].w < parts[0].h
    v.duration_ms = sum(p.duration_ms for p in ready)


async def add_part(db: AsyncSession, user: User, v: Video, media_id: int, title: str) -> VideoPart:
    """加一 P:原片先用媒体接口传好(purpose=video, kind=video_source),这里挂上并开始转码。"""
    if v.status in ("processing", "reviewing") or vs.pending_state(v) in ("processing",
                                                                          "reviewing"):
        raise HTTPException(409, "稿件正在转码 / 审核,等结果出来再加分 P")
    if v.status in ("removed", "deleted"):
        raise HTTPException(409, "稿件已下架,不能修改")
    mf = await db.get(MediaFile, media_id)
    if (mf is None or mf.owner_id != user.id or mf.kind != "video_source"
            or mf.purpose != "video" or mf.status != "ready"):
        raise HTTPException(422, "要先用媒体接口上传视频原片(purpose=video,kind=video_source)")
    used = await db.scalar(select(VideoPart.id).where(VideoPart.source_media_id == media_id))
    if used is not None:
        raise HTTPException(409, "这个文件已经用过了,重新上传一份")
    parts = await parts_of(db, v)
    if len(version_parts(v, parts)) >= PARTS_MAX:
        raise HTTPException(422, f"一个视频最多 {PARTS_MAX} P")
    title = " ".join((title or "").split())[:TITLE_MAX] or \
        (mf.name.rsplit(".", 1)[0][:TITLE_MAX] if mf.name else "")
    p = VideoPart(video_id=v.id, idx=(max((x.idx for x in parts), default=-1) + 1),
                  title=title or f"P{len(parts) + 1}", source_media_id=mf.id,
                  status="processing", error="", renditions=[], cover_media_ids=[], live=False,
                  duration_ms=mf.duration_ms, w=mf.w, h=mf.h, created_at=utcnow())
    db.add(p)
    await db.flush()
    if is_live(v):
        if vs.pending_state(v) is None or vs.pending_state(v) in ("rejected", "failed"):
            _pending(v, "editing", "uploader")
        pc = dict(v.pending_changes)
        cur = pc.get("parts") or [{"id": x.id, "title": x.title} for x in live_parts(parts)]
        pc["parts"] = [*cur, {"id": p.id, "title": p.title}]
        vs.store_pending(v, pc)
    elif v.status in ("rejected", "failed"):
        _transition(v, "draft", "uploader")
    from ..workers.media import enqueue_after_commit
    enqueue_after_commit(db, {"type": "video_part", "part_id": p.id})
    return p


async def remove_part(db: AsyncSession, v: Video, part: VideoPart) -> None:
    if v.status in ("processing", "reviewing") or vs.pending_state(v) in ("processing",
                                                                          "reviewing"):
        raise HTTPException(409, "稿件正在转码 / 审核,等结果出来再删分 P")
    if v.status in ("removed", "deleted"):
        raise HTTPException(409, "稿件已下架,不能修改")
    parts = await parts_of(db, v)
    if is_live(v):
        cur = (v.pending_changes or {}).get("parts") or \
            [{"id": x.id, "title": x.title} for x in live_parts(parts)]
        rest = [x for x in cur if int(x["id"]) != part.id]
        if not rest:
            raise HTTPException(422, "至少要留 1 P;不想要这个视频了可以删除整个稿件")
        if vs.pending_state(v) is None or vs.pending_state(v) in ("rejected", "failed"):
            _pending(v, "editing", "uploader")
        pc = dict(v.pending_changes)
        pc["parts"] = rest
        vs.store_pending(v, pc)
        if not part.live:  # 新加还没过审的:直接删
            await _drop_parts(db, [part])
        return
    if v.status in ("rejected", "failed"):
        _transition(v, "draft", "uploader")
    await _drop_parts(db, [part])
    rest = [p for p in parts if p.id != part.id]
    for i, p in enumerate(rest):
        p.idx = i
    _derive(v, rest)


def _part_objects(p: VideoPart) -> list[tuple[str, bool]]:
    keys = [(r["key"], True) for r in (p.renditions or []) if r.get("key")]
    keys += [(k, True) for k in ((p.sprite or {}).get("keys") or [])]
    return keys


def _media_objects(mf: MediaFile) -> list[tuple[str, bool]]:
    out = [(k, mf.private) for k in (mf.key, mf.thumb_key) if k]
    src = (mf.meta or {}).get("source_key")
    if src and src != mf.key:
        out.append((src, mf.private))
    return out


def remove_objects_after_commit(db: AsyncSession, objs: list[tuple[str, bool]]) -> None:
    """对象存储里的文件在**提交之后**再删:事务回滚了文件还在,不会出现「库里有、文件没了」。"""
    objs = [o for o in objs if o[0]]
    if not objs:
        return

    async def _rm():
        for key, private in objs:
            try:
                await asyncio.to_thread(storage.remove, key, private)
            except Exception:
                logger.warning("删除对象失败 %s", key, exc_info=True)

    after_commit(db, _rm)


async def _drop_parts(db: AsyncSession, parts: list[VideoPart]) -> None:
    """删分 P:行(弹幕随外键级联)、转码产物、原片和封面候选的媒体行。"""
    objs: list[tuple[str, bool]] = []
    media_ids: list[int] = []
    for p in parts:
        objs += _part_objects(p)
        media_ids += [m for m in (p.cover_media_ids or []) if m]
        if p.source_media_id:
            media_ids.append(p.source_media_id)
    if media_ids:
        for mf in await db.scalars(select(MediaFile).where(MediaFile.id.in_(media_ids))):
            objs += _media_objects(mf)
        await db.execute(delete(MediaFile).where(MediaFile.id.in_(media_ids)))
    for p in parts:
        await db.delete(p)
    remove_objects_after_commit(db, objs)


async def discard_changes(db: AsyncSession, v: Video) -> None:
    """放弃已发布稿件的改动:线上版本本来就没动过,清掉改动、删掉为改动新传的分 P。"""
    if not is_live(v) or v.pending_changes is None:
        raise HTTPException(409, "没有改动可以放弃")
    if vs.pending_state(v) == "reviewing":
        raise HTTPException(409, "改动正在审核,不能撤回")
    _pending(v, None, "uploader")
    await _drop_parts(db, [p for p in await parts_of(db, v) if not p.live])


def _check_submittable(fields: dict, parts: list[VideoPart]) -> None:
    if not (fields.get("title") or "").strip():
        raise HTTPException(422, "标题不能为空")
    if fields.get("zone") not in ZONES:
        raise HTTPException(422, "请选择分区")
    if fields.get("copyright") == "repost" and not fields.get("source_url"):
        raise HTTPException(422, "转载要填写来源链接")
    if fields.get("shop_id") and fields.get("shop_collab") is None:
        raise HTTPException(422, "挂了店铺就要选「与商家有无合作」(D16)")
    if not parts:
        raise HTTPException(422, "至少要有 1 P")
    for p in parts:
        if p.status == "failed":
            raise HTTPException(422, f"「{p.title}」转码失败:{p.error or '原因未知'}。删掉重新上传")


async def submit(db: AsyncSession, user: User, v: Video) -> None:
    """提交审核。转码没完的先进 processing,全部就绪自动进 reviewing(§5.8)。"""
    from .sanctions import check_user
    await check_user(db, user.id, "video_submit")   # 封号期间不能投稿(#368)
    now = utcnow()
    parts = await parts_of(db, v)
    if is_live(v):
        if vs.pending_state(v) != "editing":
            raise HTTPException(409, "没有需要提交的改动" if vs.pending_state(v) is None
                                else "改动已经提交了")
        pc = v.pending_changes or {}
        merged = {k: getattr(v, k) for k in CONTENT_FIELDS}
        merged.update(pc.get("fields") or {})
        ver = version_parts(v, parts)
        _check_submittable(merged, ver)
        if all(p.status == "ready" for p in ver):
            _pending(v, "reviewing", "uploader", submitted_at=now.isoformat())
        else:
            _pending(v, "processing", "uploader", submitted_at=now.isoformat())
        v.submitted_at = now
        await emit_video_event(db, v)
        return
    if v.status not in ("draft", "rejected", "failed"):
        raise HTTPException(409, f"稿件{vs.STATUS_LABELS.get(v.status, v.status)},不能提交")
    fields = {k: getattr(v, k) for k in CONTENT_FIELDS}
    _check_submittable(fields, parts)
    if v.status != "draft":
        _transition(v, "draft", "uploader")
    _transition(v, "processing", "uploader")
    v.submitted_at = now
    v.reject_code, v.reject_note, v.fail_reason = "", "", ""
    await after_part_change(db, v, parts)
    await emit_video_event(db, v)


def _ensure_cover(v: Video, parts: list[VideoPart]) -> None:
    """没选封面的,用第一 P 自动截的第一帧(10% 处,#342)。"""
    if v.cover_media_id is None and parts and parts[0].cover_media_ids:
        v.cover_media_id = parts[0].cover_media_ids[0]


async def after_part_change(db: AsyncSession, v: Video,
                            parts: list[VideoPart] | None = None) -> None:
    """某 P 转码完了 / 失败了 / 被删了:看稿件(或待审改动)能不能往下走。调用方负责锁 v、提交。"""
    parts = parts if parts is not None else await parts_of(db, v)
    if not is_live(v) and v.status != "removed":
        _derive(v, parts)
    if v.status == "processing":
        failed = [p for p in parts if p.status == "failed"]
        if failed:
            p = failed[0]
            _transition(v, "failed", "system")
            v.fail_reason = f"「{p.title}」转码失败:{p.error or '原因未知'}"[:300]
            await _notify_system(db, v, "视频转码失败",
                                 f"你的视频《{v.title}》{v.fail_reason},删掉这一 P 重新上传后再提交",
                                 "failed")
        elif parts and all(p.status == "ready" for p in parts):
            _ensure_cover(v, parts)
            _transition(v, "reviewing", "system")
    elif vs.pending_state(v) == "processing":
        ver = version_parts(v, parts)
        failed = [p for p in ver if p.status == "failed"]
        if failed:
            _pending(v, "failed", "system",
                     fail_reason=f"「{failed[0].title}」转码失败:{failed[0].error or '原因未知'}"[:300])
        elif ver and all(p.status == "ready" for p in ver):
            _pending(v, "reviewing", "system")


# ---------------- 审核(#368)----------------

async def _notify_system(db: AsyncSession, v: Video, title: str, text: str, action: str,
                         reason_code: str = "", extra: dict | None = None) -> None:
    from .social_notify import system
    await system(db, v.uploader_id, title, text, video_id=v.id, action=action,
                 reason_code=reason_code, extra=extra)


def review_state(v: Video) -> str | None:
    """这个稿件在等哪种审核:first(从没发布过的一版)/ changes(已发布稿件的改动)/ None。"""
    if v.status == "reviewing":
        return "first"
    if is_live(v) and vs.pending_state(v) == "reviewing":
        return "changes"
    return None


async def publish_cover(db: AsyncSession, v: Video) -> None:
    """过审:把选中的封面复制到公开桶(/img/…)。审核中的封面只在私密桶里(D10)。"""
    if not v.cover_media_id:
        return
    mf = await db.get(MediaFile, v.cover_media_id)
    if mf is None or not mf.key:
        return
    data = await asyncio.to_thread(storage.read, mf.key, mf.private)
    if not data:
        return
    stored = await asyncio.to_thread(storage.save, data, ".jpg", "video_cover", v.uploader_id)
    old = v.cover_url
    v.cover_url = stored.url
    if old and old != stored.url:
        remove_objects_after_commit(db, [(old.removeprefix("/img/"), False)])


def unpublish_cover(db: AsyncSession, v: Video) -> None:
    """下架 / 删除:公开桶里的封面跟着删,旧地址立刻失效。"""
    if v.cover_url:
        remove_objects_after_commit(db, [(v.cover_url.removeprefix("/img/"), False)])
    v.cover_url = ""


async def _publish_first(db: AsyncSession, v: Video, role: str) -> None:
    """第一次过审(或申诉改判驳回):这一版的全部分 P 上线,封面进公开桶,到点公开。"""
    parts = await parts_of(db, v)
    for i, p in enumerate(parts):
        p.live = True
        p.idx = i
    _derive(v, parts)
    _ensure_cover(v, parts)
    await publish_cover(db, v)
    now = utcnow()
    if v.scheduled_at and v.scheduled_at > now:
        _transition(v, "scheduled", role)
    else:
        _transition(v, "published", role)
        v.published_at = v.published_at or now
    v.reject_code, v.reject_note = "", ""


async def _apply_pending(db: AsyncSession, v: Video, role: str) -> None:
    """已发布稿件的改动过审:搬到线上。线上那一版到这一刻才被替换。"""
    pc = v.pending_changes or {}
    fields = pc.get("fields") or {}
    cover_changed = "cover_media_id" in fields and fields["cover_media_id"] != v.cover_media_id
    for k in CONTENT_FIELDS:
        if k in fields:
            setattr(v, k, fields[k])
    parts = await parts_of(db, v)
    if "parts" in pc:
        by_id = {p.id: p for p in parts}
        keep = []
        for i, x in enumerate(pc["parts"]):
            p = by_id.get(int(x["id"]))
            if p is None:
                continue
            p.live, p.idx = True, i
            if x.get("title"):
                p.title = x["title"]
            keep.append(p)
        drop = [p for p in parts if p not in keep]
        if drop:
            await _drop_parts(db, drop)
        parts = keep
    else:
        parts = live_parts(parts)
    _derive(v, parts)
    if cover_changed or not v.cover_url:
        await publish_cover(db, v)
    _pending(v, None, role)


async def _record(db: AsyncSession, v: Video, action: str, actor: User | None, *,
                  reason_code: str = "", note: str = "", note_internal: str = "",
                  appeal_of: int | None = None,
                  submitted_at: datetime | None = None) -> VideoDecision:
    d = VideoDecision(video_id=v.id, action=action, reason_code=reason_code,
                      note=(note or "").strip()[:500], note_internal=(note_internal or "")[:500],
                      actor_id=actor.id if actor else None, appeal_of=appeal_of,
                      submitted_at=submitted_at, created_at=utcnow())
    db.add(d)
    await db.flush()
    return d


def _submitted_at(v: Video, kind: str) -> datetime | None:
    """这次审核对应的那次提交(审核时长 = 结论时间 − 它)。改动的提交时间记在 pending_changes 里。"""
    if kind == "first":
        return v.submitted_at
    raw = (v.pending_changes or {}).get("submitted_at")
    try:
        return datetime.fromisoformat(raw) if raw else v.submitted_at
    except (TypeError, ValueError):
        return v.submitted_at


async def decide(db: AsyncSession, v: Video, admin: User, *, approve: bool,
                 reason_code: str = "", note: str = "", note_internal: str = "") -> VideoDecision:
    """审核:通过 / 驳回。驳回必须带原因代码,X999 必须写说明(S6)。"""
    kind = review_state(v)
    if kind is None:
        raise HTTPException(409, "这个稿件不在审核中")
    if not approve:
        reason_ok(reason_code, note)
    sub = _submitted_at(v, kind)
    if kind == "first":
        if approve:
            await _publish_first(db, v, "admin")
            d = await _record(db, v, "approve", admin, note=note, note_internal=note_internal,
                              submitted_at=sub)
            coins = await grant_approval_coins(db, v)
            await _notify_system(db, v, "视频审核通过",
                                 f"你的视频《{v.title}》审核通过了" +
                                 (",会在设定的时间公开" if v.status == "scheduled" else "") +
                                 (f",获得 {coins} 枚硬币" if coins else ""), "approve",
                                 extra={"coins": coins})
        else:
            _transition(v, "rejected", "admin")
            v.reject_code, v.reject_note = reason_code, (note or "").strip()[:500]
            d = await _record(db, v, "reject", admin, reason_code=reason_code, note=note,
                              note_internal=note_internal, submitted_at=sub)
            await _notify_system(db, v, "视频未通过审核",
                                 f"你的视频《{v.title}》未通过审核:{REASON_CODES[reason_code]}"
                                 + (f"。{v.reject_note}" if v.reject_note else "")
                                 + "。可以修改后重新提交,或者申诉", "reject", reason_code)
    else:
        if approve:
            await _apply_pending(db, v, "admin")
            d = await _record(db, v, "approve_changes", admin, note=note,
                              note_internal=note_internal, submitted_at=sub)
            await _notify_system(db, v, "视频改动审核通过",
                                 f"你对《{v.title}》的修改审核通过,已经更新到线上", "approve_changes")
        else:
            _pending(v, "rejected", "admin", reject_code=reason_code,
                     reject_note=(note or "").strip()[:500])
            d = await _record(db, v, "reject_changes", admin, reason_code=reason_code, note=note,
                              note_internal=note_internal, submitted_at=sub)
            await _notify_system(db, v, "视频改动未通过审核",
                                 f"你对《{v.title}》的修改未通过审核:{REASON_CODES[reason_code]}"
                                 + (f"。{note.strip()}" if (note or "").strip() else "")
                                 + "。线上仍是原来的版本", "reject_changes", reason_code)
    await emit_video_event(db, v)
    return d


async def take_down(db: AsyncSession, v: Video, admin: User, reason_code: str, note: str,
                    note_internal: str = "") -> VideoDecision:
    """下架(处罚)。必须带原因(S6);封面从公开桶撤掉,播放地址立即失效。"""
    reason_ok(reason_code, note)
    if v.status not in ("published", "scheduled"):
        raise HTTPException(409, "只有已发布的视频能下架")
    _transition(v, "removed", "admin")
    v.reject_code, v.reject_note = reason_code, (note or "").strip()[:500]
    unpublish_cover(db, v)
    d = await _record(db, v, "remove", admin, reason_code=reason_code, note=note,
                      note_internal=note_internal)
    await _notify_system(db, v, "视频已被下架",
                         f"你的视频《{v.title}》因「{REASON_CODES[reason_code]}」被下架"
                         + (f":{v.reject_note}" if v.reject_note else "") + "。有异议可以申诉",
                         "remove", reason_code)
    await emit_video_event(db, v)
    return d


async def appeal(db: AsyncSession, user: User, v: Video, text: str) -> VideoDecision:
    """UP 主对最近一次驳回 / 下架申诉。每个结论只能申诉一次;由另一名审核员处理(S6)。"""
    text = (text or "").strip()
    if len(text) < 5:
        raise HTTPException(422, "申诉理由至少写 5 个字")
    last = await db.scalar(select(VideoDecision).where(
        VideoDecision.video_id == v.id, VideoDecision.action.in_(APPEALABLE))
        .order_by(VideoDecision.id.desc()).limit(1))
    if last is None:
        raise HTTPException(409, "没有可以申诉的结论")
    dup = await db.scalar(select(VideoDecision.id).where(
        VideoDecision.action == "appeal", VideoDecision.appeal_of == last.id))
    if dup is not None:
        raise HTTPException(409, "每个结论只能申诉一次")
    if not _appeal_still_valid(v, last):
        raise HTTPException(409, "稿件已经改过了,重新提交审核就好,不用申诉")
    return await _record(db, v, "appeal", user, note=text[:500], appeal_of=last.id)


def _appeal_still_valid(v: Video, orig: VideoDecision) -> bool:
    if orig.action == "reject":
        return v.status == "rejected"
    if orig.action == "reject_changes":
        return vs.pending_state(v) == "rejected"
    if orig.action == "remove":
        return v.status == "removed"
    return False


async def open_appeals(db: AsyncSession) -> list[VideoDecision]:
    appeals = list(await db.scalars(select(VideoDecision).where(VideoDecision.action == "appeal")
                                    .order_by(VideoDecision.id)))
    if not appeals:
        return []
    done = set(await db.scalars(select(VideoDecision.appeal_of).where(
        VideoDecision.action.in_(("appeal_upheld", "appeal_overturned")),
        VideoDecision.appeal_of.in_([a.id for a in appeals]))))
    return [a for a in appeals if a.id not in done]


async def resolve_appeal(db: AsyncSession, ap: VideoDecision, admin: User, *, overturn: bool,
                         note: str = "", note_internal: str = "") -> VideoDecision:
    """处理申诉。**原结论是谁作出的,谁就不能处理**(S6)—— 自己复核自己等于没有申诉。"""
    if ap.action != "appeal":
        raise HTTPException(404, "申诉不存在")
    if ap.id not in {a.id for a in await open_appeals(db)}:
        raise HTTPException(409, "这条申诉已经处理过了")
    orig = await db.get(VideoDecision, ap.appeal_of)
    if orig is None:
        raise HTTPException(404, "原结论不存在")
    if orig.actor_id == admin.id:
        raise HTTPException(403, "原结论是你作出的,申诉必须由另一名审核员处理")
    if len((note or "").strip()) < 2:
        raise HTTPException(422, "写一句复核结论(会给 UP 主看)")
    v = await db.scalar(select(Video).where(Video.id == ap.video_id).with_for_update()
                        .execution_options(populate_existing=True))
    if v is None or v.deleted_at is not None:
        raise HTTPException(409, "稿件已经删除了")
    if overturn:
        if not _appeal_still_valid(v, orig):
            raise HTTPException(409, "稿件在申诉之后改过了,原结论已经不适用")
        if orig.action == "reject":
            await _publish_first(db, v, "appeal")
            await grant_approval_coins(db, v)
        elif orig.action == "reject_changes":
            await _apply_pending(db, v, "appeal")
        elif orig.action == "remove":
            _transition(v, "published", "appeal")
            v.reject_code, v.reject_note = "", ""
            await publish_cover(db, v)
    d = await _record(db, v, "appeal_overturned" if overturn else "appeal_upheld", admin,
                      note=note, note_internal=note_internal, appeal_of=ap.id)
    await _notify_system(db, v, "申诉结果",
                         (f"你对《{v.title}》的申诉成立,原结论已撤销" if overturn
                          else f"你对《{v.title}》的申诉经另一名审核员复核,维持原结论")
                         + f":{note.strip()}", "appeal_overturned" if overturn else "appeal_upheld")
    await emit_video_event(db, v)
    return d


# ---------------- 举报 ----------------

#: 7 天内 3 个不同的人举报同一个对象 → 自动进复审(#368)
REPORT_ESCALATE_USERS = 3
REPORT_ESCALATE_WINDOW = timedelta(days=7)


async def create_report(db: AsyncSession, user: User, target_type: str, target_id: int,
                        video_id: int | None, reason_code: str, note: str) -> VideoReport:
    """举报视频 / 评论 / 弹幕。举报人对被举报的一方永远匿名;同一个人同一个对象 7 天内只记一次。"""
    if reason_code not in REASON_CODES:
        raise HTTPException(422, "请选择举报原因")
    if reason_code == "X999" and len((note or "").strip()) < 5:
        raise HTTPException(422, "选「其他」要写明原因(至少 5 个字)")
    now = utcnow()
    since = now - REPORT_ESCALATE_WINDOW
    dup = await db.scalar(select(VideoReport).where(
        VideoReport.reporter_id == user.id, VideoReport.target_type == target_type,
        VideoReport.target_id == target_id, VideoReport.created_at >= since)
        .order_by(VideoReport.id.desc()).limit(1))
    if dup is not None:
        return dup
    r = VideoReport(reporter_id=user.id, target_type=target_type, target_id=target_id,
                    video_id=video_id, reason_code=reason_code, note=(note or "").strip()[:500],
                    status="open", created_at=now)
    db.add(r)
    await db.flush()
    n = await db.scalar(select(func.count(func.distinct(VideoReport.reporter_id))).where(
        VideoReport.target_type == target_type, VideoReport.target_id == target_id,
        VideoReport.created_at >= since))
    if (n or 0) >= REPORT_ESCALATE_USERS:
        await db.execute(update(VideoReport).where(
            VideoReport.target_type == target_type, VideoReport.target_id == target_id,
            VideoReport.status == "open").values(status="escalated")
            .execution_options(synchronize_session=False))
        r.status = "escalated"
    return r


# ---------------- 硬币(D13,纯积分,S4)----------------

async def _ledger(db: AsyncSession, user_id: int, delta: int, reason: str, ref: str,
                  balance: int) -> None:
    assert reason in COIN_REASONS, reason
    db.add(CoinLedger(user_id=user_id, delta=delta, reason=reason, ref=ref, balance=balance,
                      created_at=utcnow()))


async def grant_daily(db: AsyncSession, user_id: int) -> tuple[bool, int]:
    """每日首次打开视频 +1(北京日期,一天一次)。一条 UPDATE 带条件,并发两次也只成一次。"""
    await ensure_profile(db, user_id)
    today = bj_day()
    bal = await db.scalar(
        update(SocialProfile).where(
            SocialProfile.user_id == user_id,
            or_(SocialProfile.coin_day.is_(None), SocialProfile.coin_day < today))
        .values(coins=SocialProfile.coins + DAILY_COINS, coin_day=today)
        .returning(SocialProfile.coins))
    if bal is None:
        cur = await db.scalar(select(SocialProfile.coins).where(SocialProfile.user_id == user_id))
        return False, int(cur or 0)
    await _ledger(db, user_id, DAILY_COINS, "daily", today.isoformat(), bal)
    return True, int(bal)


async def grant_approval_coins(db: AsyncSession, v: Video) -> int:
    """投稿过审 +2,每天从过审拿到的封顶 10 枚;同一个稿件只奖励一次(唯一索引兜底)。"""
    await ensure_profile(db, v.uploader_id)
    # 锁住 UP 主的资料行,同一时刻两个稿件过审不会一起越过每日封顶
    await db.execute(select(SocialProfile.user_id).where(SocialProfile.user_id == v.uploader_id)
                     .with_for_update())
    since = bj_midnight(bj_day())
    got = await db.scalar(select(func.coalesce(func.sum(CoinLedger.delta), 0)).where(
        CoinLedger.user_id == v.uploader_id, CoinLedger.reason == "video_approved",
        CoinLedger.created_at >= since))
    amount = min(APPROVAL_COINS, APPROVAL_DAILY_CAP - int(got or 0))
    if amount <= 0:
        return 0
    ref = f"video:{v.vid}"
    res = await db.execute(insert(CoinLedger).values(
        user_id=v.uploader_id, delta=amount, reason="video_approved", ref=ref, balance=0,
        created_at=utcnow()).on_conflict_do_nothing(
        index_elements=["user_id", "ref"], index_where=sql_text("reason = 'video_approved'"))
        .returning(CoinLedger.id))
    lid = res.scalar()
    if lid is None:
        return 0
    bal = await db.scalar(update(SocialProfile).where(SocialProfile.user_id == v.uploader_id)
                          .values(coins=SocialProfile.coins + amount)
                          .returning(SocialProfile.coins))
    await db.execute(update(CoinLedger).where(CoinLedger.id == lid).values(balance=bal))
    return amount


async def give_coins(db: AsyncSession, user: User, v: Video, amount: int) -> dict:
    """投币:自制最多 2 枚、转载 1 枚;投出的归 UP 主(D13)。余额不够整笔回滚。"""
    cap = COIN_MAX.get(v.copyright, 1)
    if amount not in (1, 2):
        raise HTTPException(422, "一次投 1 或 2 枚")
    if amount > cap:
        raise HTTPException(422, f"{'转载' if v.copyright == 'repost' else '自制'}视频最多投 {cap} 枚")
    if user.id == v.uploader_id:
        raise HTTPException(422, "不能给自己的视频投币")
    await ensure_profile(db, user.id)
    await ensure_profile(db, v.uploader_id)
    row = await db.execute(
        insert(VideoCoin).values(video_id=v.id, user_id=user.id, amount=amount,
                                 created_at=utcnow())
        .on_conflict_do_update(index_elements=["video_id", "user_id"],
                               set_={"amount": VideoCoin.amount + amount},
                               where=(VideoCoin.amount + amount <= cap))
        .returning(VideoCoin.amount))
    total = row.scalar()
    if total is None:
        raise HTTPException(409, f"这个视频你已经投满 {cap} 枚了")
    bal = await db.scalar(update(SocialProfile).where(SocialProfile.user_id == user.id,
                                                      SocialProfile.coins >= amount)
                          .values(coins=SocialProfile.coins - amount)
                          .returning(SocialProfile.coins))
    if bal is None:
        raise HTTPException(422, "硬币不够了(每天打开视频可以领 1 枚)")
    ref = f"video:{v.vid}"
    await _ledger(db, user.id, -amount, "coin_give", ref, bal)
    up_bal = await db.scalar(update(SocialProfile).where(SocialProfile.user_id == v.uploader_id)
                             .values(coins=SocialProfile.coins + amount)
                             .returning(SocialProfile.coins))
    await _ledger(db, v.uploader_id, amount, "coin_receive", ref, up_bal)
    await db.execute(update(Video).where(Video.id == v.id).values(coins=Video.coins + amount)
                     .execution_options(synchronize_session=False))
    await bump_stat(db, v.id, coins=amount)
    return {"coins_given": int(total), "coin_max": cap, "coin_balance": int(bal)}


async def coin_page(db: AsyncSession, user_id: int, before: int | None, limit: int = 20) -> dict:
    prof = await ensure_profile(db, user_id)
    q = select(CoinLedger).where(CoinLedger.user_id == user_id)
    if before:
        q = q.where(CoinLedger.id < before)
    rows = list(await db.scalars(q.order_by(CoinLedger.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    vids = {r.ref.split(":", 1)[1] for r in rows if r.ref.startswith("video:")}
    videos = {v.vid: v for v in await db.scalars(select(Video).where(Video.vid.in_(vids)))} \
        if vids else {}
    items = []
    for r in rows:
        vv = videos.get(r.ref.split(":", 1)[1]) if r.ref.startswith("video:") else None
        items.append({"id": r.id, "delta": r.delta, "reason": r.reason,
                      "reason_label": COIN_REASONS.get(r.reason, r.reason), "balance": r.balance,
                      "video": video_brief(vv) if vv is not None and vv.deleted_at is None
                      else None, "created_at": iso(r.created_at)})
    return {"coins": prof.coins, "today_claimed": prof.coin_day == bj_day(),
            "items": items, "next_cursor": str(rows[-1].id) if more and rows else None}


# ---------------- 统计 ----------------

STAT_COLS = ("views", "likes", "coins", "favorites", "comments", "danmaku", "shares")


async def bump_stat(db: AsyncSession, video_id: int, **deltas: int) -> None:
    """按天的增量(创作中心曲线)。"""
    deltas = {k: n for k, n in deltas.items() if n}
    if not deltas:
        return
    assert set(deltas) <= set(STAT_COLS), deltas
    await db.execute(
        insert(VideoStatDay).values(video_id=video_id, day=bj_day(), **deltas)
        .on_conflict_do_update(index_elements=["video_id", "day"],
                               set_={k: getattr(VideoStatDay, k) + n for k, n in deltas.items()}))


async def stats(db: AsyncSession, v: Video, days: int = 30) -> dict:
    today = bj_day()
    start = today - timedelta(days=days - 1)
    rows = {r.day: r for r in await db.scalars(select(VideoStatDay).where(
        VideoStatDay.video_id == v.id, VideoStatDay.day >= start))}
    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        r = rows.get(d)
        series.append({"day": d.isoformat(), **{k: (getattr(r, k) if r else 0) for k in STAT_COLS}})
    totals = {"views": v.views, "likes": v.likes, "coins": v.coins, "favorites": v.favorites,
              "comments": v.comment_count, "danmaku": v.danmaku_count, "shares": v.shares}
    return {"vid": v.vid, "totals": totals, "days": series}


async def overview(db: AsyncSession, user: User) -> dict:
    by_status = dict((await db.execute(
        select(Video.status, func.count()).where(Video.uploader_id == user.id,
                                                 Video.deleted_at.is_(None))
        .group_by(Video.status))).all())
    sums = (await db.execute(select(
        func.coalesce(func.sum(Video.views), 0), func.coalesce(func.sum(Video.likes), 0),
        func.coalesce(func.sum(Video.coins), 0), func.coalesce(func.sum(Video.favorites), 0),
        func.coalesce(func.sum(Video.comment_count), 0),
        func.coalesce(func.sum(Video.danmaku_count), 0),
        func.coalesce(func.sum(Video.shares), 0)).where(
        Video.uploader_id == user.id, Video.deleted_at.is_(None)))).one()
    today = bj_day()

    async def window(n: int) -> dict:
        start = today - timedelta(days=n - 1)
        row = (await db.execute(select(*[func.coalesce(func.sum(getattr(VideoStatDay, k)), 0)
                                         for k in STAT_COLS]).join(
            Video, Video.id == VideoStatDay.video_id).where(
            Video.uploader_id == user.id, VideoStatDay.day >= start))).one()
        return dict(zip(STAT_COLS, (int(x) for x in row)))

    fans, following = await follow_counts(db, user.id)
    prof = await ensure_profile(db, user.id)
    return {"videos": {s: int(by_status.get(s, 0)) for s in vs.STATUS_LABELS if s != "deleted"},
            "totals": dict(zip(STAT_COLS, (int(x) for x in sums))),
            "today": await window(1), "last_7_days": await window(7),
            "last_30_days": await window(30), "fans": fans, "following": following,
            "coins": prof.coins}


# ---------------- 删除、注销级联(S5)、清扫 ----------------

async def delete_video(db: AsyncSession, v: Video, role: str = "uploader") -> None:
    """UP 主删除:软删,马上从所有地方消失、播放地址立即失效;媒体 30 天后由清扫清掉。
    待审改动留在行上不清 —— 清扫时还要靠它找到改动里换上的新封面一起删。"""
    _transition(v, "deleted", role)
    v.deleted_at = utcnow()
    unpublish_cover(db, v)


async def purge_video_media(db: AsyncSession, v: Video) -> None:
    """清掉一个稿件的全部媒体:各档位、雪碧图、原片、封面(公开桶和私密桶)。"""
    parts = await parts_of(db, v)
    await _drop_parts(db, parts)
    pending_cover = ((v.pending_changes or {}).get("fields") or {}).get("cover_media_id")
    media_ids = [m for m in (v.cover_media_id, pending_cover) if m]
    objs: list[tuple[str, bool]] = []
    if media_ids:
        for mf in await db.scalars(select(MediaFile).where(MediaFile.id.in_(media_ids))):
            objs += _media_objects(mf)
        await db.execute(delete(MediaFile).where(MediaFile.id.in_(media_ids)))
    unpublish_cover(db, v)
    remove_objects_after_commit(db, objs)
    v.cover_media_id = None
    vs.store_pending(v, None)
    v.purged_at = utcnow()


async def _recount(db: AsyncSession, video_ids: set[int]) -> None:
    """注销之后按明细表重算计数(赞、收藏、分享、弹幕、评论、投币)。"""
    if not video_ids:
        return
    ids = list(video_ids)
    await db.execute(sql_text("""
        UPDATE videos v SET
          likes = (SELECT count(*) FROM video_likes x WHERE x.video_id = v.id),
          favorites = (SELECT count(DISTINCT user_id) FROM fav_items x WHERE x.video_id = v.id),
          shares = (SELECT count(*) FROM video_shares x WHERE x.video_id = v.id),
          coins = (SELECT coalesce(sum(amount), 0) FROM video_coins x WHERE x.video_id = v.id),
          danmaku_count = (SELECT count(*) FROM danmaku x
                           WHERE x.video_id = v.id AND x.deleted_at IS NULL),
          comment_count = (SELECT count(*) FROM video_comments c
                           LEFT JOIN video_comments r ON r.id = c.root_id
                           WHERE c.video_id = v.id AND c.deleted_at IS NULL
                             AND (c.root_id IS NULL OR r.deleted_at IS NULL))
        WHERE v.id = ANY(:ids)"""), {"ids": ids})


async def purge_user(db: AsyncSession, user_id: int) -> None:
    """注销账号时的视频部分(S5):投稿、弹幕、评论、赞、币、收藏、历史、关注、互动消息一并处理。

    - 投稿:删除并**立即**清媒体(不等 30 天),播放地址、封面地址全部失效;
    - 弹幕删掉;评论清空正文、打上删除标记(楼中楼的结构留着,别人的回复不跟着消失,
      但这个人说过的话没了);他点的赞 / 踩、收藏夹、稍后再看、历史、关注关系、不感兴趣、
      搜索记录、硬币流水、互动消息都删;
    - 受影响的视频按明细表重算计数。调用方负责提交。
    """
    now = utcnow()
    touched: set[int] = set()
    for v in list(await db.scalars(select(Video).where(Video.uploader_id == user_id)
                                   .with_for_update().execution_options(populate_existing=True))):
        if v.status != "deleted":
            vs.transition(v, "deleted", "system")
        v.deleted_at = v.deleted_at or now
        if v.purged_at is None:
            await purge_video_media(db, v)
    # 上传了但还没挂到稿件上的原片、封面
    loose = list(await db.scalars(select(MediaFile).where(MediaFile.owner_id == user_id,
                                                          MediaFile.purpose == "video")))
    if loose:
        objs: list[tuple[str, bool]] = []
        for mf in loose:
            objs += _media_objects(mf)
        await db.execute(delete(MediaFile).where(MediaFile.id.in_([m.id for m in loose])))
        remove_objects_after_commit(db, objs)
    # 弹幕
    touched |= set(await db.scalars(select(Danmaku.video_id).where(Danmaku.user_id == user_id)
                                    .distinct()))
    await db.execute(delete(Danmaku).where(Danmaku.user_id == user_id))
    # 评论:正文清空、标删除
    touched |= set(await db.scalars(select(VideoComment.video_id).where(
        VideoComment.user_id == user_id).distinct()))
    root_ids = set(await db.scalars(select(VideoComment.root_id).where(
        VideoComment.user_id == user_id, VideoComment.root_id.is_not(None)).distinct()))
    await db.execute(update(VideoComment).where(VideoComment.user_id == user_id).values(
        text="", mentions=[], deleted_at=func.coalesce(VideoComment.deleted_at, now), pinned=False))
    # 赞 / 踩
    voted = set(await db.scalars(select(CommentVote.comment_id).where(
        CommentVote.user_id == user_id)))
    await db.execute(delete(CommentVote).where(CommentVote.user_id == user_id))
    if voted or root_ids:
        await db.execute(sql_text("""
            UPDATE video_comments c SET
              likes = (SELECT count(*) FROM comment_votes x WHERE x.comment_id = c.id AND x.vote = 1),
              dislikes = (SELECT count(*) FROM comment_votes x WHERE x.comment_id = c.id AND x.vote = -1),
              reply_count = (SELECT count(*) FROM video_comments r
                             WHERE r.root_id = c.id AND r.deleted_at IS NULL)
            WHERE c.id = ANY(:ids)"""), {"ids": list(voted | root_ids)})
    for model, col in ((VideoLike, VideoLike.user_id), (VideoCoin, VideoCoin.user_id),
                       (VideoShare, VideoShare.user_id), (FavItem, FavItem.user_id)):
        touched |= set(await db.scalars(select(model.video_id).where(col == user_id).distinct()))
        await db.execute(delete(model).where(col == user_id))
    await db.execute(delete(FavFolder).where(FavFolder.user_id == user_id))
    for model in (WatchLater, WatchHistory, VideoNotInterested, VideoUserSetting, SearchTermUser,
                  CoinLedger):
        await db.execute(delete(model).where(model.user_id == user_id))
    await db.execute(delete(Follow).where(or_(Follow.follower_id == user_id,
                                              Follow.followee_id == user_id)))
    await db.execute(delete(VideoViewDay).where(VideoViewDay.viewer_key == f"u{user_id}"))
    await db.execute(delete(SocialNotification).where(or_(
        SocialNotification.user_id == user_id, SocialNotification.actor_id == user_id)))
    # 他写的举报说明也清掉(举报记录本身是平台的处置依据,留着)
    await db.execute(update(VideoReport).where(VideoReport.reporter_id == user_id)
                     .values(note=""))
    await db.execute(update(SocialProfile).where(SocialProfile.user_id == user_id)
                     .values(coins=0, coin_day=None))
    await _recount(db, touched)


async def sweep_videos(now: datetime | None = None) -> dict[str, int]:
    """清扫:定时发布到点公开;删除满 30 天的清媒体;去重表只留 8 天。"""
    from ..db import SessionLocal

    now = now or utcnow()
    published = purged = 0
    async with SessionLocal() as db:
        due = list(await db.scalars(select(Video).where(
            Video.status == "scheduled", Video.scheduled_at <= now, Video.deleted_at.is_(None))
            .with_for_update(skip_locked=True).execution_options(populate_existing=True)
            .limit(100)))
        for v in due:
            vs.transition(v, "published", "system")
            v.published_at = now
            await _notify_system(db, v, "视频已公开", f"你的视频《{v.title}》到了定时发布的时间,已经公开",
                                 "published")
            await emit_video_event(db, v)
            published += 1
        await db.commit()
        old = list(await db.scalars(select(Video).where(
            Video.status == "deleted", Video.purged_at.is_(None),
            Video.deleted_at < now - PURGE_AFTER)
            .with_for_update(skip_locked=True).execution_options(populate_existing=True)
            .limit(50)))
        for v in old:
            await purge_video_media(db, v)
            purged += 1
        await db.execute(delete(SearchTermUser).where(
            SearchTermUser.created_at < now - timedelta(days=8)))
        await db.execute(delete(VideoViewDay).where(
            VideoViewDay.created_at < now - timedelta(days=8)))
        await db.commit()
    return {"published": published, "purged": purged}
