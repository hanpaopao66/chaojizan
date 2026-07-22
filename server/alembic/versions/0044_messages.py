"""订单内聊天:messages(用户↔骑手 / 用户↔商家,按订单建会话)。

支付后开启;订单终结 2 小时后只读;7 天后对当事人不可见
(留档供仲裁,管理后台按订单可查)。
"""
import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"),
                  nullable=False, index=True),
        sa.Column("sender_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False),
        sa.Column("sender_role", sa.String(12), nullable=False),
        # 会话对端(customer/rider/merchant):user↔rider 与 user↔merchant 两条线
        sa.Column("receiver_role", sa.String(12), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False,
                  server_default="text"),  # text/image/quick
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("messages")
