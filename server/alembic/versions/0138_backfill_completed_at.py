"""补历史:核销完成的自取单、后台先行赔付完成的单,completed_at 是空的

这两条完成路径原来只改了状态、没写完成时刻(routers/orders.pickup_verify、
routers/admin.resolve_delivery_issue 的先行赔付,代码已修)。completed_at 是交易完成时间,
法定要留存(见 0069);顾客信用分也按它算「完成一单」落在哪天,空着的只好拿下单时间顶。

怎么补:
1. 取这一单「已完成」那条流转记录的时间(order_events.to_status = 'completed',有多条取最早的)——
   两条路径改状态和写这条记录在同一个事务里,它就是当时的完成时刻;
2. 没有这条记录的(正常路径不会出现,测试夹具直接插的单才会),退一步取商家入账行的时间:
   结算(settle_order)和改状态也在同一个事务里,入账那一刻就是完成那一刻;
3. 两样都没有的不猜,留空。0069 当年拿 updated_at 兜底,可 updated_at 会被风控回写这类
   和订单流转无关的写入顶到当前时间,拿它当完成时间比留空更糟。

自取单顺手补送达时刻 delivered_at = 同一刻:自取单没有「送达」这一步,取到餐就是送达
(/transition 完成自取单、清扫自动完成都是这么写的)。外卖单的 delivered_at 不动:
先行赔付的单餐没送到,送达时间照实留空。

只动 status = 'completed' 且 completed_at 为空的行:可以重跑,重跑不改任何已有的值。
downgrade 不回退 —— 补上的是本来就该有的数,回退成空没有意义。

Revision ID: 0138
Revises: 0137
"""
import sqlalchemy as sa
from alembic import op

revision = '0138'
# 接在本批的 0137 后面:两条都接 0135 的话会有两个 head,alembic upgrade head(CI 也用它)直接失败。
# 合并时 0137 改接实际的上一条(比如 0136),这里跟着 0137 不用动
down_revision = '0137'
branch_labels = None
depends_on = None

# 两步共用:把 src 子查询给出的 (order_id, at) 写进完成时刻;自取单的送达时刻同一刻
_FILL = """
UPDATE orders o
   SET completed_at = src.at,
       delivered_at = CASE WHEN o.pickup AND o.delivered_at IS NULL THEN src.at
                           ELSE o.delivered_at END
  FROM ({src}) src
 WHERE o.id = src.order_id AND o.completed_at IS NULL
"""

_FROM_EVENTS = """
SELECT e.order_id, min(e.created_at) AS at
  FROM order_events e JOIN orders x ON x.id = e.order_id
 WHERE x.status = 'completed' AND x.completed_at IS NULL AND e.to_status = 'completed'
 GROUP BY e.order_id
"""

_FROM_EARNINGS = """
SELECT m.order_id, min(m.created_at) AS at
  FROM merchant_earnings m JOIN orders x ON x.id = m.order_id
 WHERE x.status = 'completed' AND x.completed_at IS NULL AND m.kind = 'earning'
 GROUP BY m.order_id
"""


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(_FILL.format(src=_FROM_EVENTS)))
    conn.execute(sa.text(_FILL.format(src=_FROM_EARNINGS)))


def downgrade() -> None:
    pass
