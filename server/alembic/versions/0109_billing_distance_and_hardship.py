"""配送费的计价距离存进订单 + 骑手现场难度反馈(#300/#301)

## 为什么要 orders.bill_distance_m

在此之前配送费用的距离**没有落库**:算完喂给 `delivery_fee_parts`
就丢了。于是骑手看到 8 块钱,查不到它是按几公里算的。

而这个数还刚刚从直线换成了腾讯骑行路网 —— 换算法这件事本身,
就要求「当时按什么算的」可查。配送费一分不少全归骑手,
说不清来历的钱,给多少都不叫透明。

`bill_distance_source` 记 `route`(路网)还是 `straight`(接口不可用
时的直线兜底),两者差 19%,不标出来事后无从分辨。

## 为什么要 rider_hardships

配送费里的上门难度费取决于 `floor` / `has_elevator`,而这两个字段是
**用户在地址簿里自己填的**:大多数人不填,填了也没人核实。
「要走进小区 300 米」「车进不去只能推行」这些情况根本没有字段。

平台不可能知道每栋楼的情况。**跑过的人知道。**

这张表让骑手把现场的真实难度说出来:这一单当场补钱(平台承担),
同时按地址沉淀,攒够一致反馈后转正 —— 后来的每一单在下单时
就按真实难度计价,用户下单前看得到,骑手接单前也看得到。

`addr_key` 是地址的规整键(收货点坐标取 111m 网格 + 楼层),
不是原文地址 —— 同一栋楼的地址写法千奇百怪,按原文攒永远攒不够。

⚠️ 表里**不存反馈人的评价、不存信用分**。沉淀的是地址的属性,
不是人的行为。防刷靠 (rider_id, addr_key) 唯一约束和金额上限,
不靠给骑手打分。
"""
import sqlalchemy as sa
from alembic import op

revision = '0109'
down_revision = '0108'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column(
        "bill_distance_m", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column(
        "bill_distance_source", sa.String(10),
        nullable=False, server_default=""))
    # 下单时这个地址的已知难度,一句话存下来(#301)。
    #
    # 为什么存而不是查:骑手抢单列表一屏几十单,每单去查一次地址共识
    # 就是几十次往返 —— 和 #289 抢单列表那个坑一模一样。
    # 而且这也是快照:下单那一刻我们知道什么,就该按什么算钱、
    # 按什么告诉骑手,事后共识变了不该追溯改这一单。
    op.add_column("orders", sa.Column(
        "hardship_note", sa.String(200), nullable=False, server_default=""))

    op.create_table(
        "rider_hardships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(),
                  sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("order_no", sa.String(32), nullable=False),
        sa.Column("rider_id", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=False),
        # 地址规整键:收货点 111m 网格 + 楼层。按原文地址攒永远攒不够
        sa.Column("addr_key", sa.String(64), nullable=False),
        # 勾选项:no_elevator / walk_in / no_vehicle / gate_hard / other
        sa.Column("kinds", sa.JSON(), nullable=False,
                  server_default=sa.text("'[]'::json")),
        # 无电梯时爬到几楼;要步行进小区时大约多少米
        sa.Column("floors", sa.Integer(), nullable=True),
        sa.Column("walk_m", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        # 这一单实际补给骑手多少(分)。平台承担,不向用户或商家追收
        sa.Column("comp_cents", sa.Integer(),
                  nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    # 每单只能反馈一次
    op.create_index("uq_rider_hardships_order", "rider_hardships",
                    ["order_no"], unique=True)
    # (骑手, 地址):**普通索引,不是唯一约束**。
    #
    # 一度设成唯一的,想用它实现"同一骑手同一地址只计一次"。方向错了:
    # 那样第二次反馈会直接插不进去,而每一单的现场情况本来就该留档
    # (今天车能进、明天施工进不去,是两条不同的事实)。
    #
    # "只计一次"是**共识计数**的事:consensus() 按不同骑手去重。
    # 数据库该记的是发生过什么,判定谁算数是业务逻辑。
    op.create_index("ix_rider_hardships_rider_addr", "rider_hardships",
                    ["rider_id", "addr_key"])
    # 按地址取共识时的主查询路径
    op.create_index("ix_rider_hardships_addr", "rider_hardships", ["addr_key"])


def downgrade() -> None:
    op.drop_index("ix_rider_hardships_addr", table_name="rider_hardships")
    op.drop_index("ix_rider_hardships_rider_addr", table_name="rider_hardships")
    op.drop_index("uq_rider_hardships_order", table_name="rider_hardships")
    op.drop_table("rider_hardships")
    op.drop_column("orders", "hardship_note")
    op.drop_column("orders", "bill_distance_source")
    op.drop_column("orders", "bill_distance_m")
