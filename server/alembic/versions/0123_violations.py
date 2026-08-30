"""违规事件:处置的唯一事实来源

## 存事件,不存级别

级别永远是**算出来的**(services/enforcement.level_from_counts):
窗口内这一类成立了几次,够不够阈值。这条不变量换来两件计分做不到的事:

- **归零是自动的** —— 窗口一滚出去就不算了,不需要"修复"机制;
- **申诉推翻一条,级别自动重算** —— 不需要手动减分,而"减多少"这个问题
  在计分制里永远说不清。

所以这张表**没有 level 列**。谁想加,先想清楚上面两件事怎么办。

## overturned_at 而不是删行

申诉成立不是"这件事没发生过",是"这件事不算数"。删了的话:
公示的处置总数对不上、当事人看不到自己申诉赢了、审计也查不出改过什么。
非空 = 不计入,行还在。

## 一条事件只对一个人

`subject_id` 是被判定的那个人(用户/店主/骑手)。连锁的店员做的事记在
店主头上 —— 处置的是经营主体,而店员换人不该让计数归零。
"""
from alembic import op
import sqlalchemy as sa

revision = '0123'
down_revision = '0122'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "violations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject_id", sa.Integer,
                  sa.ForeignKey("users.id"), nullable=False, index=True),
        # customer / merchant / rider。冗余于 users.role,但**判定时的身份
        # 才算数**:一个人既是用户又是骑手时,骂商家和恶意售后不是一回事
        sa.Column("audience", sa.String(16), nullable=False),
        # 见 services/enforcement.CATALOG
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("order_no", sa.String(32), nullable=True),
        # 判定说明。**对本人可见** —— 处置必须写明原因
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        # 判定人:管理员 user id;系统自动判定的填 NULL
        sa.Column("decided_by", sa.Integer,
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        # 申诉成立:非空 = 不计入。**不删行**,理由见抬头
        sa.Column("overturned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overturn_note", sa.String(300),
                  nullable=False, server_default=""),
    )
    # 算级别的那条查询:某人 + 某窗口内 + 未被推翻
    op.create_index("ix_violations_subject_time", "violations",
                    ["subject_id", "created_at"])
    # 自动判定要幂等:同一单同一类不许记两次
    op.create_index("uq_violations_auto", "violations",
                    ["kind", "order_no"], unique=True,
                    postgresql_where=sa.text("order_no IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_violations_auto", table_name="violations")
    op.drop_index("ix_violations_subject_time", table_name="violations")
    op.drop_table("violations")
