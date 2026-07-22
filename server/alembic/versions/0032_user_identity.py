"""用户实名认证(为酒类等受限品类做年龄核验):user_identities。
身份证号 Fernet 加密落库(id_no_encrypted),明文不入库不出接口;
birth_date 从证号解析,年龄判定用。按需触发,不是注册门槛。
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id"), unique=True, index=True,
                  nullable=False),
        sa.Column("real_name", sa.String(50), nullable=False),
        sa.Column("id_no_encrypted", sa.String(500), nullable=False),
        sa.Column("birth_date", sa.Date, nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_identities")
