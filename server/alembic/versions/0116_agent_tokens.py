"""AI 助手的受限令牌(MCP 接入)

「点单」意味着一个 agent 能花用户的钱。登录 token 什么都能干,
把它交给自动化程序,泄露就是钱没了。

这张表存的是一种**只能读 + 只能创建待支付订单**的令牌:
付款那一下永远在用户自己的 App 里由人按。即使令牌泄露,对方
花不掉一分钱。

落库(而不是只签一个 JWT)是为了两件 JWT 做不到的事:
用户看得到「有哪些助手连着我的账号」,以及能当场吊销其中一个。
"""
from alembic import op
import sqlalchemy as sa

revision = '0116'
down_revision = '0115'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'agent_tokens',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False, index=True),
        sa.Column('jti', sa.String(length=43), nullable=False,
                  unique=True, index=True),
        sa.Column('name', sa.String(length=40), nullable=False,
                  server_default=''),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('agent_tokens')
