"""ready_timeout_cancel_rules

出餐超时提醒 + 取消规则分级:
- merchants.promise_ready_minutes 承诺出餐时长(默认 15 分钟)
- orders.accepted_at 接单时刻(超时判定与用户反悔窗口的基准,历史数据从
  order_events 回填)、ready_alert_stage 提醒档位(0/1/2,每档一次)、
  ready_late 出餐是否超时(出餐瞬间定格,统计超时率用)

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-19 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('merchants', sa.Column('promise_ready_minutes', sa.Integer(),
                                         nullable=False, server_default='15'))
    op.add_column('orders', sa.Column('accepted_at', sa.DateTime(timezone=True),
                                      nullable=True))
    op.add_column('orders', sa.Column('ready_alert_stage', sa.SmallInteger(),
                                      nullable=False, server_default='0'))
    op.add_column('orders', sa.Column('ready_late', sa.Boolean(),
                                      nullable=False, server_default=sa.text('false')))
    # 历史订单的接单时刻从事件表回填,超时率统计从上线起就有完整口径
    op.execute("""
        UPDATE orders SET accepted_at = e.at FROM (
            SELECT order_id, min(created_at) AS at
            FROM order_events WHERE to_status = 'accepted' GROUP BY order_id
        ) e WHERE e.order_id = orders.id
    """)


def downgrade() -> None:
    op.drop_column('orders', 'ready_late')
    op.drop_column('orders', 'ready_alert_stage')
    op.drop_column('orders', 'accepted_at')
    op.drop_column('merchants', 'promise_ready_minutes')
