"""AI 机器人归用户所有,模型也自己带(#386)

2026-09-16 运营方定:**平台不做大模型级别的机器人,所有接入都是用户级别的,
平台只负责搭建平台。** 于是:

- `owner_id`:这个机器人是谁的(为空的是这之前平台建的那几个);
- `mode`:怎么接模型 —— `client` 是本机模型(App 自己调 127.0.0.1,
  key 和模型不离开设备),`server` 是用户填一个公网地址、平台去调;
- `endpoint` / `model` / `api_key_enc` / `timeout_seconds`:server 模式下用的,
  密钥加密存。

平台那几项模型配置(ai_endpoint / ai_model / ai_api_key / ai_system_prompt /
ai_timeout_seconds)同批从开关白名单里去掉 —— 平台不再替任何人调模型。
**已经写进库的那几行不动**:留着比删掉安全(万一还没升级完的进程读到),
它们不再被任何代码读。

Revision ID: 0149
Revises: 0148
"""
import sqlalchemy as sa
from alembic import op

revision = '0149'
down_revision = '0148'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ai_personas', sa.Column('owner_id', sa.Integer(), nullable=True))
    op.create_foreign_key('ai_personas_owner_id_fkey', 'ai_personas', 'users',
                          ['owner_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_ai_personas_owner_id', 'ai_personas', ['owner_id'], unique=False)
    op.add_column('ai_personas', sa.Column('mode', sa.String(length=8), nullable=False,
                                           server_default='client'))
    op.add_column('ai_personas', sa.Column('endpoint', sa.String(length=300),
                                           nullable=False, server_default=''))
    op.add_column('ai_personas', sa.Column('model', sa.String(length=80),
                                           nullable=False, server_default=''))
    op.add_column('ai_personas', sa.Column('api_key_enc', sa.Text(),
                                           nullable=False, server_default=''))
    op.add_column('ai_personas', sa.Column('timeout_seconds', sa.Integer(),
                                           nullable=False, server_default='30'))


def downgrade() -> None:
    for col in ('timeout_seconds', 'api_key_enc', 'model', 'endpoint', 'mode'):
        op.drop_column('ai_personas', col)
    op.drop_index('ix_ai_personas_owner_id', table_name='ai_personas')
    op.drop_constraint('ai_personas_owner_id_fkey', 'ai_personas', type_='foreignkey')
    op.drop_column('ai_personas', 'owner_id')
