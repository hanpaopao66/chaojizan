"""订单送达/完成时刻落库(法定记录,#168)

《网络餐饮服务经营者落实食品安全主体责任监督管理规定》(总局令第 123 号,
2026-06-01 施行)第十五条:

> 平台提供者……应当如实记录并保存网络餐饮服务的订单信息……
> 保存时间自交易完成之日起不少于三年。

要记录的项里含**送达时间**。此前 orders 表有 accepted_at 却没有
delivered_at —— 送达时间只能从 order_events 的状态流转事件推,而:

1. 事件表是流水,查一单的送达时间要 join + 过滤;
2. **直接落库的订单没有对应事件**(清扫任务自动完成、历史数据),
   实测 35042 单已送达/完成,delivered 事件只有 2055 条。

法定要记录的字段就该有自己的列。本迁移加列并从 order_events 回填。

Revision ID: 0069
Revises: 0068
"""
import sqlalchemy as sa
from alembic import op

revision = '0069'
down_revision = '0068'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column(
        "delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column(
        "completed_at", sa.DateTime(timezone=True), nullable=True))

    conn = op.get_bind()
    # 1) 有事件的:按事件时间回填(最准)
    for status, col in (("delivered", "delivered_at"),
                        ("completed", "completed_at")):
        conn.execute(sa.text(f"""
            UPDATE orders o SET {col} = e.at
            FROM (SELECT order_id, min(created_at) AS at FROM order_events
                  WHERE to_status = :s GROUP BY order_id) e
            WHERE o.id = e.order_id AND o.{col} IS NULL
        """), {"s": status})

    # 2) 没事件但状态已到位的:退而求其次用 updated_at。
    #    **这是估算,但比 NULL 强** —— 监管调取时"这单什么时候送到的"
    #    答不上来比答一个近似值更糟。真实产生的新单走 /transition,是精确的
    conn.execute(sa.text("""
        UPDATE orders SET delivered_at = updated_at
        WHERE delivered_at IS NULL AND status IN ('delivered', 'completed')
    """))
    conn.execute(sa.text("""
        UPDATE orders SET completed_at = updated_at
        WHERE completed_at IS NULL AND status = 'completed'
    """))


def downgrade() -> None:
    op.drop_column("orders", "completed_at")
    op.drop_column("orders", "delivered_at")
