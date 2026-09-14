"""标签和勋章:social_profiles 加三列,reviews(customer_id) 加索引

- tags:用户自己写的标签(最多 5 个、每个 1–8 个字,校验在 services/badges.normalize_tags);
- tags_hidden:整组标签对别人隐藏;
- badges_hidden:对别人隐藏的勋章。**勋章本身不存**,每次按公开条件现算(services/badges.py),
  所以这里没有「谁得了哪枚」的表,也不用回填。

三列都带服务端缺省值:加列只改表结构、不重写整张表;老代码和测试夹具里不写这三列的 INSERT 照常能插。

reviews.customer_id 原来没有索引(只有 merchant_id 有),「带图评价达人」要按人数评价,
不加的话每次都是整表扫。和 0106 一样用 CONCURRENTLY:建索引期间不挡写评价。
失败会留下 INVALID 索引,所以带 IF NOT EXISTS,重跑前先 DROP INDEX CONCURRENTLY(见 0106 的说明)。

Revision ID: 0134
Revises: 0133
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0134'
down_revision = '0133'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('social_profiles',
                  sa.Column('tags', JSONB, nullable=False, server_default='[]'))
    op.add_column('social_profiles',
                  sa.Column('tags_hidden', sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column('social_profiles',
                  sa.Column('badges_hidden', JSONB, nullable=False, server_default='[]'))
    # autocommit_block:CREATE INDEX CONCURRENTLY 不能在事务块里跑(见 0106)
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_reviews_customer_id "
                   "ON reviews (customer_id)")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_reviews_customer_id")
    op.drop_column('social_profiles', 'badges_hidden')
    op.drop_column('social_profiles', 'tags_hidden')
    op.drop_column('social_profiles', 'tags')
