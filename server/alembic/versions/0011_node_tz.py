"""node_tz

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-17 17:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见证节点自愿上报的时区(世界地图粗定位用),存量节点置空串
    op.add_column('witness_nodes', sa.Column('tz', sa.String(length=40), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('witness_nodes', 'tz')
