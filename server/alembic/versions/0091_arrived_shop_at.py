"""骑手到店时刻与取餐时刻

等餐时长 = picked_up_at − arrived_shop_at。三处要用:
骑手申诉超时时的证据(不用他自己举证)、商家看自己出餐表现的真数、
ETA 修正的输入。

**只记录不判罚**:有了它很容易顺手加一条「等餐超 X 分钟扣商家分」——
不做,与「不做违规积分」一致。它的作用是让争议有据可查。

picked_up_at 单开一列而不是从 order_events 里捞:那张表是给审计用的,
每次算等餐时长都去 join 它,索引和口径都不合适。

Revision ID: 0091
Revises: 0090
"""
import sqlalchemy as sa
from alembic import op

revision = '0091'
down_revision = '0090'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('arrived_shop_at',
                                      sa.DateTime(timezone=True),
                                      nullable=True))
    op.add_column('orders', sa.Column('picked_up_at',
                                      sa.DateTime(timezone=True),
                                      nullable=True))
    # 存量回填 picked_up_at:order_events 里有流转记录,取最早那条
    # (重复流转不可能,但保险起见取 min)。arrived_shop_at 不回填 ——
    # 历史上根本没采集过,猜一个出来会让等餐时长变成假数据
    op.execute("""
        UPDATE orders o SET picked_up_at = e.at
        FROM (SELECT order_id, min(created_at) AS at FROM order_events
              WHERE to_status = 'picked_up' GROUP BY order_id) e
        WHERE e.order_id = o.id
    """)


def downgrade() -> None:
    op.drop_column('orders', 'picked_up_at')
    op.drop_column('orders', 'arrived_shop_at')
