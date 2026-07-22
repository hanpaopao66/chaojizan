"""食品安全投诉(食安红线通道):food_safety_reports。
不经商家、直达平台;处置动作(退款/下架/停业)留痕在 actions JSONB,
监管检查可导出。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "food_safety_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"),
                  nullable=False, index=True),
        sa.Column("order_no", sa.String(32), nullable=False),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("merchant_id", sa.Integer, sa.ForeignKey("merchants.id"),
                  nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("images", JSONB, nullable=False, server_default="[]"),
        sa.Column("medical_urls", JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="open", index=True),
        sa.Column("actions", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("food_safety_reports")
