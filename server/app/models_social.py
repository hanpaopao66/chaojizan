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
    # 别人输入我的超级赞号(@号)能不能找到我。界面上是开关,只有 everyone / nobody 两档
    # (routers/social.SWITCH_PRIVACY);关了之后名片码改用 /u/<public_id>,见 routers/social.resolve
    "username_search": "everyone",
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
    #: 超级赞号(界面上的叫法,相当于微信号;代码和接口里沿用 username)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 上一次设置 / 修改超级赞号的时间:一年只能改一次,从这天算(services/social.username_next_change)。
    #: 空 = 从没设过,或者是迁移 0133 之前就设好的存量号 —— 这两种下一次都不用等
    username_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                             nullable=True)
    bio: Mapped[str] = mapped_column(String(140), default="")
    privacy: Mapped[dict] = mapped_column(JSONB, default=dict)
    notify: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: 视频推荐个性化(S9):关掉之后推荐和未登录的人看到的一样
    personalize_video: Mapped[bool] = mapped_column(Boolean, default=True)
    #: 标签:用户自己写的,最多 5 个、每个 1–8 个字(校验见 services/badges.normalize_tags)。
    #: 和昵称、签名同一级别的公开信息
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    #: 整组标签对别人隐藏(自己照样看得到)
    tags_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: 本人选了对别人隐藏的勋章(勋章的 key)。**勋章本身不存** —— 每次按公开条件现算(services/badges.py),
    #: 这里只存「我不想让别人看到哪几枚」
    badges_hidden: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    #: 本人选了让别人看到的勋章(迁移 0137)。和上一列合起来才分得开「没选过」和「选了显示」:
    #: 没选过的按每一枚的缺省(「实名认证」默认不显示),见 services/badges.hidden_keys
    badges_shown: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
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


class UsernameHold(Base):
    """被换掉、清空、随注销释放的超级赞号,冷冻期内谁都不能注册(迁移 0133)。

    冷冻是为了认得这个号的人:老联系人、发出去的名片链接和二维码。号一放出来就被别人注册的话,
    他们找到的就是另一个人 —— 冒充的门就开了。所以群 / 频道的公开链接也不能用冷冻中的号
    (共用 usernames 这个命名空间);**原主人不受冷冻限制**,他拿回去不会让任何人认错人,
    但拿回去算一次修改,照样要等一年一次的名额(services/social.hold_blocks)。

    和 usernames 分开放:冷冻中的号不属于任何人,放进 usernames 的话,按号找人、@ 提及、
    全局搜索这些读 usernames 的地方都得记着跳过它,漏一处就是把号解析到原主人身上。
    """

    __tablename__ = "username_holds"

    username_lc: Mapped[str] = mapped_column(String(32), primary_key=True)
    #: 谁放出来的(原主人)。他自己拿回去不受冷冻限制
    released_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    frozen_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
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
