"""cloud_printer

商家云打印机(飞鹅):merchants 表记录绑定的打印机 SN 与自动出票开关。
支付成功后服务端直推小票——不依赖商家手机在线,听单可靠性与大平台对齐。

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-18 23:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('merchants', sa.Column('printer_sn', sa.String(length=32),
                                     nullable=False, server_default=''))
    op.add_column('merchants', sa.Column('printer_auto', sa.Boolean(),
                                     nullable=False, server_default=sa.text('true')))


def downgrade() -> None:
    op.drop_column('merchants', 'printer_auto')
    op.drop_column('merchants', 'printer_sn')
