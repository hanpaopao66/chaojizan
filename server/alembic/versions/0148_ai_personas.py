"""AI 机器人的人设表(#385)

账号本身还是普通机器人(users 一行 role=bot + bots 一行),这里只多存
「它是谁、聊什么、多久说一次、上次什么时候说的」。

频率记时间戳不记计数:计数器要跨进程同步、要考虑重启清零和跨天怎么算;
而「距离上次够不够久」只是读一个时间戳,重启、多进程、改配置都不影响。

不回填任何数据。没人建 AI 号的话这张表一直是空的,`ai_bots_enabled` 也缺省关。

Revision ID: 0148
Revises: 0147
"""
import sqlalchemy as sa
from alembic import op

revision = '0148'
down_revision = '0147'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ai_personas',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('persona', sa.Text(), nullable=False, server_default=''),
        sa.Column('topics', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('posts_per_day', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('replies_per_day', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_post_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_reply_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    op.drop_table('ai_personas')
