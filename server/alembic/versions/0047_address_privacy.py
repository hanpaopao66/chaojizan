"""深夜配送信息保护 + 地址精确度:
- addresses.protect/salutation:保护模式(骑手只见粗地址)与中性称呼
- orders.addr_protect/addr_public/addr_revealed/salutation:下单快照与临时放行
- orders.delivery_photo_url:送达拍照留证(深夜保护单强制)
- address_feedback:骑手「地址不准」反馈,2 次后下单提示核对
"""
import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("addresses", sa.Column(
        "protect", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("addresses", sa.Column(
        "salutation", sa.String(12), nullable=False, server_default=""))
    op.add_column("orders", sa.Column(
        "addr_protect", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("orders", sa.Column(
        "addr_public", sa.String(200), nullable=False, server_default=""))
    op.add_column("orders", sa.Column(
        "addr_revealed", sa.Boolean, nullable=False,
        server_default=sa.false()))
    op.add_column("orders", sa.Column(
        "salutation", sa.String(12), nullable=False, server_default=""))
    op.add_column("orders", sa.Column(
        "delivery_photo_url", sa.String(300), nullable=False,
        server_default=""))
    op.create_table(
        "address_feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("address", sa.String(200), nullable=False),
        sa.Column("order_no", sa.String(32), nullable=False, unique=True),
        sa.Column("rider_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("address_feedback")
    for col in ("delivery_photo_url", "salutation", "addr_revealed",
                "addr_public", "addr_protect"):
        op.drop_column("orders", col)
    op.drop_column("addresses", "salutation")
    op.drop_column("addresses", "protect")
