"""开屏运营位:splash_configs(三端可配置图文开屏,端定向+时间窗+倒计时)。"""
import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "splash_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("audience", sa.String(12), nullable=False,
                  server_default="all"),
        sa.Column("title", sa.String(50), nullable=False, server_default=""),
        sa.Column("subtitle", sa.String(100), nullable=False,
                  server_default=""),
        sa.Column("image_url", sa.String(300), nullable=False),
        sa.Column("countdown_seconds", sa.Integer, nullable=False,
                  server_default="3"),
        sa.Column("is_active", sa.Boolean, nullable=False,
                  server_default=sa.true()),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_splash_configs_audience", "splash_configs",
                    ["audience"])


def downgrade() -> None:
    op.drop_index("ix_splash_configs_audience", table_name="splash_configs")
    op.drop_table("splash_configs")
