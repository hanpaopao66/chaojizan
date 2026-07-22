"""骑手意外险(rider_insurance_days:每日投保/登记记录,保障金池支出)
+ 交通事故上报(rider_accidents:红色加急,处置留痕)。
保险照桩模式:insurance_* 未配置时为登记模式(保障金池兜底先行赔付)。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rider_insurance_days",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rider_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("day", sa.String(10), nullable=False),  # 北京日 YYYY-MM-DD
        sa.Column("policy_no", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("premium_cents", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="registered"),  # registered/insured
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("rider_id", "day"),
    )
    op.create_table(
        "rider_accidents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rider_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lng", sa.Float, nullable=True),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("description", sa.String(500), nullable=False,
                  server_default=""),
        sa.Column("photos", JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="open", index=True),
        sa.Column("actions", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rider_accidents")
    op.drop_table("rider_insurance_days")
