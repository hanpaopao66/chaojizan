"""恶劣天气加价审核单(#307):自动判定提请 → 人工点头 → 限时生效

Revision ID: 0118
Revises: 0117
"""
import sqlalchemy as sa
from alembic import op

revision = '0118'
down_revision = '0117'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'weather_alerts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('city', sa.String(length=20), nullable=False),
        sa.Column('district', sa.String(length=20),
                  nullable=False, server_default=''),
        # native_enum=False:和库里其它状态枚举一个做法,值域改动不用 ALTER TYPE
        sa.Column('status', sa.String(length=20),
                  nullable=False, server_default='pending'),
        sa.Column('weather_code', sa.Integer(),
                  nullable=False, server_default='0'),
        sa.Column('precip_mm', sa.Float(), nullable=False, server_default='0'),
        sa.Column('wind_kmh', sa.Float(), nullable=False, server_default='0'),
        sa.Column('lat', sa.Float(), nullable=False, server_default='0'),
        sa.Column('lng', sa.Float(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_by', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('note', sa.String(length=200),
                  nullable=False, server_default=''),
    )
    op.create_index('ix_weather_alerts_city', 'weather_alerts', ['city'])
    op.create_index('ix_weather_alerts_status', 'weather_alerts', ['status'])
    # 「这个区县现在该不该加价」是每次算价都要走的路径
    op.create_index('ix_weather_alerts_zone_status', 'weather_alerts',
                    ['city', 'district', 'status'])


def downgrade() -> None:
    op.drop_index('ix_weather_alerts_zone_status', 'weather_alerts')
    op.drop_index('ix_weather_alerts_status', 'weather_alerts')
    op.drop_index('ix_weather_alerts_city', 'weather_alerts')
    op.drop_table('weather_alerts')
