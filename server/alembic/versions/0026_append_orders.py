"""append_orders

加菜 = 追加单:不改原单(金额/佣金/账本已冻结),而是关联一张免配送费的新单。
追加单不进骑手抢单池,rider 跟随原单;原单取消时清扫任务级联取消并退款。

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-19 20:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('parent_order_no', sa.String(length=32),
                                      nullable=False, server_default=''))
    op.create_index('ix_orders_parent_order_no', 'orders', ['parent_order_no'])


def downgrade() -> None:
    op.drop_index('ix_orders_parent_order_no', table_name='orders')
    op.drop_column('orders', 'parent_order_no')
