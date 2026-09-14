"""信用分的申诉记录(判定和计算在 services/credit.py,顾客、商家、骑手三种角色共用)。

信用分本身**不存**:分数永远是从原始记录现算的(完成的订单、配送异常的裁决、售后判责、
违规记录),存下来就要自己维护「窗口滚过去」和「申诉改判」两件事 ——
那正是 services/enforcement.py 抬头说计分制做不好的地方。缓存只放在 Redis 里,
随时可以丢。

这张表只记一件事:**原来的申诉通道接不上的时候,走客服工单提的信用分申诉**。
比如配送异常裁决、售后判责的 72 小时申诉期过了,或者违规记录、骑手的售后判责本来就没有
结构化的申诉入口。一条记录一次(和 appeals 表同一条规矩),工单是申诉的人和客服说话的地方,
这一行是服务端认的结论:status = overturned 的那条记录**不再计分**。

不另存角色:一个账号只有一个角色(同一个手机号的顾客号、商家号、骑手号是三个账号),
user_id 就定了是谁的分。三种记录各自的 id 也不会串 —— 一条配送异常只有一个裁决
(按送达处理算顾客的、先行赔付算骑手的),一条售后同一时刻只有一个判责方。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class CreditAppeal(Base):
    __tablename__ = "credit_appeals"
    __table_args__ = (
        # 一条记录只能走一次工单申诉。原来的申诉通道(appeals 表)各管各的,
        # 所以最多两轮:原通道维持原判之后,有新证据还能走这一次
        UniqueConstraint("kind", "record_id", name="uq_credit_appeals_record"),
        Index("ix_credit_appeals_user", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: 提申诉的人(顾客本人 / 店主本人 / 骑手本人)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    #: 扣分项的种类:delivery_fault(配送异常)/ after_sale_fault(售后判责)/ violation(违规记录)。
    #: 每种角色能申诉哪几种见 services/credit.APPEALABLE_KINDS
    kind: Mapped[str] = mapped_column(String(24))
    #: 那条记录的 id:delivery_issues.id / after_sales.id / violations.id
    record_id: Mapped[int] = mapped_column(Integer)
    #: 同时建的那张客服工单。申诉的人在「联系平台客服」里看到客服的回复
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(500))
    #: open 待处理 / upheld 维持原判 / overturned 申诉成立(这一条不再计分)
    status: Mapped[str] = mapped_column(String(12), default="open", server_default="open")
    resolve_note: Mapped[str] = mapped_column(String(300), default="", server_default="")
    admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
