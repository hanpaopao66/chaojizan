"""论坛接口 `/forum/v1`(DEV-PROMPTS-41 §8.3,#380)。接口参考:docs/FORUM-API.md。

路由只做三件事:取当前用户、调 services/forum*.py、提交。判定都在 service 里。

- 整个模块挂平台开关 `forum_enabled`(#380 §3.8):生产缺省关、开发 / CI 缺省开,
  关着回 503「论坛暂未开放」;发帖、回复、引用、编辑再挂 `forum_post_enabled`
  (「论坛发帖暂停中」)—— 出事时先停笔,不用把整个论坛关掉;
- 浏览类接口没登录也能用;写接口要登录、只对用户端账号开放(D1),而且一律走 social_user
  (封号在那里统一挡);发帖另过 sanctions 的 `forum_post` 执行点(禁言的人也发不了);
- 限流照 §5.10。
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import ForumPost, ForumTag, User
from ..ratelimit import (check_daily_limit, check_rate_limit, check_rate_limit_seconds)
from ..security import get_current_user_optional
from ..services import forum as fsvc
from ..services import forum_feed as feed
from ..services import forum_rank as rank
from ..services.flags import forum_flag_on
from ..services.social import SOCIAL_ROLES
from .social import social_user

FORUM_OFF = "论坛暂未开放"
POST_OFF = "论坛发帖暂停中"


async def forum_on(db: AsyncSession = Depends(get_db)) -> None:
    if not await forum_flag_on(db, "forum_enabled"):
        raise HTTPException(503, FORUM_OFF)


async def forum_post_on(db: AsyncSession = Depends(get_db)) -> None:
    if not await forum_flag_on(db, "forum_post_enabled"):
        raise HTTPException(503, POST_OFF)


async def viewer_optional(user: User | None = Depends(get_current_user_optional)) -> User | None:
    """没登录 = None。商家、骑手这些角色也当没登录处理(论坛只在用户端开放,D1)。"""
    if user is None or user.role not in SOCIAL_ROLES:
        return None
    return user


router = APIRouter(prefix="/forum/v1", tags=["论坛"], dependencies=[Depends(forum_on)])


# ---------------- 限流(§5.10)----------------

async def _post_limit(db: AsyncSession, user: User) -> None:
    """发帖(含回复、引用):每 10 秒 1 条、每小时 60 条、每天 300 条。"""
    from ..services.sanctions import check_user

    await check_user(db, user.id, "forum_post")
    await check_rate_limit_seconds("forum_post", str(user.id), 1, 10, "发得太快了,歇一下再发")
    await check_rate_limit_seconds("forum_post_h", str(user.id), 60, 3600,
                                   "这一小时发得太多了,歇一会儿")
    await check_daily_limit("forum_post", str(user.id), 300, "今天发的帖子太多了,明天再来")


async def _act_limit(user: User) -> None:
    """赞、转发、书签:每人每秒 5 次。"""
    await check_rate_limit_seconds("forum_act", str(user.id), 5, 1, "点得太快了,歇一下")


# =====================================================================
# 时间线
# =====================================================================

@router.get("/timeline/foryou")
async def timeline_foryou(page: int = 0, me: User | None = Depends(viewer_optional),
                          db: AsyncSession = Depends(get_db)):
    """推荐(§5.7 公开公式)。每屏 20 条、同一作者最多 2 条;每条带 rank 和 why。"""
    return await feed.foryou(db, me, feed.clamp_page(page))


@router.get("/timeline/following")
async def timeline_following(cursor: str | None = None, me: User = Depends(social_user),
                             db: AsyncSession = Depends(get_db)):
    """关注的人的帖子和转发,按事件时间倒序。"""
    return await feed.following(db, me, cursor)


# =====================================================================
# 帖子
# =====================================================================

class PollIn(BaseModel):
    options: list[str] = Field(min_length=2, max_length=4)
    minutes: int


class MediaIn(BaseModel):
    url: str = Field(max_length=300)
    w: int = 0
    h: int = 0


class CardIn(BaseModel):
    type: str = Field(max_length=16)
    id: str = Field(max_length=40)


class PostIn(BaseModel):
    text: str = Field(default="", max_length=fsvc.TEXT_MAX)
    media: list[MediaIn] | None = Field(default=None, max_length=fsvc.MEDIA_MAX)
    card: CardIn | None = None
    quote_pid: str | None = None
    reply_to_pid: str | None = None
    poll: PollIn | None = None
    reply_policy: Literal["all", "following", "mentioned"] = "all"


@router.post("/posts", dependencies=[Depends(forum_post_on)])
async def create_post(body: PostIn, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    """发帖 / 回复 / 引用(§5.6)。实体由服务端解析,客户端报的不算数。"""
    await _post_limit(db, me)
    p = await fsvc.create_post(db, me, body.model_dump())
    await db.commit()
    v = await feed.viewer_of(db, me)
    return (await feed.posts_out(db, v, [p]))[0]


@router.get("/posts/{pid}")
async def get_post(pid: str, me: User | None = Depends(viewer_optional),
                   db: AsyncSession = Depends(get_db)):
    """帖子详情 + 上文(看不见的那几条在串里占位,不是消失)。"""
    p = await fsvc.viewable(db, pid, me)
    return await feed.thread(db, me, p)


@router.get("/posts/{pid}/replies")
async def get_replies(pid: str, sort: Literal["top", "new"] = "top", cursor: str | None = None,
                      me: User | None = Depends(viewer_optional),
                      db: AsyncSession = Depends(get_db)):
    p = await fsvc.viewable(db, pid, me)
    return await feed.replies(db, me, p, sort, cursor)


class EditIn(BaseModel):
    text: str = Field(default="", max_length=fsvc.TEXT_MAX)


@router.patch("/posts/{pid}", dependencies=[Depends(forum_post_on)])
async def edit_post(pid: str, body: EditIn, me: User = Depends(social_user),
                    db: AsyncSession = Depends(get_db)):
    """编辑:发出 30 分钟内、最多 5 次,留历史,显示「已编辑」(§5.6 F3)。"""
    from ..services.sanctions import check_user

    await check_user(db, me.id, "forum_post")
    p = await fsvc.get_post(db, pid, lock=True)
    await fsvc.edit_post(db, me, p, body.text)
    await db.commit()
    v = await feed.viewer_of(db, me)
    return (await feed.posts_out(db, v, [p]))[0]


@router.get("/posts/{pid}/edits")
async def post_edits(pid: str, me: User | None = Depends(viewer_optional),
                     db: AsyncSession = Depends(get_db)):
    """编辑历史:谁都看得到(留历史才让「已编辑」这个标记有意义)。"""
    from sqlalchemy import select

    from ..models import ForumPostEdit

    p = await fsvc.viewable(db, pid, me)
    rows = list(await db.scalars(select(ForumPostEdit).where(ForumPostEdit.post_id == p.id)
                                 .order_by(ForumPostEdit.id)))
    return {"items": [{"text": r.text, "created_at": fsvc.iso(r.created_at)} for r in rows]}


@router.delete("/posts/{pid}")
async def delete_post(pid: str, me: User = Depends(social_user),
                      db: AsyncSession = Depends(get_db)):
    p = await fsvc.get_post(db, pid, lock=True)
    await fsvc.delete_post(db, me, p)
    await db.commit()
    return {"ok": True}


# ---------------- 赞、转发、书签 ----------------

@router.post("/posts/{pid}/like")
async def like(pid: str, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    p = await fsvc.viewable(db, pid, me)
    out = await fsvc.set_like(db, me, p, True)
    await db.commit()
    return out


@router.delete("/posts/{pid}/like")
async def unlike(pid: str, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    p = await fsvc.get_post(db, pid)
    out = await fsvc.set_like(db, me, p, False)
    await db.commit()
    return out


@router.post("/posts/{pid}/repost")
async def repost(pid: str, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    p = await fsvc.viewable(db, pid, me)
    out = await fsvc.set_repost(db, me, p, True)
    await db.commit()
    return out


@router.delete("/posts/{pid}/repost")
async def unrepost(pid: str, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    p = await fsvc.get_post(db, pid)
    out = await fsvc.set_repost(db, me, p, False)
    await db.commit()
    return out


@router.post("/posts/{pid}/bookmark")
async def bookmark(pid: str, me: User = Depends(social_user),
                   db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    p = await fsvc.viewable(db, pid, me)
    out = await fsvc.set_bookmark(db, me, p, True)
    await db.commit()
    return out


@router.delete("/posts/{pid}/bookmark")
async def unbookmark(pid: str, me: User = Depends(social_user),
                     db: AsyncSession = Depends(get_db)):
    await _act_limit(me)
    p = await fsvc.get_post(db, pid)
    out = await fsvc.set_bookmark(db, me, p, False)
    await db.commit()
    return out


@router.get("/posts/{pid}/quotes")
async def post_quotes(pid: str, cursor: str | None = None,
                      me: User | None = Depends(viewer_optional),
                      db: AsyncSession = Depends(get_db)):
    p = await fsvc.viewable(db, pid, me)
    return await feed.quotes_of(db, me, p, cursor)


@router.get("/posts/{pid}/likers")
async def post_likers(pid: str, cursor: str | None = None,
                      me: User | None = Depends(viewer_optional),
                      db: AsyncSession = Depends(get_db)):
    p = await fsvc.viewable(db, pid, me)
    return await feed.likers_of(db, me, p, cursor)


# ---------------- 投票、浏览、置顶 ----------------

class VoteIn(BaseModel):
    option: int


@router.post("/posts/{pid}/vote")
async def vote(pid: str, body: VoteIn, me: User = Depends(social_user),
               db: AsyncSession = Depends(get_db)):
    """投票:每人一票、不能改。投票前看不到票数(§8.1)。"""
    await _act_limit(me)
    p = await fsvc.viewable(db, pid, me)
    poll = await fsvc.vote(db, me, p, body.option)
    await db.commit()
    return await fsvc.poll_out(db, poll, p, me.id)


class ViewsIn(BaseModel):
    pids: list[str] = Field(default_factory=list, max_length=fsvc.VIEW_PIDS_MAX)
    device_id: str | None = Field(default=None, max_length=64)


@router.post("/posts/views")
async def report_views(body: ViewsIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """浏览批量上报:按人按天去重(F5)。

    写接口一律走 social_user(§5.2);封号的人照样能报(§3.8 放行表)—— 他还能看,
    看了就该算数,不算反而让浏览数少得没道理。`device_id` 收着是为了和 §8.3 的形状一致,
    登录了就按账号去重,用不上它。
    """
    await check_rate_limit("forum_views", str(me.id), 120)
    n = await fsvc.record_views(db, me, body.pids, body.device_id)
    await db.commit()
    return {"ok": True, "counted": n}


@router.post("/posts/{pid}/pin")
async def pin(pid: str, me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    p = await fsvc.get_post(db, pid)
    await fsvc.set_pin(db, me, p)
    await db.commit()
    return {"ok": True}


# 取消置顶是 `DELETE /forum/v1/pin`(§8.3 表里写的就是 `DELETE /pin`):不挂在 /posts/ 下面,
# 不然 `/posts/pin` 会先被 `/posts/{pid}` 吃掉,变成「没有这条帖子」
@router.delete("/pin")
async def unpin(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    await fsvc.set_pin(db, me, None)
    await db.commit()
    return {"ok": True}


class AppealIn(BaseModel):
    text: str = Field(max_length=fsvc.APPEAL_MAX)


@router.post("/posts/{pid}/appeal")
async def appeal(pid: str, body: AppealIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    """申诉下架。每个决定只能申诉一次,复核换人(§5.6、§3.6)。"""
    p = await fsvc.get_post(db, pid)
    await fsvc.appeal(db, me, p, body.text)
    await db.commit()
    return {"ok": True}


# =====================================================================
# 个人主页、我的
# =====================================================================

@router.get("/users/{uid}/profile")
async def user_profile(uid: int, me: User | None = Depends(viewer_optional),
                       db: AsyncSession = Depends(get_db)):
    target = await db.get(User, uid)
    if target is None or target.deleted_at is not None or target.role not in SOCIAL_ROLES:
        raise HTTPException(404, "没有这个用户")
    return await feed.profile(db, me, target)


@router.get("/users/{uid}/posts")
async def user_posts(uid: int, tab: Literal["posts", "replies", "media", "likes"] = "posts",
                     cursor: str | None = None, me: User | None = Depends(viewer_optional),
                     db: AsyncSession = Depends(get_db)):
    return await feed.user_posts(db, me, uid, tab, cursor)


@router.get("/me/bookmarks")
async def my_bookmarks(cursor: str | None = None, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    return await feed.bookmarks(db, me, cursor)


class WordIn(BaseModel):
    word: str = Field(max_length=fsvc.MUTE_WORD_MAX)


@router.get("/me/mute-words")
async def get_mute_words(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    return {"items": await fsvc.mute_words(db, me.id)}


@router.post("/me/mute-words")
async def add_mute_word(body: WordIn, me: User = Depends(social_user),
                        db: AsyncSession = Depends(get_db)):
    items = await fsvc.add_mute_word(db, me.id, body.word)
    await db.commit()
    return {"items": items}


@router.delete("/me/mute-words")
async def remove_mute_word(word: str, me: User = Depends(social_user),
                           db: AsyncSession = Depends(get_db)):
    items = await fsvc.remove_mute_word(db, me.id, word)
    await db.commit()
    return {"items": items}


class SettingsIn(BaseModel):
    personalize: bool


@router.get("/me/settings")
async def get_settings(me: User = Depends(social_user), db: AsyncSession = Depends(get_db)):
    st = await fsvc.settings_of(db, me.id)
    await db.commit()
    return {"personalize": st.personalize}


@router.put("/me/settings")
async def put_settings(body: SettingsIn, me: User = Depends(social_user),
                       db: AsyncSession = Depends(get_db)):
    """个性化推荐开关。任何时候都能关(封号期间也放行,和视频的 S9 同一个立场)。"""
    st = await fsvc.settings_of(db, me.id)
    st.personalize = body.personalize
    await db.commit()
    return {"personalize": st.personalize}


# =====================================================================
# 话题、搜索、公式、举报
# =====================================================================

@router.get("/tags/trending")
async def tags_trending(db: AsyncSession = Depends(get_db)):
    """热门话题(§5.7)。运营隐藏的不上榜,但话题页照样能打开。"""
    return await feed.trending(db)


@router.get("/tags/{tag}/posts")
async def tag_posts(tag: str, sort: Literal["top", "new"] = "top", cursor: str | None = None,
                    page: int = 0, me: User | None = Depends(viewer_optional),
                    db: AsyncSession = Depends(get_db)):
    return await feed.tag_posts(db, me, tag, sort, cursor, page)


@router.get("/search")
async def search(q: str = "", type: Literal["posts", "users", "tags"] = "posts", page: int = 0,
                 me: User | None = Depends(viewer_optional),
                 db: AsyncSession = Depends(get_db)):
    await check_rate_limit("forum_search", str(me.id) if me else "anon", 60)
    return await feed.search(db, me, q, type, page)


@router.get("/rank/formula")
async def rank_formula():
    """推荐与热门话题的公式和全部参数(§3.5:公开、可复算)。"""
    return {"formula": rank.FORMULA, "params": rank.PARAMS}


@router.get("/reason-codes")
async def reason_codes():
    """举报、下架能用的原因代码(§5.11)。客户端举报弹窗照它摆。"""
    return {"items": [{"code": k, "label": v} for k, v in fsvc.reason_codes().items()]}


class ReportIn(BaseModel):
    pid: str
    reason_code: str = Field(max_length=8)
    note: str = Field(default="", max_length=500)


@router.post("/reports")
async def report(body: ReportIn, me: User = Depends(social_user),
                 db: AsyncSession = Depends(get_db)):
    """举报帖子。举报人对被举报的一方永远匿名。"""
    await check_rate_limit("forum_report", str(me.id), 10)
    p = await fsvc.get_post(db, body.pid)
    await fsvc.report(db, me, p, body.reason_code, body.note)
    await db.commit()
    return {"ok": True}
