"""电话脱敏:orders.privacy_phone(AXB 中间号,未接入时恒空串)。

脱敏展示本身不依赖此列——商家/骑手侧接口打码是序列化层逻辑;
此列只承载绑定成功后的 X 号。
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("privacy_phone", sa.String(20), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("orders", "privacy_phone")
