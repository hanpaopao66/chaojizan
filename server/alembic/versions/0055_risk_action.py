"""反作弊闭环:users.risk_level/risk_note(分级处置)+ reviews.flagged/flag_reason(刷评标记)。"""
import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "risk_level", sa.String(10), nullable=False, server_default=""))
    op.add_column("users", sa.Column(
        "risk_note", sa.String(200), nullable=False, server_default=""))
    op.add_column("reviews", sa.Column(
        "flagged", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("reviews", sa.Column(
        "flag_reason", sa.String(100), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("reviews", "flag_reason")
    op.drop_column("reviews", "flagged")
    op.drop_column("users", "risk_note")
    op.drop_column("users", "risk_level")
