"""订单/事件热点路径的复合索引

orders 表原有 8 个索引**全是单列**:customer_id / merchant_id / order_no /
rider_id / status / parent_order_no / order_kind / drop_key。
而三端最常跑的查询无一例外是「谁的单 + 按时间倒序 + 取前 N 条」:

    骑手工作台   WHERE rider_id = ?    ORDER BY created_at DESC LIMIT 20
    商家订单页   WHERE merchant_id = ? ORDER BY created_at DESC LIMIT 20
    用户订单列表 WHERE customer_id = ? ORDER BY created_at DESC LIMIT 20

单列索引只能帮到 WHERE 那一半:库先把这个人的全部历史单捞出来,
再整个排一遍序,最后扔掉除了 20 条以外的全部。老用户的单越多越慢 ——
**越忠实的用户体验越差**,而且慢得很平滑,没有哪一天会"突然出事",
所以不盯着看根本不会发现。复合索引把排序也吃进去,变成沿着索引取前 20 条就走。

order_events(to_status, created_at) 服务的是运营侧的「今天有多少单到了某状态」
这类统计,同理。

## 为什么用 CONCURRENTLY

生产库已有 3.5 万单存量。普通 CREATE INDEX 会拿 SHARE 锁,**期间全表写入阻塞**——
建索引这几秒到几十秒里,所有人都下不了单、骑手也改不了状态。
CONCURRENTLY 不阻塞写,代价是要扫两遍表、且不能在事务块里跑。

## 为什么必须 autocommit_block

alembic/env.py 里是 `with context.begin_transaction(): context.run_migrations()`,
而且没有设 transaction_per_migration —— 整个 upgrade 跑在**一个事务**里。
CREATE INDEX CONCURRENTLY 在事务块里是非法的(Postgres 直接报错)。
`op.get_context().autocommit_block()` 会把外层事务临时提交、切到 autocommit,
块结束再开回来,这是 alembic 官方给这个场景准备的出口。

## CONCURRENTLY 失败会留下 INVALID 索引

它不是原子的:中途失败(比如超时、被 kill)会留下一个建了一半、
标记为 INVALID 的索引,而且**不会自己清理**,还会占空间。
所以这里一律带 IF NOT EXISTS,重跑安全;真遇到 INVALID 的,
先 DROP INDEX CONCURRENTLY 再重跑本迁移。查:
    SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;

Revision ID: 0106
Revises: 0105
"""
from alembic import op

revision = '0106'
down_revision = '0105'
branch_labels = None
depends_on = None

# (索引名, 表, 列定义)。DESC 是照着查询里的 ORDER BY created_at DESC 写的 ——
# Postgres 也能反向扫升序索引,但方向一致时不需要额外的排序节点
_INDEXES = [
    ("ix_orders_rider_created", "orders", "rider_id, created_at DESC"),
    ("ix_orders_merchant_created", "orders", "merchant_id, created_at DESC"),
    ("ix_orders_customer_created", "orders", "customer_id, created_at DESC"),
    ("ix_order_events_status_created", "order_events", "to_status, created_at"),
]


def upgrade() -> None:
    # autocommit_block:见文件头。没有它这里会直接报
    # "CREATE INDEX CONCURRENTLY cannot run inside a transaction block"
    with op.get_context().autocommit_block():
        for name, table, cols in _INDEXES:
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {table} ({cols})")


def downgrade() -> None:
    # 删也用 CONCURRENTLY:DROP INDEX 同样要拿排他锁挡住全表访问
    with op.get_context().autocommit_block():
        for name, _table, _cols in reversed(_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
