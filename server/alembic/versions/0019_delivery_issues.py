"""delivery_issues

配送异常工单:骑手配送途中上报,平台仲裁(协调继续/按送达处理/先行赔付)。
配送中的摩擦终于有了正式通道,不再全靠打电话。

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-19 03:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'delivery_issues',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(),
                  sa.ForeignKey('orders.id'), nullable=False, index=True),
        sa.Column('order_no', sa.String(length=32), nullable=False),
        sa.Column('rider_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('photo_url', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=12), nullable=False,
                  server_default='open', index=True),
        sa.Column('resolution', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('resolve_note', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('delivery_issues')
