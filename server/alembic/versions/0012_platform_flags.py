"""platform_flags

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-17 23:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 平台运行时开关(恶劣天气配送加价等),管理员改动即时生效
    op.create_table(
        'platform_flags',
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('value', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('platform_flags')
