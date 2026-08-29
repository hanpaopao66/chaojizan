"""开放接口的调用记录(开发者后台用)

只记「发生了什么」:方法、路径、状态码、耗时。
**没有请求体也没有响应体** —— 里面是收货地址、手机号、备注里的忌口,
为了让开发者好排查而多存一份,是拿用户的隐私补贴开发体验。

两种调用方都记:商家的 POS(kind='key')和用户的 AI 助手(kind='agent')。
记后者不只是为了排查 —— 用户有权知道自己的助手做过什么。

索引按「谁的 + 什么时候」建:两个页面都是「我的最近 N 条」。
"""
from alembic import op
import sqlalchemy as sa

revision = '0117'
down_revision = '0116'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'api_calls',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(length=8), nullable=False, index=True),
        sa.Column('merchant_id', sa.Integer(), nullable=True, index=True),
        sa.Column('user_id', sa.Integer(), nullable=True, index=True),
        sa.Column('method', sa.String(length=8), nullable=False),
        sa.Column('path', sa.String(length=200), nullable=False),
        sa.Column('status', sa.Integer(), nullable=False, index=True),
        sa.Column('duration_ms', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False, index=True),
    )
    # 两个页面问的都是「我的最近 N 条」,一个复合索引各覆盖一半
    op.create_index('ix_api_calls_merchant_time', 'api_calls',
                    ['merchant_id', 'created_at'])
    op.create_index('ix_api_calls_user_time', 'api_calls',
                    ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_api_calls_user_time', table_name='api_calls')
    op.drop_index('ix_api_calls_merchant_time', table_name='api_calls')
    op.drop_table('api_calls')
