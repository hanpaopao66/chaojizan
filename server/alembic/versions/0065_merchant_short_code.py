"""商家专属短码:海报二维码与短链 /s/{code} 用(#116)。

懒生成——存量商家不回填,第一次进推广物料页时才生成,
避免为一批可能永远不用这功能的店占号段。
"""
import sqlalchemy as sa
from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "short_code", sa.String(length=8), nullable=False, server_default=""))
    op.create_index("ix_merchants_short_code", "merchants", ["short_code"])


def downgrade() -> None:
    op.drop_index("ix_merchants_short_code", table_name="merchants")
    op.drop_column("merchants", "short_code")
