"""账本纪元:把「链被重新起头」变成一条永久公开记录(#2)

## 这张表是来补一个协议缺口的

见证节点的第一道防线是「我见过的锚点必须一字不差,消失也算篡改」。
这条防线是对的,但它分不出「平台偷偷改账」和「平台公开重置了链」。

`LEDGER-SPEC` §4 写的是「由人来判断是公告过的重置还是真的在毁账」——
机器没有任何判断依据。2026-07-28 那次重置就卡在这儿:官方节点从那天
一直报警到现在,9000 多次,而这一个月里没有人做过那个判断,
也没有任何公告。/nodes 页对外挂着一个永久的红色警报。

对外部观察者来说,那看起来就是「平台删了 16 天的账」。

## 补录第 1 纪元

这次迁移把那件事**据实写下来**:2026-07-28 因清理演示数据重置了链。

`prev_tip_hash` 留空 —— 因为那次**确实没有保留**旧链的链尾哈希,
现在也编不出来。这一栏空着本身就是记录的一部分:
下一次(如果还有)必须先冻结链尾再动手。

`prev_first_day` 记 2026-06-13:官方见证节点本地留存的最早锚点,
也就是消失的那段历史从哪天开始。这个数来自节点的报告,不是平台的账 ——
恰恰因为平台侧已经没有了,才更该由外部留存来记。
"""
import sqlalchemy as sa
from alembic import op

revision = '0110'
down_revision = '0109'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ledger_epochs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("started_day", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("prev_tip_hash", sa.String(64),
                  nullable=False, server_default=""),
        sa.Column("prev_first_day", sa.String(10),
                  nullable=False, server_default=""),
        sa.Column("prev_last_day", sa.String(10),
                  nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_ledger_epochs_epoch", "ledger_epochs",
                    ["epoch"], unique=True)

    # 补录已经发生的那次重置。只在库里确实有锚点时补 —— 空库(新开的城市、
    # CI、开发机)本来就没重置过,给它记一条"重置"是凭空捏造
    op.execute("""
        INSERT INTO ledger_epochs
            (epoch, started_day, reason, prev_tip_hash,
             prev_first_day, prev_last_day)
        SELECT 1, min(day),
               '2026-07-28 清理生产环境的演示数据(scripts/scrub_demo.py)。'
               '当时脚本按设计清空了 ledger_anchors 让链重新起链,此前的每日'
               '锚点因此消失;链尾哈希当时没有保留,这一栏是空的。'
               '后来查明:清账本本就没有必要 —— 锚点存的是当天流水的全文快照,'
               '底层单据删掉之后照样自洽,复算得出同样的哈希。脚本已改为不动'
               '账本,真要重置必须先冻结旧链链尾并留下这样一条记录。',
               '', '2026-06-13', ''
        FROM ledger_anchors
        HAVING count(*) > 0
    """)


def downgrade() -> None:
    op.drop_index("uq_ledger_epochs_epoch", table_name="ledger_epochs")
    op.drop_table("ledger_epochs")
