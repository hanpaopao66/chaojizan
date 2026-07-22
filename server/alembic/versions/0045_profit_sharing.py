"""分账合规落地(二清收口,桩模式):
- merchants.sub_mchid / ps_ready:微信特约商户号与"可分账"标记(进件+接收方绑定完成)
- orders.settle_mode / merchant_earnings.settle_mode:结算口径快照
  (platform=平台代收代付过渡口径;profit_sharing=支付机构分账,货款不经平台)
- profit_sharing_records:分账请求台账(幂等/重试/退款回退)
"""
import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "sub_mchid", sa.String(32), nullable=False, server_default=""))
    op.add_column("merchants", sa.Column(
        "ps_ready", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("orders", sa.Column(
        "settle_mode", sa.String(16), nullable=False,
        server_default="platform"))
    op.add_column("merchant_earnings", sa.Column(
        "settle_mode", sa.String(16), nullable=False,
        server_default="platform"))
    op.create_table(
        "profit_sharing_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"),
                  nullable=False, unique=True),  # 幂等:一单最多一条
        sa.Column("order_no", sa.String(32), nullable=False, index=True),
        sa.Column("merchant_id", sa.Integer, sa.ForeignKey("merchants.id"),
                  nullable=False, index=True),
        sa.Column("sub_mchid", sa.String(32), nullable=False),
        sa.Column("net_cents", sa.Integer, nullable=False),      # 分给商家
        sa.Column("commission_cents", sa.Integer, nullable=False),  # 平台留存
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="pending", index=True),
        # pending/success/failed/returned
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(),
                  nullable=False),
    )


def downgrade() -> None:
    op.drop_table("profit_sharing_records")
    op.drop_column("merchant_earnings", "settle_mode")
    op.drop_column("orders", "settle_mode")
    op.drop_column("merchants", "ps_ready")
    op.drop_column("merchants", "sub_mchid")
