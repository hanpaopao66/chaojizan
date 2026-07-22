"""深夜自动打烊+节假日营业:merchants.closed_until(临时歇业到点自动恢复)
与 merchants.holiday_plans(特殊日期计划,优先级高于每日营业时间)。
平台深夜保护窗走 platform_flags(night_curfew/night_curfew_hours),无需建表。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "merchants",
        sa.Column("closed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "merchants",
        sa.Column("holiday_plans", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("merchants", "holiday_plans")
    op.drop_column("merchants", "closed_until")
