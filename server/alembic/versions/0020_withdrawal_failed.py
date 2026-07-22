"""withdrawal_failed

提现打款失败闭环:withdrawals 加打款通道字段(为商家转账 API 预留),
状态机新增 failed(打款被退回,余额自动退回,可重新申请)。
failed 是 varchar 枚举(native_enum=False),无需数据库枚举变更。

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-19 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('withdrawals', sa.Column('channel', sa.String(length=10),
                                           nullable=False, server_default='manual'))
    op.add_column('withdrawals', sa.Column('channel_ref', sa.String(length=64),
                                           nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('withdrawals', 'channel_ref')
    op.drop_column('withdrawals', 'channel')
