"""骑手意见反馈:针对平台本身,不是针对某一单

申诉(rider_appeals)解决的是"这一单不怪我"。但骑手对平台的意见没有
任何出口 —— 抢单页太卡、某个提示看不懂、某条规则不合理,这些他只能
在群里骂,平台永远听不到。

## 一条硬要求:必须有回音

不回复的反馈通道等于没有,而且比没有更糟 —— 他提过一次没人理,
以后连骂都懒得骂了。所以这张表带 reply/replied_at,平台回复时
走推送 + 骑手消息中心。
"""
import sqlalchemy as sa
from alembic import op

revision = '0096'
down_revision = '0095'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rider_feedbacks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rider_id', sa.Integer(), sa.ForeignKey('users.id'),
                  nullable=False, index=True),
        # bug 故障 / rule 规则不合理 / feature 想要的功能 / other
        sa.Column('kind', sa.String(12), nullable=False, server_default='other'),
        sa.Column('content', sa.String(1000), nullable=False,
                  server_default=''),
        # open 待处理 / replied 已回复。**没有"已关闭"** ——
        # 关闭是平台单方面宣布这件事结束,而回复才是骑手要的
        sa.Column('status', sa.String(12), nullable=False,
                  server_default='open', index=True),
        sa.Column('reply', sa.String(1000), nullable=False, server_default=''),
        sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # 平台队列按"未处理的最老一条"排,索引跟着这个用法建
    op.create_index('ix_rider_feedbacks_queue', 'rider_feedbacks',
                    ['status', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_rider_feedbacks_queue', table_name='rider_feedbacks')
    op.drop_table('rider_feedbacks')
