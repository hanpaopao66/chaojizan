"""续证复审通道

过审后的资质字段一律锁死(随手改证号 = 让亮照公示页给假证号背书;
到期日能改成 2099 的话到期闸门就是摆设),续证提交到这张表人工核验。

**不复用"打回 pending 重审"**:那会让店在审核期间下架。
续证的店绝大多数在正常经营,只是证到期要换新的 —— 为换证停业几天
惩罚的是守规矩的人。所以单开通道:提交期间照常营业,核验通过才替换。

Revision ID: 0083
Revises: 0082
"""
import sqlalchemy as sa
from alembic import op

revision = '0083'
down_revision = '0082'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'license_renewals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(),
                  sa.ForeignKey('merchants.id'), nullable=False, index=True),
        sa.Column('submitted_by', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('license_no', sa.String(50), nullable=False,
                  server_default=''),
        sa.Column('license_image_url', sa.String(300), nullable=False,
                  server_default=''),
        sa.Column('license_expires_at', sa.Date(), nullable=True),
        sa.Column('business_license_no', sa.String(50), nullable=False,
                  server_default=''),
        sa.Column('license_subject', sa.String(100), nullable=False,
                  server_default=''),
        sa.Column('status', sa.String(10), nullable=False,
                  server_default='pending', index=True),
        sa.Column('reject_reason', sa.String(200), nullable=False,
                  server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    )
    # 「这家店有没有在审的续证」是每次提交都要查的,单店一条索引够用
    op.create_index('ix_license_renewals_shop_status', 'license_renewals',
                    ['merchant_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_license_renewals_shop_status',
                  table_name='license_renewals')
    op.drop_table('license_renewals')
