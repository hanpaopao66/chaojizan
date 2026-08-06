"""进货查验台账(食品溯源)

《食品安全法》第五十三条:食品经营者采购食品应当查验供货者的许可证和
合格证明;食品经营企业应当建立进货查验记录制度,如实记录食品名称、规格、
数量、生产日期或生产批号、保质期、进货日期以及供货者名称、地址、联系方式,
并保存相关凭证。保存期限(第五十条第二款)不少于保质期满后六个月;
没有明确保质期的不少于二年。

这是餐饮小商家普遍不做、而出事时**唯一能自证清白**的东西。

索引按 (merchant_id, purchased_on) 与 (merchant_id, name):
前者是"这段时间进了什么",后者是"这批食材是谁供的" ——
出食安问题时反查走的是后一条。

Revision ID: 0086
Revises: 0085
"""
import sqlalchemy as sa
from alembic import op

revision = '0086'
down_revision = '0085'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'purchase_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merchant_id', sa.Integer(), sa.ForeignKey('merchants.id'),
                  nullable=False),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('spec', sa.String(40), nullable=False, server_default=''),
        sa.Column('qty', sa.String(30), nullable=False, server_default=''),
        sa.Column('produced_on', sa.Date(), nullable=True),
        sa.Column('batch_no', sa.String(40), nullable=False,
                  server_default=''),
        sa.Column('shelf_life_end', sa.Date(), nullable=True),
        sa.Column('purchased_on', sa.Date(), nullable=False),
        sa.Column('supplier_name', sa.String(60), nullable=False,
                  server_default=''),
        sa.Column('supplier_address', sa.String(120), nullable=False,
                  server_default=''),
        sa.Column('supplier_phone', sa.String(20), nullable=False,
                  server_default=''),
        sa.Column('supplier_license_url', sa.String(300), nullable=False,
                  server_default=''),
        sa.Column('receipt_url', sa.String(300), nullable=False,
                  server_default=''),
        sa.Column('note', sa.String(200), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # "这段时间进了什么"
    op.create_index('ix_purchase_shop_date', 'purchase_records',
                    ['merchant_id', 'purchased_on'])
    # "这批食材是谁供的" —— 出食安问题时反查走这条
    op.create_index('ix_purchase_shop_name', 'purchase_records',
                    ['merchant_id', 'name'])


def downgrade() -> None:
    op.drop_index('ix_purchase_shop_name', table_name='purchase_records')
    op.drop_index('ix_purchase_shop_date', table_name='purchase_records')
    op.drop_table('purchase_records')
