"""社交身份:资料、@用户名、联系人、拉黑(DEV-PROMPTS-40 #340)。

「消息」和「视频」共用这一套身份 —— 聊天里的你和 UP 主空间里的你是同一个人,
名字和头像沿用 `users.name` / `users.avatar_url`(头像照旧走图片审核队列),
这里只放 users 表没有的东西。

**没有手机号**(S2):别人看你的资料永远拿不到你的手机号,按手机号找人只返回
「找到的那个人」的资料,不回显号码。
"""
from datetime import date, datetime

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Integer,
                        String, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

#: 隐私项和缺省值(DEV-PROMPTS-40 §7)。取值 everyone / contacts / nobody。
#: 缺省和 Telegram 一样都是「所有人」:我们不做通讯录上传,「联系人」是用户
#: 自己一个个加的,缺省收紧成「联系人」的话新用户谁也找不到谁
PRIVACY_DEFAULTS: dict[str, str] = {
    "last_seen": "everyone",     # 最后上线时间
    "phone_search": "everyone",  # 谁能按完整手机号找到我
    "group_invite": "everyone",  # 谁能直接把我拉进群(不允许时对方只能发邀请链接)
    "calls": "everyone",         # 谁能给我打电话
    "forwards": "everyone",      # 我的消息被转发时,是否附带指向我的链接
    "avatar": "everyone",        # 谁能看到我的头像
}
PRIVACY_VALUES = ("everyone", "contacts", "nobody")

#: 通知缺省(D20):推送里显示「发送人:内容」;三类会话默认都提醒。
#: interactions*:「视频互动」机器人会话底部的「静音」「提醒设置」(设计稿 C)。互动提醒本来就不发系统推送,
#: 只亮 App 里的角标 —— interactions=false 是静音(角标变灰、不进底栏),其余四个是哪几类算未读。
#: 存在这里而不是手机上:换手机、网页版看到的是同一份设置
NOTIFY_DEFAULTS: dict[str, object] = {
    "preview": True,
    "private": True,
    "group": True,
    "channel": True,
    "interactions": True,
    "interactions_reply": True,
    "interactions_at": True,
    "interactions_like": True,
    "interactions_system": True,
}


class SocialProfile(Base):
    """每个参与社交的账号一行,第一次用到时建(见 services/social.ensure_profile)。"""

    __tablename__ = "social_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    #: 对外的随机编号:没设用户名时名片二维码用 `/u/<public_id>`,不暴露自增 id
    public_id: Mapped[str] = mapped_column(String(16), unique=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bio: Mapped[str] = mapped_column(String(140), default="")
    privacy: Mapped[dict] = mapped_column(JSONB, default=dict)
    notify: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: 视频推荐个性化(S9):关掉之后推荐和未登录的人看到的一样
    personalize_video: Mapped[bool] = mapped_column(Boolean, default=True)
    #: 硬币余额(D13,纯积分:不能充值、提现、兑换)
    coins: Mapped[int] = mapped_column(Integer, default=0)
    #: 上次领每日硬币的北京日期
    coin_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: 用户事件序号(实时协议 §5.3 的 user_pts)
    user_pts: Mapped[int] = mapped_column(BigInteger, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())


class Username(Base):
    """@用户名的命名空间:用户、群、频道、机器人共用一张表(和 Telegram 一样)。

    主键是小写形式 —— 大小写不敏感唯一靠主键保证,不靠应用代码先查再插
    (那样两个请求同时抢一个名字会都成功)。
    """

    __tablename__ = "usernames"

    username_lc: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(8))  # user / chat
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())


class SocialContact(Base):
    """联系人:用户自己一个个加的(不上传通讯录,D2)。只对加的那一方生效。"""

    __tablename__ = "social_contacts"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                          primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                            primary_key=True, index=True)
    alias: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())


class SocialBlock(Base):
    """拉黑(S7)。判定是**双向的**:任意一方拉黑了另一方,私信、拉群、通话都不通。"""

    __tablename__ = "social_blocks"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         primary_key=True)
    blocked_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                            primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
