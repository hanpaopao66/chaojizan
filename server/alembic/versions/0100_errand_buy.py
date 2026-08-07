"""帮买:垫资由用户预付给平台

## 资金模型(已定)

用户下单时把**预估商品款**先付给平台,平台在结算时把**实付商品款**
结给骑手。骑手不垫自己的钱 —— 让收入最低的那个人先掏钱,
是把平台的资金风险转嫁给他。

## 三条规则(写死,不留给客服临场判断)

1. 实付 < 预估:差额原路退用户;
2. 实付 > 预估:20% 且 ≤20 元以内平台先结给骑手、再向用户补收;
   超出上限骑手**必须先发起确认**,用户同意才买;
3. 买不到:商品款全额退,跑腿费只收到店那段的距离费,
   且这条**写在下单页**而不是藏在协议里 —— 提前说了就不叫坑。

## 小票是唯一对账依据

代买最容易起的纠纷是"你是不是多报了"。小票必传、且给用户看得到,
这个纠纷根本不会发生。
"""
import sqlalchemy as sa
from alembic import op

revision = '0100'
down_revision = '0099'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 用户预付的预估商品款
    op.add_column('orders', sa.Column(
        'goods_budget_cents', sa.Integer(), nullable=False,
        server_default='0'))
    # 小票上的实付金额(骑手买完填)
    op.add_column('orders', sa.Column(
        'goods_actual_cents', sa.Integer(), nullable=True))
    # 小票照片:**唯一对账依据**,用户也看得到
    op.add_column('orders', sa.Column(
        'goods_receipt_url', sa.String(300), nullable=False,
        server_default=''))
    # 超出浮动上限时骑手发起的加价确认:pending/approved/rejected;
    # 空 = 没有发起过
    op.add_column('orders', sa.Column(
        'goods_raise_status', sa.String(12), nullable=False,
        server_default=''))
    op.add_column('orders', sa.Column(
        'goods_raise_cents', sa.Integer(), nullable=True))


def downgrade() -> None:
    for col in ('goods_raise_cents', 'goods_raise_status',
                'goods_receipt_url', 'goods_actual_cents',
                'goods_budget_cents'):
        op.drop_column('orders', col)
