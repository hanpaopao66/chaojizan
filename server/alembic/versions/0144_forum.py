"""论坛:帖子、回复串、转发、引用、点赞、书签、浏览、话题、提及、投票、置顶、屏蔽词、
举报、下架与申诉(DEV-PROMPTS-41 §7.2,#380)

social_notifications 加 forum_post_id(可空,帖子删了级联删通知);kind 加 repost / quote
(kind 是 String(8),没有 CHECK 约束,加种类不用改列)。

**合并时要改 down_revision**:音乐的 0143 和这一批是两个 agent 并行做的,这个 worktree 里
还没有 0143,所以 down_revision 先写 '0142';主会话合并音乐 + 论坛时改成 '0143'。

不回填任何数据。

Revision ID: 0144
Revises: 0142
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0144'
# 合并时改成 '0143'(音乐那一批的迁移),见文件头
down_revision = '0142'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'forum_posts',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('pid', sa.String(length=12), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), server_default='', nullable=False),
        sa.Column('entities', postgresql.JSONB(astext_type=sa.Text()), server_default='{}',
                  nullable=False),
        sa.Column('media', postgresql.JSONB(astext_type=sa.Text()), server_default='[]',
                  nullable=False),
        sa.Column('card', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('reply_to_id', sa.BigInteger(), nullable=True),
        sa.Column('reply_to_user_id', sa.Integer(), nullable=True),
        sa.Column('root_id', sa.BigInteger(), nullable=True),
        sa.Column('quote_of_id', sa.BigInteger(), nullable=True),
        sa.Column('reply_policy', sa.String(length=10), server_default='all', nullable=False),
        sa.Column('status', sa.String(length=8), server_default='visible', nullable=False),
        sa.Column('removed_code', sa.String(length=8), server_default='', nullable=False),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('edit_count', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('replies', sa.Integer(), server_default='0', nullable=False),
        sa.Column('reposts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('quotes', sa.Integer(), server_default='0', nullable=False),
        sa.Column('likes', sa.Integer(), server_default='0', nullable=False),
        sa.Column('bookmarks', sa.Integer(), server_default='0', nullable=False),
        sa.Column('views', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pid'),
    )
    op.create_index(op.f('ix_forum_posts_author_id'), 'forum_posts', ['author_id'])
    op.create_index(op.f('ix_forum_posts_reply_to_id'), 'forum_posts', ['reply_to_id'])
    op.create_index(op.f('ix_forum_posts_root_id'), 'forum_posts', ['root_id'])
    op.create_index(op.f('ix_forum_posts_quote_of_id'), 'forum_posts', ['quote_of_id'])
    op.create_index('ix_forum_posts_created', 'forum_posts', ['status', 'created_at'])
    op.create_index('ix_forum_posts_author_created', 'forum_posts', ['author_id', 'created_at'])
    op.create_index('ix_forum_posts_root', 'forum_posts', ['root_id', 'created_at'])

    op.create_table(
        'forum_post_edits',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('text', sa.Text(), server_default='', nullable=False),
        sa.Column('entities', postgresql.JSONB(astext_type=sa.Text()), server_default='{}',
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_forum_post_edits_post_id'), 'forum_post_edits', ['post_id'])

    op.create_table(
        'forum_reposts',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_forum_reposts_user_id'), 'forum_reposts', ['user_id'])
    op.create_index('uq_forum_reposts', 'forum_reposts', ['user_id', 'post_id'], unique=True)
    op.create_index('ix_forum_reposts_user_created', 'forum_reposts', ['user_id', 'created_at'])
    op.create_index('ix_forum_reposts_post_created', 'forum_reposts', ['post_id', 'created_at'])
    op.create_index('ix_forum_reposts_created', 'forum_reposts', ['created_at'])

    op.create_table(
        'forum_likes',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'post_id'),
    )
    op.create_index('ix_forum_likes_post_created', 'forum_likes', ['post_id', 'created_at'])
    op.create_index('ix_forum_likes_user_created', 'forum_likes', ['user_id', 'created_at'])
    op.create_index('ix_forum_likes_created', 'forum_likes', ['created_at'])

    op.create_table(
        'forum_bookmarks',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'post_id'),
    )
    op.create_index('ix_forum_bookmarks_user_created', 'forum_bookmarks',
                    ['user_id', 'created_at'])

    op.create_table(
        'forum_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tag', sa.String(length=30), nullable=False),
        sa.Column('display', sa.String(length=30), server_default='', nullable=False),
        sa.Column('posts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('hidden', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('hidden_code', sa.String(length=8), server_default='', nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tag'),
    )
    op.create_index('ix_forum_tags_last_used', 'forum_tags', ['last_used_at'])

    op.create_table(
        'forum_post_tags',
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['forum_tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('post_id', 'tag_id'),
    )
    op.create_index('ix_forum_post_tags_tag_created', 'forum_post_tags', ['tag_id', 'created_at'])
    op.create_index('ix_forum_post_tags_author', 'forum_post_tags', ['author_id', 'created_at'])

    op.create_table(
        'forum_mentions',
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('post_id', 'user_id'),
    )
    op.create_index(op.f('ix_forum_mentions_user_id'), 'forum_mentions', ['user_id'])

    op.create_table(
        'forum_polls',
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), server_default='[]',
                  nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total', sa.Integer(), server_default='0', nullable=False),
        sa.Column('closed_notified', sa.Boolean(), server_default=sa.text('false'),
                  nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('post_id'),
    )
    op.create_index('ix_forum_polls_ends', 'forum_polls', ['ends_at'])

    op.create_table(
        'forum_poll_votes',
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('option', sa.SmallInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('post_id', 'user_id'),
    )
    op.create_index(op.f('ix_forum_poll_votes_user_id'), 'forum_poll_votes', ['user_id'])

    op.create_table(
        'forum_pins',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )

    op.create_table(
        'forum_mute_words',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('word', sa.String(length=30), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'word'),
    )

    op.create_table(
        'forum_view_days',
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('viewer_key', sa.String(length=48), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('post_id', 'day', 'viewer_key'),
    )
    op.create_index('ix_forum_view_days_created', 'forum_view_days', ['created_at'])

    op.create_table(
        'forum_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reporter_id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('reason_code', sa.String(length=8), nullable=False),
        sa.Column('note', sa.String(length=500), server_default='', nullable=False),
        sa.Column('status', sa.String(length=10), server_default='open', nullable=False),
        sa.Column('handled_by', sa.Integer(), nullable=True),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution', sa.String(length=300), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_forum_reports_reporter_id'), 'forum_reports', ['reporter_id'])
    op.create_index(op.f('ix_forum_reports_post_id'), 'forum_reports', ['post_id'])
    op.create_index('ix_forum_reports_status', 'forum_reports', ['status', 'id'])

    op.create_table(
        'forum_decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=True),
        sa.Column('tag_id', sa.Integer(), nullable=True),
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('reason_code', sa.String(length=8), server_default='', nullable=False),
        sa.Column('note', sa.String(length=500), server_default='', nullable=False),
        sa.Column('note_internal', sa.String(length=500), server_default='', nullable=False),
        sa.Column('appeal_text', sa.String(length=500), server_default='', nullable=False),
        sa.Column('appeal_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('appeal_result', sa.String(length=12), server_default='', nullable=False),
        sa.Column('appeal_by', sa.Integer(), nullable=True),
        sa.Column('appeal_note', sa.String(length=500), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['admin_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['post_id'], ['forum_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['forum_tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_forum_decisions_post_id'), 'forum_decisions', ['post_id'])
    op.create_index(op.f('ix_forum_decisions_tag_id'), 'forum_decisions', ['tag_id'])
    op.create_index(op.f('ix_forum_decisions_created_at'), 'forum_decisions', ['created_at'])
    op.create_index('ix_forum_decisions_appeal', 'forum_decisions', ['appeal_result', 'id'])

    op.create_table(
        'forum_user_settings',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('personalize', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )

    # 互动消息加论坛的目标列(§5.8)。帖子删了通知跟着删
    op.add_column('social_notifications', sa.Column('forum_post_id', sa.BigInteger(),
                                                    nullable=True))
    op.create_foreign_key('fk_social_notifications_forum_post', 'social_notifications',
                          'forum_posts', ['forum_post_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('fk_social_notifications_forum_post', 'social_notifications',
                       type_='foreignkey')
    op.drop_column('social_notifications', 'forum_post_id')
    # 论坛的互动消息(kind 是 repost / quote,或者挂在帖子上的)跟着一起删:
    # 表没了以后这些行点开是空白
    op.execute("DELETE FROM social_notifications WHERE kind IN ('repost', 'quote')")
    for table in ('forum_user_settings', 'forum_decisions', 'forum_reports', 'forum_view_days',
                  'forum_mute_words', 'forum_pins', 'forum_poll_votes', 'forum_polls',
                  'forum_mentions', 'forum_post_tags', 'forum_tags', 'forum_bookmarks',
                  'forum_likes', 'forum_reposts', 'forum_post_edits', 'forum_posts'):
        op.drop_table(table)
