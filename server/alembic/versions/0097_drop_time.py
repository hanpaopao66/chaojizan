"""送达段停留时长:场景难度的唯一地基

到店等餐时长已经在记了(arrived_shop_at / picked_up_at),**送达这一段
一直没有**。而"这个小区难进""这栋写字楼电梯要等十分钟"这类事,
全部发生在这一段里 —— 没有它,场景难度就只能靠拍脑袋。

## 为什么聚合键不用地址字符串

同一栋楼十个人能写出十种地址("XX路8号1单元""XX路八号一单元""XX大厦A座")。
按字符串聚合,永远攒不出一个有样本量的点位。所以按**坐标网格 + 楼层段**
聚合,并把这个键在送达时刻**快照**到订单上 —— 事后重算的话,
网格算法一改,历史数据就全对不上了。

## 只记录,不产生任何后果

这一批不进 ETA、不进钱、不进考核。先让数据跑两周,看分位数稳不稳。
"""
import sqlalchemy as sa
from alembic import op

revision = '0097'
down_revision = '0096'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 骑手点「我到了」的时刻。幂等:重复点不刷新 ——
    # 刷新的话多点一次就把停留时长清零了(和到店时刻同一个口径)
    op.add_column('orders', sa.Column(
        'arrived_drop_at', sa.DateTime(timezone=True), nullable=True))
    # 送达段停留时长(分钟,送达时算一次存快照)
    op.add_column('orders', sa.Column(
        'drop_minutes', sa.Float(), nullable=True))
    # 聚合键快照:网格 + 楼层段。**存下来不重算** ——
    # 网格算法一改,历史数据就全对不上了
    op.add_column('orders', sa.Column(
        'drop_key', sa.String(40), nullable=True))
    # 分位数查询就是 WHERE drop_key = ? AND drop_minutes IS NOT NULL
    op.create_index('ix_orders_drop_key', 'orders', ['drop_key'])


def downgrade() -> None:
    op.drop_index('ix_orders_drop_key', table_name='orders')
    op.drop_column('orders', 'drop_key')
    op.drop_column('orders', 'drop_minutes')
    op.drop_column('orders', 'arrived_drop_at')
