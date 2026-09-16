"""AI 机器人:users 加 is_ai(#385)

社区里要引入明确标注的 AI 机器人。判据放在 users 上而不是 bots 表,
是因为**每个模块都要用它**:论坛、视频、音乐的公开排序都要把 AI 的互动剔掉,
名片上要挂 AI 标 —— 让各模块自己去 join 一次 bots 表,迟早有一处会忘。

**和 `role = 'bot'` 不是一回事**:机器人管家 @guanjia_bot 是脚本写死的流程、
替人干活,它的互动算数;这里要标的是模型生成的。

缺省 false:已有的账号(包括已有的机器人)一个都不受影响。

Revision ID: 0147
Revises: 0146
"""
import sqlalchemy as sa
from alembic import op

revision = '0147'
down_revision = '0146'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_ai', sa.Boolean(), nullable=False,
                                     server_default=sa.text('false')))
    # 排序那几条 SQL 每次都要按它过滤,而 AI 号只占全部账号的极小一部分 ——
    # 部分索引只收 is_ai 为真的那几行,几乎不占地方
    op.create_index('ix_users_is_ai', 'users', ['id'], unique=False,
                    postgresql_where=sa.text('is_ai'))


def downgrade() -> None:
    op.drop_index('ix_users_is_ai', table_name='users')
    op.drop_column('users', 'is_ai')
