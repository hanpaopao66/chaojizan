"""商家自配送:merchants.self_delivery(开关)+ orders.self_delivery(下单快照)。

自配送单不进抢单池、无骑手;配送费归商家(并入商家入账行 food 口径,
net == food - commission 恒等式不破);平台照常只抽餐费佣金。
"""
import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "self_delivery", sa.Boolean, nullable=False,
        server_default=sa.false()))
    op.add_column("orders", sa.Column(
        "self_delivery", sa.Boolean, nullable=False,
        server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("orders", "self_delivery")
    op.drop_column("merchants", "self_delivery")
