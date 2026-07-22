"""内容审核:文本敏感词同步拦截 + 图片审核队列(先发后审)。

文本:词库存 moderation_words(管理后台维护),进程内缓存 60 秒,
朴素多串匹配(词库几百条规模足够,不值得上 Aho-Corasick)。
图片:照支付桩模式,green_* 配置后接三方机审;未配置时落
content_reviews 队列人工抽查——先发后审,驳回则隐藏并通知。
"""
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ContentReview, ModerationWord

logger = logging.getLogger("superz.moderation")

_cache: dict = {"words": [], "at": 0.0}
_CACHE_TTL = 60


async def _load_words(db: AsyncSession) -> list[str]:
    now = time.monotonic()
    if now - _cache["at"] > _CACHE_TTL:
        rows = await db.scalars(select(ModerationWord.word))
        _cache["words"] = [w for w in rows if w.strip()]
        _cache["at"] = now
    return _cache["words"]


def invalidate_cache() -> None:
    """管理后台增删词后立刻生效。"""
    _cache["at"] = 0.0


async def find_banned(db: AsyncSession, text: str) -> str | None:
    """返回命中的第一个敏感词;没有命中返回 None。"""
    if not text:
        return None
    lowered = text.lower()
    for word in await _load_words(db):
        if word.lower() in lowered:
            return word
    return None


async def guard_text(db: AsyncSession, text: str, scene: str = "内容") -> None:
    """命中敏感词直接 422(不透出词本身,避免教人绕)。"""
    from fastapi import HTTPException

    hit = await find_banned(db, text)
    if hit is not None:
        logger.info("敏感词拦截 scene=%s word=%s", scene, hit)
        raise HTTPException(422, f"{scene}包含不允许发布的内容,请修改后重试")


async def submit_images(db: AsyncSession, kind: str, ref_id: int,
                        urls: list[str]) -> None:
    """图片进审核队列(先发后审)。三方机审接入前 status 停在 pending,
    管理后台人工抽查;接入后这里改为调 API 直接给结论。
    调用方自行 commit(与主体写入同事务,失败一起回滚)。
    """
    for url in urls:
        if url and url.strip():
            db.add(ContentReview(kind=kind, ref_id=ref_id, url=url.strip()))
