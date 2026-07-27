"""住宿点评:一单一评/追评/酒店回复;评分 180 天滚动、<3 条不出分。"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stay_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stay_order_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=False),
        sa.Column("image_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reply", sa.String(length=300), nullable=False),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False),
        sa.Column("append_content", sa.String(length=500), nullable=False),
        sa.Column("append_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("append_reply", sa.String(length=300), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["stay_order_id"], ["stay_orders.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stay_order_id"),
    )
    op.create_index(op.f("ix_stay_reviews_merchant_id"), "stay_reviews",
                    ["merchant_id"], unique=False)


def downgrade() -> None:
    op.drop_table("stay_reviews")
