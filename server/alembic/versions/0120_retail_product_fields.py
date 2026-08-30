"""零售商品字段:条码、品牌、规格、单位

超市和水果店和快餐店的区别只在货架上 —— 订单、骑手、结算、判责全都一样,
所以**不新建商品表,也不给 dishes 改名**:改名要动订单项、购物车、套餐、
券核销的所有引用,而用户根本看不到 "dish" 这个词。

四列都可空,只在 biz_type=retail 的店里填和显示。

## 条码是这四个里最有价值的

有了它平台才谈得上共享商品库 —— 否则每家超市都要重新录一遍
「农夫山泉 550ml」的名字、图片、规格。**但这一批只存不用**:
共享库要先解决"谁的图谁的文案算数"和"改了之后影响多少家店",
那是另一件事。现在先把数据收进来,不收的话以后想做也没有起点。

不加唯一约束:同一个条码在不同商家各有一行是正常的(各自定价、各自库存),
而同一家店同一个条码上两次是录入错误 —— 那该在商家端提示,
不该用数据库约束把整单上架卡掉。

## spec 是文案不是计价维度

"500g" 只是印在卡片上给人看的。**不做按重量计价** —— 美团自己也没做:
生鲜按标准份卖,短重走售后按比例退款,而我们已经有缺货部分退款
(Order.refund_cents + refund_note)。
"""
from alembic import op
import sqlalchemy as sa

revision = '0120'
down_revision = '0119'
branch_labels = None
depends_on = None

_COLS = [
    ("barcode", sa.String(20)),   # 商品条码(EAN-13 最长 13 位,留余量)
    ("brand", sa.String(40)),     # 品牌
    ("spec", sa.String(30)),      # 规格文案:"500g" / "6 个装"
    ("unit", sa.String(10)),      # 单位:件 / 份 / 斤
]


def upgrade() -> None:
    for name, type_ in _COLS:
        op.add_column("dishes", sa.Column(
            name, type_, nullable=False, server_default=""))
    # 按条码找商品(商家端扫码上架、以后的共享商品库)。
    # 不是唯一索引,理由见抬头
    op.create_index("ix_dishes_barcode", "dishes", ["barcode"],
                    postgresql_where=sa.text("barcode <> ''"))


def downgrade() -> None:
    op.drop_index("ix_dishes_barcode", table_name="dishes")
    for name, _ in _COLS:
        op.drop_column("dishes", name)
