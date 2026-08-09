"""堂食标识(市场监管总局令第 123 号第十二条,2026-06-01 施行)

第十二条要求平台在**列表页和商家主页**展示入网餐饮服务提供者的
「有堂食」「无堂食」标识 —— 和第十三条的明厨亮灶标识一样,要标的是两种。

三态而不是布尔:unknown 未填报 / yes 有堂食 / no 无堂食。

**存量商家一律 unknown,不给默认值**。布尔字段只能默认 false(= 无堂食)
或 true(= 有堂食),两个都是在替商家做一次没人核实过的陈述:
默认「有堂食」是给假信息背书,默认「无堂食」则会让一堆有堂食的店
被平台单方面标成没有。未填报是这里唯一诚实的初值,商家填了再改。

带索引:列表页要按它展示/筛选,同 kitchen_cam_status 的口径。

Revision ID: 0101
Revises: 0100
"""
import sqlalchemy as sa
from alembic import op

revision = '0101'
down_revision = '0100'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('merchants', sa.Column(
        'dine_in_status', sa.String(10), nullable=False,
        server_default='unknown'))
    op.create_index('ix_merchants_dine_in_status', 'merchants',
                    ['dine_in_status'])


def downgrade() -> None:
    op.drop_index('ix_merchants_dine_in_status', table_name='merchants')
    op.drop_column('merchants', 'dine_in_status')
