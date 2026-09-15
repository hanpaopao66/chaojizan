"""可下发文案加「隐藏」:后台能把一个位置整个藏起来(底部菜单的一格、一段说明),不只是改字

2026-09-15 用户:所有可配置的东西都要既能改字、又能显示 / 隐藏。哪些位置能藏、为什么有的不能藏,
写在 services/copy_registry.py(首页、我的这两格藏了就进不去设置、登录不了,不许藏)。

text 仍然不许为 NULL:只藏不改字的那一行 text 存空串,/config 下发文案时跳过空串(客户端用自己的默认值)。

Revision ID: 0142
Revises: 0141
"""
import sqlalchemy as sa
from alembic import op

revision = '0142'
down_revision = '0141'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('platform_copy',
                  sa.Column('hidden', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    # 只藏没改字的行留下来是空串文案,/config 会原样下发空串 —— 回退时一起删掉
    op.execute("DELETE FROM platform_copy WHERE text = ''")
    op.drop_column('platform_copy', 'hidden')
