"""明厨亮灶接入与探测状态(#155-#157)

《网络餐饮服务经营者落实食品安全主体责任监督管理规定》(总局令第 123 号,
2026-06-01 施行)第十三条要求平台在商家列表页展示「有明厨亮灶」「无明厨亮灶」
标识 —— 所以状态要能索引,不能塞 JSONB。

Revision ID: 0067
Revises: 0066
"""
import sqlalchemy as sa
from alembic import op

revision = '0067'
down_revision = '0066'
branch_labels = None
depends_on = None

_COLS = [
    ("kitchen_cam_status", sa.String(10), "'none'"),
    ("kitchen_cam_url", sa.String(300), "''"),
    ("kitchen_cam_vendor", sa.String(20), "''"),
    ("kitchen_cam_shot_url", sa.String(300), "''"),
    ("kitchen_cam_reason", sa.String(20), "''"),
    ("kitchen_cam_note", sa.String(200), "''"),
]


def upgrade() -> None:
    for name, type_, default in _COLS:
        op.add_column("merchants", sa.Column(
            name, type_, nullable=False, server_default=sa.text(default)))
    op.add_column("merchants", sa.Column(
        "kitchen_cam_notified", sa.Boolean(), nullable=False,
        server_default=sa.text("false")))
    for name in ("kitchen_cam_fail_streak", "kitchen_cam_ok_streak"):
        op.add_column("merchants", sa.Column(
            name, sa.Integer(), nullable=False, server_default=sa.text("0")))
    for name in ("kitchen_cam_verified_at", "kitchen_cam_checked_at"):
        op.add_column("merchants", sa.Column(
            name, sa.DateTime(timezone=True), nullable=True))
    op.add_column("merchants", sa.Column(
        "kitchen_cam_sequence", sa.Integer(), nullable=True))
    # 列表页按状态展示标识,要走索引
    op.create_index("ix_merchants_kitchen_cam_status", "merchants",
                    ["kitchen_cam_status"])


def downgrade() -> None:
    op.drop_index("ix_merchants_kitchen_cam_status", table_name="merchants")
    for name in ("kitchen_cam_sequence", "kitchen_cam_checked_at",
                 "kitchen_cam_verified_at", "kitchen_cam_ok_streak",
                 "kitchen_cam_fail_streak", "kitchen_cam_notified",
                 *(c[0] for c in _COLS)):
        op.drop_column("merchants", name)
