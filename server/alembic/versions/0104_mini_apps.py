"""小程序清单表

用户端下拉面板呼出的小程序(Telegram 模式:网页 + WebView + JS 桥)。
清单存服务端,上下架不用发版;allowed_origins 是桥的安全边界;
第三方入驻这批不做,表结构留好 status 位即可(#277)。

Revision ID: 0104
Revises: 0103
"""
import sqlalchemy as sa
from alembic import op

revision = '0104'
down_revision = '0103'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'mini_apps',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(30), nullable=False),
        sa.Column('icon', sa.String(200), nullable=False, server_default=''),
        sa.Column('tagline', sa.String(60), nullable=False, server_default=''),
        sa.Column('entry_url', sa.String(500), nullable=False),
        sa.Column('allowed_origins', sa.dialects.postgresql.JSONB(),
                  nullable=False, server_default='[]'),
        sa.Column('perms', sa.dialects.postgresql.JSONB(),
                  nullable=False, server_default='[]'),
        sa.Column('status', sa.String(10), nullable=False, server_default='on'),
        sa.Column('sort', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_miniapp_status', 'mini_apps', ['status'])


def downgrade() -> None:
    op.drop_table('mini_apps')
