"""埋点表补索引(商家流量漏斗要按店按时间切)

app_events 原先只索引了 event 与 user_id。漏斗查询要按
「某店 + 近 N 天 + 某几个事件」切,没有 created_at 和 merchant_id
的索引就是全表扫。

Revision ID: 0078
Revises: 0077
"""
from alembic import op

revision = '0078'
down_revision = '0077'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_app_events_created_at", "app_events", ["created_at"])
    # props->>'merchant_id' 的表达式索引:漏斗按店切的唯一入口
    op.execute(
        "CREATE INDEX ix_app_events_merchant "
        "ON app_events ((props->>'merchant_id'))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_app_events_merchant")
    op.drop_index("ix_app_events_created_at", table_name="app_events")
