"""视频模块的媒体判权(services/media.can_read 在 purpose == "video" 时调这里)。

purpose=video 的媒体有三种:投稿原片(kind=video_source)、UP 主上传的封面(kind=cover)、
转码时自动截的封面候选(kind=cover)。上传者本人在 media.can_read 里已经放行了,走到这里的是别人:

- 审核员:能看(D10「审核中 UP 主自己能看、审核员能看」);
- 已发布、公开 / 不公开(仅链接)稿件**正在用的封面**:能看(本来就复制到了公开桶);
- 其余一律不能看 —— 原片永远只给上传者和审核员,播放走转码后的档位(/video/v1/vod,另有判权)。
"""
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MediaFile, User, UserRole, Video


async def can_read_video_media(db: AsyncSession, user: User | None, mf: MediaFile) -> bool:
    if user is not None and user.role == UserRole.admin:
        return True
    if mf.kind != "cover":
        return False
    # 只问「有没有」,不取行里的数据,所以不需要排序
    hit = await db.scalar(select(Video.id).where(
        Video.cover_media_id == mf.id, Video.deleted_at.is_(None),
        Video.status == "published", or_(Video.visibility == "public",
                                         Video.visibility == "unlisted")).limit(1))
    return hit is not None
