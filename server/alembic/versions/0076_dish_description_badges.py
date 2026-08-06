"""菜品描述与标签

用户点之前想知道"这菜里有什么、辣不辣"。此前只有店铺介绍,
单菜一个字都没有 —— 有忌口的人只能靠猜,或者在备注里写一长串。

标签只做商家自述的客观项(新品/招牌/辣度),不含"平台推荐"——
那种标签一旦存在就会变成竞价位。

Revision ID: 0076
Revises: 0075
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0076'
down_revision = '0075'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dishes", sa.Column(
        "description", sa.String(200), nullable=False,
        server_default=sa.text("''")))
    op.add_column("dishes", sa.Column(
        "badges", JSONB(), nullable=False,
        server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("dishes", "badges")
    op.drop_column("dishes", "description")
