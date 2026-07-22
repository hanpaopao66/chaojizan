"""工程透明:health_probes 系统状态探针(/status 可用率数据源,留 90 天)。"""
import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "health_probes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("db_ok", sa.Boolean, nullable=False,
                  server_default=sa.true()),
        sa.Column("redis_ok", sa.Boolean, nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_health_probes_created_at", "health_probes",
                    ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_health_probes_created_at", table_name="health_probes")
    op.drop_table("health_probes")
