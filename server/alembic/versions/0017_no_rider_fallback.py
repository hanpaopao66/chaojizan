"""no_rider_fallback

无人接单兜底:orders 表加"已提醒"时间戳,清扫任务据此保证每单只提醒一次。
(提醒线推送在线骑手+商家;取消线全额退款、已出餐的平台赔付餐损)

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-19 01:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('no_rider_alerted_at',
                                      sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'no_rider_alerted_at')
