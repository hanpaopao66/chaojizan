"""骑手上岗管理:rider_exams 培训考试记录 + rider_gear 装备申领登记。
考试强制开关走 platform_flags(rider_exam_required,默认关=存量宽限),
开启后未通过考试不得上线。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rider_exams",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rider_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("answers", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "rider_gear",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rider_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("item", sa.String(20), nullable=False),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="requested"),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("rider_gear")
    op.drop_table("rider_exams")
