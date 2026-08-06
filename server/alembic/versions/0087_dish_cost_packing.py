"""菜品成本与菜品级打包费

cost_cents:商家知道平台抽了多少(这块做得很透),却**不知道自己哪道菜
赚钱**。销量 TOP10 已经有了,配上成本就能给出"卖得最多的第三名其实在亏钱"。
0 = 没录过(不是成本为零),毛利一律不算 —— 猜一个成本算出来的毛利
比不显示更糟。**只商家自己可见**,不进任何对外接口。

packing_fee_cents:NULL = 用店铺默认。店铺级一刀切两头不讨好 ——
汤类打包盒三块、饮料根本不要盒,收一样的钱要么商家亏、要么顾客觉得被宰。
所以是 nullable 而不是 default 0:0 是"这道菜不收打包费"的合法取值,
和"没单独设过"必须分得开。

Revision ID: 0087
Revises: 0086
"""
import sqlalchemy as sa
from alembic import op

revision = '0087'
down_revision = '0086'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dishes', sa.Column('cost_cents', sa.Integer(),
                                      nullable=False, server_default='0'))
    # nullable:NULL = 用店铺默认;0 = 这道菜不收打包费。两者必须分得开
    op.add_column('dishes', sa.Column('packing_fee_cents', sa.Integer(),
                                      nullable=True))


def downgrade() -> None:
    op.drop_column('dishes', 'packing_fee_cents')
    op.drop_column('dishes', 'cost_cents')
