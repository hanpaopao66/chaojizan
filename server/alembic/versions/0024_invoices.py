"""invoices

平台服务费发票:商家按自然月申请(金额=当月佣金+团购服务费,系统聚合),
管理员开电子普票后回填链接;商家抬头信息存档、申请单存快照。

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-19 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('merchants', sa.Column('invoice_title', sa.String(length=100),
                                         nullable=False, server_default=''))
    op.add_column('merchants', sa.Column('invoice_tax_no', sa.String(length=30),
                                         nullable=False, server_default=''))
    op.add_column('merchants', sa.Column('invoice_email', sa.String(length=100),
                                         nullable=False, server_default=''))
    op.create_table(
        'invoice_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False, index=True),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('tax_no', sa.String(length=30), nullable=False),
        sa.Column('email', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False,
                  server_default='pending', index=True),
        sa.Column('file_url', sa.String(length=300), nullable=False,
                  server_default=''),
        sa.Column('note', sa.String(length=200), nullable=False,
                  server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('merchant_id', 'period'),
    )


def downgrade() -> None:
    op.drop_table('invoice_requests')
    op.drop_column('merchants', 'invoice_email')
    op.drop_column('merchants', 'invoice_tax_no')
    op.drop_column('merchants', 'invoice_title')
