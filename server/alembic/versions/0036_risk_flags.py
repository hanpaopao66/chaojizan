"""防刷单风控:orders.risk_flags(命中规则+人工复核状态,JSONB)
+ users.device_id(登录上报的轻量设备指纹)。
只标记不拦截:钱照结算,确认刷单的单从月售/销量排行口径剔除。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("risk_flags", JSONB, nullable=True))
    op.add_column("users", sa.Column("device_id", sa.String(64),
                                     nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("users", "device_id")
    op.drop_column("orders", "risk_flags")
