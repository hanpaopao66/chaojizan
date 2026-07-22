"""库存每日回满 + 菜品估清:dishes 加三列。

daily_stock 非空 = 每天北京时间 04:00 库存重置为该值;
sold_out_today = 估清(今日售罄,区别于下架),stock_before_soldout
记估清前库存供未启用每日回满的菜次日恢复。
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dishes", sa.Column("daily_stock", sa.Integer, nullable=True))
    op.add_column(
        "dishes",
        sa.Column("sold_out_today", sa.Boolean, nullable=False,
                  server_default=sa.false()),
    )
    op.add_column(
        "dishes", sa.Column("stock_before_soldout", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("dishes", "stock_before_soldout")
    op.drop_column("dishes", "sold_out_today")
    op.drop_column("dishes", "daily_stock")
