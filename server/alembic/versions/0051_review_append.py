"""评价体验补全:真匿名开关 + 追评(一单一评一追评,平铺存储)。"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column(
        "is_anonymous", sa.Boolean, nullable=False,
        server_default=sa.false()))
    op.add_column("reviews", sa.Column(
        "append_content", sa.String(500), nullable=False, server_default=""))
    op.add_column("reviews", sa.Column(
        "append_images", JSONB, nullable=False, server_default="[]"))
    op.add_column("reviews", sa.Column(
        "append_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reviews", sa.Column(
        "append_reply", sa.String(300), nullable=False, server_default=""))


def downgrade() -> None:
    for col in ("append_reply", "append_at", "append_images",
                "append_content", "is_anonymous"):
        op.drop_column("reviews", col)
