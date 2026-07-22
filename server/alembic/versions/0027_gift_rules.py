"""满赠活动:merchants.gift_rules JSONB。

满减动钱、满赠动货:赠品以 0 元行进订单 items 快照,
food/total/佣金口径零影响,账本天然正确。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "merchants",
        sa.Column("gift_rules", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("merchants", "gift_rules")
