"""merchant_withdrawal

商家提现:withdrawals 表从骑手专用改为骑手/商家共用——
rider_id 更名 user_id(商家提现记在店主账号上),新增 role 区分,
存量数据全部是骑手,默认值 'rider' 即正确回填。

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('withdrawals', 'rider_id', new_column_name='user_id')
    op.add_column('withdrawals', sa.Column('role', sa.String(length=10),
                                           nullable=False, server_default='rider'))


def downgrade() -> None:
    op.drop_column('withdrawals', 'role')
    op.alter_column('withdrawals', 'user_id', new_column_name='rider_id')
