"""停业闸门记原因

food_safety_hold 原来只是个 bool,谁落的看不出来。加上证照过期这条新的
落闸路径之后就出问题了:续证核验通过时会去解闸,而**因食安投诉成立
被停业的店,交一张新证也会被一并解封** —— 那两件事没有关系,
混在一起就是「食安停业形同虚设」的又一种写法。

取值:food_safety(食安投诉成立)/ license_expired(证过期超宽限期)/ ""(未停业)。

存量数据回填 food_safety:此前唯一的落闸路径就是食安,回填是准确的,
不是猜。

Revision ID: 0084
Revises: 0083
"""
import sqlalchemy as sa
from alembic import op

revision = '0084'
down_revision = '0083'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('merchants',
                  sa.Column('hold_reason', sa.String(20), nullable=False,
                            server_default=''))
    # 存量:此前唯一会置 food_safety_hold 的就是食安路径,回填准确
    op.execute("UPDATE merchants SET hold_reason = 'food_safety' "
               "WHERE food_safety_hold = true")


def downgrade() -> None:
    op.drop_column('merchants', 'hold_reason')
