"""超级赞号改名规则:一年改一次,换下来的旧号冷冻 180 天

- social_profiles.username_set_at:上一次设置 / 修改超级赞号的时间,下一次修改要满 365 天
  (按北京时间的日期算,见 services/social.username_next_change)。
  **存量已经设了号的人不回填**(留空 = 下一次修改不用等,改完才开始算一年):他们是在「随时能改」
  的规则下设的号,社交身份 09-13 才上线,库里的号几乎都是这一两天试着设的;按「今天设置」算,
  等于事后替他们锁了一年。放宽的代价只是每人最多多改一次,而且改掉的旧号照样冷冻。
- username_holds:被换掉、清空、随注销释放的超级赞号,冷冻期内谁都不能注册
  (群 / 频道的公开链接也不行,它们和超级赞号共用 usernames 这个命名空间)。

Revision ID: 0133
Revises: 0132
"""
import sqlalchemy as sa
from alembic import op

revision = '0133'
down_revision = '0132'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('social_profiles',
                  sa.Column('username_set_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'username_holds',
        sa.Column('username_lc', sa.String(length=32), primary_key=True),
        sa.Column('released_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('frozen_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('username_holds')
    op.drop_column('social_profiles', 'username_set_at')
