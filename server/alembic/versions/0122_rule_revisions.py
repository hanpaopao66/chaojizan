"""规则变更留痕:规则页改了什么、什么时候改的,公开可查

## 为什么需要

规则页的每个数字都从代码常量算出来 —— 这比"后台可编辑的文案"强,
文档不可能和实现对不上。但它有个反面:**改一个常量就等于悄悄改了规则,
没有任何人被告知**。

一个刚发生的例子:给零售商家加「发货必须拍照」是新增的一项义务,
走的是一个 commit。生产上真有零售商家的话,他们会在点「已出餐」报错的
那一刻才知道这条规则存在。

美团的规则中心有「修订公示通知」,逐条新旧并排。这里做的是同一件事,
但形式不同:他们的规则是文档所以要人写 diff,我们的规则是算出来的,
所以**存快照、读的时候算 diff**。

## 存快照不存 diff

diff 是快照的函数,反过来不成立。存 diff 的话:算法改进了没法重算,
中间漏掉一次就再也对不上。账本锚点那边是同一个理由。

## revision 是每端独立的序号

`(audience, revision)` 唯一。并发时后一个插入撞唯一约束、被吞掉 ——
留痕不该因为两个人同时打开规则页而报错。

## ⚠️ 这一版只做「不再静默」,不做「生效前置」

真正的公示是"先公告、N 天后生效"。那要求每条新规则都有自己的开关
(公示期内关着,到期才开)。这一版只保证**变更被记下来且公开可读**。
差的那一半要逐条规则去做,别把这张表当成已经有了公示期。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0122'
down_revision = '0121'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_revisions",
        sa.Column("id", sa.Integer, primary_key=True),
        # customer / merchant / rider,见 services/rules.AUDIENCES
        sa.Column("audience", sa.String(16), nullable=False),
        # 每端独立的版本号,从 1 起
        sa.Column("revision", sa.Integer, nullable=False),
        # 规则内容的 sha256(取前 16 位十六进制)。变没变就看它
        sa.Column("content_hash", sa.String(16), nullable=False),
        # 当时的完整规则内容。**存快照不存 diff** —— 理由见抬头
        sa.Column("sections", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("audience", "revision",
                            name="uq_rule_revisions_audience_rev"),
    )
    op.create_index("ix_rule_revisions_audience", "rule_revisions",
                    ["audience", "revision"])


def downgrade() -> None:
    op.drop_index("ix_rule_revisions_audience", table_name="rule_revisions")
    op.drop_table("rule_revisions")
