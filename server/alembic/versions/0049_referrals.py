"""邀请有礼:users.ref_code(6 位邀请码,唯一)+ referrals(邀请关系)。

奖励挂"被邀请人完成首单"而不是注册——刷号无利可图;
双方各得券(平台承担,subsidy 口径),防刷三道:同设备不算、
邀请人月上限、风控命中单不触发。
"""
import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "ref_code", sa.String(6), nullable=True, unique=True))
    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("inviter_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("invitee_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, unique=True),  # 一个新用户只能被邀请一次
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="pending", index=True),  # pending/rewarded
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("referrals")
    op.drop_column("users", "ref_code")
