"""顾客信用分的申诉记录(判定和计算在 services/customer_credit.py)。

信用分本身**不存**:分数永远是从原始记录现算的(完成的订单、配送异常的裁决、
违规记录),存下来就要自己维护「窗口滚过去」和「申诉改判」两件事 ——
那正是 services/enforcement.py 抬头说计分制做不好的地方。缓存只放在 Redis 里,
随时可以丢。

这张表只记一件事:**原来的申诉通道接不上的时候,顾客走客服工单提的信用分申诉**。
比如配送异常裁决的 72 小时申诉期过了,或者违规记录本来就没有结构化的申诉入口。
一条记录一次(和 appeals 表同一条规矩),工单是顾客和客服说话的地方,
这一行是服务端认的结论:status = overturned 的那条记录**不再计分**。
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
    #: 提申诉的顾客
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    #: 扣分项的种类:delivery_fault(配送异常判为顾客原因)/ violation(违规记录)。
    #: 取值见 services/customer_credit.APPEALABLE_KINDS
    kind: Mapped[str] = mapped_column(String(24))
    #: 那条记录的 id:delivery_issues.id / violations.id
    record_id: Mapped[int] = mapped_column(Integer)
    #: 同时建的那张客服工单。顾客在「我的工单」里看到客服的回复
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
