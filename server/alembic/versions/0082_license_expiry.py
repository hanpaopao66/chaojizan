"""证照有效期台账

此前库里只有证号和照片,**没有到期日**。食品经营许可证一般 5 年,
到期是「静默失效」—— 商家绝不会自己记得,而过期继续经营是违法的,
平台放任有连带责任(美团把「合作期间未能保持持续有效」明列为违规)。

license_notified 记已经就哪一档提醒过(30/7/1/expired),
清扫任务每小时跑一次也不会把商家轰成 24 条消息。

已有商家的 license_expires_at 留空 = 未登记,不触发任何提醒;
商家下次编辑资质时补录。**不给存量数据瞎猜一个日期** ——
猜错的后果是把正常营业的店误判成过期。

Revision ID: 0082
Revises: 0081
"""
import sqlalchemy as sa
from alembic import op

revision = '0082'
down_revision = '0081'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('merchants',
                  sa.Column('license_expires_at', sa.Date(), nullable=True))
    op.add_column('merchants',
                  sa.Column('business_license_no', sa.String(50),
                            nullable=False, server_default=''))
    op.add_column('merchants',
                  sa.Column('license_subject', sa.String(100),
                            nullable=False, server_default=''))
    op.add_column('merchants',
                  sa.Column('license_notified', sa.dialects.postgresql.JSONB(),
                            nullable=False, server_default='[]'))
    # 清扫任务按"快到期的"扫,不能全表扫 —— 门店数上去之后这是每小时一次的活
    op.create_index('ix_merchants_license_expires_at', 'merchants',
                    ['license_expires_at'])


def downgrade() -> None:
    op.drop_index('ix_merchants_license_expires_at', table_name='merchants')
    op.drop_column('merchants', 'license_notified')
    op.drop_column('merchants', 'license_subject')
    op.drop_column('merchants', 'business_license_no')
    op.drop_column('merchants', 'license_expires_at')
