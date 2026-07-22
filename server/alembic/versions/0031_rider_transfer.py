"""骑手转单:orders.rider_pool_since(无人接单兜底的计时基准,
下单支付/转单时刷新——转出的单从转单时刻重新起算,不会一回池就被兜底取消)
与 order_events.note(事件备注,转单原因等留痕)。
存量订单回填 rider_pool_since = created_at,与原计时口径一致。
"""
import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("rider_pool_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE orders SET rider_pool_since = created_at")
    op.add_column(
        "order_events",
        sa.Column("note", sa.String(120), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("order_events", "note")
    op.drop_column("orders", "rider_pool_since")
