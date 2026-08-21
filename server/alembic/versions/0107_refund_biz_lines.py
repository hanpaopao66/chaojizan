"""退款流水表泛化到三条业务线(外卖/团购券/住宿)+ 券退款时刻列

## 为什么要动这张表

`refunds` 是资金对账的凭据表:每退一次钱写一条,自检核对
「Σ流水 == 业务表上的退款汇总」。但它从建表起就绑死在外卖上 ——
`order_id` 是 `orders.id` 的外键且非空、`order_no` 非空。

于是团购券和住宿的「退款」在结构上根本装不进来,实际代码里也确实
一条都没写:券把 `status` 改成 `refunded`、住宿给 `refund_cents`
赋个值就算退完了。模拟支付期这歪打正着地自洽(没收钱也没退钱),
真开微信支付那一刻就变成「收了钱、标记已退款、钱没退」。

## 为什么泛化一张表,而不是各建各的

`voucher_refunds` / `stay_refunds` 那条路要把三样东西各复制一遍:
自检的 Σ 恒等式、「退款挂在 requested 没回执」的挂账检查
(services/audit 规则 11 是**全表聚合**,不带业务过滤 ——
泛化之后券和住宿白得这条覆盖,分表就得再写两遍)、
以及微信 REFUND.* 回调按 out_refund_no 反查流水那一段
(routers/payments,现在是业务无关的,分表后得挨个表试)。
这个平台已经有四条业务线,复制到第三遍必然有人漏改一处。

## 列的分工

- `biz_type` + `biz_id`:所有行都有,是**唯一的**业务归属判据;
- `order_id` / `order_no`:只有外卖/跑腿行有,改成可空。留着不是冗余 ——
  `_reversal_due_ids`(规则 6 的冲账判据)要 join 回 orders,
  外键约束也只有真外键给得了。券/住宿行这两列是 NULL,
  于是所有现存的 `Refund.order_id == order.id` 查询原样正确。

## voucher_purchases.refunded_at

自检的时间窗**必须取"钱落定的那一刻"**(规则 8/9 刚为此从 created_at
改成 redeemed_at / completed_at)。券的有效期最长 365 天,
按 created_at 取 30 天窗的话,第 31 天以后退的券一生都不会被自检看到。
而 `redeemed_at` 是核销时刻,退款的券根本没核销过 —— 没有列可用,
所以新加一列。历史行回填 coalesce(paid_at, created_at) 作近似。

Revision ID: 0107
Revises: 0106
"""
import sqlalchemy as sa
from alembic import op

revision = '0107'
down_revision = '0106'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default 只为回填存量行用,回填完就摘掉:
    # 留着的话,以后哪个裸 SQL 插入忘了写 biz_type 会**静默**记成外卖,
    # 一笔券退款被算进外卖的对账里 —— 这种错没有任何症状。
    op.add_column("refunds", sa.Column(
        "biz_type", sa.String(10), nullable=False, server_default="food"))
    op.add_column("refunds", sa.Column("biz_id", sa.Integer(), nullable=True))
    op.execute("UPDATE refunds SET biz_id = order_id WHERE order_id IS NOT NULL")

    # **回滚之后再滚回来,也要认得出券/住宿那些行。**
    #
    # downgrade 会把 biz_type/biz_id 删掉,而券和住宿的行没有 order_id
    # 可以反推 —— 只按 order_id 回填的话,再 upgrade 时它们的 biz_id 是 NULL,
    # 下面那句 NOT NULL 直接失败,迁移卡死在半路,而这些行是真实退过的钱。
    #
    # 好在 `out_refund_no` 的构成是 `{业务单号}-{随机}`(历史补录是
    # `{业务单号}-legacy-{随机}`),而三种业务单号本身都是不含 '-' 的随机串,
    # split_part 取第一段就是单号,再按唯一索引等值 join 回去。
    for table, col, biz in (("voucher_purchases", "purchase_no", "voucher"),
                            ("stay_orders", "order_no", "stay")):
        op.execute(
            f"UPDATE refunds r SET biz_type = '{biz}', biz_id = t.id "
            f"FROM {table} t "
            f"WHERE r.biz_id IS NULL "
            f"  AND t.{col} = split_part(r.out_refund_no, '-', 1)")
    # 还认不出来的行到这里会让 NOT NULL 失败 —— **这是想要的**:
    # 宁可迁移报错要人来看,也不能把一笔来路不明的退款默认记成外卖的
    op.alter_column("refunds", "biz_id", nullable=False)
    op.alter_column("refunds", "biz_type", server_default=None)

    op.alter_column("refunds", "order_id",
                    existing_type=sa.Integer(), nullable=True)
    op.alter_column("refunds", "order_no",
                    existing_type=sa.String(32), nullable=True)
    # 自检按 (biz_type, biz_id) 逐笔求和,这是它唯一的取数路径。
    # 表小(万级),普通 CREATE INDEX 是毫秒级,不值得为它引入
    # CONCURRENTLY 那套「非原子、失败留 INVALID 索引」的复杂度
    # (0106 那批是 3.5 万单的 orders,量级不同)
    op.create_index("ix_refunds_biz", "refunds", ["biz_type", "biz_id"])

    # 历史行没有"退款那一刻"可用,回填 coalesce(paid_at, created_at) 作近似。
    # 只影响自检的 30 天取窗,不影响任何金额。
    op.add_column("voucher_purchases", sa.Column(
        "refunded_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE voucher_purchases SET refunded_at = "
               "coalesce(paid_at, created_at) "
               "WHERE status = 'refunded' AND refunded_at IS NULL")


def downgrade() -> None:
    op.drop_column("voucher_purchases", "refunded_at")
    op.drop_index("ix_refunds_biz", table_name="refunds")
    op.drop_column("refunds", "biz_id")
    op.drop_column("refunds", "biz_type")
    # **order_id / order_no 的 NOT NULL 不恢复。**
    #
    # 回滚发生时库里已经有券/住宿的退款流水,它们的 order_id 是 NULL ——
    # 恢复 NOT NULL 只有两条路:要么迁移直接失败(回滚不下去),
    # 要么把这些行删掉。而它们是**真实退过的钱的凭据**,
    # 删掉等于为了让 schema 好看而销毁资金记录。
    #
    # 留成可空的代价只是"约束比原来松",老代码写入时照样会填这两列;
    # 再 upgrade 回来也是幂等的。两害相权,不碰数据。
