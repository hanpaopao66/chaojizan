"""骑手一键紧急求助:rider_emergencies(红色加急,处置留痕)
+ rider_profiles.emergency_contacts_enc(紧急联系人,加密存储)。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rider_profiles", sa.Column(
        "emergency_contacts_enc", sa.String(800), nullable=False,
        server_default=""))
    op.create_table(
        "rider_emergencies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rider_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lng", sa.Float, nullable=True),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        # open/following/closed/cancelled(误触自助撤销)
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="open", index=True),
        sa.Column("actions", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rider_emergencies")
    op.drop_column("rider_profiles", "emergency_contacts_enc")
