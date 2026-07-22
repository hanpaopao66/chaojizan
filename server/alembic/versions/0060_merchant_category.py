"""外卖品类:merchants.category(白名单见 app/categories.py,存量默认快餐便当)。"""
import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "category", sa.String(20), nullable=False,
        server_default="fast_food"))
    op.create_index("ix_merchants_category", "merchants", ["category"])


def downgrade() -> None:
    op.drop_index("ix_merchants_category", table_name="merchants")
    op.drop_column("merchants", "category")
