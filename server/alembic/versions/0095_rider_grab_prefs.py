"""骑手接单偏好:单价下限 / 只看顺路 / 避开酒类

此前偏好只有一个接单半径。半径解决"离我远的别给我看",但骑手嘴里
另外三件事它一件都解决不了:

- **兼职骑手**下班路上想捎一单,他要的不是"5 公里内",是"顺路";
- 一个 3 块钱的单,他看一眼就划走,却要一天划几百次;
- 酒类要查收件人年龄,有人不想沾这个麻烦(查不查都可能起纠纷)。

三个都是**只影响他自己看到什么**,不影响订单存在与派给别人 ——
所以抢单池要把"被你的偏好挡掉了几单"摆出来。悄悄过滤会变成
"今天怎么没单",他不会想到是自己两个月前设的一个开关。
"""
import sqlalchemy as sa
from alembic import op

revision = '0095'
down_revision = '0094'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0 = 不限。用 0 而不是 NULL:这三个都是"默认全接",
    # 没有"未设置"和"设成不限"的语义差别,少一个空值分支
    op.add_column('users', sa.Column(
        'grab_min_fee_cents', sa.Integer(), nullable=False,
        server_default='0'))
    op.add_column('users', sa.Column(
        'grab_same_way_only', sa.Boolean(), nullable=False,
        server_default=sa.false()))
    op.add_column('users', sa.Column(
        'grab_avoid_alcohol', sa.Boolean(), nullable=False,
        server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('users', 'grab_avoid_alcohol')
    op.drop_column('users', 'grab_same_way_only')
    op.drop_column('users', 'grab_min_fee_cents')
