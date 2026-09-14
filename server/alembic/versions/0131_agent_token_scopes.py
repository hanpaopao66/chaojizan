"""AI 助手令牌分权限:agent_tokens.scopes

一个令牌能做哪几件事,签发时由人勾选(security.AGENT_SCOPES):
order 点餐(只到待支付)、video 发视频(建稿、传片、提审)、miniapp 发布小程序和小游戏
(传包、提审、审核通过后发布)。服务端按这一列逐次放行,默认拒绝。

已有的令牌签发时只能点餐,回填成 ["order"] —— 能力不因为这次迁移变大。

Revision ID: 0131
Revises: 0130
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0131'
down_revision = '0130'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('agent_tokens', sa.Column(
        'scopes', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'[\"order\"]'::jsonb")))


def downgrade() -> None:
    op.drop_column('agent_tokens', 'scopes')
