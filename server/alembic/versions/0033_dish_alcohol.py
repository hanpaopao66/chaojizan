"""酒类商品销售限制:dishes.is_alcohol 标记(商家上架自助勾选)。
下单拦截依赖 #14 实名(is_adult);禁售时段走 platform_flags,无需建表。
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dishes",
        sa.Column("is_alcohol", sa.Boolean, nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("dishes", "is_alcohol")
