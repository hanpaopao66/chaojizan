"""把「判商家责任要另出骑手那份」这条规则在这个库上生效的时刻记进库里

2026-09-15 起:商家有责任,商家连配送费和小费一起出 —— 平台骑手送的单,判商家责任时商家账本上另出
一行 fault_charge(services/merchant_fault.apply)。核账规则 4d 只核已经写了这一行的单;哪条路绕开了
apply、一行都没写,它看不见。规则 4e 反查:这一刻之后判了商家责任的单,必须有这一行。

**起算点为什么记在库里,不写成配置日期**:这条规则在哪个库上从哪一刻起生效,取决于这个库什么时候
升级到这一版 —— 生产是上线那一刻,CI 和本地是各自跑迁移那一刻。写成一个固定日期的话,上线晚于
那天,中间按旧规则判的单(本来就没有这一行)全被报成违规;早于那天,上线之后绕开的又漏掉;CI 还得
像信用分起算日那样另拨一个环境变量。记在库里就没有这些事,也不用改任何环境的配置。

放在 platform_flags(极简 KV)里,键 merchant_fault_charge_since,值是 UTC 的 ISO 时刻。它不是开关:
不在后台「平台开关」页(admin._KNOWN_FLAGS 没有它,改它的接口 404),也不写 flag_history、不进透明中心
的开关时间线 —— 能改它就等于能让反查对一段时间闭眼。

只在还没有这一行时写(ON CONFLICT DO NOTHING):重跑不会把起算点往后挪。
downgrade 删掉这一行;再升级就按再升级那一刻算。

Revision ID: 0141
Revises: 0140
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = '0141'
down_revision = '0140'
branch_labels = None
depends_on = None

#: 和 services/merchant_fault.CHARGE_SINCE_FLAG 同一个键(迁移不 import 应用代码,单测核两边一致)
KEY = 'merchant_fault_charge_since'


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("INSERT INTO platform_flags (key, value, updated_at) VALUES (:k, :v, now()) "
                "ON CONFLICT (key) DO NOTHING"),
        {"k": KEY, "v": datetime.now(timezone.utc).isoformat()})


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM platform_flags WHERE key = :k"), {"k": KEY})
