"""手机号按角色分账号:users.phone 全局唯一 → (phone, role) 唯一。

同一手机号可分别注册 用户/商家/骑手 账号,三端互不影响。
"""
import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_users_phone", table_name="users")
    op.create_index("ix_users_phone", "users", ["phone"])
    op.create_unique_constraint("uq_users_phone_role", "users", ["phone", "role"])


def downgrade() -> None:
    # 若存量已出现同号多角色,回退前需人工清理冲突行
    op.drop_constraint("uq_users_phone_role", "users", type_="unique")
    op.drop_index("ix_users_phone", table_name="users")
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)
