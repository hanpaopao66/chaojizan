"""内容审核:moderation_words 敏感词库(文本同步拦截,管理后台可维护)
+ content_reviews 图片审核队列(先发后审,三方桩未配置时人工)。
种子只放少量广告导流/辱骂示例词——完整词库由运营在管理后台自行维护,
不在开源仓库里放敏感词表。
"""
import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

_SEED_WORDS = [
    ("加微信", "ad"), ("加v信", "ad"), ("加qq", "ad"), ("办证", "ad"),
    ("代开发票", "ad"), ("刷单兼职", "ad"), ("博彩", "ad"), ("彩票代投", "ad"),
    ("傻逼", "abuse"), ("狗东西", "abuse"), ("去死", "abuse"),
]


def upgrade() -> None:
    words = op.create_table(
        "moderation_words",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("word", sa.String(50), nullable=False, unique=True),
        sa.Column("category", sa.String(20), nullable=False,
                  server_default="other"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.bulk_insert(words, [{"word": w, "category": c} for w, c in _SEED_WORDS])
    op.create_table(
        "content_reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),   # review/dish/avatar
        sa.Column("ref_id", sa.Integer, nullable=False),
        sa.Column("url", sa.String(300), nullable=False),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="pending", index=True),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("content_reviews")
    op.drop_table("moderation_words")
