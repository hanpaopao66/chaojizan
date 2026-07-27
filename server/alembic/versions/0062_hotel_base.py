"""酒店住宿垂类地基:merchants.biz_type + 酒店资料/房型/房价房态日历/住宿订单。

平行竖井(照团购券先例),经营主体复用 Merchant。方案见 docs/HOTEL_PLAN.md。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column(
        "biz_type", sa.String(10), nullable=False, server_default="food"))
    op.create_index("ix_merchants_biz_type", "merchants", ["biz_type"])

    op.create_table(
        "hotel_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=10), nullable=False),
        sa.Column("front_desk_phone", sa.String(length=20), nullable=False),
        sa.Column("checkin_from", sa.String(length=5), nullable=False),
        sa.Column("checkout_until", sa.String(length=5), nullable=False),
        sa.Column("facilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("special_license_no", sa.String(length=50), nullable=False),
        sa.Column("special_license_image_url", sa.String(length=300), nullable=False),
        sa.Column("hygiene_image_url", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hotel_profiles_merchant_id"), "hotel_profiles",
                    ["merchant_id"], unique=True)

    op.create_table(
        "room_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("bed_type", sa.String(length=30), nullable=False),
        sa.Column("area_m2", sa.Integer(), nullable=False),
        sa.Column("max_guests", sa.Integer(), nullable=False),
        sa.Column("image_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("facilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cancel_policy", sa.Enum(
            "limited_free", "first_night", "strict", name="cancel_policy",
            native_enum=False, length=24), nullable=False),
        sa.Column("free_cancel_until", sa.String(length=5), nullable=False),
        sa.Column("is_on_sale", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_room_types_merchant_id"), "room_types",
                    ["merchant_id"], unique=False)

    op.create_table(
        "room_calendar",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room_type_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("total_qty", sa.Integer(), nullable=False),
        sa.Column("sold_qty", sa.Integer(), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["room_type_id"], ["room_types.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_type_id", "date", name="uq_room_calendar_day"),
    )
    op.create_index(op.f("ix_room_calendar_room_type_id"), "room_calendar",
                    ["room_type_id"], unique=False)
    op.create_index(op.f("ix_room_calendar_date"), "room_calendar",
                    ["date"], unique=False)

    op.create_table(
        "stay_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_no", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("room_type_id", sa.Integer(), nullable=False),
        sa.Column("checkin_date", sa.Date(), nullable=False),
        sa.Column("checkout_date", sa.Date(), nullable=False),
        sa.Column("nights", sa.Integer(), nullable=False),
        sa.Column("rooms_qty", sa.Integer(), nullable=False),
        sa.Column("guest_name", sa.String(length=50), nullable=False),
        sa.Column("guest_phone", sa.String(length=20), nullable=False),
        sa.Column("arrival_note", sa.String(length=100), nullable=False),
        sa.Column("room_type_name", sa.String(length=60), nullable=False),
        sa.Column("nightly_prices", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("fee_cents", sa.Integer(), nullable=False),
        sa.Column("net_cents", sa.Integer(), nullable=False),
        sa.Column("cancel_policy", sa.Enum(
            "limited_free", "first_night", "strict", name="cancel_policy",
            native_enum=False, length=24), nullable=False),
        sa.Column("free_cancel_until", sa.String(length=5), nullable=False),
        sa.Column("status", sa.Enum(
            "created", "closed", "paid", "confirmed", "checked_in",
            "completed", "cancelled", "rejected", "noshow",
            name="stay_order_status", native_enum=False, length=24),
            nullable=False),
        sa.Column("reject_reason", sa.String(length=100), nullable=False),
        sa.Column("refund_cents", sa.Integer(), nullable=False),
        sa.Column("refund_note", sa.String(length=200), nullable=False),
        sa.Column("wx_transaction_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["room_type_id"], ["room_types.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stay_orders_order_no"), "stay_orders",
                    ["order_no"], unique=True)
    for col in ("customer_id", "merchant_id", "room_type_id",
                "checkin_date", "checkout_date", "status"):
        op.create_index(op.f(f"ix_stay_orders_{col}"), "stay_orders",
                        [col], unique=False)


def downgrade() -> None:
    op.drop_table("stay_orders")
    op.drop_table("room_calendar")
    op.drop_table("room_types")
    op.drop_table("hotel_profiles")
    op.drop_index("ix_merchants_biz_type", table_name="merchants")
    op.drop_column("merchants", "biz_type")
