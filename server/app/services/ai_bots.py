"""AI 机器人:让社区有人说话(#385)。

## 立场

**只做明确的机器人,不做假装成人的号**(用户 2026-09-16 定)。这几个号:

- 是 `role=bot` 的账号,客户端本来就挂「机器人」标;`users.is_ai` 再标一层,
  名片上出 AI 标(《标识办法》要的显式标识);
- **互动不进任何公开榜单和推荐权重**(见 forum_feed / video_feed / music_rank 里那几道闸)——
  推荐公式是公开可复算的,自己刷自己等于自己骗自己;
- 走的是**和真人一模一样的发帖路径**(`forum.create_post`):违禁词、先审后发、举报、
  下架、封号全都照样管得到。没有任何"内部通道"。

## 它们做什么

两件事,都很克制:

1. **发帖**:按自己的人设和兴趣话题,每天几条;
2. **回帖**:回真人发的帖 —— 这才是让社区"有人"的那部分。
   **只回公开的原帖,每条帖最多回一次,不主动私聊任何人。**

## 频率靠"上次什么时候"卡,不靠计数器

计数器要跨进程同步、要考虑重启清零;而"距离上次发帖够不够久"是从库里读一个时间戳,
重启、多进程都不影响。每天几条 → 最小间隔 = 24 小时 ÷ 条数。
"""
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AiPersona, ForumPost, User
from . import ai

logger = logging.getLogger("superz.ai.bots")

#: 一轮最多让几个号说话。**不是"把该说的都说完"** —— 一轮吐出二十条,
#: 时间线上会出现一整屏机器人,那比空着更难看
MAX_PER_TICK = 2

#: 回帖时从多近的帖子里挑。太旧的帖子下面冒出一条回复很突兀
REPLY_WINDOW_HOURS = 12

#: 挑候选时最多看多少条,从里面随机挑一条 —— 不总是回最新那条
REPLY_POOL = 30


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def due(last: datetime | None, per_day: int, now: datetime) -> bool:
    """距离上次够久了没有。per_day <= 0 = 这一项关着。"""
    if per_day <= 0:
        return False
    if last is None:
        return True
    return now - last >= timedelta(hours=24) / per_day


def post_prompt(p: AiPersona) -> str:
    """让它发一条。**不给它看别人的帖子** —— 这是"自己说点什么",不是复读。"""
    topics = [t.strip() for t in (p.topics or "").split(",") if t.strip()]
    pick = random.choice(topics) if topics else "身边的小事"
    return (f"以「{pick}」为由头,发一条你自己的动态。"
            f"一两句话,像在本地生活社区里随口说的,不要标题、不要话题标签、不要表情符号堆砌,"
            f"不要提到自己是机器人(页面上已经标了)。只输出正文。")


def reply_prompt(p: AiPersona, text: str) -> str:
    return (f"有人发了这样一条动态:\n「{text[:300]}」\n\n"
            f"以你的身份回一句。**只回一句**,像真的在聊天,不要复述对方说的话、"
            f"不要用「作为一个…」开头、不要客套。只输出你要说的话。")


async def _say(db: AsyncSession, persona: AiPersona, prompt: str) -> str:
    r = await ai.complete(db, prompt, system=persona.persona or "")
    if not r.ok:
        logger.info("AI 号 %s 没生成出来:%s", persona.user_id, r.error)
    return r.text


async def _publish(db: AsyncSession, persona: AiPersona, text: str,
                   reply_to: str | None = None) -> ForumPost | None:
    """走**和真人一样的**发帖路径。违禁词、先审后发、处罚在那条路上照样生效。"""
    from fastapi import HTTPException

    from . import forum

    user = await db.get(User, persona.user_id)
    if user is None:
        return None
    body: dict = {"text": text}
    if reply_to:
        body["reply_to_pid"] = reply_to
    try:
        return await forum.create_post(db, user, body)
    except HTTPException as e:
        # 撞违禁词、被禁言、开关关了 —— 都不该让整轮停下来
        logger.info("AI 号 %s 发不出去(%s):%s", persona.user_id, e.status_code, e.detail)
        return None


async def _pick_target(db: AsyncSession, persona: AiPersona, now: datetime) -> ForumPost | None:
    """挑一条真人的原帖来回。

    三条限制,缺一不可:
    - **只回真人的**(作者不是 AI):AI 之间互相回会滚成一片没人看的对话;
    - 只回原帖,不回回复:不然会在一条串里越接越长;
    - **这条帖它自己还没回过**:同一条下面冒出两句同一个机器人的话,是最出戏的。
    """
    since = now - timedelta(hours=REPLY_WINDOW_HOURS)
    mine = select(ForumPost.reply_to_id).where(ForumPost.author_id == persona.user_id,
                                               ForumPost.reply_to_id.is_not(None))
    rows = list(await db.scalars(
        select(ForumPost)
        .join(User, User.id == ForumPost.author_id)
        .where(ForumPost.created_at >= since, ForumPost.status == "visible",
               ForumPost.reply_to_id.is_(None), ForumPost.author_id != persona.user_id,
               User.is_ai.is_(False), ForumPost.id.not_in(mine))
        .order_by(ForumPost.created_at.desc()).limit(REPLY_POOL)))
    return random.choice(rows) if rows else None


async def tick(db: AsyncSession, *, now: datetime | None = None) -> int:
    """跑一轮。返回发了几条。**关着、没配、没人设,都是安静地什么都不做。**"""
    from .flags import forum_flag_on

    now = now or utcnow()
    if not await _on(db):
        return 0
    if not await ai.configured(db):
        return 0
    if not await forum_flag_on(db, "forum_post_enabled"):
        # 论坛都停笔了,AI 更不该在这时候说话
        return 0
    personas = list(await db.scalars(
        select(AiPersona).where(AiPersona.active.is_(True)).order_by(AiPersona.user_id)))
    random.shuffle(personas)
    done = 0
    for p in personas:
        if done >= MAX_PER_TICK:
            break
        if await _act(db, p, now):
            done += 1
    return done


async def _on(db: AsyncSession) -> bool:
    from ..models import PlatformFlag

    flag = await db.get(PlatformFlag, "ai_bots_enabled")
    # **缺省关**:没人拨过这个开关,一个字都不发
    return flag is not None and flag.value == "on"


async def _act(db: AsyncSession, p: AiPersona, now: datetime) -> bool:
    """这个号这一轮做点什么。**回帖优先于发帖** —— 有人说话的社区比有人自言自语的社区活。"""
    if due(p.last_reply_at, p.replies_per_day, now):
        target = await _pick_target(db, p, now)
        if target is not None:
            text = await _say(db, p, reply_prompt(p, target.text or ""))
            if text and await _publish(db, p, text, reply_to=target.pid) is not None:
                p.last_reply_at = now
                return True
    if due(p.last_post_at, p.posts_per_day, now):
        text = await _say(db, p, post_prompt(p))
        if text and await _publish(db, p, text) is not None:
            p.last_post_at = now
            return True
    return False


async def create(db: AsyncSession, owner: User, *, name: str, username: str, persona: str,
                 topics: str = "", posts_per_day: int = 2,
                 replies_per_day: int = 5) -> AiPersona:
    """建一个 AI 号。走的是普通机器人那条路,再标上 `is_ai`。调用方提交。"""
    from . import bots

    bot, _token = await bots.create_bot(db, owner, name, username, system=True)
    user = await db.get(User, bot.user_id)
    if user is not None:
        user.is_ai = True          # 名片上的 AI 标、榜单里的那几道闸都看它
    bot.about = persona[:120]
    row = AiPersona(user_id=bot.user_id, persona=persona, topics=topics,
                    posts_per_day=posts_per_day, replies_per_day=replies_per_day,
                    active=True)
    db.add(row)
    await db.flush()
    logger.info("建了 AI 号 %s(@%s)", bot.user_id, username)
    return row
