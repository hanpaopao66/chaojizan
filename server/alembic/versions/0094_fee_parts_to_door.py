"""配送费构成快照 + 送上门开关

## fee_parts

配送费的拆分此前只在预览接口里露过一次,**下单之后就没人看得到了** ——
订单详情、小票、骑手端、对账全都只有一个总数。夜间费和天气费等于是
"悄悄加上去的",顾客只看到总数变了。

存快照而不是事后重算:费率会调、天气开关会关,重算出来的数和当时
真正收的对不上 —— 那就不叫透明,叫"我们现在觉得应该是多少"。

存量回填 {"base": delivery_fee_cents}:历史单没有拆分记录,
**把已知的总数放进 base 而不是编造夜间/天气的分项** ——
编出来的拆分比没有拆分更糟。

## to_door

送上门 / 送到楼下由顾客自己选。默认 true(与此前行为一致:
本来就是送上门),选了楼下则不收上门难度费,骑手也没有义务上楼。

Revision ID: 0094
Revises: 0093
"""
import sqlalchemy as sa
from alembic import op

revision = '0094'
down_revision = '0093'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column(
        'fee_parts', sa.dialects.postgresql.JSONB(),
        nullable=False, server_default='{}'))
    op.add_column('orders', sa.Column(
        'to_door', sa.Boolean(), nullable=False, server_default='true'))
    # 存量:只回填已知的总数,不编造分项
    op.execute("""
        UPDATE orders SET fee_parts = jsonb_build_object(
            'base', delivery_fee_cents)
        WHERE delivery_fee_cents > 0
    """)


def downgrade() -> None:
    op.drop_column('orders', 'to_door')
    op.drop_column('orders', 'fee_parts')
