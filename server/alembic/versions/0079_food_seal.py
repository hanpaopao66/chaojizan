"""食安封签(商家自述)

一次性封签拆封即留痕,是外卖食安里成本最低、见效最直接的一件事。
平台不上门核查,所以只做"商家声明"不做"平台认证",
用户端文案也照这个口径写。

Revision ID: 0079
Revises: 0078
"""
import sqlalchemy as sa
from alembic import op

revision = '0079'
down_revision = '0078'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "food_seal", sa.Boolean(), nullable=False,
        server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("merchants", "food_seal")
