"""发货照:零售商家拣完货必须拍一张,纠纷时的事实来源

## 为什么零售需要,而餐饮不需要

外卖的纠纷是"味道不对""洒了",照片帮不上;而零售的纠纷是
**少给了、给错了、坏的**,那正是一张照片能定的事。

跑腿那条线早就有同样的东西(`pickup_photo_url`,注释写着「丢件纠纷时
唯一的事实来源 —— 东西是用户的,平台既不知道原样也不承担保价」)。
零售是同一个道理,只是时刻在商家发货那一端而不是骑手取件那一端。

## 为什么是商家拍,不是骑手拍

骑手不知道这单该有什么,也不会拆袋清点。真正能证明"我装的时候是这些"
的只有拣货的人。而且这是**责任转移的时刻** —— 判责分摊里 STAGE_COOKED
就是"成本 100% 发生"的那个点。

## 和跑腿的「不强制」是有意不一样的

`errands.upload_pickup_photo` 明确写了不强制,理由是「骑手在楼道里
手忙脚乱,卡住照片就等于卡住取件」。商家发货的处境不同:在自己柜台前、
有平板、是每天重复几十遍的动作。所以这里强制,而那里不强制,
**是两个处境的不同判断,不是其中一个漏了**。
"""
from alembic import op
import sqlalchemy as sa

revision = '0121'
down_revision = '0120'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column(
        "handover_photo_url", sa.String(300), nullable=False,
        server_default=""))


def downgrade() -> None:
    op.drop_column("orders", "handover_photo_url")
