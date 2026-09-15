"""音乐:音乐人、作品、歌曲、歌单、喜欢、收听、评论、举报、审核(DEV-PROMPTS-41 §7.1,#378)

顺带给 social_notifications 加三列音乐目标(§5.8 互动消息全站一处):music_track_id、
music_comment_id、music_release_id,都可空、删除级联 —— 歌或作品删了,指着它的互动消息跟着消失。

索引按查询建:审核队列按 (status, submitted_at)、榜单按各明细表的 (目标, 时间)、
歌单里的顺序按 (playlist_id, position)。

Revision ID: 0143
Revises: 0142
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0143'
down_revision = '0142'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'music_artists',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('aid', sa.String(12), nullable=False),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(30), nullable=False),
        sa.Column('name_lc', sa.String(30), nullable=False),
        sa.Column('bio', sa.String(500), nullable=False, server_default=''),
        sa.Column('avatar_url', sa.String(300), nullable=False, server_default=''),
        sa.Column('cover_url', sa.String(300), nullable=False, server_default=''),
        sa.Column('genres', postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('status', sa.String(10), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint('uq_music_artists_aid', 'music_artists', ['aid'])
    op.create_unique_constraint('uq_music_artists_user', 'music_artists', ['user_id'])
    # 艺名唯一靠小写去空白后的 name_lc:靠应用层比对迟早会漏(两个请求同时提交时谁也查不到对方)
    op.create_unique_constraint('uq_music_artists_name_lc', 'music_artists', ['name_lc'])

    op.create_table(
        'music_releases',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rid', sa.String(12), nullable=False),
        sa.Column('artist_id', sa.Integer(),
                  sa.ForeignKey('music_artists.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(60), nullable=False, server_default=''),
        sa.Column('kind', sa.String(8), nullable=False, server_default='single'),
        sa.Column('cover_media_id', sa.Integer(), nullable=True),
        sa.Column('cover_url', sa.String(300), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('genre', sa.String(16), nullable=False, server_default=''),
        sa.Column('language', sa.String(16), nullable=False, server_default=''),
        sa.Column('release_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(12), nullable=False, server_default='draft'),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reject_code', sa.String(8), nullable=False, server_default=''),
        sa.Column('reject_note', sa.String(500), nullable=False, server_default=''),
        sa.Column('collects', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint('uq_music_releases_rid', 'music_releases', ['rid'])
    op.create_index('ix_music_releases_artist_id', 'music_releases', ['artist_id'])
    op.create_index('ix_music_releases_artist_created', 'music_releases',
                    ['artist_id', 'created_at'])
    op.create_index('ix_music_releases_status_submitted', 'music_releases',
                    ['status', 'submitted_at'])
    op.create_index('ix_music_releases_published', 'music_releases', ['status', 'published_at'])

    op.create_table(
        'music_tracks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tid', sa.String(12), nullable=False),
        sa.Column('release_id', sa.Integer(),
                  sa.ForeignKey('music_releases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('artist_id', sa.Integer(),
                  sa.ForeignKey('music_artists.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(60), nullable=False, server_default=''),
        sa.Column('track_no', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('source_media_id', sa.Integer(), nullable=True),
        sa.Column('renditions', postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('transcode_status', sa.String(12), nullable=False, server_default='pending'),
        sa.Column('fail_reason', sa.String(300), nullable=False, server_default=''),
        sa.Column('lyrics', sa.Text(), nullable=False, server_default=''),
        sa.Column('lyrics_kind', sa.String(8), nullable=False, server_default='none'),
        sa.Column('credits', postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column('explicit', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('declaration', sa.String(12), nullable=False, server_default='original'),
        sa.Column('plays', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('likes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('comments', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint('uq_music_tracks_tid', 'music_tracks', ['tid'])
    op.create_index('ix_music_tracks_release_id', 'music_tracks', ['release_id'])
    op.create_index('ix_music_tracks_artist_id', 'music_tracks', ['artist_id'])
    op.create_index('ix_music_tracks_release_no', 'music_tracks',
                    ['release_id', 'track_no', 'id'])
    op.create_index('ix_music_tracks_artist_plays', 'music_tracks', ['artist_id', 'plays'])

    op.create_table(
        'music_playlists',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pid', sa.String(12), nullable=False),
        sa.Column('owner_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(40), nullable=False, server_default=''),
        sa.Column('description', sa.String(500), nullable=False, server_default=''),
        sa.Column('cover_url', sa.String(300), nullable=False, server_default=''),
        sa.Column('tags', postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('track_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('collects', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint('uq_music_playlists_pid', 'music_playlists', ['pid'])
    op.create_index('ix_music_playlists_owner_id', 'music_playlists', ['owner_id'])
    op.create_index('ix_music_playlists_owner_updated', 'music_playlists',
                    ['owner_id', 'updated_at'])

    op.create_table(
        'music_playlist_tracks',
        sa.Column('playlist_id', sa.Integer(),
                  sa.ForeignKey('music_playlists.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('track_id', sa.Integer(),
                  sa.ForeignKey('music_tracks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('added_by', sa.Integer(), nullable=True),
    )
    op.create_index('ix_music_playlist_tracks_order', 'music_playlist_tracks',
                    ['playlist_id', 'position', 'track_id'])
    op.create_index('ix_music_playlist_tracks_track_added', 'music_playlist_tracks',
                    ['track_id', 'added_at'])

    op.create_table(
        'music_track_likes',
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('track_id', sa.Integer(),
                  sa.ForeignKey('music_tracks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_music_track_likes_track_created', 'music_track_likes',
                    ['track_id', 'created_at'])

    op.create_table(
        'music_playlist_collects',
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('playlist_id', sa.Integer(),
                  sa.ForeignKey('music_playlists.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_music_playlist_collects_pl_created', 'music_playlist_collects',
                    ['playlist_id', 'created_at'])

    op.create_table(
        'music_release_collects',
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('release_id', sa.Integer(),
                  sa.ForeignKey('music_releases.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_music_release_collects_rel_created', 'music_release_collects',
                    ['release_id', 'created_at'])

    op.create_table(
        'music_plays',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('track_id', sa.Integer(),
                  sa.ForeignKey('music_tracks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('listener_key', sa.String(48), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('ms_listened', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('day', sa.Date(), nullable=False),
    )
    op.create_index('ix_music_plays_track_created', 'music_plays', ['track_id', 'created_at'])
    op.create_index('ix_music_plays_created', 'music_plays', ['created_at'])
    op.create_index('ix_music_plays_user', 'music_plays', ['user_id', 'created_at'])
    op.create_index('ix_music_plays_day', 'music_plays', ['day'])

    op.create_table(
        'music_history',
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('track_id', sa.Integer(),
                  sa.ForeignKey('music_tracks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('played_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_music_history_user_time', 'music_history', ['user_id', 'played_at'])

    op.create_table(
        'music_comments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('track_id', sa.Integer(),
                  sa.ForeignKey('music_tracks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('root_id', sa.Integer(), nullable=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('reply_to_user_id', sa.Integer(), nullable=True),
        sa.Column('text', sa.Text(), nullable=False, server_default=''),
        sa.Column('mentions', postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('likes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reply_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(10), nullable=False, server_default='visible'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_music_comments_track_root', 'music_comments',
                    ['track_id', 'root_id', 'id'])
    op.create_index('ix_music_comments_root', 'music_comments', ['root_id', 'id'])
    op.create_index('ix_music_comments_user', 'music_comments', ['user_id', 'created_at'])

    op.create_table(
        'music_comment_likes',
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('comment_id', sa.Integer(),
                  sa.ForeignKey('music_comments.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_music_comment_likes_comment', 'music_comment_likes', ['comment_id'])

    op.create_table(
        'music_reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('reporter_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_type', sa.String(10), nullable=False),
        sa.Column('target_id', sa.BigInteger(), nullable=False),
        sa.Column('reason_code', sa.String(8), nullable=False),
        sa.Column('note', sa.String(500), nullable=False, server_default=''),
        sa.Column('contact', sa.String(120), nullable=False, server_default=''),
        sa.Column('status', sa.String(10), nullable=False, server_default='open'),
        sa.Column('handled_by', sa.Integer(), nullable=True),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution', sa.String(300), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_music_reports_reporter_id', 'music_reports', ['reporter_id'])
    op.create_index('ix_music_reports_target', 'music_reports',
                    ['target_type', 'target_id', 'created_at'])
    op.create_index('ix_music_reports_status', 'music_reports', ['status', 'id'])

    op.create_table(
        'music_decisions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('release_id', sa.Integer(),
                  sa.ForeignKey('music_releases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('admin_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(16), nullable=False),
        sa.Column('reason_code', sa.String(8), nullable=False, server_default=''),
        sa.Column('note', sa.String(500), nullable=False, server_default=''),
        sa.Column('appeal_text', sa.String(500), nullable=False, server_default=''),
        sa.Column('appeal_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('appeal_result', sa.String(12), nullable=False, server_default=''),
        sa.Column('appeal_by', sa.Integer(), nullable=True),
        sa.Column('appeal_note', sa.String(500), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_music_decisions_release_id', 'music_decisions', ['release_id'])
    op.create_index('ix_music_decisions_created_at', 'music_decisions', ['created_at'])
    op.create_index('ix_music_decisions_appeals', 'music_decisions',
                    ['appeal_at', 'appeal_result'])

    op.create_table(
        'music_user_settings',
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('personalize', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 互动消息全站一处(§5.8):加音乐的三个目标列
    op.add_column('social_notifications', sa.Column('music_track_id', sa.Integer(), nullable=True))
    op.add_column('social_notifications',
                  sa.Column('music_comment_id', sa.Integer(), nullable=True))
    op.add_column('social_notifications',
                  sa.Column('music_release_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_social_notifications_music_track', 'social_notifications',
                          'music_tracks', ['music_track_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_social_notifications_music_comment', 'social_notifications',
                          'music_comments', ['music_comment_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_social_notifications_music_release', 'social_notifications',
                          'music_releases', ['music_release_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('fk_social_notifications_music_release', 'social_notifications',
                       type_='foreignkey')
    op.drop_constraint('fk_social_notifications_music_comment', 'social_notifications',
                       type_='foreignkey')
    op.drop_constraint('fk_social_notifications_music_track', 'social_notifications',
                       type_='foreignkey')
    op.drop_column('social_notifications', 'music_release_id')
    op.drop_column('social_notifications', 'music_comment_id')
    op.drop_column('social_notifications', 'music_track_id')
    for table in ('music_user_settings', 'music_decisions', 'music_reports',
                  'music_comment_likes', 'music_comments', 'music_history', 'music_plays',
                  'music_release_collects', 'music_playlist_collects', 'music_track_likes',
                  'music_playlist_tracks', 'music_playlists', 'music_tracks', 'music_releases',
                  'music_artists'):
        op.drop_table(table)
