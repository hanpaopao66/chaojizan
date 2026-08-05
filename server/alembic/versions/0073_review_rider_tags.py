"""评价配送维度标签(评价归因)

配送是平台的事:配送问题的标签只随骑手评分落库,
从结构上保证进不了商家维度 —— 锅不该商家背。

Revision ID: 0073
Revises: 0072
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0073'
down_revision = '0072'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column(
        "rider_tags", JSONB(), nullable=False,
        server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("reviews", "rider_tags")
