"""转单扣钱:rider_earnings 的唯一约束改成部分唯一索引

2026-10-06 运营方定「要么就接,接了就送」:接了又转出,立刻扣 10 元,扣的钱
给最后送到这单的骑手;这单取消了就退回(services/rider_transfer.py)。

骑手那一侧都是 rider_earnings 上追加的行(kind = transfer_fee / transfer_bonus /
transfer_refund;kind 列是 varchar,不用改类型)。但一单可以被转好几手,
每一手各扣一行 —— 原来的 (order_id, kind) 唯一约束装不下。改成部分唯一索引:
transfer_fee、transfer_refund 两种以外,照旧一单一种一条(结算幂等靠它)。

Revision ID: 0150
Revises: 0149
"""
from alembic import op

revision = '0150'
down_revision = '0149'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('rider_earnings_order_id_kind_key', 'rider_earnings',
                       type_='unique')
    op.create_index(
        'uq_rider_earnings_order_kind', 'rider_earnings', ['order_id', 'kind'],
        unique=True,
        postgresql_where="kind NOT IN ('transfer_fee', 'transfer_refund')")


def downgrade() -> None:
    # 有多行转单扣款的单会让这一步失败 —— 那是对的:降级会丢账,不该悄悄成功
    op.drop_index('uq_rider_earnings_order_kind', table_name='rider_earnings')
    op.create_unique_constraint('rider_earnings_order_id_kind_key',
                                'rider_earnings', ['order_id', 'kind'])
