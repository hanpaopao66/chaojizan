"""commission_5_percent

口径统一:商家佣金 6% → 5%,团购核销服务费 3% → 2%(团购费率在 config,无表结构)。
已有商家统一降到 5%(只降不升:费率低于 5% 的商家保持不动);
历史订单/历史账本锚点不动——每天的 payload 冻结了当天的 commission_rate_max,
witness 校验按当天口径复算,链上历史不受影响。

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-18 22:00:00.000000
"""
from alembic import op


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 新商家的 5% 默认值在 models.py(Python 侧 default),这里只处理存量数据
    op.execute("UPDATE merchants SET commission_rate = 0.050 "
               "WHERE commission_rate > 0.050")


def downgrade() -> None:
    # 数据不回滚:降费率是对商家的承诺,回滚版本也不应该偷偷涨回去
    pass
