"""住宿售后:到店无房赔付(全额退+30%首晚违约金) + 协商退(strict 档)。"""
import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stay_after_sales",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stay_order_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Enum(
            "no_room", "nego_refund", name="stay_after_sale_kind",
            native_enum=False, length=24), nullable=False),
        sa.Column("status", sa.Enum(
            "pending", "accepted", "rejected", "auto_accepted",
            name="stay_after_sale_status", native_enum=False, length=24),
            nullable=False),
        sa.Column("note", sa.String(length=300), nullable=False),
        sa.Column("merchant_note", sa.String(length=300), nullable=False),
        sa.Column("refund_cents", sa.Integer(), nullable=False),
        sa.Column("penalty_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["stay_order_id"], ["stay_orders.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("stay_order_id", "customer_id", "merchant_id", "status"):
        op.create_index(op.f(f"ix_stay_after_sales_{col}"),
                        "stay_after_sales", [col], unique=False)


def downgrade() -> None:
    op.drop_table("stay_after_sales")
