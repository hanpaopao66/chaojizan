"""论坛的业务逻辑:发帖、实体解析、回复串、引用、编辑、删除、投票、置顶、点赞 / 转发 / 书签、
浏览、屏蔽词、举报、下架与申诉、注销清理、清扫(DEV-PROMPTS-41 §5.6、§5.8、§5.11,#380)。

路由(routers/forum.py、routers/forum_admin.py)只取当前用户、调这里、提交;判定都在这里。
时间线、热门话题、搜索在 forum_feed.py,排序公式在 forum_rank.py(纯函数),卡片在 cards.py。

几条贯穿全模块的:

- **实体由服务端解析**(§5.6):客户端报什么话题、@ 了谁一律不算数 —— 不然「蹭话题」只要改个
  请求体就行了。解析结果同时进 `entities` 列(展示用)和 forum_post_tags / forum_mentions
  两张表(数人用);
- **图片只能是自己上传的**(§8.3):`media` 里每个地址必须长得像 `/img/forum/u<我>-…`。
  不校验的话可以把别人私密桶里的地址贴进来当自己的图;
- 不可见的帖子(删了、下架了、拉黑)在串里**占位**,不是消失:回复的上下文断了比看到一句
  「这条帖子已删除」更让人困惑;
- 平台不收钱(§3.1):这里没有任何付费、打赏、推广位的入口。
"""
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Follow, ForumBookmark, ForumDecision, ForumLike, ForumMention,
                      ForumMuteWord, ForumPin, ForumPoll, ForumPollVote, ForumPost,
                      ForumPostEdit, ForumPostTag, ForumReport, ForumRepost, ForumTag,
                      ForumUserSetting, ForumViewDay, SocialProfile, User, Username)
from . import cards
from . import video as vsvc
from .social import blocked_between, username_searchable

logger = logging.getLogger("superz.forum")

# ---------------- 常量(公开写进 docs/FORUM-API.md)----------------

#: 正文 1–500 字(按 Unicode 字符数;有图、卡片或投票时可以为空,§5.6)
TEXT_MAX = 500
#: 最多 4 张图(F1)
MEDIA_MAX = 4
#: 公开图片用途:走 POST /uploads?purpose=forum,地址长这样
MEDIA_PREFIX = "/img/forum/"
TAGS_MAX = 10
TAG_MAX = 30
MENTIONS_MAX = 10
LINKS_MAX = 3
#: 编辑:发出后 30 分钟内、最多 5 次(F3)
EDIT_WINDOW = timedelta(minutes=30)
EDIT_MAX = 5
#: 投票:2–4 项、每项 1–25 字、5 分钟–7 天(F1)
POLL_MIN_OPTIONS, POLL_MAX_OPTIONS = 2, 4
POLL_OPTION_MAX = 25
POLL_MIN_MINUTES, POLL_MAX_MINUTES = 5, 7 * 24 * 60
#: 屏蔽词每人最多 100 个
MUTE_WORDS_MAX = 100
MUTE_WORD_MAX = 30
#: 浏览上报一次最多 50 条(§8.3)
VIEW_PIDS_MAX = 50
#: 去重表留 8 天(和视频的播放去重同一个口径)
VIEW_KEEP_DAYS = 8
#: 申诉正文长度(和处罚申诉同一个口径)
APPEAL_MIN, APPEAL_MAX = 5, 500

PUBLIC_BASE = cards.PUBLIC_BASE

#: 论坛自己的原因代码(§5.11)。C1xx 和 X999 共用视频那张表
FORUM_REASON_CODES: dict[str, str] = {
    "F401": "刷屏、重复发帖",
    "F402": "蹭无关话题",
    "F403": "恶意引战、人身攻击",
}


def reason_codes() -> dict[str, str]:
    """论坛能用的全部原因代码:共用的 C101–C109 + X999,加 F401–F403(§5.11)。

    视频专有的 V2xx 不在里面 —— 给帖子按「视频侵权」下架说不通。
    """
    common = {k: v for k, v in vsvc.REASON_CODES.items() if k.startswith("C") or k == "X999"}
    return {**common, **FORUM_REASON_CODES}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def new_pid() -> str:
    """`fp` + 10 位 base58 随机(§5.1):不暴露发帖量,也不能按数字遍历。"""
    return "fp" + "".join(secrets.choice(_B58) for _ in range(10))


PID_RE = re.compile(r"^fp[1-9A-HJ-NP-Za-km-z]{10}$")


def reason_ok(code: str, note: str) -> None:
    """下架、隐藏话题必须带原因代码;选 X999 必须写说明(和视频同一个口径)。"""
    if code not in reason_codes():
        raise HTTPException(422, "原因代码不存在(见 §5.11)")
    if code == "X999" and len(note.strip()) < 5:
        raise HTTPException(422, "选「其他」必须写清楚原因(至少 5 个字)")


# ---------------- 实体解析(§5.6,纯函数,单测钉住)----------------
#
# 话题两种写法:`#话题#` 和 `#话题`(遇到空白、`#`、中英文标点截止)。带闭合井号的优先 ——
# 「#成都# 的天气」里话题是「成都」,不是「成都# 的天气」。

#: 话题里不能出现的字符:中英文标点(遇到就截止)。空白和 `#` 另外排除
_TAG_PUNCT = "，。！？；：、「」『』（）【】《》〈〉—…～·,.!?;:\"'`()[]{}<>@#$%^&*+=|\\/~"
_TAG_BODY = r"[^\s" + re.escape(_TAG_PUNCT) + r"]{1," + str(TAG_MAX) + r"}"
_TAG_RE = re.compile(rf"#({_TAG_BODY})#|#({_TAG_BODY})")
#: @超级赞号(格式同 services/social.validate_username:字母开头,5–32 位)
_MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{4,31})")
_LINK_RE = re.compile(r"https?://[^\s]{3,290}")


def parse_tags(text: str) -> list[dict]:
    """文中的话题:统一小写当 `tag`,原样留 `display`,按出现顺序去重,最多 10 个。纯函数。"""
    out: list[dict] = []
    seen: set[str] = set()
    for m in _TAG_RE.finditer(text or ""):
        raw = (m.group(1) or m.group(2) or "").strip()
        low = raw.lower()
        if not raw or low in seen:
            continue
        seen.add(low)
        out.append({"tag": low, "display": raw})
        if len(out) >= TAGS_MAX:
            break
    return out


def parse_mentions(text: str) -> list[str]:
    """文中的 @超级赞号,小写去重,最多 10 个。纯函数(查不查得到人在 _resolve_mentions)。"""
    out: list[str] = []
    for m in _MENTION_RE.finditer(text or ""):
        low = m.group(1).lower()
        if low not in out:
            out.append(low)
        if len(out) >= MENTIONS_MAX:
            break
    return out


def parse_links(text: str) -> list[str]:
    """文中的链接,去重,最多 3 个。纯函数。"""
    out: list[str] = []
    for m in _LINK_RE.finditer(text or ""):
        url = m.group(0).rstrip("，。!?;:、)）】》")
        if url not in out:
            out.append(url)
        if len(out) >= LINKS_MAX:
            break
    return out


async def _resolve_mentions(db: AsyncSession, names: list[str]) -> list[dict]:
    """@超级赞号 → 人。**对方关了「按超级赞号找到我」的不解析**,当普通文字 ——
    不出链接、不发「@我的」,和没有这个号一模一样(和视频评论、/social/v1/resolve 同一个口径)。
    不然随便发条帖 @ 一下,就能从链接里认出这个号是谁,开关白关。
    """
    if not names:
        return []
    rows = (await db.execute(
        select(Username.username_lc, Username.owner_id)
        .outerjoin(SocialProfile, SocialProfile.user_id == Username.owner_id)
        .where(Username.username_lc.in_(names), Username.owner_type == "user",
               username_searchable(SocialProfile.privacy)))).all()
    by = {n: uid for n, uid in rows}
    return [{"id": by[n], "username": n} for n in names if n in by]


async def parse_entities(db: AsyncSession, text: str) -> dict:
    """一条帖子的全部实体(§5.6)。存进 forum_posts.entities,客户端照它渲染可点的部分。"""
    return {"tags": parse_tags(text),
            "mentions": await _resolve_mentions(db, parse_mentions(text)),
            "links": parse_links(text)}


async def mentions_off(db: AsyncSession, posts) -> set[int]:
    """这些帖子里 @ 到的人当中,**现在**关着「按超级赞号找到我」的。展示时把他们从 mentions 里拿掉。

    只在发的时候挡不够:开关关掉之前发的帖子,entities 里还存着「这个号 → 这个人」,照样把号和人对上。
    一页帖子一条查询(和 video_talk.mentions_off 同一个道理)。
    """
    ids = {m.get("id") for p in posts for m in ((p.entities or {}).get("mentions") or [])
           if isinstance(m, dict) and m.get("id")}
    if not ids:
        return set()
    from .social import username_search_off
    return await username_search_off(db, ids)


# ---------------- 取帖子 ----------------

async def get_post(db: AsyncSession, pid: str, *, lock: bool = False) -> ForumPost:
    """按公开编号取帖子(含删了 / 下架了的 —— 判权在调用方)。"""
    if not PID_RE.match(pid or ""):
        raise HTTPException(404, "没有这条帖子")
    q = select(ForumPost).where(ForumPost.pid == pid)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    p = await db.scalar(q)
    if p is None:
        raise HTTPException(404, "没有这条帖子")
    return p


def is_admin(user: User | None) -> bool:
    return vsvc.is_admin(user)


async def invisible_reason(db: AsyncSession, p: ForumPost, viewer_id: int | None) -> str | None:
    """这条帖子对这个人不可见的原因;可见返回 None。占位用(§8.1)。"""
    if p.status == "deleted":
        return "deleted"
    if p.status == "removed":
        return "removed"
    if viewer_id and viewer_id != p.author_id and await blocked_between(db, viewer_id,
                                                                       p.author_id):
        return "blocked"
    return None


async def viewable(db: AsyncSession, pid: str, viewer: User | None) -> ForumPost:
    """看得到才给,看不到一律 404(不告诉你「有但看不了」)。作者本人和管理员看得到自己的。"""
    p = await get_post(db, pid)
    viewer_id = viewer.id if viewer else None
    if viewer_id == p.author_id or is_admin(viewer):
        return p
    if await invisible_reason(db, p, viewer_id) is not None:
        raise HTTPException(404, "没有这条帖子")
    return p


def placeholder(p: ForumPost, reason: str) -> dict:
    """串里、引用里看不见的那一条(§8.1)。"""
    return {"pid": p.pid, "unavailable": True, "reason": reason}


# ---------------- 发帖 ----------------

def clean_text(text: str | None) -> str:
    t = (text or "").strip()
    if len(t) > TEXT_MAX:
        raise HTTPException(422, f"正文最多 {TEXT_MAX} 字")
    return t


def _clean_media(media: list | None, user_id: int) -> list[dict]:
    """图片:最多 4 张,每张必须是**本人**通过 `POST /uploads?purpose=forum` 传的
    (`/img/forum/u<我>-…`)。

    不校验上传者的话,可以把别人的图片地址贴进来当自己的图 —— 存储 key 里本来就编了上传者
    (services/storage._new_key),这里只要认它。
    """
    items = list(media or [])
    if len(items) > MEDIA_MAX:
        raise HTTPException(422, f"最多 {MEDIA_MAX} 张图")
    out: list[dict] = []
    want = f"{MEDIA_PREFIX}u{user_id}-"
    for it in items:
        url = (it if isinstance(it, str) else (it or {}).get("url") or "").strip()
        if not url.startswith(want):
            raise HTTPException(422, "图片只能用自己刚上传的(purpose=forum)")
        w = h = 0
        if isinstance(it, dict):
            try:
                w, h = int(it.get("w") or 0), int(it.get("h") or 0)
            except (TypeError, ValueError):
                w = h = 0
        out.append({"url": url, "w": max(0, w), "h": max(0, h)})
    return out


async def _clean_card(db: AsyncSession, card: dict | None, viewer_id: int) -> dict | None:
    """卡片:只存 `{type, id}`,但发的时候要能查到 —— **只有公开可见的才能发**(§5.9)。"""
    if not card:
        return None
    type_ = str(card.get("type") or "")
    id_ = str(card.get("id") or "")
    if type_ not in cards.known_types():
        raise HTTPException(422, f"不认识的卡片类型:{type_ or '(空)'}")
    if not id_ or len(id_) > 40:
        raise HTTPException(422, "卡片编号不对")
    if await cards.resolve(db, type_, id_, viewer_id) is None:
        raise HTTPException(422, "这条内容现在分享不了(可能已删除、没过审或是私密的)")
    return {"type": type_, "id": id_}


def _clean_poll(poll: dict | None, now: datetime) -> tuple[list[dict], datetime] | None:
    """投票:2–4 项、每项 1–25 字、5 分钟–7 天(§5.6)。"""
    if not poll:
        return None
    raw = list(poll.get("options") or [])
    texts = [" ".join(str(o or "").split()) for o in raw]
    texts = [t for t in texts if t]
    if not (POLL_MIN_OPTIONS <= len(texts) <= POLL_MAX_OPTIONS):
        raise HTTPException(422, f"投票要 {POLL_MIN_OPTIONS}–{POLL_MAX_OPTIONS} 个选项")
    if len(set(texts)) != len(texts):
        raise HTTPException(422, "投票选项不能重复")
    for t in texts:
        if len(t) > POLL_OPTION_MAX:
            raise HTTPException(422, f"每个选项最多 {POLL_OPTION_MAX} 字")
    try:
        minutes = int(poll.get("minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    if not (POLL_MIN_MINUTES <= minutes <= POLL_MAX_MINUTES):
        raise HTTPException(422, "投票时长只能是 5 分钟到 7 天")
    return [{"text": t, "votes": 0} for t in texts], now + timedelta(minutes=minutes)


async def can_reply_to(db: AsyncSession, parent: ForumPost, viewer_id: int) -> bool:
    """能不能回复这一条(§5.6 F4 + 拉黑)。作者本人永远能回自己的串。"""
    if viewer_id == parent.author_id:
        return True
    if await blocked_between(db, viewer_id, parent.author_id):
        return False
    if parent.reply_policy == "following":
        # 「我关注的人」= 帖子作者关注了我
        return await db.get(Follow, (parent.author_id, viewer_id)) is not None
    if parent.reply_policy == "mentioned":
        return await db.get(ForumMention, (parent.id, viewer_id)) is not None
    return True


async def _bump_tags(db: AsyncSession, post: ForumPost, tags: list[dict],
                     now: datetime) -> None:
    """话题入库:forum_tags 一个话题一行(计数 + 最近用过),forum_post_tags 一帖一行。"""
    for t in tags:
        row = await db.scalar(insert(ForumTag).values(
            tag=t["tag"], display=t["display"], posts=1, last_used_at=now)
            .on_conflict_do_update(index_elements=["tag"],
                                   set_={"posts": ForumTag.posts + 1, "last_used_at": now})
            .returning(ForumTag.id))
        await db.execute(insert(ForumPostTag).values(
            post_id=post.id, tag_id=row, author_id=post.author_id, created_at=now)
            .on_conflict_do_nothing())


async def _write_entities(db: AsyncSession, post: ForumPost, entities: dict,
                          now: datetime) -> None:
    await _bump_tags(db, post, entities.get("tags") or [], now)
    for m in entities.get("mentions") or []:
        await db.execute(insert(ForumMention).values(post_id=post.id, user_id=m["id"])
                         .on_conflict_do_nothing())


async def create_post(db: AsyncSession, user: User, body: dict) -> ForumPost:
    """发帖 / 回复 / 引用(§5.6)。调用方负责提交。"""
    from .moderation import guard_text

    now = utcnow()
    text = clean_text(body.get("text"))
    media = _clean_media(body.get("media"), user.id)
    poll = _clean_poll(body.get("poll"), now)
    card = await _clean_card(db, body.get("card"), user.id)
    if text:
        await guard_text(db, text, "帖子")
    if poll:
        # 违禁词也管投票选项:正文干净、选项骂人一样是骂人
        for o in poll[0]:
            await guard_text(db, o["text"], "投票选项")

    reply_to = quote_of = None
    if body.get("reply_to_pid"):
        reply_to = await viewable(db, str(body["reply_to_pid"]), user)
        if not await can_reply_to(db, reply_to, user.id):
            raise HTTPException(403, "作者设置了谁能回复,你现在回复不了这条帖子")
    if body.get("quote_pid"):
        quote_of = await viewable(db, str(body["quote_pid"]), user)
        if quote_of.quote_of_id is not None:
            # 引用不套娃:引用一条引用时,引的还是它本身(展示时也只展开一层,§8.1)
            pass
    if not text and not media and not card and not poll and quote_of is None:
        raise HTTPException(422, "写点什么吧(或者配图、卡片、投票)")
    if reply_to is not None and poll is not None:
        raise HTTPException(422, "回复里不能带投票")

    policy = str(body.get("reply_policy") or "all")
    if policy not in ("all", "following", "mentioned"):
        raise HTTPException(422, "谁能回复只能是 所有人 / 我关注的人 / 我提到的人")

    entities = await parse_entities(db, text)
    post = ForumPost(
        pid=new_pid(), author_id=user.id, text=text, entities=entities, media=media,
        card=card, reply_to_id=reply_to.id if reply_to is not None else None,
        reply_to_user_id=reply_to.author_id if reply_to is not None else None,
        root_id=(reply_to.root_id or reply_to.id) if reply_to is not None else None,
        quote_of_id=quote_of.id if quote_of is not None else None,
        reply_policy=policy, status="visible", created_at=now)
    db.add(post)
    await db.flush()
    await _write_entities(db, post, entities, now)
    if poll is not None:
        db.add(ForumPoll(post_id=post.id, options=poll[0], ends_at=poll[1], total=0))
    if reply_to is not None:
        await db.execute(update(ForumPost).where(ForumPost.id == reply_to.id)
                         .values(replies=ForumPost.replies + 1))
    if quote_of is not None:
        await db.execute(update(ForumPost).where(ForumPost.id == quote_of.id)
                         .values(quotes=ForumPost.quotes + 1))
    await _notify_new_post(db, user, post, reply_to, quote_of)
    return post


async def _notify_new_post(db: AsyncSession, user: User, post: ForumPost,
                           reply_to: ForumPost | None, quote_of: ForumPost | None) -> None:
    """互动消息(§5.8):回复我的帖子 → reply;回复里 @ 我 → at;引用我的帖子 → quote。"""
    from . import social_notify

    text = " ".join((post.text or "").split())[:80]
    told: set[int] = {user.id}
    if reply_to is not None:
        await social_notify.notify(db, reply_to.author_id, "reply", actor_id=user.id,
                                   forum_post_id=post.id,
                                   data={"target": "post", "text": text})
        told.add(reply_to.author_id)
    if quote_of is not None:
        await social_notify.notify(db, quote_of.author_id, "quote", actor_id=user.id,
                                   forum_post_id=post.id,
                                   data={"target": "post", "text": text})
        told.add(quote_of.author_id)
    for m in (post.entities or {}).get("mentions") or []:
        uid = m.get("id")
        if uid and uid not in told:
            await social_notify.notify(db, uid, "at", actor_id=user.id, forum_post_id=post.id,
                                       data={"target": "post", "text": text})
            told.add(uid)


# ---------------- 编辑、删除、置顶 ----------------

async def edit_post(db: AsyncSession, user: User, p: ForumPost, text: str) -> None:
    """编辑:作者本人、发出 30 分钟内、最多 5 次;旧正文存历史(§5.6 F3)。
    **投票和图片不能改** —— 投过票的人不该发现自己投的是另一个问题。"""
    from .moderation import guard_text

    if p.author_id != user.id:
        raise HTTPException(403, "只能编辑自己的帖子")
    if p.status != "visible":
        raise HTTPException(409, "这条帖子已经删除或下架了")
    now = utcnow()
    if now - p.created_at > EDIT_WINDOW:
        raise HTTPException(409, f"发出 {int(EDIT_WINDOW.total_seconds() // 60)} 分钟内才能编辑")
    if p.edit_count >= EDIT_MAX:
        raise HTTPException(409, f"一条帖子最多编辑 {EDIT_MAX} 次")
    new_text = clean_text(text)
    if not new_text and not p.media and not p.card and p.quote_of_id is None:
        raise HTTPException(422, "正文不能删空")
    if new_text == p.text:
        return
    await guard_text(db, new_text, "帖子")
    db.add(ForumPostEdit(post_id=p.id, text=p.text, entities=p.entities or {}, created_at=now))
    entities = await parse_entities(db, new_text)
    p.text = new_text
    p.entities = entities
    p.edited_at = now
    p.edit_count = p.edit_count + 1
    # 话题、提及跟着正文走:改掉的话题不该还挂在帖子上(热门话题按 forum_post_tags 数)
    await db.execute(delete(ForumPostTag).where(ForumPostTag.post_id == p.id))
    await db.execute(delete(ForumMention).where(ForumMention.post_id == p.id))
    await _write_entities(db, p, entities, now)


async def delete_post(db: AsyncSession, user: User, p: ForumPost) -> None:
    """作者软删:下面的回复保留,这一条在串里显示「这条帖子已删除」(§5.6)。"""
    if p.author_id != user.id:
        raise HTTPException(403, "只能删自己的帖子")
    if p.status == "deleted":
        return
    p.status = "deleted"
    p.deleted_at = utcnow()
    await db.execute(delete(ForumPin).where(ForumPin.post_id == p.id))


async def set_pin(db: AsyncSession, user: User, p: ForumPost | None) -> None:
    """置顶到自己主页(每人一条);p 为 None 是取消。"""
    await db.execute(delete(ForumPin).where(ForumPin.user_id == user.id))
    if p is None:
        return
    if p.author_id != user.id:
        raise HTTPException(403, "只能置顶自己的帖子")
    if p.status != "visible":
        raise HTTPException(409, "这条帖子已经删除或下架了")
    db.add(ForumPin(user_id=user.id, post_id=p.id, created_at=utcnow()))


# ---------------- 赞、转发、书签、投票、浏览 ----------------

async def set_like(db: AsyncSession, user: User, p: ForumPost, like: bool) -> dict:
    if like:
        added = (await db.execute(
            insert(ForumLike).values(user_id=user.id, post_id=p.id, created_at=utcnow())
            .on_conflict_do_nothing().returning(ForumLike.user_id))).scalar()
        if added is not None:
            await db.execute(update(ForumPost).where(ForumPost.id == p.id)
                             .values(likes=ForumPost.likes + 1))
            await _notify_like(db, user, p)
    else:
        res = await db.execute(delete(ForumLike).where(ForumLike.user_id == user.id,
                                                       ForumLike.post_id == p.id))
        if res.rowcount:
            await db.execute(update(ForumPost).where(ForumPost.id == p.id)
                             .values(likes=func.greatest(ForumPost.likes - 1, 0)))
    likes = await db.scalar(select(func.count()).select_from(ForumLike)
                            .where(ForumLike.post_id == p.id))
    return {"liked": like, "likes": int(likes or 0)}


async def _notify_like(db: AsyncSession, user: User, p: ForumPost) -> None:
    """赞按帖子合并:「小王等 12 人赞了你的帖子」,不是 12 行(§5.8)。"""
    from . import social_notify

    n = await db.scalar(select(func.count()).select_from(ForumLike)
                        .where(ForumLike.post_id == p.id))
    await social_notify.notify(db, p.author_id, "like", actor_id=user.id, forum_post_id=p.id,
                               group_key=f"like:post:{p.id}", count=int(n or 1),
                               data={"target": "post"})


async def set_repost(db: AsyncSession, user: User, p: ForumPost, on: bool) -> dict:
    """转发(不带字)。带字的是引用 —— 那是一条新帖子,走 create_post。"""
    if on:
        if p.author_id != user.id and await blocked_between(db, user.id, p.author_id):
            raise HTTPException(403, "你们之间有拉黑关系")
        added = (await db.execute(
            insert(ForumRepost).values(user_id=user.id, post_id=p.id, created_at=utcnow())
            .on_conflict_do_nothing(index_elements=["user_id", "post_id"])
            .returning(ForumRepost.id))).scalar()
        if added is not None:
            await db.execute(update(ForumPost).where(ForumPost.id == p.id)
                             .values(reposts=ForumPost.reposts + 1))
            await _notify_repost(db, user, p)
    else:
        res = await db.execute(delete(ForumRepost).where(ForumRepost.user_id == user.id,
                                                         ForumRepost.post_id == p.id))
        if res.rowcount:
            await db.execute(update(ForumPost).where(ForumPost.id == p.id)
                             .values(reposts=func.greatest(ForumPost.reposts - 1, 0)))
    n = await db.scalar(select(func.count()).select_from(ForumRepost)
                        .where(ForumRepost.post_id == p.id))
    return {"reposted": on, "reposts": int(n or 0)}


async def _notify_repost(db: AsyncSession, user: User, p: ForumPost) -> None:
    from . import social_notify

    n = await db.scalar(select(func.count()).select_from(ForumRepost)
                        .where(ForumRepost.post_id == p.id))
    await social_notify.notify(db, p.author_id, "repost", actor_id=user.id, forum_post_id=p.id,
                               group_key=f"repost:post:{p.id}", count=int(n or 1),
                               data={"target": "post"})


async def set_bookmark(db: AsyncSession, user: User, p: ForumPost, on: bool) -> dict:
    """书签只有自己看得见(F2):不发通知,帖子上也不下发别人的书签数。"""
    if on:
        added = (await db.execute(
            insert(ForumBookmark).values(user_id=user.id, post_id=p.id, created_at=utcnow())
            .on_conflict_do_nothing().returning(ForumBookmark.user_id))).scalar()
        if added is not None:
            await db.execute(update(ForumPost).where(ForumPost.id == p.id)
                             .values(bookmarks=ForumPost.bookmarks + 1))
    else:
        res = await db.execute(delete(ForumBookmark).where(ForumBookmark.user_id == user.id,
                                                           ForumBookmark.post_id == p.id))
        if res.rowcount:
            await db.execute(update(ForumPost).where(ForumPost.id == p.id)
                             .values(bookmarks=func.greatest(ForumPost.bookmarks - 1, 0)))
    return {"bookmarked": on}


async def vote(db: AsyncSession, user: User, p: ForumPost, option: int) -> ForumPoll:
    """投票:每人一票、不能改(§5.6)。结束了不能再投。"""
    poll = await db.scalar(select(ForumPoll).where(ForumPoll.post_id == p.id)
                           .with_for_update().execution_options(populate_existing=True))
    if poll is None:
        raise HTTPException(404, "这条帖子没有投票")
    now = utcnow()
    if now >= poll.ends_at:
        raise HTTPException(409, "投票已经结束了")
    options = list(poll.options or [])
    if not (0 <= option < len(options)):
        raise HTTPException(422, "没有这个选项")
    added = (await db.execute(
        insert(ForumPollVote).values(post_id=p.id, user_id=user.id, option=option,
                                     created_at=now)
        .on_conflict_do_nothing().returning(ForumPollVote.user_id))).scalar()
    if added is None:
        raise HTTPException(409, "你已经投过票了,不能改")
    options[option] = {**options[option], "votes": int(options[option].get("votes", 0)) + 1}
    poll.options = options
    poll.total = poll.total + 1
    return poll


def viewer_key(user_id: int | None, device_id: str | None) -> str:
    """浏览去重的键:登录了按账号,没登录按设备号的哈希(和视频播放去重一个写法)。"""
    if user_id:
        return f"u{user_id}"
    h = hashlib.sha256((device_id or "").encode()).hexdigest()[:32]
    return f"d{h}"


async def record_views(db: AsyncSession, user: User | None, pids: list[str],
                       device_id: str | None) -> int:
    """浏览批量上报:按人按天去重(F5)。返回真的记上的条数。

    按请求算的话刷新一次涨一次,那个数是虚的;按人按天算,「浏览 120」说的是 120 个人看过。
    """
    pids = [p for p in dict.fromkeys(pids or []) if PID_RE.match(p or "")][:VIEW_PIDS_MAX]
    if not pids:
        return 0
    key = viewer_key(user.id if user else None, device_id)
    if key == "d" + hashlib.sha256(b"").hexdigest()[:32]:
        return 0  # 没登录又不给设备号:去重键会把所有人并成一个,不如不记
    day = vsvc.bj_day()
    rows = list(await db.scalars(select(ForumPost).where(ForumPost.pid.in_(pids),
                                                         ForumPost.status == "visible")))
    n = 0
    for p in rows:
        added = (await db.execute(
            insert(ForumViewDay).values(post_id=p.id, day=day, viewer_key=key,
                                        created_at=utcnow())
            .on_conflict_do_nothing().returning(ForumViewDay.post_id))).scalar()
        if added is not None:
            await db.execute(update(ForumPost).where(ForumPost.id == p.id)
                             .values(views=ForumPost.views + 1))
            n += 1
    return n


# ---------------- 屏蔽词、个人设置 ----------------

def clean_word(word: str) -> str:
    w = " ".join((word or "").split()).lower()
    if not w:
        raise HTTPException(422, "屏蔽词不能为空")
    if len(w) > MUTE_WORD_MAX:
        raise HTTPException(422, f"屏蔽词最多 {MUTE_WORD_MAX} 字")
    return w


async def mute_words(db: AsyncSession, user_id: int) -> list[str]:
    return list(await db.scalars(select(ForumMuteWord.word)
                                 .where(ForumMuteWord.user_id == user_id)
                                 .order_by(ForumMuteWord.created_at.desc())))


async def add_mute_word(db: AsyncSession, user_id: int, word: str) -> list[str]:
    w = clean_word(word)
    n = await db.scalar(select(func.count()).select_from(ForumMuteWord)
                        .where(ForumMuteWord.user_id == user_id))
    if (n or 0) >= MUTE_WORDS_MAX:
        raise HTTPException(422, f"屏蔽词最多 {MUTE_WORDS_MAX} 个")
    await db.execute(insert(ForumMuteWord).values(user_id=user_id, word=w,
                                                  created_at=utcnow())
                     .on_conflict_do_nothing())
    return await mute_words(db, user_id)


async def remove_mute_word(db: AsyncSession, user_id: int, word: str) -> list[str]:
    await db.execute(delete(ForumMuteWord).where(ForumMuteWord.user_id == user_id,
                                                 ForumMuteWord.word == clean_word(word)))
    return await mute_words(db, user_id)


async def settings_of(db: AsyncSession, user_id: int) -> ForumUserSetting:
    row = await db.get(ForumUserSetting, user_id)
    if row is None:
        row = ForumUserSetting(user_id=user_id, personalize=True)
        db.add(row)
        await db.flush()
    return row


# ---------------- 举报、下架、申诉 ----------------

async def report(db: AsyncSession, user: User, p: ForumPost, reason_code: str,
                 note: str) -> ForumReport:
    if reason_code not in reason_codes():
        raise HTTPException(422, "原因代码不存在(见 §5.11)")
    r = ForumReport(reporter_id=user.id, post_id=p.id, reason_code=reason_code,
                    note=(note or "")[:500], status="open", created_at=utcnow())
    db.add(r)
    return r


async def take_down(db: AsyncSession, p: ForumPost, admin: User, reason_code: str, note: str,
                    note_internal: str = "") -> ForumDecision:
    """下架(§3.6)。原因代码必填,X999 要写说明;作者收到 system 互动消息,可以申诉一次。"""
    reason_ok(reason_code, note)
    if p.status == "removed":
        raise HTTPException(409, "这条帖子已经下架了")
    if p.status == "deleted":
        raise HTTPException(409, "这条帖子作者已经删了")
    now = utcnow()
    p.status = "removed"
    p.removed_code = reason_code
    await db.execute(delete(ForumPin).where(ForumPin.post_id == p.id))
    d = ForumDecision(post_id=p.id, admin_id=admin.id, action="remove", reason_code=reason_code,
                      note=(note or "")[:500], note_internal=(note_internal or "")[:500],
                      created_at=now)
    db.add(d)
    await db.flush()
    await _notify_author(db, p, "帖子已下架",
                         f"你的帖子因「{reason_codes()[reason_code]}」被下架。有异议可以申诉一次。",
                         action="removed", reason_code=reason_code)
    return d


async def restore(db: AsyncSession, p: ForumPost, admin: User, note: str) -> ForumDecision:
    """恢复(下架撤销 / 申诉改判)。"""
    if p.status != "removed":
        raise HTTPException(409, "这条帖子不是下架状态")
    p.status = "visible"
    p.removed_code = ""
    d = ForumDecision(post_id=p.id, admin_id=admin.id, action="restore", reason_code="",
                      note=(note or "")[:500], created_at=utcnow())
    db.add(d)
    await db.flush()
    await _notify_author(db, p, "帖子已恢复", "你的帖子经复核已经恢复显示。", action="restored")
    return d


async def _notify_author(db: AsyncSession, p: ForumPost, title: str, text: str, *,
                         action: str, reason_code: str = "") -> None:
    from . import social_notify

    await social_notify.system(db, p.author_id, title, text, forum_post_id=p.id, action=action,
                               reason_code=reason_code,
                               extra={"pid": p.pid, "target": "post"})


async def appealable(db: AsyncSession, p: ForumPost) -> ForumDecision | None:
    """这条帖子最近一次能申诉的下架决定(还没申诉过的)。每个决定只能申诉一次(§5.6)。"""
    return await db.scalar(select(ForumDecision).where(
        ForumDecision.post_id == p.id, ForumDecision.action == "remove",
        ForumDecision.appeal_result == "").order_by(ForumDecision.id.desc()).limit(1))


async def appeal(db: AsyncSession, user: User, p: ForumPost, text: str) -> ForumDecision:
    if p.author_id != user.id:
        raise HTTPException(403, "只有作者能申诉")
    t = (text or "").strip()
    if not (APPEAL_MIN <= len(t) <= APPEAL_MAX):
        raise HTTPException(422, f"申诉理由 {APPEAL_MIN}–{APPEAL_MAX} 字")
    d = await appealable(db, p)
    if d is None:
        raise HTTPException(409, "没有可以申诉的下架决定(每个决定只能申诉一次)")
    d.appeal_text = t[:APPEAL_MAX]
    d.appeal_at = utcnow()
    d.appeal_result = "open"
    return d


async def resolve_appeal(db: AsyncSession, d: ForumDecision, admin: User, *, overturn: bool,
                         note: str) -> ForumDecision:
    """处理申诉。**原审核人不能复核自己的决定**(换人复核,和视频一样 403)。"""
    if d.appeal_result != "open":
        raise HTTPException(409, "这条申诉已经处理过了")
    if d.admin_id is not None and d.admin_id == admin.id:
        raise HTTPException(403, "不能复核自己作出的决定,换个人处理")
    d.appeal_result = "overturned" if overturn else "upheld"
    d.appeal_by = admin.id
    d.appeal_note = (note or "")[:500]
    p = await db.get(ForumPost, d.post_id) if d.post_id else None
    if p is not None:
        if overturn:
            if p.status == "removed":
                await restore(db, p, admin, note or "申诉改判")
        else:
            await _notify_author(db, p, "申诉结果:维持原处理",
                                 f"复核后维持下架。{(note or '').strip()}".strip(),
                                 action="appeal_upheld", reason_code=p.removed_code)
    return d


async def hide_tag(db: AsyncSession, tag: ForumTag, admin: User, *, hidden: bool,
                   reason_code: str, note: str) -> ForumDecision:
    """热门话题隐藏 / 取消隐藏。**运营能隐藏但要写原因、留痕**(§2.2,不偷偷压话题)。

    隐藏只是不上热门榜:话题页照样能打开,帖子照样在。
    """
    if hidden:
        reason_ok(reason_code, note)
    tag.hidden = hidden
    tag.hidden_code = reason_code if hidden else ""
    d = ForumDecision(tag_id=tag.id, admin_id=admin.id,
                      action="tag_hide" if hidden else "tag_unhide",
                      reason_code=reason_code if hidden else "", note=(note or "")[:500],
                      created_at=utcnow())
    db.add(d)
    await db.flush()
    return d


# ---------------- 注销与清扫 ----------------

async def purge_user(db: AsyncSession, user_id: int) -> None:
    """注销账号时的论坛部分(§3.7)。调用方负责提交。

    - 他发的帖子:正文、实体、图片、卡片清空并标删除 —— 下面别人的回复留着,但这个人说过的话没了
      (和视频评论同一个口径:不让别人的串凭空断掉);
    - 他点的赞 / 转发 / 书签 / 投票 / 置顶 / 屏蔽词 / 浏览记录 / 设置都删,受影响的帖子重算计数;
    - 举报记录本身是平台的处置依据,留着,只清掉他写的说明。
    """
    now = utcnow()
    touched: set[int] = set()
    mine = list(await db.scalars(select(ForumPost.id).where(ForumPost.author_id == user_id)))
    if mine:
        # 他回复过、引用过的帖子要重算 replies / quotes
        touched |= set(await db.scalars(select(ForumPost.reply_to_id).where(
            ForumPost.id.in_(mine), ForumPost.reply_to_id.is_not(None)).distinct()))
        touched |= set(await db.scalars(select(ForumPost.quote_of_id).where(
            ForumPost.id.in_(mine), ForumPost.quote_of_id.is_not(None)).distinct()))
        await db.execute(update(ForumPost).where(ForumPost.id.in_(mine)).values(
            text="", entities={}, media=[], card=None, status="deleted",
            deleted_at=func.coalesce(ForumPost.deleted_at, now)))
        await db.execute(delete(ForumPostTag).where(ForumPostTag.post_id.in_(mine)))
        await db.execute(delete(ForumMention).where(ForumMention.post_id.in_(mine)))
        await db.execute(delete(ForumPostEdit).where(ForumPostEdit.post_id.in_(mine)))
    touched |= set(await db.scalars(select(ForumLike.post_id)
                                    .where(ForumLike.user_id == user_id)))
    touched |= set(await db.scalars(select(ForumRepost.post_id)
                                    .where(ForumRepost.user_id == user_id)))
    touched |= set(await db.scalars(select(ForumBookmark.post_id)
                                    .where(ForumBookmark.user_id == user_id)))
    await db.execute(delete(ForumLike).where(ForumLike.user_id == user_id))
    await db.execute(delete(ForumRepost).where(ForumRepost.user_id == user_id))
    await db.execute(delete(ForumBookmark).where(ForumBookmark.user_id == user_id))
    await db.execute(delete(ForumPin).where(ForumPin.user_id == user_id))
    await db.execute(delete(ForumMuteWord).where(ForumMuteWord.user_id == user_id))
    await db.execute(delete(ForumUserSetting).where(ForumUserSetting.user_id == user_id))
    await db.execute(delete(ForumMention).where(ForumMention.user_id == user_id))
    await db.execute(delete(ForumViewDay).where(ForumViewDay.viewer_key == f"u{user_id}"))
    # 投票:他投过的票撤掉,选项计数跟着减(不然「5 人投了」里有一个已注销的幽灵)
    for v in list(await db.scalars(select(ForumPollVote)
                                   .where(ForumPollVote.user_id == user_id))):
        poll = await db.scalar(select(ForumPoll).where(ForumPoll.post_id == v.post_id)
                               .with_for_update().execution_options(populate_existing=True))
        if poll is not None:
            options = list(poll.options or [])
            if 0 <= v.option < len(options):
                options[v.option] = {**options[v.option],
                                     "votes": max(0, int(options[v.option].get("votes", 0)) - 1)}
                poll.options = options
            poll.total = max(0, poll.total - 1)
    await db.execute(delete(ForumPollVote).where(ForumPollVote.user_id == user_id))
    await db.execute(update(ForumReport).where(ForumReport.reporter_id == user_id).values(note=""))
    await _recount(db, {t for t in touched if t} - set(mine))


async def _recount(db: AsyncSession, post_ids: set[int]) -> None:
    """按明细表重算计数列(计数列只是展示用的累计数,真值在明细表里)。"""
    for pid in post_ids:
        p = await db.get(ForumPost, pid)
        if p is None:
            continue
        p.likes = int(await db.scalar(select(func.count()).select_from(ForumLike)
                                      .where(ForumLike.post_id == pid)) or 0)
        p.reposts = int(await db.scalar(select(func.count()).select_from(ForumRepost)
                                        .where(ForumRepost.post_id == pid)) or 0)
        p.bookmarks = int(await db.scalar(select(func.count()).select_from(ForumBookmark)
                                          .where(ForumBookmark.post_id == pid)) or 0)
        p.replies = int(await db.scalar(select(func.count()).select_from(ForumPost).where(
            ForumPost.reply_to_id == pid, ForumPost.status == "visible")) or 0)
        p.quotes = int(await db.scalar(select(func.count()).select_from(ForumPost).where(
            ForumPost.quote_of_id == pid, ForumPost.status == "visible")) or 0)


async def export_rows(db: AsyncSession, user_id: int) -> list[dict]:
    """数据导出里的论坛部分(§3.7「导出拿得全」):自己发过的帖子,新的在前。"""
    rows = list(await db.scalars(select(ForumPost).where(ForumPost.author_id == user_id)
                                 .order_by(ForumPost.created_at.desc()).limit(10000)))
    by_id = {p.id: p for p in rows}
    parents = {p.reply_to_id for p in rows if p.reply_to_id} - set(by_id)
    if parents:
        for p in await db.scalars(select(ForumPost).where(ForumPost.id.in_(parents))):
            by_id[p.id] = p
    out = []
    for p in rows:
        out.append({
            "pid": p.pid,
            "text": p.text,
            "media": [m.get("url") for m in (p.media or [])],
            "card": p.card,
            "reply_to": by_id[p.reply_to_id].pid if p.reply_to_id in by_id else None,
            "quote_of": by_id[p.quote_of_id].pid if p.quote_of_id in by_id else None,
            "status": p.status,
            "counts": {"replies": p.replies, "reposts": p.reposts, "quotes": p.quotes,
                       "likes": p.likes, "views": p.views},
            "edited_at": iso(p.edited_at),
            "created_at": iso(p.created_at),
            "link": f"{PUBLIC_BASE}/forum/p/{p.pid}",
        })
    return out


async def sweep_forum(now: datetime | None = None) -> dict[str, int]:
    """清扫:结束的投票给作者和投过票的人发 system;浏览去重表只留 8 天。

    `closed_notified` 是幂等标记 —— auto_flow 每 30 秒一轮,不防重会一直发。
    """
    from ..db import SessionLocal
    from . import social_notify

    now = now or utcnow()
    closed = 0
    async with SessionLocal() as db:
        due = list(await db.scalars(select(ForumPoll).where(
            ForumPoll.ends_at <= now, ForumPoll.closed_notified.is_(False))
            .with_for_update(skip_locked=True).execution_options(populate_existing=True)
            .limit(100)))
        for poll in due:
            poll.closed_notified = True
            p = await db.get(ForumPost, poll.post_id)
            if p is None or p.status != "visible":
                continue
            voters = set(await db.scalars(select(ForumPollVote.user_id)
                                          .where(ForumPollVote.post_id == poll.post_id)))
            text = " ".join((p.text or "").split())[:40]
            for uid in {p.author_id} | voters:
                await social_notify.system(
                    db, uid, "投票已结束",
                    f"「{text}」的投票结束了,共 {poll.total} 人参与,点开看结果。",
                    forum_post_id=p.id, action="poll_closed",
                    extra={"pid": p.pid, "target": "post"})
            closed += 1
        await db.commit()
        await db.execute(delete(ForumViewDay).where(
            ForumViewDay.created_at < now - timedelta(days=VIEW_KEEP_DAYS)))
        await db.commit()
    return {"polls_closed": closed}


# ---------------- 下发形状(§8.1)----------------

async def poll_out(db: AsyncSession, poll: ForumPoll | None, p: ForumPost,
                   viewer_id: int | None) -> dict | None:
    """投票那一格。**没投过、没结束、又不是作者时,每项的 votes 和 total 是 null** ——
    投票前看不到结果(和 X 一样):先看到大家怎么投的,后投的人就跟着走了。"""
    if poll is None:
        return None
    now = utcnow()
    closed = now >= poll.ends_at
    voted = None
    if viewer_id:
        row = await db.get(ForumPollVote, (p.id, viewer_id))
        voted = row.option if row is not None else None
    show = closed or voted is not None or viewer_id == p.author_id
    options = [{"text": o.get("text", ""),
                "votes": int(o.get("votes", 0)) if show else None}
               for o in (poll.options or [])]
    return {"options": options, "total": poll.total if show else None,
            "ends_at": iso(poll.ends_at), "closed": closed, "voted": voted}


def entities_out(p: ForumPost, hidden: set[int]) -> dict:
    """实体。@ 到的人里现在关着「按超级赞号找到我」的拿掉(当普通文字显示)。"""
    e = p.entities or {}
    return {"tags": list(e.get("tags") or []),
            "mentions": [m for m in (e.get("mentions") or [])
                         if isinstance(m, dict) and m.get("id") not in hidden],
            "links": list(e.get("links") or [])}
