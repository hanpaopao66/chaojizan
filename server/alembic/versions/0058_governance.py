"""治理透明:flag_history 开关变更留痕 + risk_action_log 处置留痕(月度聚合公示)。"""
import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flag_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("old_value", sa.String(200), nullable=False,
                  server_default=""),
        sa.Column("new_value", sa.String(200), nullable=False,
                  server_default=""),
        sa.Column("reason", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_flag_history_key", "flag_history", ["key"])
    op.create_table(
        "risk_action_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False),
        sa.Column("from_level", sa.String(10), nullable=False,
                  server_default=""),
        sa.Column("to_level", sa.String(10), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_risk_action_log_user_id", "risk_action_log",
                    ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_risk_action_log_user_id", table_name="risk_action_log")
    op.drop_table("risk_action_log")
    op.drop_index("ix_flag_history_key", table_name="flag_history")
    op.drop_table("flag_history")
