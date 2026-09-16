"""站内卡片的解析(DEV-PROMPTS-41 §8.3「卡片解析」)。

帖子里带的卡片、聊天里的 `card` 消息(§5.9)存的都只有 `{type, id}` —— **标题、封面每次现查**,
不存快照:对象改了名、下了架、删了,卡片跟着变,不会留着一张骗人的旧封面。查不到就是
`{"type": …, "id": …, "unavailable": true}`,客户端显示「这条内容已不可见」。

为什么单独一个注册表,而不是在论坛里 if/else:

- 论坛、音乐、聊天是并行做的三块,谁也不该 import 谁的 service —— 各自在自己的模块里
  `cards.register("track", resolver)`,这里只认 `{type: 函数}`;
- 没注册的类型(音乐还没合并进来时的 `track`)返回 None,调用方给占位,**不报错** ——
  一个模块没上线不该让另一个模块的接口 500。

解析函数的签名:`async resolver(db, public_id, viewer_id) -> dict | None`,返回
`{"title", "subtitle", "cover", "url"}`(type、id 由这里补上)。
**只有公开可见的才给**(没过审的作品、私密歌单、删了 / 下架了的帖子一律 None)。
"""
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("superz.cards")

#: 站内链接的前缀(§5.1)
PUBLIC_BASE = "https://chaojizan.cc"

Resolver = Callable[[AsyncSession, str, int | None], Awaitable[dict | None]]

_RESOLVERS: dict[str, Resolver] = {}

#: 会话列表预览的前缀(§5.9)。加新类型时这里也要加一行,不然预览是「[] 标题」
TYPE_LABELS = {"track": "歌曲", "release": "专辑", "playlist": "歌单", "artist": "音乐人",
               "post": "帖子", "video": "视频"}


def register(type_: str, resolver: Resolver) -> None:
    """注册一种卡片。模块 import 时调一次(论坛在本文件末尾注册 video / post,
    音乐在 services/music.py 里注册它那四种)。"""
    _RESOLVERS[type_] = resolver


def known_types() -> tuple[str, ...]:
    """现在认得的卡片类型。接口校验 `card.type` 用它 —— 音乐没合并进来时不许发歌曲卡片,
    发了也只能显示占位。"""
    return tuple(_RESOLVERS)


async def resolve(db: AsyncSession, type_: str, id_: str, viewer_id: int | None) -> dict | None:
    """查一张卡片。查不到、没注册、解析函数炸了都返回 None(调用方给占位)。"""
    fn = _RESOLVERS.get(type_)
    if fn is None:
        return None
    try:
        out = await fn(db, id_, viewer_id)
    except Exception:
        # 一张卡片查不出来不该让整条时间线 500
        logger.warning("卡片解析失败 type=%s id=%s", type_, id_, exc_info=True)
        return None
    if out is None:
        return None
    return {"type": type_, "id": id_, "title": out.get("title", ""),
            "subtitle": out.get("subtitle", ""), "cover": out.get("cover", ""),
            "url": out.get("url", "")}


def placeholder(type_: str, id_: str) -> dict:
    """查不到时帖子里那一格的形状(§8.1)。"""
    return {"type": type_, "id": id_, "unavailable": True}


async def resolve_or_placeholder(db: AsyncSession, card: dict | None,
                                 viewer_id: int | None) -> dict | None:
    """帖子行上的 `card` 列 → 下发的那一格。没有卡片返回 None。"""
    if not card:
        return None
    type_, id_ = str(card.get("type") or ""), str(card.get("id") or "")
    if not type_ or not id_:
        return None
    return await resolve(db, type_, id_, viewer_id) or placeholder(type_, id_)


def preview(card: dict | None) -> str:
    """会话列表 / 引用里的一行预览:`[歌曲] 标题`(§5.9)。"""
    if not card:
        return ""
    label = TYPE_LABELS.get(str(card.get("type") or ""), "内容")
    if card.get("unavailable"):
        return f"[{label}] 已不可见"
    return f"[{label}] {card.get('title') or ''}".strip()


# ---------------- 视频 ----------------

async def _video_card(db: AsyncSession, vid: str, viewer_id: int | None) -> dict | None:
    from ..models import Video
    from sqlalchemy import select

    from . import video as vsvc

    v = await db.scalar(select(Video).where(Video.vid == vid))
    # 只有公开在架的视频能当卡片发出去:没过审的、私密的、删了的都当查不到
    if v is None or v.deleted_at is not None or v.status != "published" or \
            v.visibility != "public":
        return None
    up = (await vsvc.people(db, viewer_id, [v.uploader_id])).get(v.uploader_id)
    return {"title": v.title, "subtitle": (up or {}).get("name", ""), "cover": v.cover_url or "",
            "url": f"{PUBLIC_BASE}/v/{v.vid}"}


# ---------------- 帖子 ----------------

async def _post_card(db: AsyncSession, pid: str, viewer_id: int | None) -> dict | None:
    from sqlalchemy import select

    from ..models import ForumPost
    from . import video as vsvc

    p = await db.scalar(select(ForumPost).where(ForumPost.pid == pid))
    if p is None or p.status != "visible":
        return None
    # 拉黑关系:被作者拉黑的人看不到他的帖子,卡片也一样(§3.6)
    if viewer_id and viewer_id != p.author_id:
        from .social import blocked_between
        if await blocked_between(db, viewer_id, p.author_id):
            return None
    author = (await vsvc.people(db, viewer_id, [p.author_id])).get(p.author_id)
    text = " ".join((p.text or "").split())
    return {"title": text[:30] or "(图片 / 投票)", "subtitle": (author or {}).get("name", ""),
            "cover": (p.media or [{}])[0].get("url", "") if p.media else "",
            "url": f"{PUBLIC_BASE}/forum/p/{p.pid}"}


# ---------------- 音乐(#378 在 services/music.py 里实现,这里只注册)----------------
#
# 卡片解析表在这里,解析函数在各模块里:论坛不 import 音乐,音乐也不 import 论坛,
# 谁被关掉了另一边照样能跑(关掉那一类的卡片解析不出来,就是占位「内容已不可见」)。


def _register_music() -> None:
    from . import music

    for t in ("track", "release", "playlist", "artist"):
        register(t, _music_resolver(t, music))


def _music_resolver(type_: str, music):
    async def fn(db, id_: str, viewer_id: int | None):
        return await music.card_of(db, type_, id_, viewer_id)
    return fn


register("video", _video_card)
register("post", _post_card)
_register_music()
