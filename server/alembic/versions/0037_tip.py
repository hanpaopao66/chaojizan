"""用户小费:orders.tip_cents——100% 归骑手,平台分文不取、不计佣金基数。
资金口径:实付 total 含小费;骑手结算行 = 配送费 + 小费;
审计配送侧恒等式与餐费冲账口径同步(小费随配送费同侧)。
"""
import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("tip_cents", sa.Integer,
                                      nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("orders", "tip_cents")
