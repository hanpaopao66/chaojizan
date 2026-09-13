"""视频:稿件、分 P、互动、硬币流水、收藏、历史、关注、评论、弹幕、播放去重、审核、举报、热搜、互动消息
(#357–#368,DEV-PROMPTS-40 §7「视频」)

- 线上版本和待审版本分开放:videos 行上是审核过的那一版,已发布稿件的改动先进 pending_changes;
  分 P 的 live 为真才是线上那几 P(§5.8「审核期间线上仍是上一版」);
- 排序用的「近 72 小时增量、同一个人每种互动只算一次」直接从明细表按时间窗去重数,
  所以各明细表都带 created_at 索引;
- 硬币余额用 0125 已经建好的 social_profiles.coins / coin_day,这里只加流水表;
- 不许有 bid / boost / paid / promot / rank_score / weight_override 这类列(S3)。

手写迁移,只含新表;不回填任何数据。

Revision ID: 0128
Revises: 0127
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0128'
down_revision = '0127'
branch_labels = None
depends_on = None


def _now(name: str = 'created_at', nullable: bool = False):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(),
                     nullable=nullable)


def _int0(name: str):
    return sa.Column(name, sa.Integer(), nullable=False, server_default='0')


def _user_fk(name: str, *, pk: bool = False, nullable: bool = False):
    return sa.Column(name, sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'),
                     primary_key=pk, nullable=nullable)


def _video_fk(name: str = 'video_id', *, pk: bool = False):
    return sa.Column(name, sa.Integer(), sa.ForeignKey('videos.id', ondelete='CASCADE'),
                     primary_key=pk, nullable=False)


def upgrade() -> None:
    op.create_table(
        'videos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('vid', sa.String(12), nullable=False, unique=True),
        _user_fk('uploader_id'),
        sa.Column('title', sa.String(80), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('cover_media_id', sa.Integer(), nullable=True),
        sa.Column('cover_url', sa.String(300), nullable=False, server_default=''),
        sa.Column('zone', sa.String(16), nullable=False, server_default=''),
        sa.Column('tags', postgresql.ARRAY(sa.String(20)), nullable=False, server_default='{}'),
        sa.Column('copyright', sa.String(8), nullable=False, server_default='original'),
        sa.Column('source_url', sa.String(300), nullable=False, server_default=''),
        sa.Column('status', sa.String(12), nullable=False, server_default='draft'),
        sa.Column('visibility', sa.String(8), nullable=False, server_default='public'),
        sa.Column('is_vertical', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('allow_danmaku', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('allow_comments', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('shop_id', sa.Integer(), nullable=True),
        sa.Column('shop_collab', sa.Boolean(), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reject_code', sa.String(8), nullable=False, server_default=''),
        sa.Column('reject_note', sa.String(500), nullable=False, server_default=''),
        sa.Column('fail_reason', sa.String(300), nullable=False, server_default=''),
        sa.Column('pending_changes', postgresql.JSONB(), nullable=True),
        _int0('views'), _int0('likes'), _int0('coins'), _int0('favorites'), _int0('shares'),
        _int0('danmaku_count'), _int0('comment_count'),
        _now(),
        _now('updated_at'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_videos_uploader_id', 'videos', ['uploader_id'])
    op.create_index('ix_videos_feed', 'videos', ['status', 'visibility', 'published_at'])
    op.create_index('ix_videos_uploader_created', 'videos', ['uploader_id', 'created_at'])
    op.create_index('ix_videos_status_submitted', 'videos', ['status', 'submitted_at'])

    op.create_table(
        'video_parts',
        sa.Column('id', sa.Integer(), primary_key=True),
        _video_fk(),
        sa.Column('idx', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('title', sa.String(80), nullable=False, server_default=''),
        sa.Column('source_media_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(12), nullable=False, server_default='processing'),
        sa.Column('error', sa.String(300), nullable=False, server_default=''),
        _int0('duration_ms'), _int0('w'), _int0('h'),
        sa.Column('renditions', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('sprite', postgresql.JSONB(), nullable=True),
        sa.Column('cover_media_ids', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('live', sa.Boolean(), nullable=False, server_default=sa.false()),
        _now(),
    )
    op.create_index('ix_video_parts_video_id', 'video_parts', ['video_id'])

    op.create_table(
        'video_likes',
        _video_fk(pk=True), _user_fk('user_id', pk=True), _now(),
    )
    op.create_index('ix_video_likes_user_id', 'video_likes', ['user_id'])
    op.create_index('ix_video_likes_created', 'video_likes', ['created_at'])

    op.create_table(
        'video_coins',
        _video_fk(pk=True), _user_fk('user_id', pk=True),
        sa.Column('amount', sa.SmallInteger(), nullable=False, server_default='0'),
        _now(),
    )
    op.create_index('ix_video_coins_user_id', 'video_coins', ['user_id'])
    op.create_index('ix_video_coins_created', 'video_coins', ['created_at'])

    op.create_table(
        'coin_ledger',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        _user_fk('user_id'),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(16), nullable=False),
        sa.Column('ref', sa.String(40), nullable=False, server_default=''),
        sa.Column('balance', sa.Integer(), nullable=False, server_default='0'),
        _now(),
    )
    op.create_index('ix_coin_ledger_user', 'coin_ledger', ['user_id', 'id'])
    op.create_index('uq_coin_ledger_approved', 'coin_ledger', ['user_id', 'ref'], unique=True,
                    postgresql_where=sa.text("reason = 'video_approved'"))

    op.create_table(
        'video_shares',
        _video_fk(pk=True), _user_fk('user_id', pk=True),
        sa.Column('channel', sa.String(12), nullable=False, server_default='link'),
        sa.Column('times', sa.Integer(), nullable=False, server_default='1'),
        _now(),
    )
    op.create_index('ix_video_shares_user_id', 'video_shares', ['user_id'])
    op.create_index('ix_video_shares_created', 'video_shares', ['created_at'])

    op.create_table(
        'fav_folders',
        sa.Column('id', sa.Integer(), primary_key=True),
        _user_fk('user_id'),
        sa.Column('title', sa.String(20), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('public', sa.Boolean(), nullable=False, server_default=sa.false()),
        _int0('item_count'),
        _now(), _now('updated_at'),
    )
    op.create_index('ix_fav_folders_user_id', 'fav_folders', ['user_id'])
    op.create_index('uq_fav_folders_default', 'fav_folders', ['user_id'], unique=True,
                    postgresql_where=sa.text('is_default'))

    op.create_table(
        'fav_items',
        sa.Column('folder_id', sa.Integer(), sa.ForeignKey('fav_folders.id', ondelete='CASCADE'),
                  primary_key=True),
        _video_fk(pk=True), _user_fk('user_id'), _now(),
    )
    op.create_index('ix_fav_items_user_video', 'fav_items', ['user_id', 'video_id'])
    op.create_index('ix_fav_items_video_created', 'fav_items', ['video_id', 'created_at'])
    op.create_index('ix_fav_items_created', 'fav_items', ['created_at'])

    op.create_table('watch_later', _user_fk('user_id', pk=True), _video_fk(pk=True), _now())

    op.create_table(
        'watch_history',
        _user_fk('user_id', pk=True), _video_fk(pk=True),
        _int0('part_idx'), _int0('position_ms'), _int0('duration_ms'),
        _now('watched_at'),
    )
    op.create_index('ix_watch_history_user_time', 'watch_history', ['user_id', 'watched_at'])

    op.create_table(
        'video_user_settings',
        _user_fk('user_id', pk=True),
        sa.Column('history_paused', sa.Boolean(), nullable=False, server_default=sa.false()),
        _now('updated_at'),
    )

    op.create_table('video_not_interested', _user_fk('user_id', pk=True), _video_fk(pk=True),
                    _now())

    op.create_table('follows', _user_fk('follower_id', pk=True), _user_fk('followee_id', pk=True),
                    _now())
    op.create_index('ix_follows_followee', 'follows', ['followee_id', 'created_at'])
    op.create_index('ix_follows_follower', 'follows', ['follower_id', 'created_at'])

    op.create_table(
        'video_comments',
        sa.Column('id', sa.Integer(), primary_key=True),
        _video_fk(), _user_fk('user_id'),
        sa.Column('root_id', sa.Integer(), nullable=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('reply_to_user_id', sa.Integer(), nullable=True),
        sa.Column('text', sa.Text(), nullable=False, server_default=''),
        sa.Column('mentions', postgresql.JSONB(), nullable=False, server_default='[]'),
        _int0('likes'), _int0('dislikes'), _int0('reply_count'),
        sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        _now(),
    )
    op.create_index('ix_video_comments_video_root', 'video_comments',
                    ['video_id', 'root_id', 'id'])
    op.create_index('ix_video_comments_root', 'video_comments', ['root_id', 'id'])
    op.create_index('ix_video_comments_user', 'video_comments', ['user_id', 'created_at'])
    op.create_index('ix_video_comments_created', 'video_comments', ['created_at'])

    op.create_table(
        'comment_votes',
        sa.Column('comment_id', sa.Integer(),
                  sa.ForeignKey('video_comments.id', ondelete='CASCADE'), primary_key=True),
        _user_fk('user_id', pk=True),
        sa.Column('vote', sa.SmallInteger(), nullable=False),
        _now(),
    )
    op.create_index('ix_comment_votes_user_id', 'comment_votes', ['user_id'])

    op.create_table(
        'danmaku',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        _video_fk(),
        sa.Column('part_id', sa.Integer(), sa.ForeignKey('video_parts.id', ondelete='CASCADE'),
                  nullable=False),
        _user_fk('user_id'),
        sa.Column('time_ms', sa.Integer(), nullable=False),
        sa.Column('mode', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('color', sa.Integer(), nullable=False, server_default='16777215'),
        sa.Column('size', sa.SmallInteger(), nullable=False, server_default='25'),
        sa.Column('text', sa.String(100), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        _now(),
    )
    op.create_index('ix_danmaku_part_time', 'danmaku', ['part_id', 'time_ms'])
    op.create_index('ix_danmaku_video_created', 'danmaku', ['video_id', 'created_at'])
    op.create_index('ix_danmaku_user', 'danmaku', ['user_id', 'created_at'])
    op.create_index('ix_danmaku_created', 'danmaku', ['created_at'])

    op.create_table(
        'video_view_days',
        _video_fk(pk=True),
        sa.Column('day', sa.Date(), primary_key=True),
        sa.Column('viewer_key', sa.String(48), primary_key=True),
        _now(),
    )
    op.create_index('ix_video_view_days_created', 'video_view_days', ['created_at'])

    op.create_table(
        'video_stat_days',
        _video_fk(pk=True),
        sa.Column('day', sa.Date(), primary_key=True),
        _int0('views'), _int0('likes'), _int0('coins'), _int0('favorites'), _int0('comments'),
        _int0('danmaku'), _int0('shares'),
    )

    op.create_table(
        'video_reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        _user_fk('reporter_id'),
        sa.Column('target_type', sa.String(8), nullable=False),
        sa.Column('target_id', sa.BigInteger(), nullable=False),
        sa.Column('video_id', sa.Integer(), nullable=True),
        sa.Column('reason_code', sa.String(8), nullable=False),
        sa.Column('note', sa.String(500), nullable=False, server_default=''),
        sa.Column('status', sa.String(10), nullable=False, server_default='open'),
        sa.Column('handled_by', sa.Integer(), nullable=True),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution', sa.String(300), nullable=False, server_default=''),
        _now(),
    )
    op.create_index('ix_video_reports_reporter_id', 'video_reports', ['reporter_id'])
    op.create_index('ix_video_reports_video_id', 'video_reports', ['video_id'])
    op.create_index('ix_video_reports_target', 'video_reports',
                    ['target_type', 'target_id', 'created_at'])
    op.create_index('ix_video_reports_status', 'video_reports', ['status', 'id'])

    op.create_table(
        'video_decisions',
        sa.Column('id', sa.Integer(), primary_key=True),
        _video_fk(),
        sa.Column('action', sa.String(24), nullable=False),
        sa.Column('reason_code', sa.String(8), nullable=False, server_default=''),
        sa.Column('note', sa.String(500), nullable=False, server_default=''),
        sa.Column('note_internal', sa.String(500), nullable=False, server_default=''),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('appeal_of', sa.Integer(), nullable=True),
        _now(),
    )
    op.create_index('ix_video_decisions_video_id', 'video_decisions', ['video_id'])
    op.create_index('ix_video_decisions_appeal_of', 'video_decisions', ['appeal_of'])
    op.create_index('ix_video_decisions_created_at', 'video_decisions', ['created_at'])

    op.create_table(
        'search_terms',
        sa.Column('day', sa.Date(), primary_key=True),
        sa.Column('term', sa.String(32), primary_key=True),
        _int0('users'),
    )
    op.create_table(
        'search_term_users',
        sa.Column('day', sa.Date(), primary_key=True),
        sa.Column('term', sa.String(32), primary_key=True),
        _user_fk('user_id', pk=True),
        _now(),
    )
    op.create_index('ix_search_term_users_created', 'search_term_users', ['created_at'])

    op.create_table(
        'social_notifications',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        _user_fk('user_id'),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('video_id', sa.Integer(), nullable=True),
        sa.Column('comment_id', sa.Integer(), nullable=True),
        sa.Column('group_key', sa.String(40), nullable=False, server_default=''),
        sa.Column('count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('actors', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('data', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        _now(), _now('updated_at'),
    )
    op.create_index('ix_social_notifications_user_kind', 'social_notifications',
                    ['user_id', 'kind', 'updated_at'])
    op.create_index('uq_social_notifications_group', 'social_notifications',
                    ['user_id', 'group_key'], unique=True,
                    postgresql_where=sa.text("group_key <> ''"))


def downgrade() -> None:
    for name in ('social_notifications', 'search_term_users', 'search_terms', 'video_decisions',
                 'video_reports', 'video_stat_days', 'video_view_days', 'danmaku',
                 'comment_votes', 'video_comments', 'follows', 'video_not_interested',
                 'video_user_settings', 'watch_history', 'watch_later', 'fav_items',
                 'fav_folders', 'video_shares', 'coin_ledger', 'video_coins', 'video_likes',
                 'video_parts', 'videos'):
        op.drop_table(name)
