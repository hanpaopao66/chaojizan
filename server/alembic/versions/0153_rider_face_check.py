"""骑手人脸核验:实名之后再加一道,并定时复核,防代送

- `rider_profiles` 加四列:单独同意时刻、首次核验时刻与服务商编号、最近通过时刻;
- 新表 `rider_face_checks`:每次核验的留痕。**只存结果和服务商编号,不存人脸图像。**

存量骑手四列都是空的,意味着上线后第一次上线/抢单会被要求先做一次核验
(由 RIDER_FACE_CHECK_REQUIRED 控制,服务商没配好之前可以先关掉)。

Revision ID: 0153
Revises: 0149

编号 0150-0152 预留给同时在开的转单、配送费、保险那几个 PR。
down_revision 暂时接在 main 上最新的 0149;前面那几个先合并的话,
合并本 PR 前把 down_revision 改成当时 main 上最新的那个,保持一条链。
"""
import sqlalchemy as sa
from alembic import op

revision = '0153'
down_revision = '0149'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('rider_profiles', sa.Column(
        'face_consent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('rider_profiles', sa.Column(
        'face_enrolled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('rider_profiles', sa.Column(
        'face_enroll_ref', sa.String(length=100), nullable=False,
        server_default=''))
    op.add_column('rider_profiles', sa.Column(
        'face_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'rider_face_checks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rider_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False),
        sa.Column('purpose', sa.String(length=16), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_ref', sa.String(length=100), nullable=False,
                  unique=True),
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default='pending'),
        sa.Column('reason', sa.String(length=200), nullable=False,
                  server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_rider_face_checks_rider_id', 'rider_face_checks',
                    ['rider_id'])


def downgrade() -> None:
    op.drop_index('ix_rider_face_checks_rider_id',
                  table_name='rider_face_checks')
    op.drop_table('rider_face_checks')
    for col in ('face_verified_at', 'face_enroll_ref', 'face_enrolled_at',
                'face_consent_at'):
        op.drop_column('rider_profiles', col)
