"""订单预计送达时间(orders.eta_at,支付时按距离朴素公式生成)
+ 最小平台券(coupons:超时赔付安抚券,下单抵扣走 subsidy 平台承担口径)。
"""
import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column(
        "eta_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "coupons",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("min_spend_cents", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # 已抵扣到哪个订单;空串=未使用(订单全额退款/关单时会释放回券包)
        sa.Column("used_order_no", sa.String(32), nullable=False,
                  server_default=""),
        # 发放来源(如 eta:订单号),唯一约束保证同一单最多赔一次
        sa.Column("source", sa.String(64), nullable=False, unique=True),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("coupons")
    op.drop_column("orders", "eta_at")
