"""after_sale_evidence

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-18 00:10:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 售后判责体系:举证照片(存量置空数组)+ 判责方(存量为商家责任口径,置 merchant)
    op.add_column('after_sales', sa.Column('images', JSONB(), nullable=False,
                                           server_default=sa.text("'[]'::jsonb")))
    op.add_column('after_sales', sa.Column('fault', sa.String(length=12),
                                           nullable=False, server_default='merchant'))
    # 恶意售后黑名单(客服判定,禁自助售后走工单)
    op.add_column('users', sa.Column('after_sale_banned', sa.Boolean(),
                                     nullable=False, server_default='false'))
    # 新申请默认未判责
    op.alter_column('after_sales', 'fault', server_default='')


def downgrade() -> None:
    op.drop_column('users', 'after_sale_banned')
    op.drop_column('after_sales', 'fault')
    op.drop_column('after_sales', 'images')
