"""食安停业闸门(让自动停业真的停得住)

此前 30 天 3 起食安投诉成立会自动停业,但只置 is_open=False、
status 仍是 approved —— PATCH 的营业闸门只拦非 approved,
商家把开关拨回去就继续接单。推送里写的"待人工复核"没有代码支撑。

Revision ID: 0080
Revises: 0079
"""
import sqlalchemy as sa
from alembic import op

revision = '0080'
down_revision = '0079'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "food_safety_hold", sa.Boolean(), nullable=False,
        server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("merchants", "food_safety_hold")
