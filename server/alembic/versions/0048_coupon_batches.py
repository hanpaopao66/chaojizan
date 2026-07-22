"""平台券运营化:coupon_batches(券批次)+ coupons.batch_id。

触发方式 trigger:newcomer 注册自动发 / manual 定向补偿发 /
birthday 生日券 / winback 复购提醒(#51 复用同一批次基建)。
成本全平台承担(下单抵扣走 subsidy 口径,审计已覆盖)。
"""
import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coupon_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("trigger", sa.String(12), nullable=False,
                  server_default="manual", index=True),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("min_spend_cents", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("valid_days", sa.Integer, nullable=False,
                  server_default="7"),
        sa.Column("total", sa.Integer, nullable=False),   # 总量(预算封顶)
        sa.Column("issued", sa.Integer, nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean, nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.add_column("coupons", sa.Column(
        "batch_id", sa.Integer, sa.ForeignKey("coupon_batches.id"),
        nullable=True, index=True))


def downgrade() -> None:
    op.drop_column("coupons", "batch_id")
    op.drop_table("coupon_batches")
