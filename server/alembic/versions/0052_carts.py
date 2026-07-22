"""云端购物车:carts 表(用户×商家一份未提交购物车,跨设备续用)。"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("merchant_id", sa.Integer,
                  sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("items", JSONB, nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "merchant_id",
                            name="uq_cart_user_merchant"),
    )


def downgrade() -> None:
    op.drop_table("carts")
