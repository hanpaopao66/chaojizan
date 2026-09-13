"""社区治理:对人和会话的处罚(DEV-PROMPTS-40 #368 聊天部分,S6)。

视频的驳回、下架记在 video_decisions(那是对「稿件」的结论);这里记的是对**人**和**会话**的处罚:
删消息、禁言、封群 / 频道、封号、警告。两边共用 §5.11 的原因代码表。

几条约定(判定都在 services/sanctions.py,别处不要自己查这张表):

- 「生效中」= 没撤销,并且(没有到期时间 或 到期时间还没到)。只有 mute / ban_chat / ban_account
  三种会挡人;delete_messages、warn 是一次性的,记下来是为了能申诉、能公示;
- 当事人:对人的处罚是那个人;对会话的处罚是**当前的群主**(群主转让了,申诉权跟着走);
- 申诉就记在这一行上(一次处罚只能申诉一次),处理人不能是作出处罚的那个人;
  撤销(申诉成立或管理员撤销)不删行,只填 revoked_at —— 透明中心要能数出「撤销了多少」;
- `note` 给当事人看,`note_internal` 只在后台看;两者都**不进透明中心**(可能写着人名、群名)。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

#: 处罚种类(文档 docs/COMMUNITY-GOVERNANCE.md §2 同一张表)
SANCTION_ACTIONS = ("delete_messages", "mute", "ban_chat", "ban_account", "warn")
#: 会挡人的三种(其余是一次性的)
RESTRICTIVE_ACTIONS = ("mute", "ban_chat", "ban_account")
SANCTION_TARGETS = ("user", "chat")
#: 申诉状态:"" 没申诉 / open 待处理 / upheld 维持 / overturned 撤销
APPEAL_STATUSES = ("", "open", "upheld", "overturned")


class SocialSanction(Base):
    __tablename__ = "social_sanctions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: user / chat
    target_type: Mapped[str] = mapped_column(String(8))
    target_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    #: §5.11 原因代码;X999 必须写 note
    reason_code: Mapped[str] = mapped_column(String(8))
    #: 给当事人看的说明(系统通知、处罚记录、403 里都带它)
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    #: 只在后台看得到
    note_internal: Mapped[str] = mapped_column(String(500), default="", server_default="")
    #: 到期时间。限制类处罚为空 = 永久;一次性处罚恒为空
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 这次处罚和哪个会话有关(删消息 / 封群;对人的处罚来自某个会话的举报时也记上)
    chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: delete_messages 删掉的是哪几条(会话内的 seq)
    seqs: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                 nullable=True)
    #: 来源:chat(chat_reports.id)/ video(video_reports.id)/ ""(后台直接处置)
    report_kind: Mapped[str] = mapped_column(String(8), default="", server_default="")
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoke_note: Mapped[str] = mapped_column(String(300), default="", server_default="")
    appeal_status: Mapped[str] = mapped_column(String(12), default="", server_default="")
    appeal_text: Mapped[str] = mapped_column(String(500), default="", server_default="")
    appealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appeal_admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 复核结论(给当事人看)
    appeal_note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    appeal_note_internal: Mapped[str] = mapped_column(String(500), default="",
                                                      server_default="")
    appeal_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                                nullable=True)
    #: 注销时还生效的处罚:HMAC(手机号 + 角色)。同一个号再注册,处罚跟到新账号上 ——
    #: 注销不是洗白按钮(和 models.RiskCarryover 同一个理由)。存假名不存手机号
    carry_key: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    #: 注销再注册时从哪个(已注销的)账号挪过来的:同一行改对象,不复制(条数不会因此多出来)
    carried_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_social_sanctions_target", "target_type", "target_id", "created_at"),
        # 发消息、评论、弹幕每次都要查「这个人 / 这个会话此刻有没有被挡」:只索引还没撤销的限制类
        Index("ix_social_sanctions_live", "target_type", "target_id", "action",
              postgresql_where=sql_text(
                  "revoked_at IS NULL AND action IN ('mute', 'ban_chat', 'ban_account')")),
        Index("ix_social_sanctions_appeal_open", "id",
              postgresql_where=sql_text("appeal_status = 'open'")),
    )


#: 这个模块的全部表(S3 / S4 列名守卫按这张清单扫)
MODERATION_MODELS = (SocialSanction,)
