"""多城市运营隔离:merchants.city / users.city(骑手)。

入驻时从坐标逆地理解析(天地图服务端 key,失败留空人工填);
骑手上线时按最近定位解析一次。空 city = 未标注,不参与隔离(存量宽限)。
"""
import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "city", sa.String(20), nullable=False, server_default=""))
    op.create_index("ix_merchants_city", "merchants", ["city"])
    op.add_column("users", sa.Column(
        "city", sa.String(20), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("users", "city")
    op.drop_index("ix_merchants_city", table_name="merchants")
    op.drop_column("merchants", "city")
