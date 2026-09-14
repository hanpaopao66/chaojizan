"""补历史:后台「按送达处理」的单,送达时刻空着的,补成骑手上报那条配送异常的时刻

配送异常裁决「按送达处理」(admin.resolve_delivery_issue 的 mark_delivered)原来只把状态改成
已送达、不写 delivered_at,要等 24 小时后自动完成(或者顾客确认收货)才顺手写成那一刻 ——
法定要留存的送达时间晚一天左右(代码已修:裁决时就写骑手上报异常的时刻)。

这里只补**还空着**的:裁决过、还没完成的单(delivered_at 为空、有一条 resolution =
mark_delivered 的配送异常),补成那条异常的 created_at —— 骑手就是那时候到了、联系不上人。
一单只可能有一条按送达处理的异常(裁决之后订单就不在配送中了,报不了第二条),保险起见取最早那条。

**已经完成的那批不动。** 它们的送达时刻在完成时被写成了完成那一刻(不是空的),按「只动空值」
的约定这里不改;要不要改成上报时刻另行拍板(判据是有按送达处理的裁决、送达时刻恰好等于完成时刻)。

只动 delivered_at 为空的行:可以重跑,重跑不改任何已有的值。downgrade 不回退 —— 补上的是
本来就该有的数,回退成空没有意义。

Revision ID: 0139
Revises: 0138
"""
import sqlalchemy as sa
from alembic import op

revision = '0139'
down_revision = '0138'
branch_labels = None
depends_on = None

_FILL = """
UPDATE orders o
   SET delivered_at = src.reported_at
  FROM (SELECT order_id, min(created_at) AS reported_at
          FROM delivery_issues
         WHERE resolution = 'mark_delivered'
         GROUP BY order_id) src
 WHERE o.id = src.order_id AND o.delivered_at IS NULL
"""


def upgrade() -> None:
    op.get_bind().execute(sa.text(_FILL))


def downgrade() -> None:
    pass
