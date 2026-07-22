"""骑手接单半径偏好(users.grab_radius_km,空=不限)
+ 在线时长记录(rider_sessions:上线/下线区间,只统计不考核)。
"""
import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("grab_radius_km", sa.Integer,
                                     nullable=True))
    op.create_table(
        "rider_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rider_id", sa.Integer, sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("online_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offline_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("rider_sessions")
    op.drop_column("users", "grab_radius_km")
