"""payout_accounts

对公结算基础:收款账户登记(账号加密落库)+ 提现申请快照冻结。
打款照快照打,改账户不影响在途申请;账户刚变更 24h 内的提现后台标黄人工核实。

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-19 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'payout_accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False, unique=True),
        sa.Column('role', sa.String(length=10), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('holder_name', sa.String(length=50), nullable=False),
        sa.Column('account_no_encrypted', sa.String(length=300), nullable=False),
        sa.Column('account_tail', sa.String(length=4), nullable=False),
        sa.Column('bank_name', sa.String(length=100), nullable=False,
                  server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )
    op.add_column('withdrawals',
                  sa.Column('account_snapshot', JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('withdrawals', 'account_snapshot')
    op.drop_table('payout_accounts')
