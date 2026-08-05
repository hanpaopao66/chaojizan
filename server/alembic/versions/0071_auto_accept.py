"""商家自动接单开关(工作台改造第二批)

经营诊断的文案早就写着「在店铺里把自动接单打开」,但这个开关
一直不存在 —— 本迁移把空头指引落成真功能。

Revision ID: 0071
Revises: 0070
"""
import sqlalchemy as sa
from alembic import op

revision = '0071'
down_revision = '0070'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "auto_accept", sa.Boolean(), nullable=False,
        server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("merchants", "auto_accept")
