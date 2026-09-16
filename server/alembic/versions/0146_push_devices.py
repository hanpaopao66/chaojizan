"""自建推送:设备地址表(#384)

推送原本走极光,服务端只认 `u{user_id}` 这个别名 —— **设备 token 在极光那边**。
自己发就得自己存:苹果要 APNs 的 device token,安卓各厂商要各自的 regid,
而同一个人可能有几台设备、几个端。

`(channel, token)` 唯一:一个 token 只可能属于一台设备,换人登录时改挂,不新插一行 ——
不然上一个人退出登录之后,推送还会继续发到这台手机上。

不回填任何数据。老的极光通道照旧:名下一台自建设备都没有的人,还是走别名那条路。

Revision ID: 0146
Revises: 0145
"""
import sqlalchemy as sa
from alembic import op

revision = '0146'
down_revision = '0145'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'push_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('channel', sa.String(length=10), nullable=False),
        sa.Column('token', sa.String(length=512), nullable=False),
        sa.Column('app', sa.String(length=10), nullable=False, server_default='user'),
        sa.Column('sandbox', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('seen_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('fail_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel', 'token', name='uq_push_devices_token'),
    )
    op.create_index('ix_push_devices_user_id', 'push_devices', ['user_id'], unique=False)
    op.create_index('ix_push_devices_channel', 'push_devices', ['channel'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_push_devices_channel', table_name='push_devices')
    op.drop_index('ix_push_devices_user_id', table_name='push_devices')
    op.drop_table('push_devices')
