"""连锁品牌层(总部视角的地基)

单店商家 brand_id 为空,所有既有逻辑走原路径零感知。
品牌层只在"一个人要管多家店"时才出现。

刻意不做品牌级钱包:资金仍按门店结算,与「每一笔分账可查可申诉」
的承诺保持一致 —— 钱一旦在总部合并,门店就说不清自己那份对不对。

Revision ID: 0081
Revises: 0080
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0081'
down_revision = '0080'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("logo_url", sa.String(300), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "brand_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"),
                  nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("role", sa.String(12), nullable=False,
                  server_default=sa.text("'manager'")),
        sa.Column("shop_ids", JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("brand_id", "user_id", name="uq_brand_member"),
    )
    op.add_column("merchants", sa.Column(
        "brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=True))
    op.create_index("ix_merchants_brand_id", "merchants", ["brand_id"])
    # 「一号一店」原本是**库级 UNIQUE**,连锁下必须放开。
    # 约束改由应用层守:POST /merchants 仍然拒绝第二家(单店商家行为不变),
    # 开分店只能走 /brands/me/shops —— 那条路要求品牌所有者身份 + 独立证照
    op.drop_constraint("merchants_owner_id_key", "merchants", type_="unique")
    op.create_index("ix_merchants_owner_id", "merchants", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_merchants_owner_id", table_name="merchants")
    op.create_unique_constraint(
        "merchants_owner_id_key", "merchants", ["owner_id"])
    op.drop_index("ix_merchants_brand_id", table_name="merchants")
    op.drop_column("merchants", "brand_id")
    op.drop_table("brand_members")
    op.drop_table("brands")
