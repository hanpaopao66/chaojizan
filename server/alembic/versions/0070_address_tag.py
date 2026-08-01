"""收货地址标签(家/公司/学校,#169)

地址簿里三个"XX路XX号"排在一起时,用户得逐字读才知道哪个是家 ——
一个标签省掉这次阅读。对齐主流外卖 App 的交互。

Revision ID: 0070
Revises: 0069
"""
import sqlalchemy as sa
from alembic import op

revision = '0070'
down_revision = '0069'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("addresses", sa.Column(
        "tag", sa.String(8), nullable=False, server_default=sa.text("''")))


def downgrade() -> None:
    op.drop_column("addresses", "tag")
