"""机器人平台:菜单按钮、webhook 最近错误、webhook 密钥加密存,更新队列的两个索引(#355,DEV-PROMPTS-40 §5.13)

bots / bot_updates 两张表 0126 已经建好,这里只补:
- 菜单按钮分三种(命令列表 / 打开小程序 / 无),0126 只有 menu_app_id,补上类型和按钮文字;
- getWebhookInfo 要的「最近一次投递失败的时间和原因」;
- webhook 的 secret_token 最长 256 位,而且要**加密落库**(库被拖走时拿不到它去伪造推给开发者的请求),
  密文比 64 长,改成 Text;
- 投递循环按「到点没投」扫(next_try_at),过期清理按 created_at 扫,各一个索引。

手写迁移,不回填任何数据。

Revision ID: 0129
Revises: 0128
"""
import sqlalchemy as sa
from alembic import op

revision = '0129'
down_revision = '0128'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bots', sa.Column('menu_type', sa.String(length=10), nullable=False,
                                    server_default=''))
    op.add_column('bots', sa.Column('menu_text', sa.String(length=64), nullable=False,
                                    server_default=''))
    op.add_column('bots', sa.Column('webhook_error_at', sa.DateTime(timezone=True),
                                    nullable=True))
    op.add_column('bots', sa.Column('webhook_error', sa.String(length=300), nullable=False,
                                    server_default=''))
    op.alter_column('bots', 'webhook_secret', type_=sa.Text(),
                    existing_type=sa.String(length=64), existing_nullable=False)
    op.create_index('ix_bot_updates_due', 'bot_updates', ['next_try_at'],
                    postgresql_where=sa.text('delivered_at IS NULL'))
    op.create_index('ix_bot_updates_created', 'bot_updates', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_bot_updates_created', table_name='bot_updates')
    op.drop_index('ix_bot_updates_due', table_name='bot_updates')
    op.alter_column('bots', 'webhook_secret', type_=sa.String(length=64),
                    existing_type=sa.Text(), existing_nullable=False,
                    postgresql_using='left(webhook_secret, 64)')
    op.drop_column('bots', 'webhook_error')
    op.drop_column('bots', 'webhook_error_at')
    op.drop_column('bots', 'menu_text')
    op.drop_column('bots', 'menu_type')
