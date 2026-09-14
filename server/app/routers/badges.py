"""标签和勋章的接口(判据、口径都在 services/badges.py)。

- `GET /transparency/badges`:勋章怎么发,公开、不用登录。读的是 services/badges.BADGES ——
  和发勋章用的是同一份定义,不另抄一份;
- `GET /social/v1/me/tags-badges`:我的标签和全部勋章(拿没拿到、隐没隐藏、每一枚的条件);
- `PATCH /social/v1/me/tags-badges`:改标签,隐藏 / 显示整组标签和每一枚勋章。

别人的标签和勋章跟着资料卡走:GET /social/v1/users/{id} 这类单人名片(services/social.user_card)
和 UP 主空间。会话列表、成员列表那些批量名片不带 —— 那些地方不显示它,也就不为它多查。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import User
from ..ratelimit import check_rate_limit
from ..services import badges
from ..services.moderation import find_banned
from ..services.social import ensure_profile
from .social import social_user

router = APIRouter(tags=["标签与勋章"])

#: 改标签每人每分钟几次(不合规的也算:屏蔽词不能拿这个接口一个个试)
TAGS_PER_MINUTE = 20


@router.get("/transparency/badges")
async def badges_public():
    """勋章怎么发:每一枚的名字、一句话条件、按哪份记录算、哪些不算、门槛;标签的规矩;平台不做的事。"""
    return badges.public_spec()


@router.get("/social/v1/me/tags-badges")
async def my_tags_badges(user: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    p = await ensure_profile(db, user.id)
    await db.commit()
    return await badges.settings_view(db, user, p)


class TagsBadgesPatch(BaseModel):
    #: 整组替换。条数、字数、重复、屏蔽词在下面逐条判,这里只挡离谱的大包
    tags: list[str] | None = Field(default=None, max_length=50)
    tags_hidden: bool | None = None
    #: {勋章 key: 是否对别人隐藏}。只改传了的那几枚;还没拿到的也能先设成隐藏
    hidden_badges: dict[str, bool] | None = None


@router.patch("/social/v1/me/tags-badges")
async def patch_tags_badges(body: TagsBadgesPatch, user: User = Depends(social_user),
                            db: AsyncSession = Depends(get_db)):
    """封号期间这个接口放行(services/sanctions.ACCOUNT_BAN_ALLOWED):隐藏是自我保护。
    但标签是给别人看的文字,改标签照样挡 —— 和 PATCH /social/v1/me 里的签名一个口径。"""
    p = await ensure_profile(db, user.id)
    if body.hidden_badges:
        unknown = sorted(k for k in body.hidden_badges if k not in badges.BADGE_KEYS)
        if unknown:
            raise HTTPException(422, f"没有这枚勋章:{unknown[0]}")
    if body.tags is not None:
        from ..services.sanctions import check_user
        await check_user(db, user.id, "social_write")
        await check_rate_limit("social_tags", str(user.id), TAGS_PER_MINUTE)
        tags, problem = badges.normalize_tags(body.tags)
        if problem:
            raise HTTPException(422, problem)
        # 屏蔽词和签名、用户名用同一个词库(services/moderation);只说第几个,不透出命中的词
        for i, t in enumerate(tags, 1):
            if await find_banned(db, t):
                raise HTTPException(422, f"第 {i} 个标签包含不允许使用的内容,换一个吧")
        p.tags = tags
    if body.tags_hidden is not None:
        p.tags_hidden = body.tags_hidden
    if body.hidden_badges:
        want = set(p.badges_hidden or [])
        for k, v in body.hidden_badges.items():
            if v:
                want.add(k)
            else:
                want.discard(k)
        # 整个换掉:JSONB 列原地改了 SQLAlchemy 看不出来
        p.badges_hidden = [k for k in badges.BADGE_KEYS if k in want]
    await db.commit()
    return await badges.settings_view(db, user, p)
