"""媒体文件与分片上传(DEV-PROMPTS-40 §7「媒体」,#341)。

聊天里的图片、视频、文件、语音,视频投稿的原片和转码产物,贴纸 —— 全部是一行 media_files。
**聊天媒体一律进私密桶**,下载每次判「是不是这个媒体所在会话的成员」(S1);
公开的只有贴纸、视频封面这类本来就给所有人看的东西。
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

MEDIA_KINDS = ("photo", "video", "file", "voice", "video_note", "sticker", "gif", "cover",
               "avatar", "video_source")


class MediaFile(Base):
    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                 nullable=True, index=True)
    #: 用途:chat / video / sticker / avatar(判权按它分流,见 services/media.can_read)
    purpose: Mapped[str] = mapped_column(String(12), default="chat")
    private: Mapped[bool] = mapped_column(default=True)
    key: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(12))
    mime: Mapped[str] = mapped_column(String(80), default="application/octet-stream")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    w: Mapped[int] = mapped_column(Integer, default=0)
    h: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    thumb_key: Mapped[str] = mapped_column(String(200), default="")
    #: 语音波形:64 个 0–31 的整数
    waveform: Mapped[list] = mapped_column(JSONB, default=list)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(200), default="")
    #: ready / processing / failed
    status: Mapped[str] = mapped_column(String(12), default="ready")
    error: Mapped[str] = mapped_column(String(300), default="")
    #: 转码产物等附加信息(聊天视频的原片 key、GIF 转出来的 mp4……)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    __table_args__ = (Index("ix_media_files_status", "status"),)


class Upload(Base):
    """分片上传(断点续传)。片先落本地临时目录,收齐后拼起来进对象存储。24 小时没传完就清掉。"""

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(12), default="chat")
    size: Mapped[int] = mapped_column(BigInteger)
    chunk_size: Mapped[int] = mapped_column(Integer)
    #: 已收到的片号
    received: Mapped[list] = mapped_column(JSONB, default=list)
    mime: Mapped[str] = mapped_column(String(80), default="")
    name: Mapped[str] = mapped_column(String(200), default="")
    #: open / done / failed
    status: Mapped[str] = mapped_column(String(8), default="open")
    media_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
