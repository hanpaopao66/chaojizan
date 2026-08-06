"""POS/收银系统开放接口凭证(只读拉单)

稍大的餐厅都用收银系统(客如云/银豹等),没有拉单接口
他们就要两套系统抄单 —— 这是连锁商家入驻前必问的一项。

Revision ID: 0074
Revises: 0073
"""
import sqlalchemy as sa
from alembic import op

revision = '0074'
down_revision = '0073'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchant_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("merchant_id", sa.Integer(),
                  sa.ForeignKey("merchants.id"), nullable=False, index=True),
        sa.Column("name", sa.String(30), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(12), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("merchant_api_keys")
