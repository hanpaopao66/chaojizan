"""骑手每日汇总(#310):统计留存,不做考核

Revision ID: 0119
Revises: 0118
"""
import sqlalchemy as sa
from alembic import op

revision = '0119'
down_revision = '0118'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rider_daily_stats',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rider_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('orders', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('earned_cents', sa.Integer(),
                  nullable=False, server_default='0'),
        sa.Column('online_minutes', sa.Integer(),
                  nullable=False, server_default='0'),
        sa.Column('meters', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('wait_minutes', sa.Integer(),
                  nullable=False, server_default='0'),
        sa.Column('transfers', sa.Integer(),
                  nullable=False, server_default='0'),
        sa.Column('issues', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('filtered_by_prefs', sa.Integer(),
                  nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        # 一人一天一行:汇总要能幂等补跑,不能越跑越多
        sa.UniqueConstraint('rider_id', 'day', name='uq_rider_daily_stats'),
    )
    op.create_index('ix_rider_daily_stats_rider_id',
                    'rider_daily_stats', ['rider_id'])
    # 统计分析最常见的两种查法:某人的时间线、某天的全平台
    op.create_index('ix_rider_daily_stats_day', 'rider_daily_stats', ['day'])


def downgrade() -> None:
    op.drop_index('ix_rider_daily_stats_day', 'rider_daily_stats')
    op.drop_index('ix_rider_daily_stats_rider_id', 'rider_daily_stats')
    op.drop_table('rider_daily_stats')
