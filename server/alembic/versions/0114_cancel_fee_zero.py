"""整单缺货退款漏清的配送费/小费,历史数据补齐

## 为什么要补

整单缺货退款把 菜/打包/满减/补贴/实付/佣金 都置 0,**漏了配送费和小费**。
钱是退对了(refund_amount 取的就是当时的 total_cents,整额退给用户),
错的是订单**不再自洽**:total(0) ≠ 0+0-0+配送费+小费-0。

而审计规则 3 又把已取消单整个排除在外,所以这类脏数据一直没人看见。

代码那一侧已经改好(routers/orders.py 的 full_cancel 分支),规则 3 也
不再跳过已取消单 —— 但历史行不补的话,规则 3 一开就会常年报警,
而**常年报警的自检等于没有自检**,下一个真问题会被淹在噪音里。

## 为什么这样补是安全的

只动**已取消**、**实付已归零**、**取消原因是整单缺货**的行,
把配送费/小费置 0。这几列在这些行上是残留值:钱早已整额退还,
没有任何结算读它们(两处会聚合配送费的地方都排除了已取消单)。

改的是账面的自洽性,不是任何一笔钱。
"""
from alembic import op

revision = '0114'
down_revision = '0113'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE orders
           SET delivery_fee_cents = 0, tip_cents = 0
         WHERE status = 'cancelled'
           AND total_cents = 0
           AND cancel_reason = '商家缺货,整单退款'
           AND (delivery_fee_cents <> 0 OR tip_cents <> 0)
    """)


def downgrade() -> None:
    # 原值没有留档,回滚不了 —— 而这些是残留值,回滚也没有意义
    pass
