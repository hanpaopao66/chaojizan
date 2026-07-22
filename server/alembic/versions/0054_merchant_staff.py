"""商家子账号:merchant_staff 表(店员能接单/出餐/估清,不能提现改价)。"""
import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchant_staff",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("merchant_id", sa.Integer,
                  sa.ForeignKey("merchants.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(50), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("merchant_id", "user_id",
                            name="uq_staff_merchant_user"),
    )


def downgrade() -> None:
    op.drop_table("merchant_staff")
