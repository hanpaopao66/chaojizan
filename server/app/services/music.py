"""音乐的业务逻辑:音乐人、作品、歌曲、审核、申诉、播放签名、卡片、注销级联、清扫
(DEV-PROMPTS-41 #378,§5.1–§5.5、§5.11、§7.1、§8.2)。

路由(routers/music.py、routers/music_admin.py)只取当前用户、调这里、提交;判定都在这里。
听 / 喜欢 / 歌单 / 收藏 / 最近播放在 music_interact.py,评论在 music_talk.py,
榜单与推荐在 music_rank.py,转码在 music_media.py,状态机在 music_state.py。

**审核的单位是作品**(M3):单曲 / EP / 专辑连同里面的全部歌曲一起审。没过审的作品
除了作者本人和管理员,谁也拿不到详情、封面和播放地址(§3.3,一律 404 —— 不告诉你
「有这个作品但你看不了」)。过审后歌曲不能改,要改就下架重交。

**平台不收钱**(§3.1):这里没有付费单曲、数字专辑、打赏、会员、推广位。
**不要求实名**(§3.2):开通音乐人只要手机号账号,这个模块不引用 UserIdentity。
"""
import asyncio
import hashlib
import hmac
import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import (MediaFile, MusicArtist, MusicComment, MusicCommentLike, MusicDecision,
                      MusicHistory, MusicPlay, MusicPlaylist, MusicPlaylistCollect,
                      MusicPlaylistTrack, MusicRelease, MusicReleaseCollect, MusicReport,
                      MusicTrack, MusicTrackLike, MusicUserSetting, User, UserRole)
from ..state_machine import TransitionError
from . import music_state as ms
from . import storage
from .rt_events import after_commit
from .video import REASON_CODES as VIDEO_REASON_CODES
from .video import bj_day, bj_midnight, iso, people, utcnow

logger = logging.getLogger("superz.music")

# ---------------- 常量(公开写进 docs/MUSIC-API.md)----------------

#: 曲风。key 进库、名字给人看;客户端从 GET /music/v1/genres 拿,不自己写一份
GENRES: dict[str, str] = {
    "pop": "流行", "rock": "摇滚", "folk": "民谣", "electronic": "电子", "rap": "说唱",
    "rnb": "R&B", "jazz": "爵士", "classical": "古典", "country": "乡村", "metal": "金属",
    "punk": "朋克", "ancient": "古风", "acg": "动漫", "soundtrack": "影视原声",
    "world": "世界音乐", "kids": "儿童", "instrumental": "纯音乐", "other": "其他",
}
#: 语种(作品上填一个)
LANGUAGES: dict[str, str] = {
    "mandarin": "华语", "cantonese": "粤语", "english": "英语", "japanese": "日语",
    "korean": "韩语", "none": "无人声", "other": "其他",
}

#: 音乐自己的原因代码(§5.11),和视频共用 C1xx / X999
MUSIC_ONLY_CODES: dict[str, str] = {
    "M301": "非原创且没有授权(侵权)",
    "M302": "音频不完整(无声、截断、严重失真)",
    "M303": "歌名 / 封面 / 署名与内容不符",
    "M304": "歌词违规",
    "M305": "冒充其他音乐人",
}
#: 审核、下架、举报共用的一张表:视频的通用项 + 音乐自己的 + 其他
REASON_CODES: dict[str, str] = {
    **{k: v for k, v in VIDEO_REASON_CODES.items() if k.startswith("C")},
    **MUSIC_ONLY_CODES,
    "X999": VIDEO_REASON_CODES["X999"],
}
#: 版权投诉:必须留联系方式(M1)—— 侵权要联系得上投诉人
COPYRIGHT_CODE = "M301"

ARTIST_NAME_MIN, ARTIST_NAME_MAX = 2, 30
ARTIST_BIO_MAX = 500
TITLE_MAX = 60
DESC_MAX = 2000
LYRICS_MAX = 10000
#: 署名的四类角色(M 的「词曲编制作」)
CREDIT_ROLES = ("lyricist", "composer", "arranger", "producer")
CREDIT_NAMES_MAX = 10
CREDIT_NAME_MAX = 30
PLAYLIST_TITLE_MAX = 40
PLAYLIST_DESC_MAX = 500
PLAYLIST_TAGS_MAX = 5
#: 一个歌单最多 1000 首(§8.2)
PLAYLIST_TRACKS_MAX = 1000
#: 一个作品最多几首歌(专辑撑死几十首,给足余量)
RELEASE_TRACKS_MAX = 50
#: 最近播放每人留最近 300 首(§7.1)
HISTORY_KEEP = 300
#: music_plays 留 60 天(§7.1)
PLAYS_KEEP_DAYS = 60

#: 艺名里不许出现的词:冒充平台、官方、客服的(和小程序名字、超级赞号一个口径)。
#: 冒充其他音乐人靠举报(M2),这里只挡「冒充平台」这一类 —— 那是谁都不该占的名字
RESERVED_WORDS = ("超级赞", "官方", "客服", "管理员", "系统", "admin", "official", "superz",
                  "supperz", "staff")

PUBLIC_BASE = "https://chaojizan.cc"

#: 公开编号的前缀(§5.1)
PREFIXES = {"track": "mt", "release": "mr", "playlist": "mp", "artist": "ma"}
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ID_RE = {k: re.compile(rf"^{p}[1-9A-HJ-NP-Za-km-z]{{10}}$") for k, p in PREFIXES.items()}


def new_id(kind: str) -> str:
    """`mt` / `mr` / `mp` / `ma` + 10 位 base58 随机(§5.1):不暴露上传量,也不能按数字遍历。"""
    return PREFIXES[kind] + "".join(secrets.choice(_B58) for _ in range(10))


def valid_id(kind: str, value: str) -> bool:
    return bool(_ID_RE[kind].fullmatch(value or ""))


def link_of(kind: str, public_id: str) -> str:
    """站内链接(§5.1),分享卡片和聊天卡片用它。"""
    return f"{PUBLIC_BASE}/music/{PREFIXES[kind][1]}/{public_id}"


def reason_ok(code: str, note: str) -> None:
    """驳回、下架必须带原因代码;选 X999 必须写说明(和视频同一个口径)。"""
    if code not in REASON_CODES:
        raise HTTPException(422, "原因代码不存在(见 §5.11)")
    if code == "X999" and len((note or "").strip()) < 5:
        raise HTTPException(422, "选「X999 其他」必须写明原因(至少 5 个字)")


# ---------------- 判权 ----------------

def is_admin(user: User | None) -> bool:
    return user is not None and user.role == UserRole.admin


def release_visible(r: MusicRelease | None, artist: MusicArtist | None,
                    user: User | None) -> bool:
    """这个人能不能看这个作品(§3.3)。"""
    if r is None or r.deleted_at is not None:
        return False
    if user is not None and is_admin(user):
        return True
    if user is not None and artist is not None and artist.user_id == user.id:
        return True
    return r.status in ms.PUBLIC_STATUSES and (artist is None or artist.status != "suspended")


async def get_release(db: AsyncSession, rid: str, *, lock: bool = False) -> MusicRelease:
    if not valid_id("release", rid):
        raise HTTPException(404, "作品不存在或已删除")
    q = select(MusicRelease).where(MusicRelease.rid == rid)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    r = await db.scalar(q)
    if r is None or r.deleted_at is not None:
        raise HTTPException(404, "作品不存在或已删除")
    return r


async def viewable_release(db: AsyncSession, rid: str, user: User | None, *,
                           lock: bool = False) -> tuple[MusicRelease, MusicArtist]:
    r = await get_release(db, rid, lock=lock)
    artist = await db.get(MusicArtist, r.artist_id)
    if not release_visible(r, artist, user):
        # 没有、没过审、下架了 —— 一律 404,不告诉你「有这个作品但你看不了」
        raise HTTPException(404, "作品不存在或已删除")
    return r, artist


async def get_track(db: AsyncSession, tid: str, *, lock: bool = False) -> MusicTrack:
    if not valid_id("track", tid):
        raise HTTPException(404, "歌曲不存在或已删除")
    q = select(MusicTrack).where(MusicTrack.tid == tid)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    t = await db.scalar(q)
    if t is None:
        raise HTTPException(404, "歌曲不存在或已删除")
    return t


async def viewable_track(db: AsyncSession, tid: str,
                         user: User | None) -> tuple[MusicTrack, MusicRelease, MusicArtist]:
    t = await get_track(db, tid)
    r = await db.get(MusicRelease, t.release_id)
    artist = await db.get(MusicArtist, t.artist_id)
    if not release_visible(r, artist, user):
        raise HTTPException(404, "歌曲不存在或已删除")
    return t, r, artist


async def artist_of_user(db: AsyncSession, user_id: int) -> MusicArtist | None:
    return await db.scalar(select(MusicArtist).where(MusicArtist.user_id == user_id))


async def my_artist(db: AsyncSession, user: User) -> MusicArtist:
    a = await artist_of_user(db, user.id)
    if a is None:
        raise HTTPException(403, "还没有开通音乐人")
    if a.status == "suspended":
        raise HTTPException(403, "音乐人身份已被停用,有异议请联系客服")
    return a


async def own_release(db: AsyncSession, rid: str, artist: MusicArtist, *,
                      lock: bool = True) -> MusicRelease:
    r = await get_release(db, rid, lock=lock)
    if r.artist_id != artist.id:
        raise HTTPException(404, "作品不存在或已删除")
    return r


# ---------------- 播放地址(带绑定用户的签名,§5.5)----------------
#
# 和视频的 vod_sig 同一个办法,换一个命名空间:地址带 `?u=<用户,没登录是 0>&e=<到期>&s=<签名>`,
# **播放时照样按这个用户重新判权** —— 作品下架了、删了,旧地址立刻失效。
# 不登录也能听(M5),所以 u=0 也签得出来;有效期 6 小时。

STREAM_TTL_SECONDS = 6 * 3600


def _stream_key() -> bytes:
    return hashlib.sha256(f"superz-music-url:{settings.jwt_secret}".encode()).digest()


def stream_sig(tid: str, user_id: int, exp: int) -> str:
    return hmac.new(_stream_key(), f"{tid}:{user_id}:{exp}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def check_stream_sig(tid: str, user_id: int, exp: int, sig: str) -> bool:
    import time
    if exp < time.time():
        return False
    return hmac.compare_digest(stream_sig(tid, user_id, exp), sig or "")


def stream_expiry(now: datetime | None = None) -> int:
    return int((now or utcnow()).timestamp()) + STREAM_TTL_SECONDS


def stream_urls(t: MusicTrack, viewer_id: int | None, now: datetime | None = None) -> dict:
    """一首歌的播放地址(§8.2 的 `stream` 字段)。没有的档位是 null。"""
    exp = stream_expiry(now)
    uid = viewer_id or 0
    sig = stream_sig(t.tid, uid, exp)
    have = {r.get("q") for r in (t.renditions or [])}
    out: dict = {"expires_at": iso(datetime.fromtimestamp(exp, tz=timezone.utc))}
    for q in ("std", "hq"):
        out[q] = (f"/music/v1/stream/{t.tid}/{q}.m4a?u={uid}&e={exp}&s={sig}"
                  if q in have else None)
    return out


# ---------------- 卡片(§8.1,形状是规范性的)----------------

def track_card(t: MusicTrack, r: MusicRelease | None, a: MusicArtist | None,
               *, liked: bool = False) -> dict:
    return {
        "tid": t.tid,
        "title": t.title,
        "duration_ms": t.duration_ms,
        "cover": (r.cover_url or "") if r is not None else "",
        "explicit": bool(t.explicit),
        "genre": (r.genre or "") if r is not None else "",
        "genre_name": GENRES.get((r.genre or "") if r is not None else "", ""),
        "plays": t.plays,
        "likes": t.likes,
        "comments": t.comments,
        "liked": bool(liked),
        "artist": artist_brief(a) if a is not None else None,
        "release": ({"rid": r.rid, "title": r.title, "kind": r.kind}
                    if r is not None else None),
        "published_at": iso(r.published_at) if r is not None else None,
    }


def artist_brief(a: MusicArtist) -> dict:
    """列表里的音乐人简版(§8.1)。"""
    return {"aid": a.aid, "name": a.name, "avatar": a.avatar_url or "", "user_id": a.user_id}


def release_card(r: MusicRelease, a: MusicArtist | None, track_count: int = 0) -> dict:
    return {
        "rid": r.rid, "title": r.title, "kind": r.kind, "cover": r.cover_url or "",
        "artist": artist_brief(a) if a is not None else None,
        "track_count": track_count, "release_date": r.release_date.isoformat()
        if r.release_date else None,
        "collects": r.collects, "published_at": iso(r.published_at),
    }


def playlist_card(p: MusicPlaylist, owner: dict | None) -> dict:
    return {
        "pid": p.pid, "title": p.title, "cover": p.cover_url or "",
        "track_count": p.track_count, "collects": p.collects, "is_public": p.is_public,
        "owner": owner or {"id": p.owner_id, "name": "", "username": None, "avatar": ""},
        "tags": list(p.tags or []),
    }


def artist_card(a: MusicArtist, *, fans: int = 0, followed: bool = False,
                track_count: int = 0) -> dict:
    return {
        "aid": a.aid, "name": a.name, "bio": a.bio or "", "avatar": a.avatar_url or "",
        "cover": a.cover_url or "", "genres": list(a.genres or []), "user_id": a.user_id,
        "fans": fans, "followed": bool(followed), "track_count": track_count,
    }


async def track_cards(db: AsyncSession, viewer_id: int | None,
                      tracks: list[MusicTrack]) -> list[dict]:
    """一批歌的卡片(补上作品、音乐人、我喜欢没有)。一次查完,不在循环里查库。"""
    if not tracks:
        return []
    rel_ids = {t.release_id for t in tracks}
    art_ids = {t.artist_id for t in tracks}
    rels = {r.id: r for r in await db.scalars(
        select(MusicRelease).where(MusicRelease.id.in_(rel_ids)))}
    arts = {a.id: a for a in await db.scalars(
        select(MusicArtist).where(MusicArtist.id.in_(art_ids)))}
    liked: set[int] = set()
    if viewer_id:
        liked = set(await db.scalars(select(MusicTrackLike.track_id).where(
            MusicTrackLike.user_id == viewer_id,
            MusicTrackLike.track_id.in_([t.id for t in tracks]))))
    return [track_card(t, rels.get(t.release_id), arts.get(t.artist_id), liked=t.id in liked)
            for t in tracks]


async def playlist_cards(db: AsyncSession, viewer_id: int | None,
                         rows: list[MusicPlaylist]) -> list[dict]:
    owners = await people(db, viewer_id, [p.owner_id for p in rows])
    return [playlist_card(p, owners.get(p.owner_id)) for p in rows]


async def release_cards(db: AsyncSession, rows: list[MusicRelease]) -> list[dict]:
    if not rows:
        return []
    arts = {a.id: a for a in await db.scalars(
        select(MusicArtist).where(MusicArtist.id.in_({r.artist_id for r in rows})))}
    counts = dict((await db.execute(
        select(MusicTrack.release_id, func.count()).where(
            MusicTrack.release_id.in_([r.id for r in rows])).group_by(MusicTrack.release_id))).all())
    return [release_card(r, arts.get(r.artist_id), int(counts.get(r.id, 0))) for r in rows]


async def card_of(db: AsyncSession, type: str, public_id: str,
                  viewer_id: int | None) -> dict | None:
    """分享卡片(§5.9、§8.3 的 services/cards.py 注册进来的解析器)。

    `type ∈ track / release / playlist / artist`,看不到的一律返回 None ——
    没过审的作品、私密歌单、停用的音乐人都不许被转成卡片发出去。
    """
    viewer = await db.get(User, viewer_id) if viewer_id else None
    if type == "track":
        if not valid_id("track", public_id):
            return None
        t = await db.scalar(select(MusicTrack).where(MusicTrack.tid == public_id))
        if t is None:
            return None
        r = await db.get(MusicRelease, t.release_id)
        a = await db.get(MusicArtist, t.artist_id)
        if not release_visible(r, a, viewer) or r.status not in ms.PUBLIC_STATUSES:
            return None
        return {"type": "track", "id": t.tid, "title": t.title,
                "subtitle": a.name if a else "", "cover": r.cover_url or "",
                "url": link_of("track", t.tid)}
    if type == "release":
        if not valid_id("release", public_id):
            return None
        r = await db.scalar(select(MusicRelease).where(MusicRelease.rid == public_id))
        if r is None:
            return None
        a = await db.get(MusicArtist, r.artist_id)
        if not release_visible(r, a, viewer) or r.status not in ms.PUBLIC_STATUSES:
            return None
        return {"type": "release", "id": r.rid, "title": r.title,
                "subtitle": a.name if a else "", "cover": r.cover_url or "",
                "url": link_of("release", r.rid)}
    if type == "playlist":
        if not valid_id("playlist", public_id):
            return None
        p = await db.scalar(select(MusicPlaylist).where(MusicPlaylist.pid == public_id))
        if p is None or p.deleted_at is not None:
            return None
        if not p.is_public and p.owner_id != viewer_id:
            return None
        owner = (await people(db, viewer_id, [p.owner_id])).get(p.owner_id) or {}
        return {"type": "playlist", "id": p.pid, "title": p.title,
                "subtitle": f"{p.track_count} 首 · {owner.get('name', '')}".strip(" ·"),
                "cover": p.cover_url or "", "url": link_of("playlist", p.pid)}
    if type == "artist":
        if not valid_id("artist", public_id):
            return None
        a = await db.scalar(select(MusicArtist).where(MusicArtist.aid == public_id))
        if a is None or a.status != "active":
            return None
        return {"type": "artist", "id": a.aid, "title": a.name,
                "subtitle": (a.bio or "")[:40], "cover": a.avatar_url or "",
                "url": link_of("artist", a.aid)}
    return None


# ---------------- 对象存储的收尾 ----------------

def media_objects(mf: MediaFile) -> list[tuple[str, bool]]:
    out = [(k, mf.private) for k in (mf.key, mf.thumb_key) if k]
    src = (mf.meta or {}).get("source_key")
    if src and src != mf.key:
        out.append((src, mf.private))
    return out


def track_objects(t: MusicTrack) -> list[tuple[str, bool]]:
    return [(r["key"], True) for r in (t.renditions or []) if r.get("key")]


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


async def publish_cover(db: AsyncSession, r: MusicRelease) -> None:
    """过审:把封面复制到公开桶(/img/…)。审核中的封面只在私密桶里(§3.3)。"""
    if not r.cover_media_id:
        return
    mf = await db.get(MediaFile, r.cover_media_id)
    if mf is None or not mf.key:
        return
    data = await asyncio.to_thread(storage.read, mf.key, mf.private)
    if not data:
        return
    stored = await asyncio.to_thread(storage.save, data, ".jpg", "music_cover", r.artist_id)
    old = r.cover_url
    r.cover_url = stored.url
    if old and old != stored.url:
        remove_objects_after_commit(db, [(old.removeprefix("/img/"), False)])


def unpublish_cover(db: AsyncSession, r: MusicRelease) -> None:
    """下架 / 删除:公开桶里的封面跟着删,旧地址立刻失效。"""
    if r.cover_url:
        remove_objects_after_commit(db, [(r.cover_url.removeprefix("/img/"), False)])
    r.cover_url = ""


# ---------------- 音乐人(M2)----------------

def normalize_artist_name(name: str) -> str:
    return " ".join((name or "").split())


def name_lc(name: str) -> str:
    """艺名唯一性的判据:小写 + 去掉全部空白。「周杰伦」和「周 杰 伦」是同一个名字。"""
    return re.sub(r"\s+", "", (name or "")).lower()


def check_artist_name(name: str) -> str:
    n = normalize_artist_name(name)
    if not ARTIST_NAME_MIN <= len(n) <= ARTIST_NAME_MAX:
        raise HTTPException(422, f"艺名 {ARTIST_NAME_MIN}–{ARTIST_NAME_MAX} 个字")
    low = name_lc(n)
    for w in RESERVED_WORDS:
        if w.lower() in low:
            raise HTTPException(422, f"艺名里不能带「{w}」")
    return n


def check_genres(genres) -> list[str]:
    out = [g for g in dict.fromkeys(genres or []) if g in GENRES]
    if len(out) != len(list(dict.fromkeys(genres or []))):
        raise HTTPException(422, "有不认识的曲风(见 GET /music/v1/genres)")
    return out[:3]


async def open_artist(db: AsyncSession, user: User, name: str, bio: str,
                      genres: list[str] | None) -> MusicArtist:
    """开通音乐人。**不要求实名**(M2、§3.2),冒充走举报。"""
    from .moderation import guard_text

    if await artist_of_user(db, user.id) is not None:
        raise HTTPException(409, "你已经是音乐人了")
    n = check_artist_name(name)
    await guard_text(db, n, "艺名")
    bio = (bio or "").strip()[:ARTIST_BIO_MAX]
    if bio:
        await guard_text(db, bio, "音乐人简介")
    taken = await db.scalar(select(MusicArtist.id).where(MusicArtist.name_lc == name_lc(n)))
    if taken is not None:
        raise HTTPException(409, "这个艺名已经有人用了,换一个")
    a = MusicArtist(aid=new_id("artist"), user_id=user.id, name=n, name_lc=name_lc(n), bio=bio,
                    genres=check_genres(genres), status="active", created_at=utcnow())
    db.add(a)
    try:
        await db.flush()
    except Exception as e:      # 两个人同时提交同一个艺名:唯一索引拦下,给一句人话
        await db.rollback()
        raise HTTPException(409, "这个艺名已经有人用了,换一个") from e
    return a


async def edit_artist(db: AsyncSession, a: MusicArtist, body: dict) -> MusicArtist:
    from .moderation import guard_text

    if "name" in body and body["name"] is not None:
        n = check_artist_name(body["name"])
        if name_lc(n) != a.name_lc:
            await guard_text(db, n, "艺名")
            taken = await db.scalar(select(MusicArtist.id).where(
                MusicArtist.name_lc == name_lc(n), MusicArtist.id != a.id))
            if taken is not None:
                raise HTTPException(409, "这个艺名已经有人用了,换一个")
            a.name, a.name_lc = n, name_lc(n)
    if "bio" in body and body["bio"] is not None:
        bio = (body["bio"] or "").strip()[:ARTIST_BIO_MAX]
        if bio:
            await guard_text(db, bio, "音乐人简介")
        a.bio = bio
    if "genres" in body and body["genres"] is not None:
        a.genres = check_genres(body["genres"])
    for k, purpose in (("avatar_url", "music_cover"), ("cover_url", "music_cover")):
        if k in body and body[k] is not None:
            setattr(a, k, check_public_image(body[k], purpose))
    a.updated_at = utcnow()
    return a


_IMG_RE = re.compile(r"^/img/[A-Za-z0-9_./-]{3,280}$")


def check_public_image(url: str, purpose: str) -> str:
    """头像 / 横幅 / 歌单封面:只收本站公开桶的地址(POST /uploads 传上来的),不收外链。

    收外链等于让别人的服务器决定我们页面上显示什么,而且随时会 404 或被换成别的图。
    """
    u = (url or "").strip()
    if not u:
        return ""
    if not _IMG_RE.fullmatch(u):
        raise HTTPException(422, "图片地址不对,请用站内上传的图片")
    return u[:300]


# ---------------- 作品与歌曲(音乐人中心)----------------

def _check_editable(r: MusicRelease) -> None:
    if not ms.editable(r):
        raise HTTPException(409, f"「{ms.STATUS_LABELS.get(r.status, r.status)}」的作品不能改;"
                                 "已发布的要改请先下架")


async def create_release(db: AsyncSession, a: MusicArtist, body: dict) -> MusicRelease:
    from .moderation import guard_text

    title = " ".join((body.get("title") or "").split())[:TITLE_MAX]
    if not title:
        raise HTTPException(422, "作品名不能为空")
    await guard_text(db, title, "作品名")
    kind = body.get("kind") or "single"
    if kind not in ("single", "ep", "album"):
        raise HTTPException(422, "作品类型只能是 single / ep / album")
    genre = body.get("genre") or ""
    if genre and genre not in GENRES:
        raise HTTPException(422, "没有这个曲风")
    language = body.get("language") or ""
    if language and language not in LANGUAGES:
        raise HTTPException(422, "没有这个语种")
    desc = (body.get("description") or "").strip()[:DESC_MAX]
    if desc:
        await guard_text(db, desc, "作品简介")
    rd = body.get("release_date")
    if isinstance(rd, str):
        try:
            rd = date.fromisoformat(rd)
        except ValueError as e:
            raise HTTPException(422, "发行日期格式不对(YYYY-MM-DD)") from e
    r = MusicRelease(rid=new_id("release"), artist_id=a.id, title=title, kind=kind, genre=genre,
                     language=language, description=desc, release_date=rd, status="draft",
                     created_at=utcnow())
    if body.get("cover_media_id"):
        r.cover_media_id = await _own_media(db, a, int(body["cover_media_id"]), "cover")
    db.add(r)
    await db.flush()
    return r


async def _own_media(db: AsyncSession, a: MusicArtist, media_id: int, kind: str) -> int:
    """这份媒体是不是这位音乐人自己传的、用途对不对。别人的 media_id 一律 404。"""
    mf = await db.get(MediaFile, media_id)
    if mf is None or mf.owner_id != a.user_id or mf.purpose != "music" or mf.kind != kind:
        raise HTTPException(404, "没有这个文件")
    return mf.id


async def edit_release(db: AsyncSession, a: MusicArtist, r: MusicRelease, body: dict) -> None:
    from .moderation import guard_text

    _check_editable(r)
    if "title" in body and body["title"] is not None:
        title = " ".join(body["title"].split())[:TITLE_MAX]
        if not title:
            raise HTTPException(422, "作品名不能为空")
        await guard_text(db, title, "作品名")
        r.title = title
    if "kind" in body and body["kind"] is not None:
        if body["kind"] not in ("single", "ep", "album"):
            raise HTTPException(422, "作品类型只能是 single / ep / album")
        r.kind = body["kind"]
    if "genre" in body and body["genre"] is not None:
        if body["genre"] and body["genre"] not in GENRES:
            raise HTTPException(422, "没有这个曲风")
        r.genre = body["genre"]
    if "language" in body and body["language"] is not None:
        if body["language"] and body["language"] not in LANGUAGES:
            raise HTTPException(422, "没有这个语种")
        r.language = body["language"]
    if "description" in body and body["description"] is not None:
        desc = body["description"].strip()[:DESC_MAX]
        if desc:
            await guard_text(db, desc, "作品简介")
        r.description = desc
    if "release_date" in body and body["release_date"] is not None:
        rd = body["release_date"]
        if isinstance(rd, str):
            try:
                rd = date.fromisoformat(rd)
            except ValueError as e:
                raise HTTPException(422, "发行日期格式不对(YYYY-MM-DD)") from e
        r.release_date = rd
    if "cover_media_id" in body and body["cover_media_id"] is not None:
        r.cover_media_id = await _own_media(db, a, int(body["cover_media_id"]), "cover")
    r.updated_at = utcnow()


def clean_credits(credits) -> dict:
    """署名(词 / 曲 / 编 / 制作)。只认这四类,每类最多 10 个名字。"""
    out: dict[str, list[str]] = {}
    for role in CREDIT_ROLES:
        names = (credits or {}).get(role) or []
        if not isinstance(names, list):
            raise HTTPException(422, "署名格式不对")
        cleaned = [" ".join(str(n).split())[:CREDIT_NAME_MAX] for n in names]
        out[role] = [n for n in dict.fromkeys(cleaned) if n][:CREDIT_NAMES_MAX]
    return out


def detect_lyrics_kind(text: str) -> str:
    """歌词是 LRC(带时间轴)还是纯文本(M8)。有 `[mm:ss` 那样的时间标签就算 LRC。"""
    if not (text or "").strip():
        return "none"
    return "lrc" if re.search(r"^\s*\[\d{1,2}:\d{2}", text, re.M) else "plain"


async def add_track(db: AsyncSession, a: MusicArtist, r: MusicRelease, body: dict) -> MusicTrack:
    from ..workers.media import enqueue_after_commit
    from .moderation import guard_text

    _check_editable(r)
    n = int(await db.scalar(select(func.count()).select_from(MusicTrack).where(
        MusicTrack.release_id == r.id)) or 0)
    if n >= RELEASE_TRACKS_MAX:
        raise HTTPException(409, f"一个作品最多 {RELEASE_TRACKS_MAX} 首歌")
    title = " ".join((body.get("title") or "").split())[:TITLE_MAX]
    if not title:
        raise HTTPException(422, "歌名不能为空")
    await guard_text(db, title, "歌名")
    declaration = body.get("declaration") or ""
    if declaration not in ("original", "authorized"):
        raise HTTPException(422, "要勾选原创声明或已获授权声明(M1)")
    media_id = await _own_media(db, a, int(body.get("media_id") or 0), "audio_source")
    used = await db.scalar(select(MusicTrack.id).where(MusicTrack.source_media_id == media_id))
    if used is not None:
        raise HTTPException(409, "这个音频已经挂在别的歌上了")
    lyrics = (body.get("lyrics") or "")[:LYRICS_MAX]
    if lyrics.strip():
        await guard_text(db, lyrics, "歌词")
    credits = clean_credits(body.get("credits"))
    for role in CREDIT_ROLES:
        for nm in credits[role]:
            await guard_text(db, nm, "署名")
    mf = await db.get(MediaFile, media_id)
    t = MusicTrack(tid=new_id("track"), release_id=r.id, artist_id=a.id, title=title,
                   track_no=n + 1, duration_ms=(mf.duration_ms or 0) if mf else 0,
                   source_media_id=media_id, renditions=[], transcode_status="pending",
                   lyrics=lyrics, lyrics_kind=detect_lyrics_kind(lyrics), credits=credits,
                   explicit=bool(body.get("explicit")), declaration=declaration,
                   created_at=utcnow())
    db.add(t)
    await db.flush()
    r.updated_at = utcnow()
    enqueue_after_commit(db, {"type": "music_track", "track_id": t.id})
    return t


async def edit_track(db: AsyncSession, r: MusicRelease, t: MusicTrack, body: dict) -> None:
    from .moderation import guard_text

    _check_editable(r)
    if "title" in body and body["title"] is not None:
        title = " ".join(body["title"].split())[:TITLE_MAX]
        if not title:
            raise HTTPException(422, "歌名不能为空")
        await guard_text(db, title, "歌名")
        t.title = title
    if "lyrics" in body and body["lyrics"] is not None:
        lyrics = body["lyrics"][:LYRICS_MAX]
        if lyrics.strip():
            await guard_text(db, lyrics, "歌词")
        t.lyrics, t.lyrics_kind = lyrics, detect_lyrics_kind(lyrics)
    if "credits" in body and body["credits"] is not None:
        credits = clean_credits(body["credits"])
        for role in CREDIT_ROLES:
            for nm in credits[role]:
                await guard_text(db, nm, "署名")
        t.credits = credits
    if "explicit" in body and body["explicit"] is not None:
        t.explicit = bool(body["explicit"])
    if "declaration" in body and body["declaration"] is not None:
        if body["declaration"] not in ("original", "authorized"):
            raise HTTPException(422, "声明只能是 original / authorized")
        t.declaration = body["declaration"]
    t.updated_at = utcnow()


async def delete_track(db: AsyncSession, r: MusicRelease, t: MusicTrack) -> None:
    """删歌:行(评论、喜欢随外键级联)、转码产物、原文件的媒体行一起清。"""
    _check_editable(r)
    objs = track_objects(t)
    if t.source_media_id:
        mf = await db.get(MediaFile, t.source_media_id)
        if mf is not None:
            objs += media_objects(mf)
            await db.execute(delete(MediaFile).where(MediaFile.id == mf.id))
    await db.execute(delete(MusicTrack).where(MusicTrack.id == t.id))
    remove_objects_after_commit(db, objs)
    await renumber_tracks(db, r)


async def renumber_tracks(db: AsyncSession, r: MusicRelease,
                          order: list[str] | None = None) -> None:
    """重排曲序。order 给了就按它,否则按现在的 track_no 紧一遍(删了中间一首之后)。"""
    rows = list(await db.scalars(select(MusicTrack).where(MusicTrack.release_id == r.id)
                                 .order_by(MusicTrack.track_no, MusicTrack.id)))
    if order:
        by_tid = {t.tid: t for t in rows}
        if set(order) != set(by_tid):
            raise HTTPException(422, "新顺序必须正好是这个作品里的全部歌曲")
        rows = [by_tid[tid] for tid in order]
    for i, t in enumerate(rows, 1):
        t.track_no = i
    r.updated_at = utcnow()


async def tracks_of(db: AsyncSession, release_id: int) -> list[MusicTrack]:
    return list(await db.scalars(select(MusicTrack).where(MusicTrack.release_id == release_id)
                                 .order_by(MusicTrack.track_no, MusicTrack.id)))


async def delete_release(db: AsyncSession, r: MusicRelease) -> None:
    """音乐人删作品:软删,马上从所有地方消失;媒体当场清掉(不像视频等 30 天 ——
    没发布过的作品没有别人在看,留着只是占存储)。"""
    _check_editable(r)
    await purge_release_media(db, r)
    r.deleted_at = utcnow()


async def purge_release_media(db: AsyncSession, r: MusicRelease) -> None:
    objs: list[tuple[str, bool]] = []
    media_ids: list[int] = []
    for t in await tracks_of(db, r.id):
        objs += track_objects(t)
        if t.source_media_id:
            media_ids.append(t.source_media_id)
        t.renditions = []
    if r.cover_media_id:
        media_ids.append(r.cover_media_id)
    if media_ids:
        for mf in await db.scalars(select(MediaFile).where(MediaFile.id.in_(media_ids))):
            objs += media_objects(mf)
        await db.execute(delete(MediaFile).where(MediaFile.id.in_(media_ids)))
    r.cover_media_id = None
    unpublish_cover(db, r)
    remove_objects_after_commit(db, objs)


# ---------------- 提交与审核(§5.3)----------------

def _transition(r: MusicRelease, target: str, role: str) -> None:
    try:
        ms.transition(r, target, role)
    except TransitionError as e:
        raise HTTPException(403 if e.forbidden else 409, e.message) from e


async def check_submittable(db: AsyncSession, r: MusicRelease) -> list[MusicTrack]:
    """提交的前提(§5.3):至少 1 首歌、每首都转码完成、有封面、每首都勾了声明。"""
    tracks = await tracks_of(db, r.id)
    if not tracks:
        raise HTTPException(422, "作品里至少要有 1 首歌")
    pending = [t for t in tracks if t.transcode_status != "ready"]
    if pending:
        bad = [t for t in pending if t.transcode_status == "failed"]
        if bad:
            raise HTTPException(422, f"《{bad[0].title}》转码失败:{bad[0].fail_reason or '原因未知'};"
                                     "删掉重新上传一次")
        raise HTTPException(409, f"还有 {len(pending)} 首歌在转码,转完再提交")
    if not r.cover_media_id and not r.cover_url:
        raise HTTPException(422, "作品要有封面")
    if any(t.declaration not in ("original", "authorized") for t in tracks):
        raise HTTPException(422, "每首歌都要勾原创或已获授权的声明(M1)")
    return tracks


async def submit(db: AsyncSession, r: MusicRelease) -> None:
    await check_submittable(db, r)
    _transition(r, "reviewing", "artist")
    r.submitted_at = utcnow()
    r.reject_code, r.reject_note = "", ""


async def cancel_submit(db: AsyncSession, r: MusicRelease) -> None:
    _transition(r, "draft", "artist")


async def withdraw(db: AsyncSession, r: MusicRelease) -> None:
    """音乐人自己下架已发布的作品(§5.3)。封面从公开桶撤掉,播放地址立即失效。"""
    _transition(r, "withdrawn", "artist")
    unpublish_cover(db, r)


async def _notify(db: AsyncSession, r: MusicRelease, artist_user_id: int, title: str, text: str,
                  action: str, reason_code: str = "") -> None:
    from .social_notify import system

    await system(db, artist_user_id, title, text, music_release_id=r.id, action=action,
                 reason_code=reason_code, reason_label=REASON_CODES.get(reason_code, ""))


async def _record(db: AsyncSession, r: MusicRelease, action: str, admin: User | None, *,
                  reason_code: str = "", note: str = "") -> MusicDecision:
    d = MusicDecision(release_id=r.id, admin_id=admin.id if admin else None, action=action,
                      reason_code=reason_code, note=(note or "").strip()[:500],
                      created_at=utcnow())
    db.add(d)
    await db.flush()
    return d


async def decide(db: AsyncSession, r: MusicRelease, admin: User, *, approve: bool,
                 reason_code: str = "", note: str = "") -> MusicDecision:
    """审核:通过 / 驳回。驳回必须带原因代码,X999 必须写说明(§5.3)。"""
    if r.status != "reviewing":
        raise HTTPException(409, "这个作品不在审核中")
    artist = await db.get(MusicArtist, r.artist_id)
    if approve:
        _transition(r, "published", "admin")
        r.published_at = r.published_at or utcnow()
        r.reject_code, r.reject_note = "", ""
        await publish_cover(db, r)
        d = await _record(db, r, "approve", admin, note=note)
        await _notify(db, r, artist.user_id, "作品审核通过",
                      f"你的作品《{r.title}》审核通过了,已经上线", "approve")
    else:
        reason_ok(reason_code, note)
        _transition(r, "rejected", "admin")
        r.reject_code, r.reject_note = reason_code, (note or "").strip()[:500]
        d = await _record(db, r, "reject", admin, reason_code=reason_code, note=note)
        await _notify(db, r, artist.user_id, "作品未通过审核",
                      f"你的作品《{r.title}》未通过审核:{REASON_CODES[reason_code]}"
                      + (f"。{r.reject_note}" if r.reject_note else "")
                      + "。可以修改后重新提交,或者申诉", "reject", reason_code)
    return d


async def take_down(db: AsyncSession, r: MusicRelease, admin: User, reason_code: str,
                    note: str) -> MusicDecision:
    """平台下架。必须带原因;封面从公开桶撤掉,播放地址立即失效。"""
    reason_ok(reason_code, note)
    if r.status != "published":
        raise HTTPException(409, "只有已发布的作品能下架")
    artist = await db.get(MusicArtist, r.artist_id)
    _transition(r, "removed", "admin")
    r.reject_code, r.reject_note = reason_code, (note or "").strip()[:500]
    unpublish_cover(db, r)
    d = await _record(db, r, "remove", admin, reason_code=reason_code, note=note)
    await _notify(db, r, artist.user_id, "作品已被下架",
                  f"你的作品《{r.title}》因「{REASON_CODES[reason_code]}」被下架"
                  + (f":{r.reject_note}" if r.reject_note else "") + "。有异议可以申诉",
                  "remove", reason_code)
    return d


async def restore(db: AsyncSession, r: MusicRelease, admin: User, note: str) -> MusicDecision:
    """恢复被平台下架的作品(不是申诉,是平台自己改主意)。"""
    if r.status != "removed":
        raise HTTPException(409, "只有被平台下架的作品能恢复")
    artist = await db.get(MusicArtist, r.artist_id)
    _transition(r, "published", "admin")
    r.reject_code, r.reject_note = "", ""
    await publish_cover(db, r)
    d = await _record(db, r, "restore", admin, note=note)
    await _notify(db, r, artist.user_id, "作品已恢复",
                  f"你的作品《{r.title}》已经恢复上线" + (f":{note.strip()}" if note.strip() else ""),
                  "restore")
    return d


#: 能申诉的决定(§5.3):驳回和平台下架
APPEALABLE = ("reject", "remove")
APPEAL_MIN, APPEAL_MAX = 5, 500


async def last_appealable(db: AsyncSession, r: MusicRelease) -> MusicDecision | None:
    return await db.scalar(select(MusicDecision).where(
        MusicDecision.release_id == r.id, MusicDecision.action.in_(APPEALABLE))
        .order_by(MusicDecision.id.desc()).limit(1))


def appeal_still_valid(r: MusicRelease, d: MusicDecision) -> bool:
    """作品在这次决定之后又动过了,原决定就不适用了(改完重交比申诉快)。"""
    if d.action == "reject":
        return r.status == "rejected"
    if d.action == "remove":
        return r.status == "removed"
    return False


async def appeal(db: AsyncSession, r: MusicRelease, text: str) -> MusicDecision:
    """对最近一次驳回 / 下架申诉。**每个决定只能申诉一次**(§5.3)。"""
    text = (text or "").strip()
    if len(text) < APPEAL_MIN:
        raise HTTPException(422, f"申诉理由至少写 {APPEAL_MIN} 个字")
    d = await last_appealable(db, r)
    if d is None:
        raise HTTPException(409, "没有可以申诉的结论")
    if d.appeal_at is not None:
        raise HTTPException(409, "每个结论只能申诉一次")
    if not appeal_still_valid(r, d):
        raise HTTPException(409, "作品已经改过了,重新提交审核就好,不用申诉")
    d.appeal_text = text[:APPEAL_MAX]
    d.appeal_at = utcnow()
    return d


async def open_appeals(db: AsyncSession) -> list[MusicDecision]:
    return list(await db.scalars(select(MusicDecision).where(
        MusicDecision.appeal_at.is_not(None), MusicDecision.appeal_result == "")
        .order_by(MusicDecision.appeal_at)))


async def resolve_appeal(db: AsyncSession, d: MusicDecision, admin: User, *, overturn: bool,
                         note: str) -> MusicRelease:
    """处理申诉。**原决定是谁作出的,谁就不能处理**(§5.3)—— 自己复核自己等于没有申诉。"""
    if d.appeal_at is None:
        raise HTTPException(404, "这个决定没有申诉")
    if d.appeal_result:
        raise HTTPException(409, "这条申诉已经处理过了")
    if d.admin_id is not None and d.admin_id == admin.id:
        raise HTTPException(403, "原结论是你作出的,申诉必须由另一名审核员处理")
    note = (note or "").strip()
    if len(note) < 2:
        raise HTTPException(422, "写一句复核结论(会给音乐人看)")
    r = await db.scalar(select(MusicRelease).where(MusicRelease.id == d.release_id)
                        .with_for_update().execution_options(populate_existing=True))
    if r is None or r.deleted_at is not None:
        raise HTTPException(409, "作品已经删除了")
    artist = await db.get(MusicArtist, r.artist_id)
    if overturn:
        if not appeal_still_valid(r, d):
            raise HTTPException(409, "作品在申诉之后改过了,原结论已经不适用")
        _transition(r, "published", "appeal")
        r.published_at = r.published_at or utcnow()
        r.reject_code, r.reject_note = "", ""
        await publish_cover(db, r)
    d.appeal_result = "overturned" if overturn else "upheld"
    d.appeal_by = admin.id
    d.appeal_note = note[:500]
    await _notify(db, r, artist.user_id, "申诉结果",
                  (f"你对《{r.title}》的申诉成立,原结论已撤销" if overturn
                   else f"你对《{r.title}》的申诉经另一名审核员复核,维持原结论") + f":{note}",
                  "appeal_overturned" if overturn else "appeal_upheld")
    return r


# ---------------- 举报 ----------------

REPORT_ESCALATE_USERS = 3
REPORT_ESCALATE_WINDOW = timedelta(days=7)
REPORT_TARGETS = ("track", "release", "comment", "playlist", "artist")


async def create_report(db: AsyncSession, user: User, target_type: str, target_id: int,
                        reason_code: str, note: str, contact: str) -> MusicReport:
    """举报。版权投诉(M301)**必须留联系方式**(M1)—— 侵权要联系得上投诉人。"""
    if target_type not in REPORT_TARGETS:
        raise HTTPException(422, "举报对象不对")
    if reason_code not in REASON_CODES:
        raise HTTPException(422, "请选择举报原因")
    if reason_code == "X999" and len((note or "").strip()) < 5:
        raise HTTPException(422, "选「其他」要写明原因(至少 5 个字)")
    contact = (contact or "").strip()[:120]
    if reason_code == COPYRIGHT_CODE and len(contact) < 5:
        raise HTTPException(422, "版权投诉要留联系方式(邮箱或电话),我们要能找到你核实")
    from sqlalchemy import update as sql_update

    now = utcnow()
    since = now - REPORT_ESCALATE_WINDOW
    dup = await db.scalar(select(MusicReport).where(
        MusicReport.reporter_id == user.id, MusicReport.target_type == target_type,
        MusicReport.target_id == target_id, MusicReport.created_at >= since)
        .order_by(MusicReport.id.desc()).limit(1))
    if dup is not None:
        return dup
    r = MusicReport(reporter_id=user.id, target_type=target_type, target_id=target_id,
                    reason_code=reason_code, note=(note or "").strip()[:500], contact=contact,
                    status="open", created_at=now)
    db.add(r)
    await db.flush()
    n = await db.scalar(select(func.count(func.distinct(MusicReport.reporter_id))).where(
        MusicReport.target_type == target_type, MusicReport.target_id == target_id,
        MusicReport.created_at >= since))
    if (n or 0) >= REPORT_ESCALATE_USERS:
        await db.execute(sql_update(MusicReport).where(
            MusicReport.target_type == target_type, MusicReport.target_id == target_id,
            MusicReport.status == "open").values(status="escalated")
            .execution_options(synchronize_session=False))
        r.status = "escalated"
    return r


# ---------------- 音乐人主页与数据 ----------------

async def fans_of(db: AsyncSession, user_id: int) -> int:
    from ..models import Follow

    return int(await db.scalar(select(func.count()).select_from(Follow).where(
        Follow.followee_id == user_id)) or 0)


async def published_track_ids(db: AsyncSession, artist_id: int) -> list[int]:
    return list(await db.scalars(
        select(MusicTrack.id).join(MusicRelease, MusicRelease.id == MusicTrack.release_id)
        .where(MusicTrack.artist_id == artist_id, MusicRelease.status == "published",
               MusicRelease.deleted_at.is_(None))))


async def artist_stats(db: AsyncSession, a: MusicArtist, days: int = 30) -> dict:
    """音乐人的数据(§8.2 /studio/stats)。收听人数按 listener_key 去重。"""
    ids = await published_track_ids(db, a.id)
    if not ids:
        return {"plays": 0, "listeners": 0, "likes": 0, "fans": await fans_of(db, a.user_id),
                "per_day": [], "top_tracks": []}
    since = bj_midnight(bj_day() - timedelta(days=days - 1))
    plays = int(await db.scalar(select(func.count()).select_from(MusicPlay).where(
        MusicPlay.track_id.in_(ids), MusicPlay.created_at >= since)) or 0)
    listeners = int(await db.scalar(
        select(func.count(func.distinct(MusicPlay.listener_key))).where(
            MusicPlay.track_id.in_(ids), MusicPlay.created_at >= since)) or 0)
    likes = int(await db.scalar(select(func.count()).select_from(MusicTrackLike).where(
        MusicTrackLike.track_id.in_(ids))) or 0)
    rows = (await db.execute(
        select(MusicPlay.day, func.count(), func.count(func.distinct(MusicPlay.listener_key)))
        .where(MusicPlay.track_id.in_(ids), MusicPlay.created_at >= since)
        .group_by(MusicPlay.day).order_by(MusicPlay.day))).all()
    top = list(await db.scalars(select(MusicTrack).where(MusicTrack.id.in_(ids))
                                .order_by(MusicTrack.plays.desc(), MusicTrack.id).limit(10)))
    return {"plays": plays, "listeners": listeners, "likes": likes,
            "fans": await fans_of(db, a.user_id),
            "per_day": [{"day": d.isoformat(), "plays": int(p), "listeners": int(ls)}
                        for d, p, ls in rows],
            "top_tracks": await track_cards(db, a.user_id, top)}


# ---------------- 个人设置 ----------------

async def get_setting(db: AsyncSession, user_id: int) -> MusicUserSetting:
    s = await db.get(MusicUserSetting, user_id)
    if s is None:
        s = MusicUserSetting(user_id=user_id, personalize=True)
        db.add(s)
        await db.flush()
    return s


async def personalize_on(db: AsyncSession, user_id: int | None) -> bool:
    if not user_id:
        return False
    s = await db.get(MusicUserSetting, user_id)
    return True if s is None else bool(s.personalize)


# ---------------- 注销与清扫 ----------------

async def purge_user(db: AsyncSession, user_id: int) -> None:
    """注销账号时的音乐部分(§3.7):音乐人身份、作品、歌曲、媒体、歌单、喜欢、收听、
    最近播放、评论、举报说明全都处理掉。调用方负责提交。

    - 作品:删掉并**立即**清媒体(播放地址、封面地址当场失效);
    - 评论:清空正文、标成 deleted(楼中楼的结构留着,别人的回复不跟着消失);
    - 他点的喜欢 / 收藏、歌单、最近播放、收听明细、设置都删;
    - 受影响的歌按明细表重算计数。
    """
    from sqlalchemy import text as sql_text
    from sqlalchemy import update as sql_update

    now = utcnow()
    a = await artist_of_user(db, user_id)
    if a is not None:
        for r in list(await db.scalars(select(MusicRelease).where(
                MusicRelease.artist_id == a.id).with_for_update()
                .execution_options(populate_existing=True))):
            await purge_release_media(db, r)
            r.deleted_at = r.deleted_at or now
        # 作品、歌曲随外键级联;音乐人行留着会占掉艺名,直接删
        await db.execute(delete(MusicArtist).where(MusicArtist.id == a.id))
    # 上传了但还没挂到歌 / 作品上的音频、封面
    loose = list(await db.scalars(select(MediaFile).where(MediaFile.owner_id == user_id,
                                                          MediaFile.purpose == "music")))
    if loose:
        objs: list[tuple[str, bool]] = []
        for mf in loose:
            objs += media_objects(mf)
        await db.execute(delete(MediaFile).where(MediaFile.id.in_([m.id for m in loose])))
        remove_objects_after_commit(db, objs)
    touched: set[int] = set()
    touched |= set(await db.scalars(select(MusicComment.track_id).where(
        MusicComment.user_id == user_id).distinct()))
    root_ids = set(await db.scalars(select(MusicComment.root_id).where(
        MusicComment.user_id == user_id, MusicComment.root_id.is_not(None)).distinct()))
    await db.execute(sql_update(MusicComment).where(MusicComment.user_id == user_id)
                     .values(text="", mentions=[], status="deleted"))
    voted = set(await db.scalars(select(MusicCommentLike.comment_id).where(
        MusicCommentLike.user_id == user_id)))
    await db.execute(delete(MusicCommentLike).where(MusicCommentLike.user_id == user_id))
    if voted or root_ids:
        await db.execute(sql_text("""
            UPDATE music_comments c SET
              likes = (SELECT count(*) FROM music_comment_likes x WHERE x.comment_id = c.id),
              reply_count = (SELECT count(*) FROM music_comments r
                             WHERE r.root_id = c.id AND r.status = 'visible')
            WHERE c.id = ANY(:ids)"""), {"ids": list(voted | root_ids)})
    touched |= set(await db.scalars(select(MusicTrackLike.track_id).where(
        MusicTrackLike.user_id == user_id).distinct()))
    await db.execute(delete(MusicTrackLike).where(MusicTrackLike.user_id == user_id))
    touched |= set(await db.scalars(select(MusicPlaylistTrack.track_id).where(
        MusicPlaylistTrack.added_by == user_id).distinct()))
    for pl in list(await db.scalars(select(MusicPlaylist).where(
            MusicPlaylist.owner_id == user_id))):
        await db.execute(delete(MusicPlaylist).where(MusicPlaylist.id == pl.id))
    await db.execute(delete(MusicPlaylistCollect).where(MusicPlaylistCollect.user_id == user_id))
    await db.execute(delete(MusicReleaseCollect).where(MusicReleaseCollect.user_id == user_id))
    await db.execute(delete(MusicHistory).where(MusicHistory.user_id == user_id))
    await db.execute(delete(MusicPlay).where(MusicPlay.user_id == user_id))
    await db.execute(delete(MusicUserSetting).where(MusicUserSetting.user_id == user_id))
    # 他写的举报说明和联系方式清掉(举报记录本身是平台的处置依据,留着)
    await db.execute(sql_update(MusicReport).where(MusicReport.reporter_id == user_id)
                     .values(note="", contact=""))
    await _recount(db, touched)


async def _recount(db: AsyncSession, track_ids: set[int]) -> None:
    from sqlalchemy import text as sql_text

    if not track_ids:
        return
    await db.execute(sql_text("""
        UPDATE music_tracks t SET
          likes = (SELECT count(*) FROM music_track_likes x WHERE x.track_id = t.id),
          comments = (SELECT count(*) FROM music_comments c
                      WHERE c.track_id = t.id AND c.status = 'visible'),
          plays = (SELECT count(*) FROM music_plays p WHERE p.track_id = t.id)
        WHERE t.id = ANY(:ids)"""), {"ids": list(track_ids)})
    await db.execute(sql_text("""
        UPDATE music_playlists p SET
          track_count = (SELECT count(*) FROM music_playlist_tracks x
                         WHERE x.playlist_id = p.id),
          collects = (SELECT count(*) FROM music_playlist_collects x
                      WHERE x.playlist_id = p.id)
        WHERE p.deleted_at IS NULL"""))


async def sweep_music(now: datetime | None = None) -> dict[str, int]:
    """清扫(§3.7 的另一半):收听明细留 60 天;最近播放每人只留 300 首。"""
    from ..db import SessionLocal
    from sqlalchemy import text as sql_text

    now = now or utcnow()
    async with SessionLocal() as db:
        res = await db.execute(delete(MusicPlay).where(
            MusicPlay.created_at < now - timedelta(days=PLAYS_KEEP_DAYS)))
        plays = res.rowcount or 0
        # 超出 300 首的按 played_at 从旧到新截掉。一条 SQL 做完:
        # 拉回 Python 里逐人处理的话,活跃用户一多就是几万次往返
        trimmed = await db.execute(sql_text("""
            DELETE FROM music_history h USING (
              SELECT user_id, track_id, row_number() OVER (
                       PARTITION BY user_id ORDER BY played_at DESC, track_id DESC) AS rn
              FROM music_history) r
            WHERE h.user_id = r.user_id AND h.track_id = r.track_id AND r.rn > :keep"""),
            {"keep": HISTORY_KEEP})
        await db.commit()
    return {"plays_deleted": int(plays), "history_trimmed": int(trimmed.rowcount or 0)}


