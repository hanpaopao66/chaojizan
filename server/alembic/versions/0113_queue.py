"""到店排队:桌型、号、设置、事件留痕

## 为什么建这四张表

团购券解决「钱先付了」,排队解决「位怎么排」。两件事**故意不绑在一起**:
取号免费开放,和买没买券无关 —— 绑起来就是「花钱买插队权」的变体,
而调研美团生态时正好看到有商家在干这个(引导办卡免排队)。

- `queue_table_types`:桌型各自一条队。混成一条队,预估等待必然是错的,
  而用户就是照着那个数字决定要不要等。
- `queue_settings`:商家能配的只有节奏和容量。叫号后多久才能标过号是
  平台规则,不在这张表里。
- `queue_tickets`:号。`sort_key` 是队列位置,`day` 按**北京时间**切。
- `queue_events`:每一次队列变化的留痕。公示上写着「没人能把号往前挪」,
  这句话要能被证伪,就得有一份谁在什么时候动了谁的完整记录。

## 索引为什么是这几个

排队页每次刷新都在问同一个问题:「这条队现在还有几个人、我排第几」。
`(table_type_id, day, status, sort_key)` 正好覆盖它 —— 定位队列、
滤掉已走的、按位置排序,一个索引全包。少了 sort_key 就要额外排序,
而这是用户端刷得最勤的接口之一。

`(merchant_id, customer_id, day)` 服务的是取号前那次查重(一人一店一号)。
"""
from alembic import op
import sqlalchemy as sa

revision = '0113'
down_revision = '0112'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'queue_table_types',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(),
                  sa.ForeignKey('merchants.id'), nullable=False, index=True),
        sa.Column('name', sa.String(length=20), nullable=False),
        sa.Column('seats_min', sa.Integer(), nullable=False),
        sa.Column('seats_max', sa.Integer(), nullable=False),
        sa.Column('table_count', sa.Integer(), nullable=False),
        sa.Column('turn_minutes', sa.Integer(), nullable=False,
                  server_default='45'),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'queue_settings',
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('cap_multiplier', sa.Integer(), nullable=False,
                  server_default='3'),
        sa.Column('defer_tables', sa.Integer(), nullable=False,
                  server_default='3'),
        sa.Column('notify_ahead', sa.Integer(), nullable=False,
                  server_default='3'),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'queue_tickets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ticket_no', sa.String(length=24), nullable=False,
                  unique=True, index=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False, index=True),
        sa.Column('table_type_id', sa.Integer(),
                  sa.ForeignKey('queue_table_types.id'),
                  nullable=False, index=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False, index=True),
        sa.Column('party_size', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False, index=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('sort_key', sa.Numeric(18, 6), nullable=False),
        # 过号前的位置。申诉判成立时要还原到这个值 ——
        # **平台也只能还原到这里记着的数,不能填一个任意位置**
        sa.Column('pre_pass_sort_key', sa.Numeric(18, 6), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False,
                  server_default='waiting', index=True),
        sa.Column('passed_count', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('called_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('seated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notified_ahead_at', sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # 用户端刷得最勤的那个问题:这条队还有几个人、我排第几
    op.create_index('ix_queue_tickets_queue', 'queue_tickets',
                    ['table_type_id', 'day', 'status', 'sort_key'])
    # 取号前的查重:一人一店一号
    op.create_index('ix_queue_tickets_mine', 'queue_tickets',
                    ['merchant_id', 'customer_id', 'day'])
    op.create_table(
        'queue_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ticket_id', sa.Integer(),
                  sa.ForeignKey('queue_tickets.id'), nullable=False,
                  index=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False, index=True),
        sa.Column('action', sa.String(length=24), nullable=False),
        sa.Column('actor_role', sa.String(length=12), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('detail', sa.String(length=200), nullable=False,
                  server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table('queue_events')
    op.drop_index('ix_queue_tickets_mine', table_name='queue_tickets')
    op.drop_index('ix_queue_tickets_queue', table_name='queue_tickets')
    op.drop_table('queue_tickets')
    op.drop_table('queue_settings')
    op.drop_table('queue_table_types')
