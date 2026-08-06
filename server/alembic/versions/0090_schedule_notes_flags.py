"""定时改价 + 顾客备注 + 异常订单标记

dish_schedules:**一次性**的定时动作(夜宵档提价、限时降价),
与 Dish.serve_window(每天重复、只灰不改价)不是一回事。
过期太久的不补跑 —— 把三天前该降的价降下来,商家会莫名其妙亏一笔。

customer_notes:"302 那位不要香菜"。这是**顾客的个人信息**,商家能记
是因为他在服务这个人 —— 只对本店可见,不跨店、不进任何对外接口。

order_flags:商家标记的疑似职业索赔/恶意差评。**只上报给平台,
不给商家拉黑顾客的权力** —— 给了拉黑权它会变成报复工具(差评了就拉黑),
而真正的职业索赔是跨店行为,只有平台看得到全局。

Revision ID: 0090
Revises: 0089
"""
import sqlalchemy as sa
from alembic import op

revision = '0090'
down_revision = '0089'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'dish_schedules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False),
        sa.Column('dish_id', sa.Integer(), sa.ForeignKey('dishes.id'),
                  nullable=False),
        sa.Column('action', sa.String(10), nullable=False),
        sa.Column('price_cents', sa.Integer(), nullable=True),
        sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(10), nullable=False,
                  server_default='pending'),
        sa.Column('note', sa.String(100), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sched_shop', 'dish_schedules', ['merchant_id'])
    op.create_index('ix_sched_dish', 'dish_schedules', ['dish_id'])
    # 清扫扫描走这条:只捞 pending 且到点的
    op.create_index('ix_sched_due', 'dish_schedules', ['status', 'run_at'])

    op.create_table(
        'customer_notes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False),
        sa.Column('note', sa.String(200), nullable=False, server_default=''),
        sa.Column('tags', sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default='[]'),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # 一店一顾客一条:接单台按 (店, 人) 直查,重复记录会让人看到两份备注
    op.create_index('ix_notes_shop_user', 'customer_notes',
                    ['merchant_id', 'user_id'], unique=True)

    op.create_table(
        'order_flags',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False),
        sa.Column('order_no', sa.String(32), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False),
        sa.Column('kind', sa.String(10), nullable=False,
                  server_default='other'),
        sa.Column('reason', sa.String(300), nullable=False,
                  server_default=''),
        sa.Column('status', sa.String(10), nullable=False,
                  server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_flags_shop', 'order_flags', ['merchant_id'])
    op.create_index('ix_flags_user', 'order_flags', ['user_id'])
    op.create_index('ix_flags_status', 'order_flags', ['status'])
    # 一店一单只能标一次(重复标记不会让它更成立,只会把队列灌满)
    op.create_index('ix_flags_shop_order', 'order_flags',
                    ['merchant_id', 'order_no'], unique=True)


def downgrade() -> None:
    op.drop_table('order_flags')
    op.drop_table('customer_notes')
    op.drop_table('dish_schedules')
