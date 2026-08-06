"""菜品排序位(菜单装修)

招牌放最前、饮品小食垫后是商家最常做的动作,
此前只能靠改分类名硬凑顺序。

Revision ID: 0075
Revises: 0074
"""
import sqlalchemy as sa
from alembic import op

revision = '0075'
down_revision = '0074'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dishes", sa.Column(
        "sort", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("dishes", "sort")
