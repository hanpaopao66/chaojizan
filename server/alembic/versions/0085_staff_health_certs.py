"""从业人员健康证台账

《食品安全法》四十五条要求接触直接入口食品的从业人员每年体检、持证上岗。
证一年一换、到期静默失效 —— 和食品经营许可证同一个毛病,只是人更多、
更没人记得。监管检查要看的是**记录**,塞在抽屉里翻不出来就是没有。

主体是员工本人不是商家:照片走私密桶,列表里证件号打码,
**绝不进「亮照公示」那个无鉴权的对外出口**。

到期只提醒不停业:健康证是按人的,一个员工的证过期停整家店不成比例。

Revision ID: 0085
Revises: 0084
"""
import sqlalchemy as sa
from alembic import op

revision = '0085'
down_revision = '0084'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'staff_health_certs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False, index=True),
        sa.Column('name', sa.String(30), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default=''),
        sa.Column('cert_no', sa.String(40), nullable=False, server_default=''),
        sa.Column('photo_url', sa.String(300), nullable=False,
                  server_default=''),
        sa.Column('issued_at', sa.Date(), nullable=True),
        sa.Column('expires_at', sa.Date(), nullable=True, index=True),
        # 离职的归档不删除:监管查的是"当时在岗的人有没有证",
        # 删掉等于把当时的合规记录一起删了
        sa.Column('archived', sa.Boolean(), nullable=False,
                  server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # 到期清扫按"这家店快到期的证"扫,不全表扫
    op.create_index('ix_health_certs_shop_expires', 'staff_health_certs',
                    ['merchant_id', 'expires_at'])


def downgrade() -> None:
    op.drop_index('ix_health_certs_shop_expires',
                  table_name='staff_health_certs')
    op.drop_table('staff_health_certs')
