"""社交身份:资料、@用户名命名空间、联系人、拉黑(#340,DEV-PROMPTS-40)

「消息」和「视频」共用这一套身份。名字、头像沿用 users 表,这里只放 users 没有的:
用户名、签名、隐私、通知偏好、个性化推荐开关、硬币、用户事件序号、最后上线时间。

usernames 是用户、群、频道、机器人共用的命名空间,主键是小写形式(大小写不敏感唯一)。
不回填:资料在第一次用到时建(services/social.ensure_profile)。

Revision ID: 0125
Revises: 0124
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0125'
down_revision = '0124'
branch_labels = None
depends_on = None


def _created():
    return sa.Column('created_at', sa.DateTime(timezone=True),
                     server_default=sa.func.now(), nullable=False)


def upgrade():
    op.create_table(
        'social_profiles',
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('public_id', sa.String(16), nullable=False, unique=True),
        sa.Column('username', sa.String(32), nullable=True),
        sa.Column('bio', sa.String(140), nullable=False, server_default=''),
        sa.Column('privacy', JSONB, nullable=False, server_default='{}'),
        sa.Column('notify', JSONB, nullable=False, server_default='{}'),
        sa.Column('personalize_video', sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column('coins', sa.Integer, nullable=False, server_default='0'),
        sa.Column('coin_day', sa.Date, nullable=True),
        sa.Column('user_pts', sa.BigInteger, nullable=False, server_default='0'),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        _created(),
    )
    op.create_table(
        'usernames',
        sa.Column('username_lc', sa.String(32), primary_key=True),
        sa.Column('owner_type', sa.String(8), nullable=False),
        sa.Column('owner_id', sa.Integer, nullable=False),
        _created(),
    )
    op.create_index('ix_usernames_owner_id', 'usernames', ['owner_id'])
    op.create_table(
        'social_contacts',
        sa.Column('owner_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('contact_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('alias', sa.String(40), nullable=False, server_default=''),
        _created(),
    )
    op.create_index('ix_social_contacts_contact_id', 'social_contacts', ['contact_id'])
    op.create_table(
        'social_blocks',
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('blocked_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'),
                  primary_key=True),
        _created(),
    )
    op.create_index('ix_social_blocks_blocked_id', 'social_blocks', ['blocked_id'])


def downgrade():
    op.drop_table('social_blocks')
    op.drop_table('social_contacts')
    op.drop_table('usernames')
    op.drop_table('social_profiles')
