"""商家承担配送费:merchants 加分担设置,orders 加下单快照(2026-10-08)

商家可以替顾客出一部分配送费:固定金额或比例二选一。订单上的
merchant_delivery_cents 是**已经算进 discount_cents 的那一部分**,单独存一列只为展示,
账目口径不变。

缺省 0:已有商家和订单一个都不受影响。

Revision ID: 0150
Revises: 0149
"""
import sqlalchemy as sa
from alembic import op

revision = '0150'
down_revision = '0149'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('merchants', sa.Column('delivery_share_cents', sa.Integer(),
                                         nullable=False, server_default='0'))
    op.add_column('merchants', sa.Column('delivery_share_pct', sa.Integer(),
                                         nullable=False, server_default='0'))
    op.add_column('orders', sa.Column('merchant_delivery_cents', sa.Integer(),
                                      nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('orders', 'merchant_delivery_cents')
    op.drop_column('merchants', 'delivery_share_pct')
    op.drop_column('merchants', 'delivery_share_cents')
