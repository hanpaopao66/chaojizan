"""骑手申诉通道

商家早就能对差评申诉,骑手不能 —— 被判超时、收到差评时完全没有说话的
地方,而超时的成因里商家出餐慢、地址填错、顾客不接电话占了相当一部分。

evidence 存**快照**不存引用:事后重算的话天气开关早就关了、ETA 也重估过,
证据会自己变。

申诉成立只把这一单标注为「非骑手责任」,不加回任何分数 ——
平台本来就没有骑手评分体系。

Revision ID: 0092
Revises: 0091
"""
import sqlalchemy as sa
from alembic import op

revision = '0092'
down_revision = '0091'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rider_appeals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rider_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False),
        sa.Column('order_no', sa.String(32), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False,
                  server_default='late'),
        sa.Column('reason', sa.String(300), nullable=False,
                  server_default=''),
        sa.Column('photo_url', sa.String(300), nullable=False,
                  server_default=''),
        sa.Column('evidence', sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default='{}'),
        sa.Column('status', sa.String(10), nullable=False,
                  server_default='pending'),
        sa.Column('verdict_note', sa.String(200), nullable=False,
                  server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_rappeal_rider', 'rider_appeals', ['rider_id'])
    op.create_index('ix_rappeal_order', 'rider_appeals', ['order_no'])
    op.create_index('ix_rappeal_status', 'rider_appeals', ['status'])
    # 一单一诉:同一单反复提交不会让它更成立,只会把核查队列灌满
    op.create_index('ix_rappeal_rider_order', 'rider_appeals',
                    ['rider_id', 'order_no'], unique=True)


def downgrade() -> None:
    op.drop_table('rider_appeals')
