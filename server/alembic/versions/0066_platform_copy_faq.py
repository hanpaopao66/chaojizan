"""platform copy and faq (#122):可下发的说明性文案与帮助中心问答

只建两张新表。autogenerate 顺带扫出的 carts/merchant_staff/orders 的
alter_column 与 withdrawals 索引改名是既有的模型-库漂移,与本条无关,
已剔除 —— 让无关的结构变更搭一趟顺风车,出事时根本对不上是哪次改的。

Revision ID: 0066
Revises: 0065
"""
from alembic import op
import sqlalchemy as sa

revision = '0066'
down_revision = '0065'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'platform_copy',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=60), nullable=False),
        sa.Column('text', sa.String(length=1000), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_platform_copy_key'), 'platform_copy',
                    ['key'], unique=True)
    op.create_table(
        'platform_faq',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('audience', sa.String(length=12), nullable=False),
        sa.Column('question', sa.String(length=120), nullable=False),
        sa.Column('answer', sa.String(length=1000), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_platform_faq_audience'), 'platform_faq',
                    ['audience'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_platform_faq_audience'), table_name='platform_faq')
    op.drop_table('platform_faq')
    op.drop_index(op.f('ix_platform_copy_key'), table_name='platform_copy')
    op.drop_table('platform_copy')
