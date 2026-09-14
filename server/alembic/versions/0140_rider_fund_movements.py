"""骑手保障金池的支出和回池:rider_fund_movements

2026-09-14 拍板「平台没有钱,不做平台出钱的赔付」:判骑手责任时,商家那份餐钱先从骑手
保障金池出,池子不够的部分从骑手收入里扣(services/rider_fault.py)。池子的计提一直在公开账本里
(每笔配送入账计提固定额),支出以前没有 —— 这张表记每一笔支出(payout)和申诉改判后的回池
(return),同样进公开账本(rider_fund.rows)。

骑手那一侧不用建表:冲回这单收入、另扣的部分、改判加回去,都是 rider_earnings 上追加的行
(kind = fault_reversal / fault_charge / fault_refund;kind 列是 varchar,不用改类型)。

一单一种一条(唯一约束),只追加。

Revision ID: 0140
Revises: 0139
"""
import sqlalchemy as sa
from alembic import op

revision = '0140'
down_revision = '0139'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rider_fund_movements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=False),
        sa.Column('order_no', sa.String(length=32), nullable=False),
        # payout 从池子支出 / return 改判回池
        sa.Column('kind', sa.String(length=12), nullable=False),
        # 恒为正数,方向看 kind
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('order_id', 'kind', name='uq_rider_fund_movements_order_kind'),
    )
    op.create_index('ix_rider_fund_movements_created_at', 'rider_fund_movements',
                    ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_rider_fund_movements_created_at', table_name='rider_fund_movements')
    op.drop_table('rider_fund_movements')
