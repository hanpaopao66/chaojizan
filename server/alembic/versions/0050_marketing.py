"""营销触达三合一:users.birthday(MM-DD,年不收集——最小化原则)
+ users.marketing_push(营销推送开关,默认开,一键关闭)。
生日券/复购提醒/收藏店上新共用每周 2 条频控(Redis)。
"""
import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "birthday", sa.String(5), nullable=False, server_default=""))
    op.add_column("users", sa.Column(
        "marketing_push", sa.Boolean, nullable=False,
        server_default=sa.true()))
    # 收藏店上新提醒需要知道菜是什么时候上的
    op.add_column("dishes", sa.Column(
        "created_at", sa.DateTime(timezone=True),
        server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
    op.drop_column("dishes", "created_at")
    op.drop_column("users", "marketing_push")
    op.drop_column("users", "birthday")
