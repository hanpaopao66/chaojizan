"""多台云打印机 + 小票开关

原先 Merchant.printer_sn 只有一个字段,前厅后厨只能共用一台 ——
出餐的人得跑到前台去拿单子。飞鹅本身一个账号就支持挂多台设备。

purpose 不只是标签:**后厨那张不印顾客手机号和地址**(后厨不需要,
而单子会被随手丢在操作台上),前厅那张要印(骑手来取要核对)。

存量迁移:把 Merchant.printer_sn 搬成一条 purpose=front 的记录,
沿用原来的 printer_auto。**老字段不删** —— 回滚要用,
而且删列这种不可逆的事不该和加功能混在一次发布里。

Revision ID: 0088
Revises: 0087
"""
import sqlalchemy as sa
from alembic import op

revision = '0088'
down_revision = '0087'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'merchant_printers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False, index=True),
        sa.Column('sn', sa.String(32), nullable=False),
        sa.Column('name', sa.String(30), nullable=False, server_default=''),
        sa.Column('purpose', sa.String(10), nullable=False,
                  server_default='front'),
        sa.Column('auto', sa.Boolean(), nullable=False,
                  server_default='true'),
        sa.Column('options', sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_printers_shop', 'merchant_printers', ['merchant_id'])
    # 存量搬迁:已绑的那台成为「前厅小票」
    op.execute("""
        INSERT INTO merchant_printers
            (merchant_id, sn, name, purpose, auto, options, created_at)
        SELECT id, printer_sn, '前厅小票', 'front',
               printer_auto, '{}'::jsonb, now()
        FROM merchants WHERE printer_sn <> ''
    """)


def downgrade() -> None:
    op.drop_index('ix_printers_shop', table_name='merchant_printers')
    op.drop_table('merchant_printers')
