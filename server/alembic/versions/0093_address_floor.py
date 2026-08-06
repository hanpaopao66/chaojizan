"""地址楼层与电梯

爬 6 楼和 1 楼临街是两种活,用同一个 ETA 对骑手不公平、对顾客也是个
不准的承诺。

**null = 没填**,不加时 —— 猜一个出来会让 ETA 变成假承诺,
顾客看到的时间不该建立在我们对他家几楼的猜测上。

加时进的是**给顾客看的 ETA**(不是只放宽骑手判定):平台本来就不因超时
处罚骑手,而一个诚实的 35 分钟好过一个乐观的 28 分钟再超时赔付。

Revision ID: 0093
Revises: 0092
"""
import sqlalchemy as sa
from alembic import op

revision = '0093'
down_revision = '0092'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('addresses', 'orders'):
        op.add_column(table, sa.Column('floor', sa.Integer(), nullable=True))
        op.add_column(table, sa.Column('has_elevator', sa.Boolean(),
                                       nullable=True))


def downgrade() -> None:
    for table in ('addresses', 'orders'):
        op.drop_column(table, 'has_elevator')
        op.drop_column(table, 'floor')
