"""pickup_orders

到店自取:orders 表加 pickup 标记与取餐码。自取单免配送费、不进骑手抢单池、
不受无人接单兜底影响;用户凭取餐码到店,商家核对后订单完成并结算。

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-19 02:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('pickup', sa.Boolean(),
                                      nullable=False, server_default=sa.text('false')))
    op.add_column('orders', sa.Column('pickup_code', sa.String(length=8),
                                      nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('orders', 'pickup_code')
    op.drop_column('orders', 'pickup')
