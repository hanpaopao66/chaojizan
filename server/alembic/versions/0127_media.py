"""媒体文件与分片上传(#341,DEV-PROMPTS-40)

media_files:聊天媒体、视频原片与转码产物、贴纸、封面。聊天媒体一律私密桶,下载每次判权。
uploads:分片上传(断点续传),24 小时没传完清掉。

Revision ID: 0127
Revises: 0126
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0127'
down_revision = '0126'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'media_files',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('purpose', sa.String(12), nullable=False, server_default='chat'),
        sa.Column('private', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('key', sa.String(200), nullable=False, server_default=''),
        sa.Column('kind', sa.String(12), nullable=False),
        sa.Column('mime', sa.String(80), nullable=False,
                  server_default='application/octet-stream'),
        sa.Column('size', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('w', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('h', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('thumb_key', sa.String(200), nullable=False, server_default=''),
        sa.Column('waveform', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('sha256', sa.String(64), nullable=False, server_default=''),
        sa.Column('name', sa.String(200), nullable=False, server_default=''),
        sa.Column('status', sa.String(12), nullable=False, server_default='ready'),
        sa.Column('error', sa.String(300), nullable=False, server_default=''),
        sa.Column('meta', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index('ix_media_files_owner_id', 'media_files', ['owner_id'])
    op.create_index('ix_media_files_status', 'media_files', ['status'])
    op.create_table(
        'uploads',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('purpose', sa.String(12), nullable=False, server_default='chat'),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('chunk_size', sa.Integer(), nullable=False),
        sa.Column('received', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('mime', sa.String(80), nullable=False, server_default=''),
        sa.Column('name', sa.String(200), nullable=False, server_default=''),
        sa.Column('status', sa.String(8), nullable=False, server_default='open'),
        sa.Column('media_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_uploads_owner_id', 'uploads', ['owner_id'])


def downgrade() -> None:
    op.drop_table('uploads')
    op.drop_table('media_files')
