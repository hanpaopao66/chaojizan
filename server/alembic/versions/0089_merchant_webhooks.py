"""商家系统回调(收银/ERP 主动收单)

此前开放接口只有两个 GET,商家的收银系统只能轮询 —— 要么慢(轮询间隔
就是延迟),要么把接口打爆(为了快就 1 秒一次)。

secret 存哈希、明文只在创建时给一次:与 API Key 同一套做法,
理由也一样 —— 库被拖走时拿到哈希签不出有效请求。

webhook_deliveries 的写入量和订单量同阶,是这套里最会长的表:
按 (status, next_retry_at) 建索引给重试扫描用,按 created_at 给清理用。

Revision ID: 0089
Revises: 0088
"""
import sqlalchemy as sa
from alembic import op

revision = '0089'
down_revision = '0088'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'merchant_webhooks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False, index=True),
        sa.Column('url', sa.String(300), nullable=False),
        sa.Column('secret_hash', sa.String(64), nullable=False),
        sa.Column('events', sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default='[]'),
        sa.Column('active', sa.Boolean(), nullable=False,
                  server_default='true'),
        sa.Column('fail_streak', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('last_error', sa.String(200), nullable=False,
                  server_default=''),
        sa.Column('last_ok_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('webhook_id', sa.Integer(),
                  sa.ForeignKey('merchant_webhooks.id'), nullable=False),
        sa.Column('event', sa.String(30), nullable=False),
        sa.Column('delivery_id', sa.String(36), nullable=False),
        sa.Column('order_no', sa.String(32), nullable=False,
                  server_default=''),
        sa.Column('attempts', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('status', sa.String(10), nullable=False,
                  server_default='pending'),
        sa.Column('last_status_code', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('last_error', sa.String(200), nullable=False,
                  server_default=''),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payload', sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_deliveries_webhook', 'webhook_deliveries',
                    ['webhook_id'])
    op.create_index('ix_deliveries_delivery_id', 'webhook_deliveries',
                    ['delivery_id'])
    # 重试扫描走这条:只捞 pending 且到点的
    op.create_index('ix_deliveries_retry', 'webhook_deliveries',
                    ['status', 'next_retry_at'])
    # 清理走这条(这张表的写入量和订单量同阶)
    op.create_index('ix_deliveries_created', 'webhook_deliveries',
                    ['created_at'])


def downgrade() -> None:
    op.drop_table('webhook_deliveries')
    op.drop_table('merchant_webhooks')
