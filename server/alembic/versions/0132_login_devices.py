"""扫码登录过的网页和电脑:login_devices

用户端网页版、桌面版扫码登录成功时建一行,给那台设备一把 device_key(只存 SHA-256)。
下次带着它来是「一键登录」:只能让服务端去问一次手机,手机上确认了才签 token。
扫码登录签的 token 里带着这一行的 id,用户在手机上「移除」之后那台设备立刻退出登录。

Revision ID: 0132
Revises: 0131
"""
import sqlalchemy as sa
from alembic import op

revision = '0132'
down_revision = '0131'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'login_devices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False, index=True),
        sa.Column('key_hash', sa.String(length=64), nullable=False, unique=True),
        sa.Column('client', sa.String(length=16), nullable=False, server_default='web'),
        sa.Column('device', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('ip_masked', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('login_devices')
