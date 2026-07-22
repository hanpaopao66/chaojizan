"""appeals

判责申诉:骑手/商家对平台裁决(售后判责/配送异常/差评)的复核通道。
reviews 加 hidden(申诉成立的差评隐藏且不参与评分)。

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-19 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'appeals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False, index=True),
        sa.Column('role', sa.String(length=10), nullable=False),
        sa.Column('target_type', sa.String(length=20), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('images', JSONB(), nullable=False, server_default='[]'),
        sa.Column('status', sa.String(length=12), nullable=False,
                  server_default='open', index=True),
        sa.Column('resolve_note', sa.String(length=300), nullable=False,
                  server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('target_type', 'target_id'),
    )
    op.add_column('reviews', sa.Column('hidden', sa.Boolean(),
                                       nullable=False,
                                       server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('reviews', 'hidden')
    op.drop_table('appeals')
