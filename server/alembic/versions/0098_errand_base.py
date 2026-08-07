"""跑腿地基:order_kind + 订单自带取件点(纯结构,不含任何跑腿功能)

见 docs/DESIGN-errand.md。这一步只加字段和访问器,先跑通回归,
再上帮送/帮买 —— 一次把结构和功能一起改,出问题分不清是哪边的。

外卖单的取件点是那家店(固定),跑腿单的取件点是用户当场填的(每单不同),
所以取件点放订单上。merchant_id 的非空约束不动:跑腿单挂到本城一个
biz_type='errand' 的服务主体上,那 106 处依赖 merchant_id 的代码一行不改。
"""
import sqlalchemy as sa
from alembic import op

revision = '0098'
down_revision = '0097'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # food(默认) / errand_send 帮送 / errand_buy 帮买。
    # 存量订单全部落到 food —— 这是唯一正确的默认值
    op.add_column('orders', sa.Column(
        'order_kind', sa.String(16), nullable=False, server_default='food'))
    op.create_index('ix_orders_order_kind', 'orders', ['order_kind'])

    # 取件点。外卖单这几列为空,读的时候走 services/errand.pickup_point
    op.add_column('orders', sa.Column(
        'pickup_address', sa.String(200), nullable=False, server_default=''))
    op.add_column('orders', sa.Column(
        'pickup_lat', sa.Float(), nullable=True))
    op.add_column('orders', sa.Column(
        'pickup_lng', sa.Float(), nullable=True))
    op.add_column('orders', sa.Column(
        'pickup_contact_name', sa.String(50), nullable=False,
        server_default=''))
    op.add_column('orders', sa.Column(
        'pickup_contact_phone', sa.String(20), nullable=False,
        server_default=''))
    # 物品描述 / 要买什么
    op.add_column('orders', sa.Column(
        'errand_note', sa.String(300), nullable=False, server_default=''))


def downgrade() -> None:
    for col in ('errand_note', 'pickup_contact_phone', 'pickup_contact_name',
                'pickup_lng', 'pickup_lat', 'pickup_address'):
        op.drop_column('orders', col)
    op.drop_index('ix_orders_order_kind', table_name='orders')
    op.drop_column('orders', 'order_kind')
