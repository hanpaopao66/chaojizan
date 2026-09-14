"""顾客信用分:credit_appeals(走客服工单的信用分申诉)

信用分本身不落库 —— 分数永远从原始记录现算(见 services/customer_credit.py),
这里只记「原来的申诉通道接不上时,顾客走客服工单提的申诉」和它的结论。
status = overturned 的那条记录不再计分。一条记录一次(唯一约束)。

Revision ID: 0135
Revises: 0134
"""
import sqlalchemy as sa
from alembic import op

revision = '0135'
down_revision = '0134'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'credit_appeals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        # delivery_fault / violation
        sa.Column('kind', sa.String(length=24), nullable=False),
        # delivery_issues.id / violations.id
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id'), nullable=True),
        sa.Column('reason', sa.String(length=500), nullable=False),
        # open / upheld / overturned
        sa.Column('status', sa.String(length=12), nullable=False, server_default='open'),
        sa.Column('resolve_note', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('kind', 'record_id', name='uq_credit_appeals_record'),
    )
    op.create_index('ix_credit_appeals_user', 'credit_appeals', ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_credit_appeals_user', table_name='credit_appeals')
    op.drop_table('credit_appeals')
