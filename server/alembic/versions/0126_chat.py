"""聊天:会话、成员、消息、事件、投票、邀请链接、贴纸、分组、通话、机器人、举报(#343 #344,DEV-PROMPTS-40)

表名 `chat_messages`:`messages` 已经是订单内聊天那张表,两者无关。
事件按会话记(chat_events,会话内 pts 连续)和按人记(user_events),保留 7 天(§5.3)。
不回填任何数据。

Revision ID: 0126
Revises: 0125
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0126'
down_revision = '0125'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('bot_updates',
    sa.Column('bot_id', sa.Integer(), nullable=False),
    sa.Column('update_id', sa.BigInteger(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_try_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['bot_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('bot_id', 'update_id')
    )
    op.create_table('bots',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('token_prefix', sa.String(length=12), nullable=False),
    sa.Column('about', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=512), nullable=False),
    sa.Column('commands', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('webhook_url', sa.String(length=300), nullable=False),
    sa.Column('webhook_secret', sa.String(length=64), nullable=False),
    sa.Column('menu_app_id', sa.String(length=24), nullable=False),
    sa.Column('privacy_mode', sa.Boolean(), nullable=False),
    sa.Column('next_update_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_bots_owner_id'), 'bots', ['owner_id'], unique=False)
    op.create_table('calls',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('call_id', sa.String(length=24), nullable=False),
    sa.Column('caller_id', sa.Integer(), nullable=False),
    sa.Column('callee_id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.Integer(), nullable=True),
    sa.Column('video', sa.Boolean(), nullable=False),
    sa.Column('state', sa.String(length=10), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reason', sa.String(length=24), nullable=False),
    sa.ForeignKeyConstraint(['callee_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['caller_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('call_id')
    )
    op.create_index(op.f('ix_calls_callee_id'), 'calls', ['callee_id'], unique=False)
    op.create_index(op.f('ix_calls_caller_id'), 'calls', ['caller_id'], unique=False)
    op.create_table('chat_folders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=12), nullable=False),
    sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chat_folders_user_id'), 'chat_folders', ['user_id'], unique=False)
    op.create_table('chat_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('reporter_id', sa.Integer(), nullable=False),
    sa.Column('target_type', sa.String(length=8), nullable=False),
    sa.Column('chat_id', sa.Integer(), nullable=True),
    sa.Column('seqs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('reason_code', sa.String(length=8), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('decision', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('handled_by', sa.Integer(), nullable=True),
    sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chat_reports_chat_id'), 'chat_reports', ['chat_id'], unique=False)
    op.create_index(op.f('ix_chat_reports_reporter_id'), 'chat_reports', ['reporter_id'], unique=False)
    op.create_index(op.f('ix_chat_reports_user_id'), 'chat_reports', ['user_id'], unique=False)
    op.create_table('chats',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=8), nullable=False),
    sa.Column('public_id', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=128), nullable=False),
    sa.Column('about', sa.String(length=255), nullable=False),
    sa.Column('photo_url', sa.String(length=300), nullable=False),
    sa.Column('username', sa.String(length=32), nullable=True),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('pair_key', sa.String(length=32), nullable=True),
    sa.Column('last_seq', sa.BigInteger(), nullable=False),
    sa.Column('pts', sa.BigInteger(), nullable=False),
    sa.Column('member_count', sa.Integer(), nullable=False),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('pair_key'),
    sa.UniqueConstraint('public_id')
    )
    op.create_table('sticker_sets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('short_name', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=64), nullable=False),
    sa.Column('is_official', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('short_name')
    )
    op.create_table('user_events',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('pts', sa.BigInteger(), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'pts')
    )
    op.create_index('ix_user_events_created', 'user_events', ['created_at'], unique=False)
    op.create_table('admin_chat_views',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('admin_id', sa.Integer(), nullable=False),
    sa.Column('report_id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('seqs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['report_id'], ['chat_reports.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_admin_chat_views_admin_id'), 'admin_chat_views', ['admin_id'], unique=False)
    op.create_table('chat_events',
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('pts', sa.BigInteger(), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chat_id', 'pts')
    )
    op.create_index('ix_chat_events_created', 'chat_events', ['created_at'], unique=False)
    op.create_table('chat_members',
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=12), nullable=False),
    sa.Column('rights', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('restrictions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('title', sa.String(length=16), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('invited_by', sa.Integer(), nullable=True),
    sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('join_seq', sa.BigInteger(), nullable=False),
    sa.Column('last_read_seq', sa.BigInteger(), nullable=False),
    sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cleared_seq', sa.BigInteger(), nullable=False),
    sa.Column('muted_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pinned_rank', sa.Integer(), nullable=True),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('marked_unread', sa.Boolean(), nullable=False),
    sa.Column('draft', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('visible', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chat_id', 'user_id')
    )
    op.create_index('ix_chat_members_user_role', 'chat_members', ['user_id', 'role'], unique=False)
    op.create_table('chat_messages',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('sender_id', sa.Integer(), nullable=True),
    sa.Column('as_chat', sa.Boolean(), nullable=False),
    sa.Column('random_id', sa.BigInteger(), nullable=True),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('entities', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('media', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reply_to_seq', sa.BigInteger(), nullable=True),
    sa.Column('forward', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('grouped_id', sa.BigInteger(), nullable=True),
    sa.Column('poll_id', sa.Integer(), nullable=True),
    sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('markup', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('via_bot_id', sa.Integer(), nullable=True),
    sa.Column('silent', sa.Boolean(), nullable=False),
    sa.Column('views', sa.Integer(), nullable=False),
    sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('chat_id', 'seq', name='uq_chat_messages_seq')
    )
    op.create_index('ix_chat_messages_pinned', 'chat_messages', ['chat_id'], unique=False, postgresql_where=sa.text('pinned_at IS NOT NULL'))
    op.create_index('ix_chat_messages_media', 'chat_messages', ['media'], unique=False, postgresql_using='gin', postgresql_ops={'media': 'jsonb_path_ops'})
    op.create_index('ix_chat_messages_sender_time', 'chat_messages', ['sender_id', 'created_at'], unique=False)
    op.create_index('uq_chat_messages_random', 'chat_messages', ['chat_id', 'sender_id', 'random_id'], unique=True, postgresql_where=sa.text('random_id IS NOT NULL'))
    op.create_table('invite_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=24), nullable=False),
    sa.Column('creator_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=32), nullable=False),
    sa.Column('expire_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('usage_limit', sa.Integer(), nullable=True),
    sa.Column('usage_count', sa.Integer(), nullable=False),
    sa.Column('requires_approval', sa.Boolean(), nullable=False),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_invite_links_chat_id'), 'invite_links', ['chat_id'], unique=False)
    op.create_table('join_requests',
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('invite_code', sa.String(length=24), nullable=False),
    sa.Column('about', sa.String(length=140), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chat_id', 'user_id')
    )
    op.create_table('message_hides',
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chat_id', 'seq', 'user_id')
    )
    op.create_table('message_mentions',
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chat_id', 'seq', 'user_id')
    )
    op.create_index('ix_message_mentions_user', 'message_mentions', ['user_id', 'chat_id', 'seq'], unique=False)
    op.create_table('message_reactions',
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('emoji', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chat_id', 'seq', 'user_id', 'emoji')
    )
    op.create_table('polls',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('creator_id', sa.Integer(), nullable=True),
    sa.Column('question', sa.String(length=255), nullable=False),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('multiple', sa.Boolean(), nullable=False),
    sa.Column('quiz', sa.Boolean(), nullable=False),
    sa.Column('correct', sa.Integer(), nullable=True),
    sa.Column('explanation', sa.String(length=200), nullable=False),
    sa.Column('anonymous', sa.Boolean(), nullable=False),
    sa.Column('closed', sa.Boolean(), nullable=False),
    sa.Column('close_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('scheduled_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('sender_id', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('send_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scheduled_messages_chat_id'), 'scheduled_messages', ['chat_id'], unique=False)
    op.create_index(op.f('ix_scheduled_messages_send_at'), 'scheduled_messages', ['send_at'], unique=False)
    op.create_table('stickers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('set_id', sa.Integer(), nullable=False),
    sa.Column('media_id', sa.Integer(), nullable=False),
    sa.Column('emoji', sa.String(length=16), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['set_id'], ['sticker_sets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stickers_set_id'), 'stickers', ['set_id'], unique=False)
    op.create_table('user_sticker_sets',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('set_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('installed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['set_id'], ['sticker_sets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'set_id')
    )
    op.create_table('poll_votes',
    sa.Column('poll_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['poll_id'], ['polls.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('poll_id', 'user_id')
    )


def downgrade() -> None:
    op.drop_table('poll_votes')
    op.drop_table('user_sticker_sets')
    op.drop_table('stickers')
    op.drop_table('scheduled_messages')
    op.drop_table('polls')
    op.drop_table('message_reactions')
    op.drop_table('message_mentions')
    op.drop_table('message_hides')
    op.drop_table('join_requests')
    op.drop_table('invite_links')
    op.drop_table('chat_messages')
    op.drop_table('chat_members')
    op.drop_table('chat_events')
    op.drop_table('admin_chat_views')
    op.drop_table('user_events')
    op.drop_table('sticker_sets')
    op.drop_table('chats')
    op.drop_table('chat_reports')
    op.drop_table('chat_folders')
    op.drop_table('calls')
    op.drop_table('bots')
    op.drop_table('bot_updates')
