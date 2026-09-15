"""音乐模块的媒体判权(services/media.can_read 在 purpose == "music" 时调这里)。

purpose=music 的媒体有两种:歌曲的原始音频(kind=audio_source)、作品封面(kind=cover)。
上传者本人在 media.can_read 里已经放行了,走到这里的是别人:

- 审核员:能看(§3.3「没过审的作品除了作者本人和管理员谁也拿不到」的另一半 —— 审核得看得见);
- 其余一律不能看。**原始音频永远只给作者和审核员**:它是无损 / 高码率的源文件,
  给出去就等于把版权方的母带发出去了;听歌走转码后的档位(/music/v1/stream,另有签名和判权)。
- 过审作品的封面不在这里放行:过审时封面已经复制进公开桶(services/music.publish_cover),
  客户端拿到的是 /img/… 的公开地址,根本不会走媒体判权这条路。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MediaFile, User, UserRole


async def can_read_music_media(db: AsyncSession, user: User | None, mf: MediaFile) -> bool:
    return user is not None and user.role == UserRole.admin
