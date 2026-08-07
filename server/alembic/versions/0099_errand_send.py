"""帮送:取件照 + 订单类型索引补齐

取件拍照是**丢件纠纷时唯一的事实来源**:东西是用户的,平台既不知道原样
也不承担保价,只有这张照片能说明"骑手拿到手时是什么样"。

不设成必填 —— 骑手在楼道里手忙脚乱,卡住照片就等于卡住取件。
界面上说清楚没拍的后果就够了。
"""
import sqlalchemy as sa
from alembic import op

revision = '0099'
down_revision = '0098'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column(
        'pickup_photo_url', sa.String(300), nullable=False,
        server_default=''))


def downgrade() -> None:
    op.drop_column('orders', 'pickup_photo_url')
