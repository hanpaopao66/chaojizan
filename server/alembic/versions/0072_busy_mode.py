"""商家忙碌模式(高峰压单)

高峰期商家原先只有两个选项:硬扛(超时挨差评)或直接闭店(丢单)。
忙碌模式是中间态:不闭店,ETA 和出餐超时判定放宽 N 分钟,
用户端亮「出餐较慢」标 —— 先说清楚再让用户下单。

Revision ID: 0072
Revises: 0071
"""
import sqlalchemy as sa
from alembic import op

revision = '0072'
down_revision = '0071'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "busy_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("merchants", sa.Column(
        "busy_extra_minutes", sa.Integer(), nullable=False,
        server_default=sa.text("10")))


def downgrade() -> None:
    op.drop_column("merchants", "busy_extra_minutes")
    op.drop_column("merchants", "busy_until")
