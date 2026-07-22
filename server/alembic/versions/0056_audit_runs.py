"""透明中心:audit_runs 每日核账运行记录(干净的运行也留痕,公开可查)。"""
import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("day", sa.String(10), nullable=False, unique=True),
        sa.Column("checked_orders", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("problem_count", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_runs")
