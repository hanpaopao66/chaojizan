"""merchant_deposit

商家保证金:从营收自动留存(不强制预缴),可提余额 = 余额 - 应留保证金。
默认 ¥500,平台可按店调;用于售后冲账余额为负的兜底,退店无纠纷全额退还。

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-19 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('merchants',
                  sa.Column('deposit_required_cents', sa.Integer(),
                            nullable=False, server_default='50000'))


def downgrade() -> None:
    op.drop_column('merchants', 'deposit_required_cents')
