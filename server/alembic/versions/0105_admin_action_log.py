"""管理员写操作留痕

商家审批、骑手实名、平台开关、提现打款 —— 这些接口原先都拿到了
`admin: User` 却一个都没记谁操作的。只能 curl 时缺口还小,
做成后台点两下就能批之后,它就是个真问题。界面和留痕一起上。

Revision ID: 0105
Revises: 0104
"""
import sqlalchemy as sa
from alembic import op

revision = '0105'
down_revision = '0104'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'admin_action_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('admin_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False),
        # 操作当时的手机号快照:人会离职、号会变,外键答"是谁",快照答"当时他是谁"
        sa.Column('admin_phone', sa.String(20), nullable=False,
                  server_default=''),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('target_type', sa.String(30), nullable=False,
                  server_default=''),
        sa.Column('target_id', sa.String(40), nullable=False,
                  server_default=''),
        sa.Column('detail', sa.dialects.postgresql.JSONB(),
                  nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_adminlog_admin', 'admin_action_logs', ['admin_id'])
    op.create_index('ix_adminlog_action', 'admin_action_logs', ['action'])
    # 按对象查历史:"这家店被谁动过"
    op.create_index('ix_adminlog_target', 'admin_action_logs',
                    ['target_type', 'target_id'])
    # 列表默认按时间倒序
    op.create_index('ix_adminlog_created', 'admin_action_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_adminlog_created', table_name='admin_action_logs')
    op.drop_index('ix_adminlog_target', table_name='admin_action_logs')
    op.drop_index('ix_adminlog_action', table_name='admin_action_logs')
    op.drop_index('ix_adminlog_admin', table_name='admin_action_logs')
    op.drop_table('admin_action_logs')
