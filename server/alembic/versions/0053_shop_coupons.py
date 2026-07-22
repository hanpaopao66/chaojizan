"""商家自建店铺券:coupons 加 funder/merchant_id(区分资金方与限定店),
coupon_batches 加 merchant_id/per_user_limit(店铺券批次)。
"""
import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("coupons", sa.Column(
        "funder", sa.String(10), nullable=False, server_default="platform"))
    op.add_column("coupons", sa.Column(
        "merchant_id", sa.Integer, sa.ForeignKey("merchants.id"),
        nullable=True))
    op.add_column("coupon_batches", sa.Column(
        "merchant_id", sa.Integer, sa.ForeignKey("merchants.id"),
        nullable=True, index=True))
    op.add_column("coupon_batches", sa.Column(
        "per_user_limit", sa.Integer, nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("coupon_batches", "per_user_limit")
    op.drop_column("coupon_batches", "merchant_id")
    op.drop_column("coupons", "merchant_id")
    op.drop_column("coupons", "funder")
