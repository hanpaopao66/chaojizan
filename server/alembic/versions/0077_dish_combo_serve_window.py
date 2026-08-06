"""套餐与分时段供应(菜单第二批)

- combo_items:套餐 = 一道"虚拟菜"挂若干子项,自身价就是套餐价。
  不用负价 delta 表达优惠,那会打破"改价就改基础价"的约定。
- serve_window:早餐/夜宵这类只在某时段供应的菜。非供应时段置灰不消失。

两列同属 dishes 且同期上线,合成一个迁移,免得串行。

Revision ID: 0077
Revises: 0076
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0077'
down_revision = '0076'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dishes", sa.Column(
        "combo_items", JSONB(), nullable=False,
        server_default=sa.text("'[]'::jsonb")))
    op.add_column("dishes", sa.Column(
        "serve_window", sa.String(11), nullable=False,
        server_default=sa.text("''")))


def downgrade() -> None:
    op.drop_column("dishes", "serve_window")
    op.drop_column("dishes", "combo_items")
